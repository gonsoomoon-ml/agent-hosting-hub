"""Fake AWS clients for unit tests of the hub's steps. They record what the steps do; nothing calls AWS."""
import json
import types

from botocore.exceptions import ClientError

from platform_team.shared_code.hub_state import Platform

ACCOUNT = "111122223333"
TOOLS = ["Parts___get_part_spec", "Parts___get_test_result", "Quality___get_inspection_data",
         "Release___file_review_request"]

ENV = {
    "HUB_REGION": "us-west-2", "PREFIX": "hub", "ACCOUNT": ACCOUNT, "ENGINE_ID": "engine-1",
    "AGENT_GW_ID": "agentgw1", "AGENT_GW_ARN": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:gateway/agentgw1",
    "TOOL_GW_ARN": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:gateway/toolgw1",
    "TESTCALL_ROLE": "hub-review-testcall-role", "EXAMPLE_KEY": "AKIAIOSFODNN7EXAMPLE",
    "CATALOG_TOOLS": ",".join(TOOLS), "AGENT_BOUNDARY": f"arn:aws:iam::{ACCOUNT}:policy/hub-agent-boundary",
}

SPEC = {"name": "quality_agent", "team": "appliance", "framework": "strands",
        "tools": ["Parts___get_part_spec", "Quality___get_inspection_data"],
        "code_key": "agents/quality_agent/code.zip", "code_version": "v1"}

CTX = {"registryId": "reg-1", "recordId": "rec-1", "record": "quality_agent", "spec": SPEC}

PLATFORM = Platform(
    account=ACCOUNT,
    agent_gw={"id": "agentgw1", "arn": ENV["AGENT_GW_ARN"],
              "url": "https://agentgw1.gateway.bedrock-agentcore.us-west-2.amazonaws.com"},
    tool_gw={"id": "toolgw1", "arn": ENV["TOOL_GW_ARN"],
             "url": "https://toolgw1.gateway.bedrock-agentcore.us-west-2.amazonaws.com"},
    engine_id="engine-1", engine_arn=f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:policy-engine/engine-1",
    registry_id="reg-1", topic_arn=f"arn:aws:sns:us-west-2:{ACCOUNT}:hub-alerts",
    tool_lambda_arn=f"arn:aws:lambda:us-west-2:{ACCOUNT}:function:hub-tools",
    dev_role_arn=f"arn:aws:iam::{ACCOUNT}:role/hub-dev-role",
    bucket=f"hub-{ACCOUNT}-us-west-2",
    machine_arn=f"arn:aws:states:us-west-2:{ACCOUNT}:stateMachine:hub-review")


def _client_error(code: str, message: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, op)


class _Ctl:
    """bedrock-agentcore-control: policies and gateway targets."""

    def __init__(self, owner):
        self.o = owner

    def list_policies(self, **kw):
        return {"policies": [{"policyId": p["id"], "name": n} for n, p in self.o.policies.items()]}

    def create_policy(self, name, definition, **kw):
        pid = f"{name}-id"
        statement = next(iter(definition.values()))["statement"]
        rec = {"id": pid, "name": name, "statement": statement}
        self.o.policies[name] = rec
        self.o.created_policies.append(rec)
        return {"policyId": pid}

    def get_policy(self, policyEngineId, policyId):
        name = next(n for n, p in self.o.policies.items() if p["id"] == policyId)
        if name in self.o.existing_policies:
            return {"status": "ACTIVE"}
        return {"status": self.o.policy_status, "statusReasons": self.o.policy_reasons}

    def delete_policy(self, policyEngineId, policyId):
        self.o.deleted_policies.append(policyId)
        self.o.policies = {n: p for n, p in self.o.policies.items() if p["id"] != policyId}

    def get_waiter(self, name):
        return types.SimpleNamespace(wait=lambda **kw: None)

    def list_gateway_targets(self, **kw):
        return {"items": [{"name": n, "targetId": t} for n, t in self.o.targets.items()]}

    def create_gateway_target(self, gatewayIdentifier, name, targetConfiguration, **kw):
        self.o.targets[name] = f"{name}-tid"
        self.o.target_arns[name] = targetConfiguration["http"]["agentcoreRuntime"]["arn"]
        return {"targetId": f"{name}-tid"}

    def get_gateway_target(self, gatewayIdentifier, targetId):
        return {"status": "READY"}


class _Iam:
    def __init__(self, owner):
        self.o = owner
        self.exceptions = types.SimpleNamespace(NoSuchEntityException=type("NoSuchEntityException", (ClientError,), {}))

    def get_role(self, RoleName):
        if RoleName not in self.o.existing_roles and RoleName not in self.o.roles:
            raise self.exceptions.NoSuchEntityException(
                {"Error": {"Code": "NoSuchEntity", "Message": "no role"}}, "GetRole")
        return {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/{RoleName}"}}

    def create_role(self, RoleName, AssumeRolePolicyDocument, PermissionsBoundary=None, **kw):
        self.o.roles[RoleName] = {"trust": json.loads(AssumeRolePolicyDocument), "boundary": PermissionsBoundary}
        return {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/{RoleName}"}}

    def put_role_policy(self, RoleName, PolicyName, PolicyDocument):
        self.o.roles.setdefault(RoleName, {})["permissions"] = json.loads(PolicyDocument)


class _Ssm:
    def __init__(self, owner):
        self.o = owner

    def get_parameter(self, Name):
        if self.o.runtime_arn is None:
            raise _client_error("ParameterNotFound", Name, "GetParameter")
        return {"Parameter": {"Value": self.o.runtime_arn}}


class _Reg:
    def __init__(self, owner):
        self.o = owner

    def get_registry_record(self, registryId, recordId):
        return {"name": "quality_agent", "status": self.o.record_status,
                "descriptors": {"custom": {"data": json.dumps(self.o.record_spec)}}}

    def update_registry_record_status(self, registryId, recordId, status, statusReason):
        self.o.record_status, self.o.status_reason = status, statusReason
        return {"status": status}


class FakeClients:
    """Stands in for platform_team.shared_code.aws_helpers.Clients (iam, ssm, ctl, reg).
    http: the (status, text) answers of the signed POSTs, in turn; the last one repeats; an exception
    instance is raised instead (tests patch review_steps.signed_post with FakeClients.latest.post).
    Recorded: created_policies (id, name, statement), deleted_policies, policies, roles, targets,
    posts (url, body), status_reason."""

    latest = None       # the most recently built fake, for the patched signed_post

    def __init__(self, record_spec=None, record_status="PENDING_APPROVAL", existing_policies=(), existing_roles=(),
                 policy_status="ACTIVE", policy_reasons=None, runtime_arn=None, http=None):
        self.record_spec = SPEC if record_spec is None else record_spec
        self.record_status, self.status_reason = record_status, None
        self.existing_policies, self.existing_roles = set(existing_policies), set(existing_roles)
        self.policy_status, self.policy_reasons = policy_status, policy_reasons
        self.runtime_arn = runtime_arn
        self.http = list(http or [(200, '{"answer": "ok"}'), (403, "refused")])
        self.policies = {n: {"id": f"{n}-id", "name": n, "statement": ""} for n in self.existing_policies}
        self.created_policies, self.deleted_policies = [], []
        self.roles, self.targets, self.target_arns, self.posts = {}, {}, {}, []
        self.ctl, self.iam, self.ssm, self.reg = _Ctl(self), _Iam(self), _Ssm(self), _Reg(self)
        FakeClients.latest = self

    def post(self, url, body, region, **kw):
        """What a patched `signed_post` answers: the next `http` entry (an exception instance is raised)."""
        self.posts.append((url, body))
        answer = self.http.pop(0) if len(self.http) > 1 else self.http[0]
        if isinstance(answer, Exception):
            raise answer
        return answer
