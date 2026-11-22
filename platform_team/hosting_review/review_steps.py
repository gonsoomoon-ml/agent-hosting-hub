"""The Lambda steps of the hosting review: Read, Grant, Entry, TestCall, Approve.
Each step is a plain function of (state, clients, environment), so it can be tested with fakes. Task 7's
Terraform deploys them as five Lambda functions, each with its own role and ACTION set to its step.
None of these steps opens or runs the submitted code: that happens in CodeBuild (scan, deploy).

Every wait of a step takes its normal ceiling or the time its Lambda has left (`deadline`, set by
lambda_handler), whichever is shorter. A step that runs out of time stops with its own error and leaves no
half-made policy behind; without a deadline (unit tests, local runs) every wait gets its ceiling."""
import json
import time
import urllib.error

from platform_team.agent_catalog import application_form
from platform_team.agent_gateway.gateway_targets import ensure_runtime_target
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_engine import ensure_policy
from platform_team.shared_code.aws_helpers import Deadline, signed_post
from platform_team.shared_code.config import Settings

NORMAL_PROMPT = "What is the spec of part P-100?"
NORMAL_ATTEMPTS = 38     # a new target needs a while before it answers
SECRET_ATTEMPTS = 15     # a new policy needs a moment before it refuses
POLICY_WAIT = 300        # s, until a new policy is ACTIVE
TARGET_WAIT = 300        # s, until a new gateway target is READY
CALL_TIMEOUT = 180       # s, one test call


def _settings(env: dict) -> Settings:
    return Settings(region=env["HUB_REGION"], prefix=env["PREFIX"])


def _policy_name(agent: str, tool_id: str) -> str:
    return f"tool_permit_{agent}_{tool_id.replace('___', '_')}"


def _policy(c, env: dict, deadline: Deadline, name: str, statement: str, guardrail: bool = False) -> str:
    """ensure_policy, waiting no longer than the step has left."""
    return ensure_policy(c, env["ENGINE_ID"], name, statement, guardrail=guardrail,
                         wait=deadline.wait(POLICY_WAIT, f"policy {name}"))


def read(event: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """1 Read the application from the catalog record and check it. Passes on where the code is; does not open it."""
    d = event["detail"]
    rec = c.reg.get_registry_record(registryId=d["registryId"], recordId=d["registryRecordId"])
    spec = json.loads(rec["descriptors"]["custom"]["data"])
    problems = application_form.validate(spec, set(filter(None, env["CATALOG_TOOLS"].split(","))))
    problems += [f"missing: {k}" for k in ("code_key", "code_version") if not spec.get(k)]
    if problems:
        raise ValueError("; ".join(problems))
    return {"registryId": d["registryId"], "recordId": d["registryRecordId"], "record": rec["name"], "spec": spec}


def _execution_role(env: dict) -> tuple[dict, dict]:
    """Trust policy and permissions of an agent's execution role. The role is created under the permissions
    boundary AGENT_BOUNDARY (hosting_review/terraform/iam.tf), which allows no more than these permissions."""
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
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:GetWorkloadAccessToken",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
         "Resource": [wid, wid + "/workload-identity/*"]},
    ]}
    return trust, perms


def grant(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """3 Create the agent's execution role and permit the tools named in the application (tool gateway)."""
    deadline = deadline or Deadline()
    s, agent = _settings(env), ctx["spec"]["name"]
    role = s.agent_role(agent)
    trust, perms = _execution_role(env)
    try:
        arn = c.iam.get_role(RoleName=role)["Role"]["Arn"]
    except c.iam.exceptions.NoSuchEntityException:
        arn = c.iam.create_role(RoleName=role, AssumeRolePolicyDocument=json.dumps(trust),
                                Description="hosting review: agent execution role",
                                PermissionsBoundary=env["AGENT_BOUNDARY"])["Role"]["Arn"]
    c.iam.put_role_policy(RoleName=role, PolicyName="agent", PolicyDocument=json.dumps(perms))
    made = [_policy(c, env, deadline, _policy_name(agent, tool),
                    cedar.tool_permit(env["ACCOUNT"], role, tool, env["TOOL_GW_ARN"]))
            for tool in ctx["spec"]["tools"]]
    return {**ctx, "roleArn": arn, "toolPolicies": made}


def entry(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """5 Put the deployed agent behind the agent gateway. Only the review's test call may enter so far."""
    deadline = deadline or Deadline()
    s, agent = _settings(env), ctx["spec"]["name"]
    runtime_arn = c.ssm.get_parameter(Name=s.ssm("agents", agent, "runtime_arn"))["Parameter"]["Value"]
    target = s.target_name(agent)
    target_id = ensure_runtime_target(c, env["AGENT_GW_ID"], target, runtime_arn,
                                      wait=deadline.wait(TARGET_WAIT, f"target {target}"))
    review = _policy(c, env, deadline, f"entry_permit_review_{agent}",
                     cedar.entry_permit(target, env["AGENT_GW_ARN"], env["ACCOUNT"], env["TESTCALL_ROLE"]))
    guard = _policy(c, env, deadline, f"guard_secret_{agent}", cedar.guard_secret(target, env["AGENT_GW_ARN"]),
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


def _record_unchanged(ctx: dict, c) -> None:
    """The record still holds the application the review started with. A team can change its record while the
    review runs; approving then would approve content nobody reviewed."""
    rec = c.reg.get_registry_record(registryId=ctx["registryId"], recordId=ctx["recordId"])
    data = ((rec.get("descriptors") or {}).get("custom") or {}).get("data")
    try:
        spec = json.loads(data) if data else None
    except ValueError:
        spec = None
    if spec != ctx["spec"]:
        raise RuntimeError("the record changed after the review started: it is not approved "
                           "(the changed record goes through a review of its own)")


def approve(ctx: dict, c, env: dict, deadline: Deadline | None = None) -> dict:
    """7 Let users in and mark the record approved, only if the record still holds the reviewed application."""
    deadline = deadline or Deadline()
    _record_unchanged(ctx, c)
    policy = _policy(c, env, deadline, f"entry_permit_{ctx['spec']['name']}",
                     cedar.entry_permit(ctx["target"], env["AGENT_GW_ARN"]))
    _record_unchanged(ctx, c)                     # once more right before approving: the policy wait takes a while
    r = c.reg.update_registry_record_status(registryId=ctx["registryId"], recordId=ctx["recordId"],
                                            status="APPROVED", statusReason="passed the hosting review")
    return {**ctx, "entryPolicy": policy, "recordStatus": r["status"]}


STEPS = {"read": read, "grant": grant, "entry": entry, "testcall": testcall, "approve": approve}
