"""The Lambda steps of the hosting review: Read, Grant, Entry, TestCall, Approve.
Each step is a plain function of (state, clients, environment), so it can be tested with fakes. Task 7's
Terraform deploys them as five Lambda functions, each with its own role and ACTION set to its step.
None of these steps opens or runs the submitted code: that happens in CodeBuild (scan, deploy)."""
import json
import time

from platform_team.agent_catalog import application_form
from platform_team.agent_gateway.gateway_targets import ensure_runtime_target
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_engine import ensure_policy
from platform_team.shared_code.aws_helpers import signed_post
from platform_team.shared_code.config import Settings

NORMAL_PROMPT = "What is the spec of part P-100?"
NORMAL_ATTEMPTS = 38     # a new target needs a while before it answers
SECRET_ATTEMPTS = 15     # a new policy needs a moment before it refuses


def _settings(env: dict) -> Settings:
    return Settings(region=env["HUB_REGION"], prefix=env["PREFIX"])


def _policy_name(agent: str, tool_id: str) -> str:
    return f"tool_permit_{agent}_{tool_id.replace('___', '_')}"


def read(event: dict, c, env: dict) -> dict:
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
    """Trust policy and permissions of an agent's execution role."""
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


def grant(ctx: dict, c, env: dict) -> dict:
    """3 Create the agent's execution role and permit the tools named in the application (tool gateway)."""
    s, agent = _settings(env), ctx["spec"]["name"]
    role = s.agent_role(agent)
    trust, perms = _execution_role(env)
    try:
        arn = c.iam.get_role(RoleName=role)["Role"]["Arn"]
    except c.iam.exceptions.NoSuchEntityException:
        arn = c.iam.create_role(RoleName=role, AssumeRolePolicyDocument=json.dumps(trust),
                                Description="hosting review: agent execution role")["Role"]["Arn"]
    c.iam.put_role_policy(RoleName=role, PolicyName="agent", PolicyDocument=json.dumps(perms))
    made = [ensure_policy(c, env["ENGINE_ID"], _policy_name(agent, tool),
                          cedar.tool_permit(env["ACCOUNT"], role, tool, env["TOOL_GW_ARN"]))
            for tool in ctx["spec"]["tools"]]
    return {**ctx, "roleArn": arn, "toolPolicies": made}


def entry(ctx: dict, c, env: dict) -> dict:
    """5 Put the deployed agent behind the agent gateway. Only the review's test call may enter so far."""
    s, agent = _settings(env), ctx["spec"]["name"]
    runtime_arn = c.ssm.get_parameter(Name=s.ssm("agents", agent, "runtime_arn"))["Parameter"]["Value"]
    target = s.target_name(agent)
    target_id = ensure_runtime_target(c, env["AGENT_GW_ID"], target, runtime_arn)
    review = ensure_policy(c, env["ENGINE_ID"], f"entry_permit_review_{agent}",
                           cedar.entry_permit(target, env["AGENT_GW_ARN"], env["ACCOUNT"], env["TESTCALL_ROLE"]))
    guard = ensure_policy(c, env["ENGINE_ID"], f"guard_secret_{agent}",
                          cedar.guard_secret(target, env["AGENT_GW_ARN"]), guardrail=True)
    return {**ctx, "runtimeArn": runtime_arn, "target": target, "targetId": target_id,
            "reviewPolicy": review, "guardPolicy": guard}


def testcall(ctx: dict, c, env: dict) -> dict:
    """6 Call the agent through the agent gateway: a normal question must be answered, a secret in the prompt
    must be refused. A new target or policy takes a moment, so each call is tried again for a while."""
    region, wait = env["HUB_REGION"], float(env.get("TESTCALL_WAIT", "8"))
    url = f"https://{env['AGENT_GW_ID']}.gateway.bedrock-agentcore.{region}.amazonaws.com/{ctx['target']}/invocations"
    post = getattr(c, "signed_post", signed_post)       # tests hand in a fake through the clients

    def until(prompt: str, want: int, attempts: int) -> tuple[int, str]:
        for i in range(attempts):
            code, body = post(url, {"prompt": prompt}, region)
            if code == want or i == attempts - 1:
                return code, body
            time.sleep(wait)

    code, body = until(NORMAL_PROMPT, 200, NORMAL_ATTEMPTS)
    if code != 200:
        raise RuntimeError(f"test call failed: {code} {body[:300]}")
    code2, body2 = until(f"Use this key for the upload: {env['EXAMPLE_KEY']}", 403, SECRET_ATTEMPTS)
    if code2 != 403:
        raise RuntimeError(f"a prompt with an access key was not refused: {code2} {body2[:300]}")
    return {**ctx, "testCall": {"normal": code, "with_secret": code2, "answer": body[:400]}}


def approve(ctx: dict, c, env: dict) -> dict:
    """7 Let users in and mark the record approved."""
    policy = ensure_policy(c, env["ENGINE_ID"], f"entry_permit_{ctx['spec']['name']}",
                           cedar.entry_permit(ctx["target"], env["AGENT_GW_ARN"]))
    r = c.reg.update_registry_record_status(registryId=ctx["registryId"], recordId=ctx["recordId"],
                                            status="APPROVED", statusReason="passed the hosting review")
    return {**ctx, "entryPolicy": policy, "recordStatus": r["status"]}


STEPS = {"read": read, "grant": grant, "entry": entry, "testcall": testcall, "approve": approve}
