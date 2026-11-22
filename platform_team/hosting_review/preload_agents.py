"""The two agents that are there from the start. The platform team puts them on the hub with its own credentials:

    python -m platform_team.hosting_review.preload_agents      # make preload

spec_assistant (dev_team/preloaded_agents/spec_assistant) is a managed harness (AgentCore harness): a model, a system
prompt and the hub's tool gateway, and no code. The review hosts code, so it does not host a harness (Read skips an
application whose framework is harness). host_harness does for it what the review's Grant does for an agent, and makes
the harness and its approved catalog record. Its role is made by the function Grant makes every agent role with
(review_steps.ensure_agent_role), under the same boundary; host_harness itself runs with the platform team's
credentials, not with a role of the review.

docs_adk (dev_team/preloaded_agents/docs_adk) is a Google ADK agent with code. It is published like any team's agent
(publish_agent.publish) and goes through the same review; preload waits until that review ends.

What is there already is left as it is: an approved record, a harness of the agent's name with its role and tool
permits (also when agent.json or MODEL_ID changed). So a second run makes nothing new. Nothing calls AWS at import time.
"""
import json
import sys
import time
import uuid
from pathlib import Path

from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import name_problems, validate
from platform_team.agent_catalog.catalog_records import put_record, records, set_status, submit
from platform_team.agent_catalog.publish_agent import _catalog_tools, publish, record_description
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_engine import ensure_policy
from platform_team.company_policy.policy_names import tool_policy_name
from platform_team.hosting_review.agent_cleanup import cause, check_agent, check_harness
from platform_team.hosting_review import review_steps
from platform_team.hosting_review.review_steps import NOT_HOSTED_FRAMEWORK, POLICY_WAIT
from platform_team.shared_code.aws_helpers import Clients, wait_status
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

PRELOADED = Path(__file__).resolve().parents[2] / "dev_team" / "preloaded_agents"
HARNESS_AGENT, CODE_AGENT = PRELOADED / "spec_assistant", PRELOADED / "docs_adk"
HARNESS_NAME_MAX = 40          # CreateHarness's harnessName is [a-zA-Z][a-zA-Z0-9_]{0,39} (botocore 1.44.9)
# The harness's name for the tool gateway. allowedTools selects a gateway's tools as @<this name>/<tool>; a plain name
# selects a built-in tool (the AgentCore guide, "Tools", read on 2026-11-22), and without allowedTools the harness gets
# the recommended built-in set (shell and file tools among them). So every tool is listed, and only the hub's.
GATEWAY_TOOL = "hub_tools"
APPROVED_REASON = "preloaded by the platform team"
CREATE_TRIES, CREATE_STEP = 8, 15      # a role made a moment ago may not be usable yet (as in deploy_build)
HARNESS_WAIT, HARNESS_STEP = 600, 5    # s, until a new harness is READY
START_WAIT, REVIEW_WAIT, REVIEW_STEP = 120, 1200, 10    # s, until the review starts, until it ends, between looks


def application(folder: Path) -> dict:
    return json.loads((Path(folder) / "agent.json").read_text(encoding="utf-8"))


def _env(s: Settings, p: Platform) -> dict:
    """The values review_steps.ensure_agent_role reads, as a review step's environment holds them."""
    return {"HUB_REGION": s.region, "PREFIX": s.prefix, "ACCOUNT": p.account, "MODEL_ID": s.model_id,
            "TOOL_GW_ARN": p.tool_gw["arn"], "AGENT_BOUNDARY": f"arn:aws:iam::{p.account}:policy/{s.agent_boundary}"}


def harness_problems(s: Settings, app: dict) -> list[str]:
    """What keeps the hub from hosting this application as a harness: the form's problems (validate), a framework that
    is not harness, no system prompt, or a harness name longer than CreateHarness takes."""
    problems = validate(app, _catalog_tools())
    if app.get("framework") != NOT_HOSTED_FRAMEWORK:
        problems.append(f"framework must be {NOT_HOSTED_FRAMEWORK}")
    if not isinstance(app.get("system_prompt"), str) or not app["system_prompt"].strip():
        problems.append("system_prompt must be text: the harness's instructions")
    name = s.harness_name(app["name"]) if not name_problems(app.get("name")) else ""
    if len(name) > HARNESS_NAME_MAX:
        problems.append(f"harness name {name} has {len(name)} characters; CreateHarness takes at most "
                        f"{HARNESS_NAME_MAX}")
    return problems


def _create_harness(c, **request) -> dict:
    """create_harness, tried again while the role made a moment ago settles (ValidationException or
    AccessDeniedException, as for a new Runtime); any other error, and the last try, raise."""
    for attempt in range(CREATE_TRIES):
        try:
            return c.ctl.create_harness(**request)["harness"]
        except ClientError as e:
            if attempt == CREATE_TRIES - 1 or e.response["Error"]["Code"] not in ("ValidationException",
                                                                                 "AccessDeniedException"):
                raise
            time.sleep(CREATE_STEP)


def ensure_harness(c, s: Settings, p: Platform, app: dict, role_arn: str) -> str:
    """The agent's harness: made when there is none of its name, kept as it is otherwise. Waits until it is READY and
    returns its ARN. It runs the hub's model with the application's system prompt, has the tool gateway as its one
    tool (signed with its execution role) and may call only the application's tools; it has no memory."""
    name = s.harness_name(app["name"])
    harness = check_harness(c, s, app["name"])
    if harness is None:
        harness = _create_harness(
            c, harnessName=name, executionRoleArn=role_arn, model={"bedrockModelConfig": {"modelId": s.model_id}},
            systemPrompt=[{"text": app["system_prompt"]}],
            tools=[{"type": "agentcore_gateway", "name": GATEWAY_TOOL, "config": {"agentCoreGateway": {
                "gatewayArn": p.tool_gw["arn"], "outboundAuth": {"awsIam": {}}}}}],
            allowedTools=[f"@{GATEWAY_TOOL}/{tool}" for tool in app["tools"]],
            memory={"disabled": {}})          # without it the service makes a managed memory for the harness
    hid = harness["harnessId"]
    ready = wait_status(lambda: (lambda h: {**h, "statusReason": h.get("failureReason")})(
        c.ctl.get_harness(harnessId=hid)["harness"]), ("READY",), f"harness {name}", timeout=HARNESS_WAIT,
        step=HARNESS_STEP)
    return ready["arn"]


def _approved_record(c, p: Platform, app: dict) -> tuple[str, bool]:
    """The agent's catalog record, APPROVED by the platform team: written, submitted (the review that starts skips a
    harness), then approved. An approved record is kept. Returns its status and whether it changed."""
    rec = records(c, p.registry_id).get(app["name"])
    if rec and rec["status"] == "APPROVED":
        return "APPROVED", False
    rid = put_record(c, p.registry_id, app["name"], "AGENT", record_description(app), app)
    if records(c, p.registry_id)[app["name"]]["status"] == "DRAFT":    # a run that stopped after submit left it pending
        submit(c, p.registry_id, rid)
    return set_status(c, p.registry_id, rid, "APPROVED", APPROVED_REASON), True


def host_harness(c, s: Settings, p: Platform, app: dict) -> dict:
    """Host the application as a managed harness, in this order: check the application (harness_problems) and that the
    agent's role, Runtime and harness are not someone else's (agent_cleanup.check_agent), before anything is made;
    the execution role under the hub's agent boundary, made as Grant makes it (review_steps.ensure_agent_role); a tool
    permit on the tool gateway for each tool it names; the
    harness (ensure_harness); its ARN in SSM /<prefix>/agents/<agent>/harness_arn; an APPROVED catalog record.

    A harness of the agent's name that is there already is kept exactly as it is, and so are its role and its tool
    permits: the role is not written again and no permit is added or dropped, also when MODEL_ID or the application's
    tools changed. So the role keeps allowing the model the harness runs; a changed MODEL_ID or tool list reaches the
    harness only when it is made again, after the agent is removed. Returns {"agent", "harness_arn",
    "record_status", "kept"} (kept: the harness was there). Raises ValueError for an application it cannot host."""
    problems = harness_problems(s, app)
    if problems:
        raise ValueError("; ".join(problems))
    agent = app["name"]
    check_agent(c, s, agent)
    found = check_harness(c, s, agent)
    if found is None:
        role_arn = review_steps.ensure_agent_role(c, _env(s, p), agent, "platform team: harness execution role")
        for tool in app["tools"]:
            ensure_policy(c, p.engine_id, tool_policy_name(agent, tool),
                          cedar.tool_permit(p.account, s.agent_role(agent), tool, p.tool_gw["arn"]), wait=POLICY_WAIT)
    else:
        role_arn = found["executionRoleArn"]           # check_harness: the agent's role, of this account
    arn = ensure_harness(c, s, p, app, role_arn)
    c.ssm.put_parameter(Name=s.ssm("agents", agent, "harness_arn"), Value=arn, Type="String", Overwrite=True)
    status, _ = _approved_record(c, p, app)
    return {"agent": agent, "harness_arn": arn, "record_status": status, "kept": found is not None}


def ask_harness(c, harness_arn: str, question: str) -> str:
    """Ask the harness one question in a new session and return the text of its answer: the text of every
    contentBlockDelta of the stream, joined (tool inputs and results are not text). An error event in the stream raises
    RuntimeError with its message. The call names no tools, model or prompt of its own: the harness's are used."""
    answer = c.data.invoke_harness(harnessArn=harness_arn, runtimeSessionId=f"ask-{uuid.uuid4().hex}",
                                   messages=[{"role": "user", "content": [{"text": question}]}])
    text = []
    for event in answer["stream"]:
        for kind in ("runtimeClientError", "internalServerException", "validationException"):
            if kind in event:
                raise RuntimeError(f"the harness answered {kind}: {event[kind].get('message')}")
        text.append(event.get("contentBlockDelta", {}).get("delta", {}).get("text", ""))
    return "".join(text)


def _input_record(c, execution_arn: str) -> str | None:
    detail = (json.loads(c.sfn.describe_execution(executionArn=execution_arn).get("input") or "{}") or {}).get("detail")
    return (detail or {}).get("registryRecordId") if isinstance(detail, dict) else None


def wait_review(c, p: Platform, record_id: str, after: float) -> dict | None:
    """The review of this record that started at or after `after` (epoch s), waited on until it stops: {"execution",
    "status", "seconds"}. None when no such review starts within START_WAIT seconds."""
    found, seen, give_up = None, set(), time.time() + START_WAIT
    while found is None and time.time() < give_up:
        for e in c.sfn.list_executions(stateMachineArn=p.machine_arn, maxResults=20)["executions"]:
            if e["executionArn"] not in seen and e["startDate"].timestamp() >= after - 5:
                seen.add(e["executionArn"])
                if _input_record(c, e["executionArn"]) == record_id:
                    found = e
                    break
        else:
            time.sleep(3)
    if found is None:
        return None
    t0 = time.monotonic()
    while True:
        d = c.sfn.describe_execution(executionArn=found["executionArn"])
        if d["status"] != "RUNNING" or time.monotonic() - t0 > REVIEW_WAIT:
            took = (d["stopDate"] - d["startDate"]).total_seconds() if d.get("stopDate") else None
            return {"execution": d["name"], "status": d["status"], "seconds": took}
        time.sleep(REVIEW_STEP)


def _reviewed(c, s: Settings, p: Platform, folder: Path) -> dict:
    """The agent with code, published like a team's agent and reviewed; an approved record is kept. Raises
    RuntimeError when its review ends and the record is not APPROVED."""
    name = application(folder)["name"]
    rec = records(c, p.registry_id).get(name)
    if rec and rec["status"] == "APPROVED":
        return {"agent": name, "record_status": "APPROVED", "review": None}
    after = time.time()
    out = publish(folder, s, c=c)
    # not submitted again (a run that stopped left the record pending): the most recent review of the record is the one
    review = wait_review(c, p, out["record_id"], 0 if out.get("note") else after)
    status = records(c, p.registry_id)[name]["status"]
    if status != "APPROVED":
        what = f"review {review['execution']} ended {review['status']}" if review else "no review started"
        raise RuntimeError(f"{name}: {what}; the record is {status} (the review's alert says why)")
    return {"agent": name, "record_status": status, "review": review}


def preload(s: Settings, c=None, say=print) -> dict:
    """Host spec_assistant as a harness (host_harness), then publish docs_adk and wait for its review. Returns each
    agent's result by name. `say` gets one line per agent."""
    c = c or Clients.for_settings(s)
    p = load(s, c)
    app = application(HARNESS_AGENT)
    harness = host_harness(c, s, p, app)
    say(f"{harness['agent']}: harness {s.harness_name(app['name'])} READY, record {harness['record_status']}"
        + (" (kept as it is, with its role and tool permits)" if harness["kept"] else ""))
    code = _reviewed(c, s, p, CODE_AGENT)
    review = code["review"]
    say(f"{code['agent']}: record {code['record_status']}" + (
        f", review {review['execution']} {review['status']} in {review['seconds']:.0f}s" if review else " (kept)"))
    return {harness["agent"]: harness, code["agent"]: code}


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("usage: python -m platform_team.hosting_review.preload_agents")
        return 2
    hub = "this hub"
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        preload(s)
    except Exception as e:          # one line, account IDs masked, no traceback
        print(f"not preloaded ({hub}): {cause(e)}")
        return 1
    print(f"preloaded ({hub})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
