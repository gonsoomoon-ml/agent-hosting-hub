"""Fake AWS clients for unit tests of the hub's steps. They record what the steps do; nothing calls AWS."""
import json
import types

from botocore.exceptions import ClientError

from platform_team.hosting_review.review_steps import application_digest
from platform_team.shared_code.hub_state import Platform

ACCOUNT = "123456789012"
TOOLS = ["Parts___get_part_spec", "Parts___get_test_result", "Quality___get_inspection_data",
         "Release___file_review_request"]

ENV = {
    "HUB_REGION": "us-west-2", "PREFIX": "hub", "ACCOUNT": ACCOUNT, "ENGINE_ID": "engine-1",
    "AGENT_GW_ID": "hub-agents-abcdefghij", "AGENT_GW_ARN": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:gateway/hub-agents-abcdefghij",
    "TOOL_GW_ARN": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:gateway/hub-tools-abcdefghij",
    "TESTCALL_ROLE": "hub-review-testcall-role", "EXAMPLE_KEY": "EXAMPLE-ACCESS-KEY",
    "CATALOG_TOOLS": ",".join(TOOLS), "AGENT_BOUNDARY": f"arn:aws:iam::{ACCOUNT}:policy/hub-agent-boundary",
}

SPEC = {"name": "quality_agent", "team": "appliance", "framework": "strands",
        "tools": ["Parts___get_part_spec", "Quality___get_inspection_data"],
        "code_key": "submissions/appliance/quality_agent/agent.zip", "code_version": "v1"}     # the key publish writes

CTX = {"registryId": "reg-1", "recordId": "rec-1", "record": "quality_agent", "spec": SPEC,
       "applicationDigest": application_digest(SPEC)}                   # what Read passes on for the record SPEC

PLATFORM = Platform(
    account=ACCOUNT,
    agent_gw={"id": "hub-agents-abcdefghij", "arn": ENV["AGENT_GW_ARN"],
              "url": "https://hub-agents-abcdefghij.gateway.bedrock-agentcore.us-west-2.amazonaws.com"},
    tool_gw={"id": "hub-tools-abcdefghij", "arn": ENV["TOOL_GW_ARN"],
             "url": "https://hub-tools-abcdefghij.gateway.bedrock-agentcore.us-west-2.amazonaws.com"},
    engine_id="engine-1", engine_arn=f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:policy-engine/engine-1",
    registry_id="reg-1", topic_arn=f"arn:aws:sns:us-west-2:{ACCOUNT}:hub-alerts",
    tool_lambda_arn=f"arn:aws:lambda:us-west-2:{ACCOUNT}:function:hub-tools",
    dev_role_arn=f"arn:aws:iam::{ACCOUNT}:role/hub-dev-role",
    bucket=f"hub-{ACCOUNT}-us-west-2",
    machine_arn=f"arn:aws:states:us-west-2:{ACCOUNT}:stateMachine:hub-review")


def _client_error(code: str, message: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, op)


class _Client:
    """One fake service. get_paginator(name).paginate(**kw) gives one page: the answer of the method of that name."""

    def __init__(self, owner):
        self.o = owner

    def get_paginator(self, name):
        return types.SimpleNamespace(paginate=lambda **kw: [getattr(self, name)(**kw)])


class _Ctl(_Client):
    """bedrock-agentcore-control: policies and gateway targets."""

    def list_policies(self, **kw):
        return {"policies": [{"policyId": p["id"], "name": n, "definition": {p["kind"]: {"statement": p["statement"]}}}
                             for n, p in self.o.policies.items()]}

    def create_policy(self, name, definition, **kw):
        pid = f"{name}-id"
        kind = next(iter(definition))
        rec = {"id": pid, "name": name, "statement": definition[kind]["statement"], "kind": kind}
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
        name = next((n for n, t in self.o.targets.items() if t == targetId), None)
        if name is None:
            raise _client_error("ResourceNotFoundException", "no target", "GetGatewayTarget")
        return {"name": name, "targetId": targetId, "status": "READY",
                "targetConfiguration": {"http": {"agentcoreRuntime": {"arn": self.o.target_arns.get(name)}}}}

    def delete_gateway_target(self, gatewayIdentifier, targetId):
        name = next((n for n, t in self.o.targets.items() if t == targetId), None)
        if name is None:
            raise _client_error("ResourceNotFoundException", "no target", "DeleteGatewayTarget")
        del self.o.targets[name]
        return {"targetId": targetId, "status": "DELETING"}


class _Iam(_Client):
    """Roles: existing_roles (made before, each with the inline policy "agent") and roles (made by the test). A role's
    permissions boundary is the hub's agent boundary unless role_boundaries says otherwise (None: no boundary);
    attached and instance_profiles give a role's managed policies and instance profiles by name."""

    def __init__(self, owner):
        super().__init__(owner)
        self.exceptions = types.SimpleNamespace(NoSuchEntityException=type("NoSuchEntityException", (ClientError,), {}))

    def _no_role(self, RoleName, op):
        if RoleName not in self.o.existing_roles and RoleName not in self.o.roles:
            raise self.exceptions.NoSuchEntityException({"Error": {"Code": "NoSuchEntity", "Message": "no role"}}, op)

    def _boundary(self, RoleName):
        if RoleName in self.o.role_boundaries:
            return self.o.role_boundaries[RoleName]
        return self.o.roles.get(RoleName, {}).get("boundary") or ENV["AGENT_BOUNDARY"]

    def get_role(self, RoleName):
        self._no_role(RoleName, "GetRole")
        boundary = self._boundary(RoleName)
        return {"Role": {"RoleName": RoleName, "Arn": f"arn:aws:iam::{ACCOUNT}:role/{RoleName}",
                         **({"PermissionsBoundary": {"PermissionsBoundaryType": "PermissionsBoundaryPolicy",
                                                     "PermissionsBoundaryArn": boundary}} if boundary else {})}}

    def list_attached_role_policies(self, RoleName):
        self._no_role(RoleName, "ListAttachedRolePolicies")
        return {"AttachedPolicies": [{"PolicyName": n, "PolicyArn": f"arn:aws:iam::aws:policy/{n}"}
                                     for n in self.o.attached.get(RoleName, [])]}

    def list_instance_profiles_for_role(self, RoleName):
        self._no_role(RoleName, "ListInstanceProfilesForRole")
        return {"InstanceProfiles": [{"InstanceProfileName": n} for n in self.o.instance_profiles.get(RoleName, [])]}

    def list_roles(self, **kw):
        return {"Roles": [{"RoleName": n} for n in sorted(self.o.existing_roles | set(self.o.roles))]}

    def list_role_policies(self, RoleName):
        self._no_role(RoleName, "ListRolePolicies")
        return {"PolicyNames": sorted(self.o.inline.get(RoleName, ()))}

    def delete_role_policy(self, RoleName, PolicyName):
        if PolicyName not in self.o.inline.get(RoleName, ()):
            raise self.exceptions.NoSuchEntityException(
                {"Error": {"Code": "NoSuchEntity", "Message": "no policy"}}, "DeleteRolePolicy")
        self.o.inline[RoleName].discard(PolicyName)

    def delete_role(self, RoleName):
        self._no_role(RoleName, "DeleteRole")
        if self.o.inline.get(RoleName):
            raise _client_error("DeleteConflict", "Cannot delete entity, must delete policies first.", "DeleteRole")
        self.o.existing_roles.discard(RoleName)
        self.o.roles.pop(RoleName, None)

    def create_role(self, RoleName, AssumeRolePolicyDocument, PermissionsBoundary=None, **kw):
        self.o.roles[RoleName] = {"trust": json.loads(AssumeRolePolicyDocument), "boundary": PermissionsBoundary}
        return {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/{RoleName}"}}

    def put_role_policy(self, RoleName, PolicyName, PolicyDocument):
        self.o.roles.setdefault(RoleName, {})["permissions"] = json.loads(PolicyDocument)
        self.o.inline.setdefault(RoleName, set()).add(PolicyName)


class _Ssm(_Client):
    def get_parameter(self, Name):
        if Name in self.o.parameters:
            return {"Parameter": {"Name": Name, "Value": self.o.parameters[Name]}}
        if self.o.runtime_arn is None:
            raise _client_error("ParameterNotFound", Name, "GetParameter")
        return {"Parameter": {"Value": self.o.runtime_arn}}

    def get_parameters_by_path(self, Path, Recursive=False, **kw):
        """Matches by plain prefix, wider than SSM's hierarchy: code that trusts the path alone is caught."""
        return {"Parameters": [{"Name": n, "Value": v} for n, v in sorted(self.o.parameters.items()) if n.startswith(Path)]}

    def delete_parameter(self, Name):
        if Name not in self.o.parameters:
            raise _client_error("ParameterNotFound", Name, "DeleteParameter")
        del self.o.parameters[Name]


class _Cfn(_Client):
    """CloudFormation: stacks {name: {"status", "reason", "resources", "template"}}. A deleted stack is gone at once,
    or shows DELETE_IN_PROGRESS to the next stack_delete_polls looks (inf: for ever), or ends DELETE_FAILED with
    stack_delete_reason."""

    def _stack(self, StackName, op):
        st = self.o.stacks.get(StackName)
        if st is not None and st.get("polls_left") is not None:
            if st["polls_left"] <= 0:
                del self.o.stacks[StackName]
                st = None
            else:
                st["polls_left"] -= 1
        if st is None:
            raise _client_error("ValidationError", f"Stack with id {StackName} does not exist", op)
        return st

    def describe_stacks(self, StackName):
        st = self._stack(StackName, "DescribeStacks")
        return {"Stacks": [{"StackName": StackName, "StackStatus": st["status"],
                            **({"StackStatusReason": st["reason"]} if st.get("reason") else {})}]}

    def list_stack_resources(self, StackName):
        return {"StackResourceSummaries": list(self._stack(StackName, "ListStackResources").get("resources", []))}

    def get_template(self, StackName):
        return {"TemplateBody": self._stack(StackName, "GetTemplate").get("template", {"Resources": {}})}

    def delete_stack(self, StackName):
        st = self.o.stacks.get(StackName)
        if st is None:
            return {}
        if self.o.stack_delete_reason:
            st.update(status="DELETE_FAILED", reason=self.o.stack_delete_reason)
        elif self.o.stack_delete_polls:
            st.update(status="DELETE_IN_PROGRESS", polls_left=self.o.stack_delete_polls)
        else:
            del self.o.stacks[StackName]
        return {}


class _Logs(_Client):
    def describe_log_groups(self, logGroupNamePrefix, **kw):
        return {"logGroups": [{"logGroupName": n} for n in sorted(self.o.log_groups) if n.startswith(logGroupNamePrefix)]}

    def delete_log_group(self, logGroupName):
        if logGroupName not in self.o.log_groups:
            raise _client_error("ResourceNotFoundException", "The specified log group does not exist.", "DeleteLogGroup")
        self.o.log_groups.discard(logGroupName)


class _Reg(_Client):
    """The catalog: the record quality_agent (rec-1, status record_status; None means no record) and other_records."""

    def list_registry_records(self, registryId, **kw):
        main = [{"name": "quality_agent", "recordId": "rec-1", "recordType": "AGENT", "status": self.o.record_status}]
        return {"registryRecords": (main if self.o.record_status else []) + list(self.o.other_records)}

    def delete_registry_record(self, registryId, recordId):
        if recordId == "rec-1" and self.o.record_status:
            self.o.record_status = None
        elif any(r["recordId"] == recordId for r in self.o.other_records):
            self.o.other_records = [r for r in self.o.other_records if r["recordId"] != recordId]
        else:
            raise _client_error("ResourceNotFoundException", "no record", "DeleteRegistryRecord")
        return {}

    def get_registry_record(self, registryId, recordId):
        """The record's name is record_name, or else the name its application gives (quality_agent by default)."""
        spec = self.o.record_spec
        name = self.o.record_name or (spec.get("name") if isinstance(spec, dict) else None) or "quality_agent"
        return {"name": name, "recordType": self.o.record_type, "status": self.o.record_status,
                "descriptors": {"custom": {"data": json.dumps(spec)}}}

    def update_registry_record_status(self, registryId, recordId, status, statusReason):
        self.o.record_status, self.o.status_reason = status, statusReason
        return {"status": status}


class _Sfn(_Client):
    """Step Functions: `running` holds (execution name, record ID) for each review still RUNNING."""

    def list_executions(self, stateMachineArn, statusFilter=None, **kw):
        return {"executions": [{"executionArn": f"{stateMachineArn}:{n}", "name": n, "status": "RUNNING"}
                               for n, _ in self.o.running if statusFilter in (None, "RUNNING")]}

    def describe_execution(self, executionArn):
        name = executionArn.rsplit(":", 1)[-1]
        return {"executionArn": executionArn, "name": name, "status": "RUNNING",
                "input": json.dumps({"detail": {"registryId": "reg-1", "registryRecordId": dict(self.o.running)[name]}})}


class FakeClients:
    """Stands in for platform_team.shared_code.aws_helpers.Clients (iam, ssm, ctl, reg, cfn, logs).
    http: the (status, text) answers of the signed POSTs, in turn; the last one repeats; an exception
    instance is raised instead (tests patch review_steps.signed_post with FakeClients.latest.post).
    Recorded: created_policies (id, name, statement), deleted_policies, policies, roles, inline (role -> inline
    policy names), targets, posts (url, body), record_status, status_reason. Tests may also fill stacks, log_groups,
    parameters, other_records and running (the reviews still running)."""

    latest = None       # the most recently built fake, for the patched signed_post

    def __init__(self, record_spec=None, record_status="PENDING_APPROVAL", existing_policies=(), existing_roles=(),
                 policy_status="ACTIVE", policy_reasons=None, runtime_arn=None, http=None, stack_delete_reason=None,
                 stack_delete_polls=0, record_name=None, record_type="AGENT"):
        self.record_spec = SPEC if record_spec is None else record_spec
        self.record_name, self.record_type = record_name, record_type
        self.record_status, self.status_reason = record_status, None
        self.existing_policies, self.existing_roles = set(existing_policies), set(existing_roles)
        self.policy_status, self.policy_reasons = policy_status, policy_reasons
        self.runtime_arn = runtime_arn
        self.http = list(http or [(200, '{"answer": "ok"}'), (403, "refused")])
        self.policies = {n: {"id": f"{n}-id", "name": n, "statement": "", "kind": "cedar"} for n in self.existing_policies}
        self.created_policies, self.deleted_policies = [], []
        self.roles, self.targets, self.target_arns, self.posts = {}, {}, {}, []
        self.inline = {r: {"agent"} for r in self.existing_roles}
        self.stacks, self.log_groups, self.parameters, self.other_records = {}, set(), {}, []
        self.stack_delete_reason, self.stack_delete_polls = stack_delete_reason, stack_delete_polls
        self.role_boundaries, self.attached, self.instance_profiles = {}, {}, {}
        self.running = []
        self.ctl, self.iam, self.ssm, self.reg = _Ctl(self), _Iam(self), _Ssm(self), _Reg(self)
        self.cfn, self.logs, self.sfn = _Cfn(self), _Logs(self), _Sfn(self)
        FakeClients.latest = self

    def post(self, url, body, region, **kw):
        """What a patched `signed_post` answers: the next `http` entry (an exception instance is raised)."""
        self.posts.append((url, body))
        answer = self.http.pop(0) if len(self.http) > 1 else self.http[0]
        if isinstance(answer, Exception):
            raise answer
        return answer
