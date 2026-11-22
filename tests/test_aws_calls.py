"""The calls of reject and of the cleanup, checked against the AWS service models on this machine. The clients are
real boto3 clients, each wrapped in a botocore Stubber. So every operation name and parameter is validated against
the model, and every answer against the operation's output shape; a wrong parameter name fails here even though the
fakes would accept it. No network and no credentials: the clients get dummy keys and a region."""
import datetime
import json

import boto3
import pytest
from botocore.stub import Stubber

from platform_team.hosting_review import agent_cleanup, reject_agent, review_steps
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform
from tests.fakes import ENV

ACCOUNT, REGION, NOW = "111122223333", "us-west-2", datetime.datetime(2026, 11, 22)
ENGINE, GW, REG, REC, TID = "hub_pe-abcdefghij", "hub-agents-abcdefghij", "abcdef123456", "rec123456789", "Tgt1234567"
S, AGENT = Settings(), "quality_agent"
ROLE, STACK, RUNTIME = S.agent_role(AGENT), S.stack_name(AGENT), S.runtime_name(AGENT)
RUNTIME_ID = f"{RUNTIME}-Ab12Cd34Ef"
LOG, PARAM = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT", S.ssm("agents", AGENT, "runtime_arn")
P = Platform(account=ACCOUNT, agent_gw={"id": GW, "arn": "a", "url": "u"}, engine_id=ENGINE, registry_id=REG)
RUNTIME_TYPE = "AWS::BedrockAgentCore::Runtime"


@pytest.fixture
def aws(monkeypatch, tmp_path):
    """Clients whose every call is answered by a Stubber; at the end each Stubber must have been used up."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setattr("time.sleep", lambda seconds: None)                 # a poll answered DELETE_IN_PROGRESS
    c = Clients(boto3.Session(region_name=REGION, aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
                              aws_secret_access_key="example"))
    stubs = {name: Stubber(getattr(c, name)) for name in ("ctl", "cfn", "logs", "iam", "ssm", "reg", "sfn")}
    for st in stubs.values():
        st.activate()
    yield c, stubs
    for st in stubs.values():
        st.assert_no_pending_responses()
        st.deactivate()


def _record(status):
    return {"registryArn": f"arn:aws:agent-registry:{REGION}:{ACCOUNT}:registry/{REG}",
            "recordArn": f"arn:aws:agent-registry:{REGION}:{ACCOUNT}:registry/{REG}/record/{REC}", "recordId": REC,
            "name": AGENT, "recordType": "AGENT", "recordVersion": "1.0.0", "status": status,
            "createdAt": NOW, "updatedAt": NOW}


def _policy(name):
    pid = f"{name}-abcdefghij"
    return {"policyId": pid, "name": name, "policyEngineId": ENGINE, "createdAt": NOW, "updatedAt": NOW,
            "status": "ACTIVE", "statusReasons": [], "definition": {"cedar": {"statement": "permit (principal, action, resource);"}},
            "policyArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:policy-engine/{ENGINE}/policy/{pid}"}


def _role():
    return {"Path": "/", "RoleName": ROLE, "RoleId": "AROAEXAMPLEEXAMPLE01", "CreateDate": NOW,
            "Arn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
            "PermissionsBoundary": {"PermissionsBoundaryType": "PermissionsBoundaryPolicy",
                                    "PermissionsBoundaryArn": f"arn:aws:iam::{ACCOUNT}:policy/{S.agent_boundary}"}}


def _runtime_resource(**changes):
    return {"LogicalResourceId": "AgentRuntime", "PhysicalResourceId": RUNTIME_ID, "ResourceType": RUNTIME_TYPE,
            "LastUpdatedTimestamp": NOW, "ResourceStatus": "CREATE_COMPLETE", **changes}


def _ownership_checks(stubs, role=True):
    """check_agent: the role's boundary, managed policies and instance profiles; the stack's Runtime."""
    iam, cfn = stubs["iam"], stubs["cfn"]
    if role:
        iam.add_response("get_role", {"Role": _role()}, {"RoleName": ROLE})
        iam.add_response("list_attached_role_policies", {"AttachedPolicies": [], "IsTruncated": False}, {"RoleName": ROLE})
        iam.add_response("list_instance_profiles_for_role", {"InstanceProfiles": [], "IsTruncated": False}, {"RoleName": ROLE})
    else:
        iam.add_client_error("get_role", "NoSuchEntity", http_status_code=404, expected_params={"RoleName": ROLE})
    cfn.add_response("describe_stacks", {"Stacks": [{"StackName": STACK, "CreationTime": NOW,
                                                     "StackStatus": "CREATE_COMPLETE"}]}, {"StackName": STACK})
    cfn.add_response("list_stack_resources", {"StackResourceSummaries": [_runtime_resource()]}, {"StackName": STACK})


def _removal(stubs, role=True):
    """remove_agent after its checks: one of each kind the review makes."""
    ctl, cfn, logs, iam, ssm = (stubs[k] for k in ("ctl", "cfn", "logs", "iam", "ssm"))
    pol = _policy("entry_permit_quality_agent")
    ctl.add_response("list_policies", {"policies": [pol]}, {"policyEngineId": ENGINE, "maxResults": 100})
    ctl.add_response("delete_policy", {**pol, "status": "DELETING"}, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    ctl.add_client_error("get_policy", "ResourceNotFoundException", http_status_code=404,
                         expected_params={"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    ctl.add_response("list_gateway_targets", {"items": [{"targetId": TID, "name": "QualityAgent", "status": "READY",
                                                         "createdAt": NOW, "updatedAt": NOW}]},
                     {"gatewayIdentifier": GW, "maxResults": 100})
    ctl.add_response("delete_gateway_target", {"gatewayArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/{GW}",
                                               "targetId": TID, "status": "DELETING"},
                     {"gatewayIdentifier": GW, "targetId": TID})
    ctl.add_client_error("get_gateway_target", "ResourceNotFoundException", http_status_code=404,
                         expected_params={"gatewayIdentifier": GW, "targetId": TID})
    stack = {"StackName": STACK, "CreationTime": NOW}
    cfn.add_response("describe_stacks", {"Stacks": [{**stack, "StackStatus": "CREATE_COMPLETE"}]}, {"StackName": STACK})
    cfn.add_response("delete_stack", {}, {"StackName": STACK})
    cfn.add_response("describe_stacks", {"Stacks": [{**stack, "StackStatus": "DELETE_IN_PROGRESS"}]}, {"StackName": STACK})
    cfn.add_client_error("describe_stacks", "ValidationError", f"Stack with id {STACK} does not exist",
                         expected_params={"StackName": STACK})
    logs.add_response("describe_log_groups", {"logGroups": [{"logGroupName": LOG}]},
                      {"logGroupNamePrefix": f"/aws/bedrock-agentcore/runtimes/{RUNTIME}-"})
    logs.add_response("delete_log_group", {}, {"logGroupName": LOG})
    if role:
        iam.add_response("list_role_policies", {"PolicyNames": ["agent"], "IsTruncated": False}, {"RoleName": ROLE})
        iam.add_response("delete_role_policy", {}, {"RoleName": ROLE, "PolicyName": "agent"})
        iam.add_response("delete_role", {}, {"RoleName": ROLE})
    else:
        iam.add_client_error("list_role_policies", "NoSuchEntity", http_status_code=404, expected_params={"RoleName": ROLE})
    ssm.add_response("get_parameters_by_path", {"Parameters": [{"Name": PARAM, "Type": "String", "Value": "v"}]},
                     {"Path": S.ssm("agents", AGENT), "Recursive": True})
    ssm.add_response("delete_parameter", {}, {"Name": PARAM})


REMOVED = ["policy entry_permit_quality_agent", "target QualityAgent", f"stack {STACK}", f"log group {LOG}",
           f"role {ROLE}", f"parameter {PARAM}"]


MACHINE = f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:hub-review"


def test_reject_calls_match_the_service_models(aws):
    c, stubs = aws
    stubs["reg"].add_response("list_registry_records", {"registryRecords": [_record("PENDING_APPROVAL")]},
                              {"registryId": REG, "maxResults": 100})
    other = f"arn:aws:states:{REGION}:{ACCOUNT}:execution:hub-review:other"          # final review M-3: is a review running?
    stubs["sfn"].add_response("list_executions", {"executions": [{
        "executionArn": other, "stateMachineArn": MACHINE, "name": "other", "status": "RUNNING", "startDate": NOW}]},
        {"stateMachineArn": MACHINE, "statusFilter": "RUNNING"})
    stubs["sfn"].add_response("describe_execution", {
        "executionArn": other, "stateMachineArn": MACHINE, "name": "other", "status": "RUNNING", "startDate": NOW,
        "input": json.dumps({"detail": {"registryId": REG, "registryRecordId": "rec999999999"}})}, {"executionArn": other})
    _ownership_checks(stubs)                                                 # reject checks before the status changes
    stubs["reg"].add_response("update_registry_record_status", {
        "registryArn": _record("x")["registryArn"], "recordArn": _record("x")["recordArn"], "recordId": REC,
        "status": "REJECTED", "statusReason": "why", "updatedAt": NOW},
        {"registryId": REG, "recordId": REC, "status": "REJECTED", "statusReason": "why"})
    _ownership_checks(stubs)                                                 # remove_agent checks again
    _removal(stubs)
    with_machine = Platform(**{**P.__dict__, "machine_arn": MACHINE})
    assert reject_agent.reject(c, S, with_machine, AGENT, "why") == {"status": "REJECTED", "removed": REMOVED}


def test_clean_agents_calls_match_the_service_models(aws, monkeypatch):
    c, stubs = aws
    monkeypatch.setattr(agent_cleanup, "load", lambda s, c=None: P)
    stubs["reg"].add_response("list_registry_records", {"registryRecords": [_record("APPROVED")]},
                              {"registryId": REG, "maxResults": 100})
    stubs["ssm"].add_response("get_parameters_by_path", {"Parameters": []}, {"Path": S.ssm("agents"), "Recursive": True})
    stubs["iam"].add_response("list_roles", {"Roles": [{k: v for k, v in _role().items() if k != "PermissionsBoundary"}],
                                             "IsTruncated": False}, {})
    stubs["iam"].add_response("get_role", {"Role": _role()}, {"RoleName": ROLE})       # is the role this hub's?
    _ownership_checks(stubs)
    _removal(stubs)
    stubs["reg"].add_response("list_registry_records", {"registryRecords": [_record("APPROVED")]},
                              {"registryId": REG, "maxResults": 100})
    stubs["reg"].add_response("delete_registry_record", {}, {"registryId": REG, "recordId": REC})
    stubs["reg"].add_response("list_registry_records", {"registryRecords": []}, {"registryId": REG, "maxResults": 100})
    assert agent_cleanup.clean_agents(S, c, say=pytest.fail) == [*REMOVED, f"record {AGENT}"]


APPLICATION = {"name": AGENT, "team": "appliance", "framework": "strands", "tools": ["Parts___get_part_spec"],
               "code_key": f"submissions/appliance/{AGENT}/agent.zip", "code_version": "3HL4kqtJlcpXroDTDmJ.rmSpXd3dIbrH",
               "description": "Answers questions about inspection results."}


def _full_record(status, app=APPLICATION):
    """GetRegistryRecord's answer: the record with the application in its custom descriptor, as publish writes it."""
    return {**_record(status), "description": "quality_agent: agent of team appliance",
            "descriptors": {"custom": {"data": json.dumps(app)}}}


def test_read_calls_match_the_service_model(aws):
    """final review I-1: Read reads the record's name and type from GetRegistryRecord's answer."""
    c, stubs = aws
    stubs["reg"].add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    out = review_steps.read({"detail": {"registryId": REG, "registryRecordId": REC}}, c, ENV)
    assert out["spec"] == {k: APPLICATION[k] for k in review_steps.REVIEWED_FIELDS} and out["record"] == AGENT


def test_approve_calls_match_the_service_models(aws):
    """final review I-2: Approve reads the record (its status too) before and after making the entry permit."""
    c, stubs = aws
    reg, ctl = stubs["reg"], stubs["ctl"]
    ctx = {"registryId": REG, "recordId": REC, "record": AGENT, "target": "QualityAgent",
           "spec": {k: APPLICATION[k] for k in review_steps.REVIEWED_FIELDS},
           "applicationDigest": review_steps.application_digest(APPLICATION)}
    env = {**ENV, "ENGINE_ID": ENGINE}
    pol = _policy("entry_permit_quality_agent")
    reg.add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})
    ctl.add_response("create_policy", {**pol, "status": "CREATING"}, {
        "policyEngineId": ENGINE, "name": pol["name"], "validationMode": "IGNORE_ALL_FINDINGS", "enforcementMode": "ACTIVE",
        "definition": {"cedar": {"statement": review_steps.cedar.entry_permit("QualityAgent", ENV["AGENT_GW_ARN"])}}})
    ctl.add_response("get_policy", pol, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    reg.add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    reg.add_response("update_registry_record_status", {
        "registryArn": _record("x")["registryArn"], "recordArn": _record("x")["recordArn"], "recordId": REC,
        "status": "APPROVED", "statusReason": "passed the hosting review", "updatedAt": NOW},
        {"registryId": REG, "recordId": REC, "status": "APPROVED", "statusReason": "passed the hosting review"})
    out = review_steps.approve(ctx, c, env)
    assert out["recordStatus"] == "APPROVED" and out["entryPolicy"] == pol["policyId"]


RUNTIME_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/{RUNTIME_ID}"


def _target(arn):
    """GetGatewayTarget's answer for a Runtime target that points to `arn`."""
    return {"gatewayArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/{GW}", "targetId": TID,
            "createdAt": NOW, "updatedAt": NOW, "status": "READY", "statusReasons": [], "name": "QualityAgent",
            "targetConfiguration": {"http": {"agentcoreRuntime": {"arn": arn, "qualifier": "DEFAULT"}}},
            "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]}


def test_a_found_target_is_kept_only_when_it_points_to_this_runtime(aws):
    """final review M-2: ensure_runtime_target reads the found target's Runtime from GetGatewayTarget's answer."""
    from platform_team.agent_gateway.gateway_targets import ensure_runtime_target
    c, stubs = aws
    ctl = stubs["ctl"]
    listed = {"items": [{"targetId": TID, "name": "QualityAgent", "status": "READY", "createdAt": NOW, "updatedAt": NOW}]}
    ctl.add_response("list_gateway_targets", listed, {"gatewayIdentifier": GW, "maxResults": 100})
    ctl.add_response("get_gateway_target", _target(RUNTIME_ARN), {"gatewayIdentifier": GW, "targetId": TID})
    ctl.add_response("get_gateway_target", _target(RUNTIME_ARN), {"gatewayIdentifier": GW, "targetId": TID})   # READY
    assert ensure_runtime_target(c, GW, "QualityAgent", RUNTIME_ARN) == TID
    other = RUNTIME_ARN.replace("Ab12Cd34Ef", "Zz98Yy76Xx")
    ctl.add_response("list_gateway_targets", listed, {"gatewayIdentifier": GW, "maxResults": 100})
    ctl.add_response("get_gateway_target", _target(other), {"gatewayIdentifier": GW, "targetId": TID})
    with pytest.raises(RuntimeError, match="already exists and points to .*Zz98Yy76Xx"):
        ensure_runtime_target(c, GW, "QualityAgent", RUNTIME_ARN)


def test_a_stack_without_a_made_runtime_is_checked_by_its_template(aws):
    c, stubs = aws
    stubs["iam"].add_client_error("get_role", "NoSuchEntity", http_status_code=404, expected_params={"RoleName": ROLE})
    stubs["cfn"].add_response("describe_stacks", {"Stacks": [{"StackName": STACK, "CreationTime": NOW,
                                                              "StackStatus": "ROLLBACK_COMPLETE"}]}, {"StackName": STACK})
    resource = {k: v for k, v in _runtime_resource(ResourceStatus="DELETE_COMPLETE").items() if k != "PhysicalResourceId"}
    stubs["cfn"].add_response("list_stack_resources", {"StackResourceSummaries": [resource]}, {"StackName": STACK})
    template = {"Resources": {"AgentRuntime": {"Type": RUNTIME_TYPE, "Properties": {"AgentRuntimeName": RUNTIME}}}}
    stubs["cfn"].add_response("get_template", {"TemplateBody": json.dumps(template)}, {"StackName": STACK})
    _removal(stubs, role=False)
    assert agent_cleanup.remove_agent(c, S, P, AGENT) == [r for r in REMOVED if not r.startswith("role")]
