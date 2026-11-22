"""Fake AWS clients for unit tests of the hub's steps. They record what the steps do; nothing calls AWS."""
import datetime
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
    "MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
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
    machine_arn=f"arn:aws:states:us-west-2:{ACCOUNT}:stateMachine:hub-review",
    interceptor_arn=f"arn:aws:lambda:us-west-2:{ACCOUNT}:function:hub-guardrail")

EVENT = {"detail": {"registryId": "reg-1", "registryRecordId": "rec-1"}}    # the Registry's event for the record SPEC
STARTED = datetime.datetime(2026, 11, 22, 9, 0, tzinfo=datetime.timezone.utc)   # when the first running review started


def read_input(event=EVENT, execution="this-one") -> dict:
    """Read's input as the state machine passes it: the Registry's event, the ARN of this review's execution (named
    `execution`) and the state machine's ARN."""
    executions = PLATFORM.machine_arn.replace(":stateMachine:", ":execution:")
    return {"event": event, "execution": f"{executions}:{execution}", "machine": PLATFORM.machine_arn}


def _client_error(code: str, message: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, op)


class _Client:
    """One fake service. get_paginator(name).paginate(**kw) gives one page: the answer of the method of that name."""

    service = ""            # the name in FakeClients.calls

    def __init__(self, owner):
        self.o = owner

    def __getattribute__(self, name):
        """A call of a public method is written to owner.calls as (service, method), in the order it happens."""
        attr = super().__getattribute__(name)
        if name.startswith("_") or name in ("o", "service", "exceptions") or not callable(attr):
            return attr

        def recorded(*args, **kw):
            self.o.calls.append((self.service, name))
            return attr(*args, **kw)
        return recorded

    def get_paginator(self, name):
        return types.SimpleNamespace(paginate=lambda **kw: [getattr(self, name)(**kw)])


class _Ctl(_Client):
    """bedrock-agentcore-control: policies, gateway targets and Runtimes.
    Runtimes: runtimes {name: {"id", "arn", "version", "config", "status", "gets"}}. A new or updated Runtime is READY,
    or shows CREATING / UPDATING to the next runtime_ready_after looks (inf: for ever); runtime_status other than
    READY is where it ends instead (with runtime_failure as its failureReason). runtime_create_errors are raised by
    create_agent_runtime, in turn, before it works. A deleted Runtime is gone at once, or shows DELETING to the next
    runtime_delete_polls looks (with runtime_delete_keeps_status: the status it had before the delete), or ends
    DELETE_FAILED with runtime_delete_failure. workload_identities: the names list_workload_identities gives."""
    service = "ctl"


    def list_policies(self, **kw):
        return {"policies": [{"policyId": p["id"], "name": n, "status": "ACTIVE", "enforcementMode": p["mode"],
                              "definition": {p["kind"]: {"statement": p["statement"]}}}
                             for n, p in self.o.policies.items()]}

    def create_policy(self, name, definition, enforcementMode="ACTIVE", **kw):
        pid = f"{name}-id"
        kind = next(iter(definition))
        rec = {"id": pid, "name": name, "statement": definition[kind]["statement"], "kind": kind,
               "mode": enforcementMode}
        self.o.policies[name] = rec
        self.o.created_policies.append(rec)
        return {"policyId": pid}

    def get_policy(self, policyEngineId, policyId):
        name = next(n for n, p in self.o.policies.items() if p["id"] == policyId)
        if name in self.o.existing_policies:
            return {"status": "ACTIVE"}
        return {"status": self.o.policy_status, "statusReasons": self.o.policy_reasons}

    def update_policy(self, policyEngineId, policyId, enforcementMode=None, **kw):
        name = next(n for n, p in self.o.policies.items() if p["id"] == policyId)
        if enforcementMode:
            self.o.policies[name]["mode"] = enforcementMode
            self.o.mode_changes.append((name, enforcementMode))
        return {"policyId": policyId, "name": name, "status": "UPDATING"}

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

    def _runtime_by_id(self, agentRuntimeId, op):
        name = next((n for n, r in self.o.runtimes.items() if r["id"] == agentRuntimeId), None)
        if name is None:
            raise _client_error("ResourceNotFoundException", f"no Runtime {agentRuntimeId}", op)
        return name, self.o.runtimes[name]

    def _made(self, rt, status):
        rt.update(status=status, gets=0)
        return {"agentRuntimeArn": rt["arn"], "agentRuntimeId": rt["id"], "agentRuntimeVersion": rt["version"],
                "status": status}

    def list_agent_runtimes(self, **kw):
        return {"agentRuntimes": [{"agentRuntimeName": n, "agentRuntimeId": r["id"], "agentRuntimeArn": r["arn"],
                                   "agentRuntimeVersion": r["version"], "status": r["status"]}
                                  for n, r in sorted(self.o.runtimes.items())]}

    def create_agent_runtime(self, agentRuntimeName, **config):
        self.o.runtime_create_tries += 1
        if self.o.runtime_create_errors:
            raise self.o.runtime_create_errors.pop(0)
        if agentRuntimeName in self.o.runtimes:
            raise _client_error("ConflictException", f"Runtime {agentRuntimeName} already exists", "CreateAgentRuntime")
        rid = f"{agentRuntimeName}-Ab12Cd34Ef"
        rt = {"id": rid, "arn": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:runtime/{rid}", "version": "1",
              "config": config}
        self.o.runtimes[agentRuntimeName] = rt
        self.o.runtime_calls.append(f"create {agentRuntimeName}")
        return self._made(rt, "CREATING")

    def update_agent_runtime(self, agentRuntimeId, **config):
        _, rt = self._runtime_by_id(agentRuntimeId, "UpdateAgentRuntime")
        rt.update(version=str(int(rt["version"]) + 1), config=config)
        self.o.runtime_calls.append(f"update {agentRuntimeId}")
        return self._made(rt, "UPDATING")

    def get_agent_runtime(self, agentRuntimeId):
        self.o.runtime_gets += 1
        name, rt = self._runtime_by_id(agentRuntimeId, "GetAgentRuntime")
        rt["gets"] += 1
        if rt.get("deleting") and rt["gets"] > self.o.runtime_delete_polls:
            del self.o.runtimes[name]
            raise _client_error("ResourceNotFoundException", f"no Runtime {agentRuntimeId}", "GetAgentRuntime")
        if rt["status"] in ("CREATING", "UPDATING") and rt["gets"] > self.o.runtime_ready_after:
            rt.update(status=self.o.runtime_status,
                      **({"failure": self.o.runtime_failure} if self.o.runtime_status != "READY" else {}))
        return {"agentRuntimeName": name, "agentRuntimeId": rt["id"], "agentRuntimeArn": rt["arn"],
                "agentRuntimeVersion": rt["version"], "roleArn": rt["config"].get("roleArn", ""), "status": rt["status"],
                **({"failureReason": rt["failure"]} if rt.get("failure") else {})}

    def delete_agent_runtime(self, agentRuntimeId):
        name, rt = self._runtime_by_id(agentRuntimeId, "DeleteAgentRuntime")
        self.o.runtime_calls.append(f"delete {agentRuntimeId}")
        if self.o.runtime_delete_failure:
            rt.update(status="DELETE_FAILED", failure=self.o.runtime_delete_failure)
        elif self.o.runtime_delete_polls:
            rt.update(deleting=True, gets=0, **({} if self.o.runtime_delete_keeps_status else {"status": "DELETING"}))
        else:
            del self.o.runtimes[name]
        return {"agentRuntimeId": agentRuntimeId, "status": "DELETING"}

    def list_workload_identities(self, **kw):
        return {"workloadIdentities": [{"name": n} for n in self.o.workload_identities]}


class _Iam(_Client):
    """Roles: existing_roles (made before, each with the inline policy "agent") and roles (made by the test). A role's
    permissions boundary is the hub's agent boundary unless role_boundaries says otherwise (None: no boundary);
    attached and instance_profiles give a role's managed policies and instance profiles by name."""
    service = "iam"


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
    service = "ssm"
    def put_parameter(self, Name, Value, Type, Overwrite=False):
        if Name in self.o.parameters and not Overwrite:
            raise _client_error("ParameterAlreadyExists", Name, "PutParameter")
        self.o.parameters[Name] = Value
        return {"Version": 1}

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


class _S3(_Client):
    """The inbox bucket (its name is not checked): objects {key: [version IDs, oldest first]}."""
    service = "s3"


    def put_object(self, Bucket, Key, Body=b"", **kw):
        versions = self.o.objects.setdefault(Key, [])
        versions.append(f"{Key}-version-{len(versions) + 1}")
        return {"VersionId": versions[-1]}

    def list_object_versions(self, Bucket, Prefix="", **kw):
        return {"Versions": [{"Key": k, "VersionId": v} for k, vs in sorted(self.o.objects.items()) if k.startswith(Prefix)
                             for v in vs]}

    def delete_object(self, Bucket, Key, VersionId=None):
        versions = self.o.objects.get(Key, [])
        if VersionId in versions:
            versions.remove(VersionId)
        if not versions:
            self.o.objects.pop(Key, None)
        return {}


class _Logs(_Client):
    service = "logs"
    def describe_log_groups(self, logGroupNamePrefix, **kw):
        return {"logGroups": [{"logGroupName": n} for n in sorted(self.o.log_groups) if n.startswith(logGroupNamePrefix)]}

    def delete_log_group(self, logGroupName):
        if logGroupName not in self.o.log_groups:
            raise _client_error("ResourceNotFoundException", "The specified log group does not exist.", "DeleteLogGroup")
        self.o.log_groups.discard(logGroupName)


class _Reg(_Client):
    """The catalog: the record quality_agent (rec-1, status record_status; None means no record) and other_records."""
    service = "reg"


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
    """Step Functions: `running` holds (execution name, record ID) for each review still RUNNING, in the order they
    started. list_executions gives them most recent first, as the service documents it, each with its startDate (one
    second after the one before); an execution's input is the Registry's event for its record."""
    service = "sfn"


    def _execution(self, stateMachineArn, n, i):
        return {"executionArn": f"{stateMachineArn.replace(':stateMachine:', ':execution:', 1)}:{n}",
                "stateMachineArn": stateMachineArn, "name": n, "status": "RUNNING",
                "startDate": STARTED + datetime.timedelta(seconds=i)}

    def list_executions(self, stateMachineArn, statusFilter=None, **kw):
        return {"executions": [self._execution(stateMachineArn, n, i) for i, (n, _) in enumerate(self.o.running)
                               if statusFilter in (None, "RUNNING")][::-1]}

    def describe_execution(self, executionArn):
        machine, name = executionArn.replace(":execution:", ":stateMachine:", 1).rsplit(":", 1)
        i = [n for n, _ in self.o.running].index(name)
        return {**self._execution(machine, name, i),
                "input": json.dumps({"detail": {"registryId": "reg-1", "registryRecordId": self.o.running[i][1]}})}


class FakeClients:
    """Stands in for platform_team.shared_code.aws_helpers.Clients (iam, ssm, ctl, reg, logs, sfn, s3).
    http: the (status, text) answers of the signed POSTs, in turn; the last one repeats; an exception
    instance is raised instead (tests patch review_steps.signed_post with FakeClients.latest.post).
    policy_mode: the enforcement mode of the existing_policies; parameters: the SSM values at the start; targets: the
    names of the targets the agent gateway already has; running: (execution name, record ID) of each review still
    RUNNING, in the order they started.
    Recorded: created_policies (id, name, statement, kind, mode), mode_changes ((name, mode) of each update_policy),
    calls ((service, method) of every fake call, in order), deleted_policies, policies, roles, inline (role -> inline
    policy names), targets, posts (url, body), record_status, status_reason, runtimes, runtime_calls ("create <name>",
    "update <ID>", "delete <ID>"), runtime_gets, runtime_create_tries, parameters, objects. Tests may also fill
    log_groups, parameters, objects, other_records, runtime_create_errors and running (the reviews still running)."""

    latest = None       # the most recently built fake, for the patched signed_post

    def __init__(self, record_spec=None, record_status="PENDING_APPROVAL", existing_policies=(), existing_roles=(),
                 policy_status="ACTIVE", policy_reasons=None, runtime_arn=None, http=None, record_name=None,
                 record_type="AGENT", runtime_status="READY", runtime_failure=None, runtime_ready_after=0,
                 runtime_delete_failure=None, runtime_delete_polls=0, runtime_delete_keeps_status=False,
                 policy_mode="ACTIVE", parameters=None, targets=(), running=()):
        self.record_spec = SPEC if record_spec is None else record_spec
        self.record_name, self.record_type = record_name, record_type
        self.record_status, self.status_reason = record_status, None
        self.existing_policies, self.existing_roles = set(existing_policies), set(existing_roles)
        self.policy_status, self.policy_reasons = policy_status, policy_reasons
        self.runtime_arn = runtime_arn
        self.http = list(http or [(200, '{"answer": "ok"}'), (403, "refused")])
        self.policies = {n: {"id": f"{n}-id", "name": n, "statement": "", "kind": "cedar", "mode": policy_mode}
                         for n in self.existing_policies}
        self.created_policies, self.deleted_policies, self.mode_changes, self.calls = [], [], [], []
        self.roles, self.posts = {}, []
        self.targets = {n: f"{n}-tid" for n in targets}
        self.target_arns = {}
        self.inline = {r: {"agent"} for r in self.existing_roles}
        self.log_groups, self.parameters, self.other_records, self.objects = set(), dict(parameters or {}), [], {}
        self.runtimes, self.runtime_calls, self.runtime_gets, self.runtime_create_tries = {}, [], 0, 0
        self.runtime_status, self.runtime_failure, self.runtime_ready_after = runtime_status, runtime_failure, runtime_ready_after
        self.runtime_delete_failure, self.runtime_delete_polls = runtime_delete_failure, runtime_delete_polls
        self.runtime_delete_keeps_status, self.runtime_create_errors, self.workload_identities = \
            runtime_delete_keeps_status, [], []
        self.role_boundaries, self.attached, self.instance_profiles = {}, {}, {}
        self.running = list(running)
        self.ctl, self.iam, self.ssm, self.reg = _Ctl(self), _Iam(self), _Ssm(self), _Reg(self)
        self.logs, self.sfn, self.s3 = _Logs(self), _Sfn(self), _S3(self)
        FakeClients.latest = self

    def post(self, url, body, region, **kw):
        """What a patched `signed_post` answers: the next `http` entry (an exception instance is raised)."""
        self.posts.append((url, body))
        answer = self.http.pop(0) if len(self.http) > 1 else self.http[0]
        if isinstance(answer, Exception):
            raise answer
        return answer
