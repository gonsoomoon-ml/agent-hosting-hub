"""The Lambda steps of the hosting review: Read, Grant, Entry, TestCall, Approve.
Each step is a plain function of (state, clients, environment), so it can be tested with fakes. Task 7's
Terraform deploys them as five Lambda functions, each with its own role and ACTION set to its step.
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
from platform_team.company_policy.policy_engine import ensure_policy
from platform_team.company_policy.policy_names import (entry_permit_name, guard_secret_name, review_permit_name,
                                                       tool_policy_name)
from platform_team.shared_code.aws_helpers import Deadline, signed_post
from platform_team.shared_code.config import Settings

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


def read(event: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """1 Read the catalog record. A record the review does not host (skip_reason) gives {"skip": <reason>}: the state
    machine ends the review there (Skipped), with no alert. For any other record, check the application
    (application) and pass on the checked fields only, among them where the code is; does not open the code."""
    d = event["detail"]
    rec = c.reg.get_registry_record(registryId=d["registryId"], recordId=d["registryRecordId"])
    reason = skip_reason(rec)
    if reason:
        return {"skip": reason}
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
    <Runtime name>-* (the shape of the AWS example of a Runtime execution role)."""
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
        {"Effect": "Allow", "Action": ["bedrock-agentcore:InvokeGateway"], "Resource": [env["TOOL_GW_ARN"]]},
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
         "Resource": _model_resources(env)},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:GetWorkloadAccessToken",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
         "Resource": [wid, f"{wid}/workload-identity/{_settings(env).runtime_name(agent)}-*"]},
    ]}
    return trust, perms


def grant(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """3 Create the agent's execution role and permit the tools named in the application (tool gateway)."""
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
    made = [_policy(c, env, deadline, tool_policy_name(agent, tool),
                    cedar.tool_permit(env["ACCOUNT"], role, tool, env["TOOL_GW_ARN"]))
            for tool in ctx["spec"]["tools"]]
    return {**ctx, "roleArn": arn, "toolPolicies": made}


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


def approve(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """7 Let users in and mark the record approved, only if the record still holds the reviewed application."""
    deadline = deadline or Deadline()
    _record_unchanged(ctx, c, env)
    policy = _policy(c, env, deadline, entry_permit_name(ctx["spec"]["name"]),
                     cedar.entry_permit(ctx["target"], env["AGENT_GW_ARN"]))
    _record_unchanged(ctx, c, env)                # once more right before approving: the policy wait takes a while
    r = c.reg.update_registry_record_status(registryId=ctx["registryId"], recordId=ctx["recordId"],
                                            status="APPROVED", statusReason="passed the hosting review")
    return {**ctx, "entryPolicy": policy, "recordStatus": r["status"]}


STEPS = {"read": read, "grant": grant, "entry": entry, "testcall": testcall, "approve": approve}
