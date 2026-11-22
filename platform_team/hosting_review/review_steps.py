"""The Lambda steps of the hosting review: Read, Grant, Entry, TestCall, Approve.
Each step is a plain function of (state, clients, environment), so it can be tested with fakes. The Terraform of
hosting_review/terraform deploys them as five Lambda functions, each with its own role and ACTION set to its step.
None of these steps opens or runs the submitted code: that happens in CodeBuild (scan, deploy).

Every wait of a step takes its normal ceiling or the time its Lambda has left (`deadline`, set by
lambda_handler), whichever is shorter. A step that runs out of time stops with its own error and leaves no
half-made policy behind; without a deadline (unit tests, local runs) every wait gets its ceiling."""
import hashlib
import json
import re
import time
import urllib.error

from platform_team.agent_catalog import application_form
from platform_team.agent_gateway.gateway_targets import ensure_runtime_target
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_engine import drop_policy, ensure_policy, list_policies
from platform_team.company_policy.policy_names import (entry_permit_name, guard_secret_name, review_permit_name,
                                                       tool_policy_name, tool_policy_pattern)
from platform_team.company_policy.policy_rollout import apply_to_agent
from platform_team.hosting_review.reject_agent import running_reviews
from platform_team.shared_code.aws_helpers import Deadline, signed_post
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform

NORMAL_PROMPT = "What is the spec of part P-100?"
NORMAL_ATTEMPTS = 38     # a new target needs a while before it answers
SECRET_ATTEMPTS = 15     # a new policy needs a moment before it refuses
POLICY_WAIT = 300        # s, until a new policy is ACTIVE
TARGET_WAIT = 300        # s, until a new gateway target is READY
CALL_TIMEOUT = 180       # s, one test call
# The fields of an application the later steps use: Read passes on these and nothing else (application()).
REVIEWED_FIELDS = ("name", "team", "framework", "tools", "code_key", "code_version")
SUBMISSIONS = "submissions/"     # where the dev team role uploads; the builds may read nothing else of the inbox
SHOWN = 160                      # characters of a record's (or SSM) value an error message shows
MAX_ERROR = 2000                 # characters of Read's error: it travels in the review's state to the alert
NOT_HOSTED_FRAMEWORK = "harness"  # a managed harness has no code: there is nothing for the review to scan or deploy
# A cross-Region inference profile's ID is a geography and the foundation model's ID (us.anthropic.claude-...).
PROFILE_GEOGRAPHY = re.compile(r"(us|us-gov|eu|apac|jp|au|ca|global)\.(?=[a-z0-9-]+\.)")


def _settings(env: dict) -> Settings:
    return Settings(region=env["HUB_REGION"], prefix=env["PREFIX"])


def _policy(c, env: dict, deadline: Deadline, name: str, statement: str, guardrail: bool = False) -> str:
    """ensure_policy, waiting no longer than the step has left."""
    return ensure_policy(c, env["ENGINE_ID"], name, statement, guardrail=guardrail,
                         wait=deadline.wait(POLICY_WAIT, f"policy {name}"))


def application_digest(app: dict) -> str:
    """A fingerprint of a whole application, so Approve can tell any change, also in a field Read does not pass on."""
    return hashlib.sha256(json.dumps(app, sort_keys=True).encode()).hexdigest()


def _shown(value) -> str:
    """A value from the record as an error shows it: short, whatever its type."""
    return str(value)[:SHOWN]


def _application_of(rec: dict) -> dict | None:
    """The JSON object a catalog record holds as its application (descriptors.custom.data), or None."""
    data = ((rec.get("descriptors") or {}).get("custom") or {}).get("data")
    try:
        app = json.loads(data) if isinstance(data, str) else None
    except ValueError:
        return None
    return app if isinstance(app, dict) else None


def skip_reason(rec: dict) -> str | None:
    """Why the review does not host this record, or None when it reviews it: a record that is not an AGENT record
    (a shared tool), and an application whose framework is harness (no code). It looks at nothing else, so it comes
    before every check of the application: a record the review skips need not be an application it could pass."""
    if rec.get("recordType") != "AGENT":
        return f"record type is {_shown(rec.get('recordType'))}: the hosting review hosts AGENT records only"
    if (_application_of(rec) or {}).get("framework") == NOT_HOSTED_FRAMEWORK:
        return f"the application's framework is {NOT_HOSTED_FRAMEWORK}: it has no code for the review to scan or deploy"
    return None


def application(rec: dict, env: dict) -> tuple[dict, str]:
    """The application a catalog record holds, checked and cut down to the fields the later steps use
    (REVIEWED_FIELDS), with the digest of the whole application. Read and Approve both read the record through
    this one function, so what Approve compares is exactly what Read passed on.

    The record must be an AGENT record whose name is the application's name: every later step names things after the
    application, while reject and the cleanup find them by the record's name. The code must sit under submissions/.
    Raises ValueError with every problem found."""
    app = _application_of(rec)
    if app is None:
        raise ValueError("the record holds no application: descriptors.custom.data is not a JSON object")
    problems = []
    if rec.get("recordType") != "AGENT":
        problems.append(f"record type is {_shown(rec.get('recordType'))}, not AGENT")
    if app.get("name") != rec.get("name"):
        problems.append(f"the application's name {_shown(app.get('name'))} is not the record's name "
                        f"{_shown(rec.get('name'))}")
    problems += application_form.validate(app, set(filter(None, env["CATALOG_TOOLS"].split(","))))
    problems += [f"missing: {k}" for k in ("code_key", "code_version") if not app.get(k)]
    key, version = app.get("code_key"), app.get("code_version")
    if key and not (isinstance(key, str) and key.startswith(SUBMISSIONS) and len(key) > len(SUBMISSIONS)):
        problems.append(f"code_key must be a key under {SUBMISSIONS}: {_shown(key)}")
    if version and not isinstance(version, str):
        problems.append(f"code_version must be a string: {_shown(version)}")
    if problems:
        raise ValueError("; ".join(problems)[:MAX_ERROR])
    return {k: app[k] for k in REVIEWED_FIELDS}, application_digest(app)


def _earlier_reviews(c, review: dict, record_id: str) -> list[str]:
    """The names of the reviews of this record that started before this one and still run (running_reviews, oldest
    first). ListExecutions is eventually consistent (its documentation in the service model), so a review that just
    started may not see itself in the list: then every other running review of the record counts as earlier."""
    mine = review["execution"].rsplit(":", 1)[-1]
    running = running_reviews(c, Platform(machine_arn=review["machine"]), record_id)
    return running[:running.index(mine)] if mine in running else running


def read(review: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """1 Read the catalog record. The state machine passes {"event": <the Registry's event>, "execution": <this
    review's execution ARN>, "machine": <the state machine's ARN>}. In this order: a record the review does not host
    (skip_reason) gives {"skip": <reason>}, and the state machine ends the review there (Skipped), with no alert; a
    review of the same record that started before this one and still runs stops this one with RuntimeError (the two
    would make and remove the same role, Runtime and permits); then the application is checked (application) and
    only the checked fields are passed on, among them where the code is. Does not open the code."""
    d = review["event"]["detail"]
    rec = c.reg.get_registry_record(registryId=d["registryId"], recordId=d["registryRecordId"])
    reason = skip_reason(rec)
    if reason:
        return {"skip": reason}
    earlier = _earlier_reviews(c, review, d["registryRecordId"])
    if earlier:
        raise RuntimeError(f"a review of this record is already running: {', '.join(earlier)}"[:MAX_ERROR])
    spec, digest = application(rec, env)
    return {"registryId": d["registryId"], "recordId": d["registryRecordId"], "record": rec["name"], "spec": spec,
            "applicationDigest": digest}


def _model_resources(env: dict) -> list[str]:
    """What an agent role may invoke: the one model the hub runs its agents with (MODEL_ID). A cross-Region inference
    profile (us.anthropic....) is in the hub's Region and account, and routes to the foundation model behind it in
    other Regions; any other ID names a foundation model of the hub's Region."""
    region, account, model = env["HUB_REGION"], env["ACCOUNT"], env["MODEL_ID"]
    geography = PROFILE_GEOGRAPHY.match(model)
    if not geography:
        return [f"arn:aws:bedrock:{region}::foundation-model/{model}"]
    return [f"arn:aws:bedrock:{region}:{account}:inference-profile/{model}",
            f"arn:aws:bedrock:*::foundation-model/{model[geography.end():]}"]


def _execution_role(env: dict, agent: str) -> tuple[dict, dict]:
    """Trust policy and permissions of an agent's execution role. The role is created under the permissions
    boundary AGENT_BOUNDARY (hosting_review/terraform/iam.tf), which allows no more than these permissions.
    It may call the hub's model (MODEL_ID) and no other, and get tokens for the workload identity of its own Runtime
    only: AgentCore names that identity after the Runtime's ID, <Runtime name>-<10 characters>, so the resource is
    <Runtime name>-* (the shape of the AWS example of a Runtime execution role). It may send traces to X-Ray and
    its own metrics to CloudWatch (namespace bedrock-agentcore), as that example does."""
    region, account = env["HUB_REGION"], env["ACCOUNT"]
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": account}}}]}
    logs = f"arn:aws:logs:{region}:{account}:log-group"
    wid = f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default"
    perms = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
         "Resource": [logs + ":/aws/bedrock-agentcore/runtimes/*"]},
        {"Effect": "Allow", "Action": ["logs:DescribeLogGroups"], "Resource": [logs + ":*"]},
        {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": [logs + ":/aws/bedrock-agentcore/runtimes/*:log-stream:*"]},
        # Traces and the agent's own metrics, copied from the AWS example of a Runtime execution role ("IAM
        # Permissions for AgentCore Runtime", read on 2026-11-22). The Service Authorization Reference gives the four
        # X-Ray actions no resource type, so only "*" matches them. PutMetricData is on "*" as in the example, held
        # to the namespace bedrock-agentcore by the condition. The example also grants logs:PutResourcePolicy on the
        # agent's log group (for spans delivered there); it is left out: it is a permissions-management action, and
        # the reference gives it no resource type either, so a log-group resource may not narrow it.
        {"Effect": "Allow", "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules",
                                       "xray:GetSamplingTargets"], "Resource": ["*"]},
        {"Effect": "Allow", "Action": ["cloudwatch:PutMetricData"], "Resource": ["*"],
         "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:InvokeGateway"], "Resource": [env["TOOL_GW_ARN"]]},
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
         "Resource": _model_resources(env)},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:GetWorkloadAccessToken",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
         "Resource": [wid, f"{wid}/workload-identity/{_settings(env).runtime_name(agent)}-*"]},
    ]}
    return trust, perms


def _drop_unnamed_tool_permits(c, env: dict, agent: str, tools, found: dict) -> list[str]:
    """Delete this agent's tool permits for tools the application does not name (a version approved before named
    them) and return their names. `found` is the engine's policies by name. The permits are found by the shape of
    their names (tool_policy_pattern), which is exact for one agent, so another agent's permits are never touched."""
    named, own = {tool_policy_name(agent, t) for t in tools}, re.compile(tool_policy_pattern(agent))
    return [name for name in sorted(n for n in found if own.fullmatch(n) and n not in named)
            if drop_policy(c, env["ENGINE_ID"], found[name]["policyId"])]


def grant(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """3 Create the agent's execution role and permit the tools named in the application (tool gateway). A permit of
    this agent for a tool the application no longer names is deleted first (removedToolPolicies): the permits follow
    the application under review. The deletes come before the policy waits, which take the step's deadline.

    From the same list of the engine's policies, Grant notes whether the agent's entry permit is there
    (entryPermitBefore). Only Approve makes it, and Approve runs after Grant: so the value says whether it was there
    before this review, and it is the same for every attempt of Approve (approve)."""
    deadline = deadline or Deadline()
    s, agent = _settings(env), ctx["spec"]["name"]
    role = s.agent_role(agent)
    trust, perms = _execution_role(env, agent)
    try:
        arn = c.iam.get_role(RoleName=role)["Role"]["Arn"]
    except c.iam.exceptions.NoSuchEntityException:
        arn = c.iam.create_role(RoleName=role, AssumeRolePolicyDocument=json.dumps(trust),
                                Description="hosting review: agent execution role",
                                PermissionsBoundary=env["AGENT_BOUNDARY"])["Role"]["Arn"]
    c.iam.put_role_policy(RoleName=role, PolicyName="agent", PolicyDocument=json.dumps(perms))
    found = list_policies(c, env["ENGINE_ID"])
    removed = _drop_unnamed_tool_permits(c, env, agent, ctx["spec"]["tools"], found)
    made = [_policy(c, env, deadline, tool_policy_name(agent, tool),
                    cedar.tool_permit(env["ACCOUNT"], role, tool, env["TOOL_GW_ARN"]))
            for tool in ctx["spec"]["tools"]]
    return {**ctx, "roleArn": arn, "toolPolicies": made, "removedToolPolicies": removed,
            "entryPermitBefore": entry_permit_name(agent) in found}


def entry(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """5 Put the deployed agent behind the agent gateway. Only the review's test call may enter so far."""
    deadline = deadline or Deadline()
    s, agent = _settings(env), ctx["spec"]["name"]
    param = s.ssm("agents", agent, "runtime_arn")
    runtime_arn = c.ssm.get_parameter(Name=param)["Parameter"]["Value"]
    if not re.fullmatch(s.runtime_arn_pattern(agent, env["ACCOUNT"]), runtime_arn):     # the deploy build wrote it
        raise ValueError(f"{param} holds {_shown(runtime_arn)!r}, which is not the ARN of this agent's Runtime "
                         f"(runtime/{s.runtime_name(agent)}-<10 letters or digits> in this account and Region): "
                         "no target is made")
    target = s.target_name(agent)
    target_id = ensure_runtime_target(c, env["AGENT_GW_ID"], target, runtime_arn,
                                      wait=deadline.wait(TARGET_WAIT, f"target {target}"))
    review = _policy(c, env, deadline, review_permit_name(agent),
                     cedar.review_permit(target, env["AGENT_GW_ARN"], env["ACCOUNT"], env["TESTCALL_ROLE"]))
    guard = _policy(c, env, deadline, guard_secret_name(agent), cedar.guard_secret(target, env["AGENT_GW_ARN"]),
                    guardrail=True)
    return {**ctx, "runtimeArn": runtime_arn, "target": target, "targetId": target_id,
            "reviewPolicy": review, "guardPolicy": guard}


def testcall(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """6 Call the agent through the agent gateway: a normal question must be answered, a secret in the prompt
    must be refused. A new target or policy takes a moment, so each call is tried again for a while, but never
    past the deadline."""
    deadline = deadline or Deadline()
    region, wait = env["HUB_REGION"], float(env.get("TESTCALL_WAIT", "8"))
    url = f"https://{env['AGENT_GW_ID']}.gateway.bedrock-agentcore.{region}.amazonaws.com/{ctx['target']}/invocations"
    def until(prompt: str, want: int, attempts: int) -> tuple[int, str]:
        for i in range(attempts):
            timeout = deadline.wait(CALL_TIMEOUT, "the test call")
            try:
                code, body = signed_post(url, {"prompt": prompt}, region, timeout=timeout)
            except (OSError, urllib.error.URLError) as e:     # a timeout or reset: try again like any other not-yet answer
                code, body = 0, str(e)
            if code == want or i == attempts - 1 or deadline.left() < wait + 1:
                return code, body
            time.sleep(wait)

    code, body = until(NORMAL_PROMPT, 200, NORMAL_ATTEMPTS)
    if code != 200:
        raise RuntimeError(f"test call failed: {code} {body[:300]}")
    code2, body2 = until(f"Use this key for the upload: {env['EXAMPLE_KEY']}", 403, SECRET_ATTEMPTS)
    if code2 != 403:
        raise RuntimeError(f"a prompt with an access key was not refused: {code2} {body2[:300]}")
    return {**ctx, "testCall": {"normal": code, "with_secret": code2, "answer": body[:400]}}


def _record_unchanged(ctx: dict, c, env: dict) -> None:
    """The record still holds the application the review started with, and still asks for approval. A team can
    change its record while the review runs, and the platform team can reject it; approving then would approve
    content nobody reviewed, or open a rejected agent to every user. The record is read through the same check as
    in Read (application), the whole application must be as it was (its digest), and its status PENDING_APPROVAL."""
    rec = c.reg.get_registry_record(registryId=ctx["registryId"], recordId=ctx["recordId"])
    try:
        spec, digest = application(rec, env)
    except ValueError:
        spec = digest = None
    if spec != ctx["spec"] or digest != ctx.get("applicationDigest"):
        raise RuntimeError("the record changed after the review started: it is not approved "
                           "(the changed record goes through a review of its own)")
    if rec.get("status") != "PENDING_APPROVAL":
        raise RuntimeError(f"record {_shown(rec.get('name'))} is {_shown(rec.get('status'))}, not PENDING_APPROVAL: "
                           "it is not approved")


def _platform(env: dict) -> Platform:
    """The platform values a step's environment holds, as company_policy.policy_rollout takes them."""
    return Platform(account=env["ACCOUNT"], engine_id=env["ENGINE_ID"],
                    agent_gw={"id": env["AGENT_GW_ID"], "arn": env["AGENT_GW_ARN"]})


def _take_back(c, env: dict, name: str, why: Exception) -> None:
    """Delete the entry permit this review made, found by its name, because the approval stopped (why). One that is
    not there (never made, or ensure_policy deleted it) is fine. A delete that fails is said together with why the
    approval stopped."""
    try:
        found = list_policies(c, env["ENGINE_ID"]).get(name)
        if found:
            drop_policy(c, env["ENGINE_ID"], found["policyId"])
    except Exception as e:
        raise RuntimeError(f"{why}; taking back {name}, which this review made, failed too: {e}") from why


def approve(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """7 Give the agent the company policies the platform team has deployed, each in its mode (policy_rollout), let
    users in and mark the record approved, only if the record still holds the reviewed application. In this order:
    record check, company policies, entry permit, record check, APPROVED.

    Whether the entry permit was there before this review is entryPermitBefore, which Grant put in the context: an
    input without it (true or false) stops the approval before anything is made. When it was not there, any failure
    from making the entry permit on (the permit's wait, the second record check, the status update) takes the permit
    back and raises the error again. Step Functions may call Approve again with the same input, so a retry takes back
    a permit an earlier attempt made, too. If the status update in fact succeeded but its answer was lost, the record
    is APPROVED without an entry permit: users are refused until the agent is submitted again. An entry permit that
    was there before (a version approved earlier runs) stays, and so do the company policies made in this run (a
    forbid lets nobody in). A failure before the entry permit takes nothing back: a retry after an attempt that
    approved finds the record APPROVED there, and that permit must stay."""
    before = ctx.get("entryPermitBefore")
    if not isinstance(before, bool):
        raise ValueError("the review's state does not say whether the entry permit was there before the review "
                         "(entryPermitBefore, from Grant): nothing is approved")
    deadline = deadline or Deadline()
    _record_unchanged(ctx, c, env)
    agent = ctx["spec"]["name"]
    company = apply_to_agent(c, _settings(env), _platform(env), agent,
                             wait=deadline.wait(POLICY_WAIT, "the company policies"))
    name = entry_permit_name(agent)
    try:
        policy = _policy(c, env, deadline, name, cedar.entry_permit(ctx["target"], env["AGENT_GW_ARN"]))
        _record_unchanged(ctx, c, env)            # once more right before approving: the policy waits take a while
        r = c.reg.update_registry_record_status(registryId=ctx["registryId"], recordId=ctx["recordId"],
                                                status="APPROVED", statusReason="passed the hosting review")
    except Exception as e:                        # any failure: an entry permit this review made must not outlive it
        if not before:
            _take_back(c, env, name, e)
        raise
    return {**ctx, "companyPolicies": company, "entryPolicy": policy, "recordStatus": r["status"]}


STEPS = {"read": read, "grant": grant, "entry": entry, "testcall": testcall, "approve": approve}
