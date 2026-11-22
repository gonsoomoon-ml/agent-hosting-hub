"""The calls of reject, of the cleanup, of the review's steps and of the deploy build, checked against the AWS
service models on this machine. The clients are real boto3 clients, each wrapped in a botocore Stubber. So every
operation name and parameter is validated against the model, and every answer against the operation's output shape;
a wrong parameter name fails here even though the fakes would accept it. No network and no credentials: the clients get dummy keys and a region."""
import datetime
import io
import json
import zipfile

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from platform_team.company_policy import policy_rollout
from platform_team.company_policy.policy_engine import ensure_policy, set_mode
from platform_team.hosting_review import agent_cleanup, deploy_build, reject_agent, review_steps
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform
from tests.fakes import ENV

ACCOUNT, REGION, NOW = "123456789012", "us-west-2", datetime.datetime(2026, 11, 22)
ENGINE, GW, REG, REC, TID = "hub_pe-abcdefghij", "hub-agents-abcdefghij", "abcdef123456", "rec123456789", "Tgt1234567"
S, AGENT = Settings(), "quality_agent"
ROLE, RUNTIME = S.agent_role(AGENT), S.runtime_name(AGENT)
RUNTIME_ID = f"{RUNTIME}-Ab12Cd34Ef"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/{RUNTIME_ID}"
LOG, PARAM = f"/aws/bedrock-agentcore/runtimes/{RUNTIME_ID}-DEFAULT", S.ssm("agents", AGENT, "runtime_arn")
BUCKET = S.bucket(ACCOUNT)
PACKAGE = S.package_key(AGENT, "3HL4kqtJlcpXroDTDmJ.rmSpXd3dIbrH")
P = Platform(account=ACCOUNT, agent_gw={"id": GW, "arn": "a", "url": "u"}, engine_id=ENGINE, registry_id=REG,
             bucket=BUCKET)


@pytest.fixture
def aws(monkeypatch, tmp_path):
    """Clients whose every call is answered by a Stubber; at the end each Stubber must have been used up."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setattr("time.sleep", lambda seconds: None)                 # a poll answered DELETE_IN_PROGRESS
    c = Clients(boto3.Session(region_name=REGION, aws_access_key_id="test-access-key",
                              aws_secret_access_key="example"))
    stubs = {name: Stubber(getattr(c, name)) for name in ("ctl", "logs", "iam", "ssm", "reg", "sfn", "s3")}
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


def _listed_runtime(status="READY", version="1"):
    """One item of ListAgentRuntimes' answer: this agent's Runtime."""
    return {"agentRuntimeArn": RUNTIME_ARN, "agentRuntimeId": RUNTIME_ID, "agentRuntimeVersion": version,
            "agentRuntimeName": RUNTIME, "description": "hosted agent", "lastUpdatedAt": NOW, "status": status}


def _runtime(status="READY", version="1", role_arn=f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"):
    """GetAgentRuntime's answer for this agent's Runtime."""
    return {**{k: v for k, v in _listed_runtime(status, version).items() if k != "description"}, "createdAt": NOW,
            "roleArn": role_arn, "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 900, "maxLifetime": 28800}}


def _find_runtime(stubs, status="READY"):
    """Find this agent's Runtime by name (every page of ListAgentRuntimes) and read it (its roleArn)."""
    other = {**_listed_runtime(), "agentRuntimeName": "other_team_runtime", "agentRuntimeId": "other_team_runtime-Zz98Yy76Xx",
             "agentRuntimeArn": RUNTIME_ARN.replace(RUNTIME_ID, "other_team_runtime-Zz98Yy76Xx")}
    stubs["ctl"].add_response("list_agent_runtimes", {"agentRuntimes": [other], "nextToken": "page-2"}, {"maxResults": 100})
    stubs["ctl"].add_response("list_agent_runtimes", {"agentRuntimes": [_listed_runtime(status)]},
                              {"maxResults": 100, "nextToken": "page-2"})
    stubs["ctl"].add_response("get_agent_runtime", _runtime(status), {"agentRuntimeId": RUNTIME_ID})


def _ownership_checks(stubs, role=True):
    """check_agent: the role's boundary, managed policies and instance profiles; the Runtime's role."""
    iam = stubs["iam"]
    if role:
        iam.add_response("get_role", {"Role": _role()}, {"RoleName": ROLE})
        iam.add_response("list_attached_role_policies", {"AttachedPolicies": [], "IsTruncated": False}, {"RoleName": ROLE})
        iam.add_response("list_instance_profiles_for_role", {"InstanceProfiles": [], "IsTruncated": False}, {"RoleName": ROLE})
    else:
        iam.add_client_error("get_role", "NoSuchEntity", http_status_code=404, expected_params={"RoleName": ROLE})
    _find_runtime(stubs)


def _removal(stubs, role=True, policy="entry_permit_quality_agent"):
    """remove_agent after its checks: one of each kind the review makes (the policy `policy`)."""
    ctl, logs, iam, ssm, s3 = (stubs[k] for k in ("ctl", "logs", "iam", "ssm", "s3"))
    pol = _policy(policy)
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
    _find_runtime(stubs)                                                      # found and checked again
    ctl.add_response("delete_agent_runtime", {"status": "DELETING", "agentRuntimeId": RUNTIME_ID}, {"agentRuntimeId": RUNTIME_ID})
    ctl.add_response("get_agent_runtime", _runtime("DELETING"), {"agentRuntimeId": RUNTIME_ID})
    ctl.add_client_error("get_agent_runtime", "ResourceNotFoundException", http_status_code=404,
                         expected_params={"agentRuntimeId": RUNTIME_ID})
    logs.add_response("describe_log_groups", {"logGroups": [{"logGroupName": LOG}]},
                      {"logGroupNamePrefix": f"/aws/bedrock-agentcore/runtimes/{RUNTIME}-"})
    logs.add_response("delete_log_group", {}, {"logGroupName": LOG})
    s3.add_response("list_object_versions", {
        "Versions": [{"Key": PACKAGE, "VersionId": "version-1", "IsLatest": False, "Size": 3, "LastModified": NOW}],
        "DeleteMarkers": [{"Key": PACKAGE, "VersionId": "marker-1", "IsLatest": True, "LastModified": NOW}],
        "IsTruncated": False}, {"Bucket": BUCKET, "Prefix": f"packages/{AGENT}/"})
    s3.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": PACKAGE, "VersionId": "version-1"})
    s3.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": PACKAGE, "VersionId": "marker-1"})
    if role:
        iam.add_response("list_role_policies", {"PolicyNames": ["agent"], "IsTruncated": False}, {"RoleName": ROLE})
        iam.add_response("delete_role_policy", {}, {"RoleName": ROLE, "PolicyName": "agent"})
        iam.add_response("delete_role", {}, {"RoleName": ROLE})
    else:
        iam.add_client_error("list_role_policies", "NoSuchEntity", http_status_code=404, expected_params={"RoleName": ROLE})
    ssm.add_response("get_parameters_by_path", {"Parameters": [{"Name": PARAM, "Type": "String", "Value": "v"}]},
                     {"Path": S.ssm("agents", AGENT), "Recursive": True})
    ssm.add_response("delete_parameter", {}, {"Name": PARAM})


REMOVED = ["policy entry_permit_quality_agent", "target QualityAgent", f"Runtime {RUNTIME}", f"log group {LOG}",
           f"package {PACKAGE}", f"role {ROLE}", f"parameter {PARAM}"]


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
    stubs["ctl"].add_response("list_policies", {"policies": [_policy("review_permit_quality_agent")]},
                              {"policyEngineId": ENGINE, "maxResults": 100})          # no entry permit: no version runs
    stubs["reg"].add_response("update_registry_record_status", {
        "registryArn": _record("x")["registryArn"], "recordArn": _record("x")["recordArn"], "recordId": REC,
        "status": "REJECTED", "statusReason": "why", "updatedAt": NOW},
        {"registryId": REG, "recordId": REC, "status": "REJECTED", "statusReason": "why"})
    _ownership_checks(stubs)                                                 # remove_agent checks again
    _removal(stubs, policy="review_permit_quality_agent")
    with_machine = Platform(**{**P.__dict__, "machine_arn": MACHINE})
    assert reject_agent.reject(c, S, with_machine, AGENT, "why") == {
        "status": "REJECTED", "removed": ["policy review_permit_quality_agent", *REMOVED[1:]]}


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


EXECUTIONS = MACHINE.replace(":stateMachine:", ":execution:")
READ_INPUT = {"event": {"detail": {"registryId": REG, "registryRecordId": REC}}, "execution": f"{EXECUTIONS}:this-one",
              "machine": MACHINE}


def _running(stubs, *reviews):
    """The RUNNING reviews (name, record ID, start), most recent first as ListExecutions gives them, and each one's input."""
    def item(name, start):
        return {"executionArn": f"{EXECUTIONS}:{name}", "stateMachineArn": MACHINE, "name": name, "status": "RUNNING",
                "startDate": start}
    stubs["sfn"].add_response("list_executions", {"executions": [item(n, start) for n, _, start in reviews]},
                              {"stateMachineArn": MACHINE, "statusFilter": "RUNNING"})
    for name, record, start in reviews:
        stubs["sfn"].add_response("describe_execution", {
            **item(name, start), "input": json.dumps({"detail": {"registryId": REG, "registryRecordId": record}})},
            {"executionArn": f"{EXECUTIONS}:{name}"})


def test_read_calls_match_the_service_model(aws):
    """final review I-1: Read reads the record's name and type from GetRegistryRecord's answer. Then it looks for an
    earlier review of the record (ListExecutions, DescribeExecution): here only this one runs."""
    c, stubs = aws
    stubs["reg"].add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    _running(stubs, ("this-one", REC, NOW))
    out = review_steps.read(READ_INPUT, c, ENV)
    assert out["spec"] == {k: APPLICATION[k] for k in review_steps.REVIEWED_FIELDS} and out["record"] == AGENT


def test_read_stops_at_an_earlier_review_of_the_record_with_calls_the_model_accepts(aws):
    c, stubs = aws
    stubs["reg"].add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    _running(stubs, ("this-one", REC, NOW + datetime.timedelta(seconds=40)), ("other-record", "rec999999999", NOW),
             ("older", REC, NOW))
    with pytest.raises(RuntimeError, match="^a review of this record is already running: older$"):
        review_steps.read(READ_INPUT, c, ENV)


APPROVE_CTX = {"registryId": REG, "recordId": REC, "record": AGENT, "target": "QualityAgent",
               "spec": {k: APPLICATION[k] for k in review_steps.REVIEWED_FIELDS},
               "applicationDigest": review_steps.application_digest(APPLICATION)}


def _made_policy(ctl, name, definition, mode="ACTIVE"):
    """ensure_policy for a policy that is not there yet: list, create, and the first look finds it ACTIVE."""
    pol = _policy(name)
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})
    ctl.add_response("create_policy", {**pol, "status": "CREATING"}, {
        "policyEngineId": ENGINE, "name": name, "validationMode": "IGNORE_ALL_FINDINGS", "enforcementMode": mode,
        "definition": definition})
    ctl.add_response("get_policy", pol, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    return pol


def _approval(reg):
    reg.add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    reg.add_response("update_registry_record_status", {
        "registryArn": _record("x")["registryArn"], "recordArn": _record("x")["recordArn"], "recordId": REC,
        "status": "APPROVED", "statusReason": "passed the hosting review", "updatedAt": NOW},
        {"registryId": REG, "recordId": REC, "status": "APPROVED", "statusReason": "passed the hosting review"})


def test_approve_calls_match_the_service_models(aws):
    """final review I-2: Approve reads the record (its status too) before and after making the entry permit.
    Between the first read and the entry permit it reads the company policies' modes: none are deployed here."""
    c, stubs = aws
    reg, ctl = stubs["reg"], stubs["ctl"]
    env = {**ENV, "ENGINE_ID": ENGINE}
    reg.add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    stubs["ssm"].add_response("get_parameters_by_path", {"Parameters": []}, {"Path": "/hub/policies"})
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})   # made by this run?
    pol = _made_policy(ctl, "entry_permit_quality_agent",
                       {"cedar": {"statement": review_steps.cedar.entry_permit("QualityAgent", ENV["AGENT_GW_ARN"])}})
    _approval(reg)
    out = review_steps.approve(dict(APPROVE_CTX), c, env)
    assert out["recordStatus"] == "APPROVED" and out["entryPolicy"] == pol["policyId"] and out["companyPolicies"] == {}


def test_approve_with_a_company_policy_deployed_calls_match_the_service_models(aws):
    """The path is passed as the approve role's policy names it: /<prefix>/policies, no trailing slash."""
    c, stubs = aws
    reg, ctl = stubs["reg"], stubs["ctl"]
    env = {**ENV, "ENGINE_ID": ENGINE}
    reg.add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    stubs["ssm"].add_response("get_parameters_by_path", {"Parameters": [
        {"Name": "/hub/policies/guard_prompt", "Type": "String", "Value": "LOG_ONLY", "Version": 1}]},
        {"Path": "/hub/policies"})
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})   # not in another mode
    _made_policy(ctl, "guard_prompt_quality_agent",
                 {"policy": {"statement": review_steps.cedar.guard_prompt("QualityAgent", ENV["AGENT_GW_ARN"])}},
                 mode="LOG_ONLY")
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})   # made by this run?
    _made_policy(ctl, "entry_permit_quality_agent",
                 {"cedar": {"statement": review_steps.cedar.entry_permit("QualityAgent", ENV["AGENT_GW_ARN"])}})
    _approval(reg)
    out = review_steps.approve(dict(APPROVE_CTX), c, env)
    assert out["companyPolicies"] == {"guard_prompt": "LOG_ONLY"} and out["recordStatus"] == "APPROVED"


AGENT_GW_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/{GW}"
ROLLOUT_P = Platform(account=ACCOUNT, agent_gw={"id": GW, "arn": AGENT_GW_ARN, "url": "u"}, engine_id=ENGINE)


def test_rollout_calls_match_the_service_models(aws):
    """The mode first (PutParameter), then the hosted agents (SSM and the agent gateway's targets), then the policy."""
    c, stubs = aws
    ssm, ctl = stubs["ssm"], stubs["ctl"]
    ssm.add_response("put_parameter", {"Version": 1, "Tier": "Standard"},
                     {"Name": "/hub/policies/guard_prompt", "Value": "LOG_ONLY", "Type": "String", "Overwrite": True})
    ssm.add_response("get_parameters_by_path", {"Parameters": [{"Name": PARAM, "Type": "String", "Value": RUNTIME_ARN}]},
                     {"Path": "/hub/agents", "Recursive": True})
    ctl.add_response("list_gateway_targets", {"items": [{"targetId": TID, "name": "QualityAgent", "status": "READY",
                                                         "createdAt": NOW, "updatedAt": NOW}]},
                     {"gatewayIdentifier": GW, "maxResults": 100})
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})
    _made_policy(ctl, "guard_prompt_quality_agent",
                 {"policy": {"statement": review_steps.cedar.guard_prompt("QualityAgent", AGENT_GW_ARN)}}, mode="LOG_ONLY")
    out = policy_rollout.rollout(c, S, ROLLOUT_P, "guard_prompt", "log-only", say=lambda line: None)
    assert out == {"policy": "guard_prompt", "mode": "LOG_ONLY", "agents": {AGENT: "created"}}


def test_remove_and_forget_calls_match_the_service_models(aws):
    c, stubs = aws
    ssm, ctl = stubs["ssm"], stubs["ctl"]
    ssm.add_response("delete_parameter", {}, {"Name": "/hub/policies/guard_prompt"})
    pol = _policy("guard_prompt_quality_agent")
    ctl.add_response("list_policies", {"policies": [pol, _policy("entry_permit_quality_agent")]},
                     {"policyEngineId": ENGINE, "maxResults": 100})
    ctl.add_response("delete_policy", {**pol, "status": "DELETING"}, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    ctl.add_client_error("get_policy", "ResourceNotFoundException", http_status_code=404,
                         expected_params={"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    assert policy_rollout.remove(c, S, ROLLOUT_P, "guard_prompt", say=lambda line: None) == {
        "policy": "guard_prompt", "agents": {AGENT: "removed"}}
    ssm.add_response("get_parameters_by_path", {"Parameters": [
        {"Name": "/hub/policies/guard_prompt", "Type": "String", "Value": "ACTIVE"}]}, {"Path": "/hub/policies"})
    ssm.add_response("delete_parameter", {}, {"Name": "/hub/policies/guard_prompt"})
    assert policy_rollout.forget(c, S) == ["/hub/policies/guard_prompt"]


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


def test_removal_without_the_role_calls_match_the_service_models(aws):
    c, stubs = aws
    _ownership_checks(stubs, role=False)
    _removal(stubs, role=False)
    assert agent_cleanup.remove_agent(c, S, P, AGENT) == [r for r in REMOVED if not r.startswith("role")]


def test_a_runtime_under_another_role_is_refused_before_anything_is_deleted(aws):
    c, stubs = aws
    stubs["iam"].add_client_error("get_role", "NoSuchEntity", http_status_code=404, expected_params={"RoleName": ROLE})
    stubs["ctl"].add_response("list_agent_runtimes", {"agentRuntimes": [_listed_runtime()]}, {"maxResults": 100})
    other = f"arn:aws:iam::{ACCOUNT}:role/hub-agent-release_review-role"
    stubs["ctl"].add_response("get_agent_runtime", _runtime(role_arn=other), {"agentRuntimeId": RUNTIME_ID})
    with pytest.raises(agent_cleanup.CleanupFailed, match="it runs under role hub-agent-release_review-role, not") as e:
        agent_cleanup.remove_agent(c, S, P, AGENT)
    assert e.value.removed == []


# ------------------------------------------------------------------ the deploy build

DEPLOY_ENV = {"AGENT": AGENT, "PREFIX": "hub", "AWS_REGION": REGION, "ROLE_ARN": f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
              "TOOL_GW_URL": f"https://{GW}.gateway.bedrock-agentcore.{REGION}.amazonaws.com/mcp",
              "MODEL_ID": S.model_id, "BUCKET": BUCKET, "CODE_KEY": APPLICATION["code_key"],
              "CODE_VERSION": APPLICATION["code_version"]}


def _made(version, created):
    """CreateAgentRuntime's or UpdateAgentRuntime's answer."""
    return {"agentRuntimeArn": RUNTIME_ARN, "agentRuntimeId": RUNTIME_ID, "agentRuntimeVersion": version,
            "createdAt": NOW, **({} if created else {"lastUpdatedAt": NOW}),
            "workloadIdentityDetails": {"workloadIdentityArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:"
                                                               f"workload-identity-directory/default/workload-identity/{RUNTIME}-abcdefghij"},
            "status": "CREATING" if created else "UPDATING"}


def _ready_and_written(ctl, ssm, version, status):
    ctl.add_response("get_agent_runtime", _runtime(status, version), {"agentRuntimeId": RUNTIME_ID})
    ctl.add_response("get_agent_runtime", _runtime("READY", version), {"agentRuntimeId": RUNTIME_ID})
    ssm.add_response("put_parameter", {"Version": int(version), "Tier": "Standard"},
                     {"Name": PARAM, "Value": RUNTIME_ARN, "Type": "String", "Overwrite": True})


def _submission() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.py", "M = 1\n")
        z.writestr("requirements.txt", "strands-agents==1.65.0  # the framework\n")
        z.writestr("uv.toml", "[pip]\nindex-url = 'http://127.0.0.1:9/evil-simple'\n")
    return buf.getvalue()


def _get_submission(stubs, body: bytes):
    stubs["s3"].add_response("get_object", {"Body": StreamingBody(io.BytesIO(body), len(body)), "ContentLength": len(body)},
                             {"Bucket": BUCKET, "Key": DEPLOY_ENV["CODE_KEY"], "VersionId": DEPLOY_ENV["CODE_VERSION"]})


def test_the_deploy_builds_calls_match_the_service_models(aws, monkeypatch, tmp_path, capsys):
    """main(): read the submission, install (faked), upload the package, create the Runtime, wait, write the ARN."""
    c, stubs = aws
    monkeypatch.setattr(deploy_build.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    installed = []

    def install(cmd, cwd):
        assert cmd == deploy_build.install_command(tmp_path / "requirements.txt", tmp_path / "site") and cwd == tmp_path
        assert (tmp_path / "requirements.txt").read_text() == "strands-agents==1.65.0\n"     # the platform's own file
        assert not (tmp_path / "submission" / "uv.toml").exists()
        (tmp_path / "site" / "strands").mkdir(parents=True)
        (tmp_path / "site" / "strands" / "__init__.py").write_text("S = 1\n")
        installed.append(cmd)
    monkeypatch.setattr(deploy_build, "run", install)
    _get_submission(stubs, _submission())
    stubs["s3"].add_response("put_object", {"ETag": '"abcdef"', "VersionId": "package-version-1"},
                             {"Bucket": BUCKET, "Key": PACKAGE, "Body": ANY})
    ctl = stubs["ctl"]
    ctl.add_response("list_agent_runtimes", {"agentRuntimes": []}, {"maxResults": 100})
    ctl.add_response("create_agent_runtime", _made("1", created=True),
                     {"agentRuntimeName": RUNTIME, **deploy_build.runtime_config(DEPLOY_ENV, PACKAGE)})
    _ready_and_written(ctl, stubs["ssm"], "1", "CREATING")
    out = deploy_build.main(DEPLOY_ENV, c)
    assert installed and out["created"] is True and out["runtimeArn"] == RUNTIME_ARN and out["version"] == "1"
    with zipfile.ZipFile(tmp_path / "package.zip") as z:
        assert z.namelist() == ["main.py", "strands/__init__.py"]
    assert f"package uploaded: s3://{BUCKET}/{PACKAGE}" in capsys.readouterr().out


def test_a_later_deploy_updates_the_runtime_and_its_calls_match_the_service_models(aws):
    c, stubs = aws
    ctl = stubs["ctl"]
    ctl.add_response("list_agent_runtimes", {"agentRuntimes": [_listed_runtime(version="1")]}, {"maxResults": 100})
    ctl.add_response("update_agent_runtime", _made("2", created=False),
                     {"agentRuntimeId": RUNTIME_ID, **deploy_build.runtime_config(DEPLOY_ENV, PACKAGE)})
    ctl.add_response("get_agent_runtime", _runtime("READY", "1"), {"agentRuntimeId": RUNTIME_ID})   # not the new version yet
    _ready_and_written(ctl, stubs["ssm"], "2", "UPDATING")
    out = deploy_build.deploy(c, DEPLOY_ENV, PACKAGE)
    assert (out["created"], out["version"], out["runtimeId"]) == (False, "2", RUNTIME_ID)


def test_a_submission_the_rules_refuse_is_not_installed(aws, monkeypatch, tmp_path):
    c, stubs = aws
    monkeypatch.setattr(deploy_build.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setattr(deploy_build, "run", lambda cmd, cwd: pytest.fail("installed a refused submission"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.py", "M = 1\n")
        z.writestr("requirements.txt", "--index-url http://127.0.0.1:9/evil-simple\nstrands-agents\n")
    _get_submission(stubs, buf.getvalue())
    with pytest.raises(SystemExit, match="deploy refused: requirements.txt: pip options are not allowed"):
        deploy_build.main(DEPLOY_ENV, c)


def test_set_mode_calls_match_the_service_models(aws):
    c, stubs = aws
    pol = _policy("guard_prompt_quality_agent")
    stubs["ctl"].add_response("update_policy", {**pol, "status": "UPDATING"},
                              {"policyEngineId": ENGINE, "policyId": pol["policyId"], "enforcementMode": "LOG_ONLY"})
    stubs["ctl"].add_response("get_policy", pol, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    set_mode(c, ENGINE, pol["policyId"], "LOG_ONLY")


def test_a_policy_in_another_mode_is_listed_and_switched_with_calls_the_models_accept(aws):
    c, stubs = aws
    pol = _policy("guard_prompt_quality_agent")
    stubs["ctl"].add_response("list_policies", {"policies": [{**pol, "enforcementMode": "LOG_ONLY"}]},
                              {"policyEngineId": ENGINE, "maxResults": 100})
    stubs["ctl"].add_response("get_policy", pol, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    stubs["ctl"].add_response("update_policy", {**pol, "status": "UPDATING"},
                              {"policyEngineId": ENGINE, "policyId": pol["policyId"], "enforcementMode": "ACTIVE"})
    stubs["ctl"].add_response("get_policy", pol, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    assert ensure_policy(c, ENGINE, pol["name"], "forbid ...;", guardrail=True, mode="ACTIVE") == pol["policyId"]


# ------------------------------------------------------------------ the review of a new version

def test_grant_removes_a_dropped_tools_permit_with_calls_the_models_accept(aws):
    """The permits of this agent for tools the application no longer names go first; then the named ones are made."""
    c, stubs = aws
    iam, ctl = stubs["iam"], stubs["ctl"]
    env = {**ENV, "ENGINE_ID": ENGINE}
    iam.add_response("get_role", {"Role": _role()}, {"RoleName": ROLE})
    iam.add_response("put_role_policy", {}, {"RoleName": ROLE, "PolicyName": "agent", "PolicyDocument": ANY})
    kept, dropped, other = (_policy(n) for n in ("tool_quality_agent_Parts_get_part_spec",
                                                  "tool_quality_agent_Parts_get_test_result", "tool_quality_Parts_get_test_result"))
    ctl.add_response("list_policies", {"policies": [kept, dropped, other]}, {"policyEngineId": ENGINE, "maxResults": 100})
    ctl.add_response("delete_policy", {**dropped, "status": "DELETING"}, {"policyEngineId": ENGINE, "policyId": dropped["policyId"]})
    ctl.add_client_error("get_policy", "ResourceNotFoundException", http_status_code=404,
                         expected_params={"policyEngineId": ENGINE, "policyId": dropped["policyId"]})
    ctl.add_response("list_policies", {"policies": [kept, other]}, {"policyEngineId": ENGINE, "maxResults": 100})
    ctl.add_response("get_policy", kept, {"policyEngineId": ENGINE, "policyId": kept["policyId"]})
    out = review_steps.grant(dict(APPROVE_CTX), c, env)
    assert out["removedToolPolicies"] == ["tool_quality_agent_Parts_get_test_result"]
    assert out["toolPolicies"] == [kept["policyId"]] and out["roleArn"] == _role()["Arn"]


def test_approve_takes_back_the_entry_permit_it_made_with_calls_the_models_accept(aws):
    c, stubs = aws
    reg, ctl = stubs["reg"], stubs["ctl"]
    env = {**ENV, "ENGINE_ID": ENGINE}
    reg.add_response("get_registry_record", _full_record("PENDING_APPROVAL"), {"registryId": REG, "recordId": REC})
    stubs["ssm"].add_response("get_parameters_by_path", {"Parameters": []}, {"Path": "/hub/policies"})
    ctl.add_response("list_policies", {"policies": []}, {"policyEngineId": ENGINE, "maxResults": 100})   # not there before
    pol = _made_policy(ctl, "entry_permit_quality_agent",
                       {"cedar": {"statement": review_steps.cedar.entry_permit("QualityAgent", ENV["AGENT_GW_ARN"])}})
    reg.add_response("get_registry_record", _full_record("DRAFT"), {"registryId": REG, "recordId": REC})   # the team edited it
    ctl.add_response("delete_policy", {**pol, "status": "DELETING"}, {"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    ctl.add_client_error("get_policy", "ResourceNotFoundException", http_status_code=404,
                         expected_params={"policyEngineId": ENGINE, "policyId": pol["policyId"]})
    with pytest.raises(RuntimeError, match="record quality_agent is DRAFT, not PENDING_APPROVAL"):
        review_steps.approve(dict(APPROVE_CTX), c, env)


def test_rejecting_a_new_version_calls_match_the_service_models(aws):
    c, stubs = aws
    stubs["reg"].add_response("list_registry_records", {"registryRecords": [_record("PENDING_APPROVAL")]},
                              {"registryId": REG, "maxResults": 100})
    stubs["sfn"].add_response("list_executions", {"executions": []}, {"stateMachineArn": MACHINE, "statusFilter": "RUNNING"})
    _ownership_checks(stubs)
    stubs["ctl"].add_response("list_policies", {"policies": [_policy("entry_permit_quality_agent"),
                                                             _policy("tool_quality_agent_Parts_get_part_spec")]},
                              {"policyEngineId": ENGINE, "maxResults": 100})
    stubs["reg"].add_response("update_registry_record_status", {
        "registryArn": _record("x")["registryArn"], "recordArn": _record("x")["recordArn"], "recordId": REC,
        "status": "REJECTED", "statusReason": "why", "updatedAt": NOW},
        {"registryId": REG, "recordId": REC, "status": "REJECTED", "statusReason": "why"})
    with_machine = Platform(**{**P.__dict__, "machine_arn": MACHINE})
    assert reject_agent.reject(c, S, with_machine, AGENT, "why") == {
        "status": "REJECTED", "removed": [], "note": "an approved version is running and was left as it is"}
