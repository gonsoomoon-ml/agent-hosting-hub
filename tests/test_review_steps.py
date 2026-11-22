import pytest
from platform_team.hosting_review import review_steps as steps
from tests.fakes import FakeClients, ENV, CTX

def test_read_refuses_an_application_with_an_unknown_tool():       # Review Focus 3
    c = FakeClients(record_spec={"name": "quality_agent", "team": "appliance", "framework": "strands",
                                 "tools": ["Parts___nope"], "code_key": "k", "code_version": "v"})
    with pytest.raises(ValueError, match="tool not in the catalog: Parts___nope"):
        steps.read({"detail": {"registryId": "r", "registryRecordId": "x"}}, c, ENV)

def test_grant_creates_the_role_and_one_permit_per_tool():
    c = FakeClients()
    out = steps.grant(dict(CTX), c, ENV)
    assert out["roleArn"].endswith(":role/hub-agent-quality_agent-role")
    assert [p["name"] for p in c.created_policies] == ["tool_permit_quality_agent_Parts_get_part_spec",
                                                        "tool_permit_quality_agent_Quality_get_inspection_data"]
    assert 'action == AgentCore::Action::"Parts___get_part_spec"' in c.created_policies[0]["statement"]

def test_policy_conflict_is_kept():                                  # Review Focus 1
    c = FakeClients(existing_policies={"tool_permit_quality_agent_Parts_get_part_spec"})
    steps.grant(dict(CTX), c, ENV)
    assert "tool_permit_quality_agent_Parts_get_part_spec" not in [p["name"] for p in c.created_policies]

def test_failed_policy_is_removed_and_reason_raised():               # Review Focus 2
    c = FakeClients(policy_status="CREATE_FAILED", policy_reasons=["Insufficient permissions to call gateway"])
    with pytest.raises(RuntimeError, match="Insufficient permissions to call gateway"):
        steps.grant(dict(CTX), c, ENV)
    assert c.deleted_policies == [c.created_policies[0]["id"]]

def test_entry_lets_only_the_test_call_in_before_approval():
    c = FakeClients(runtime_arn="arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/hub_quality_agent-x")
    out = steps.entry({**CTX, "roleArn": "r"}, c, ENV)
    names = [p["name"] for p in c.created_policies]
    assert names == ["entry_permit_review_quality_agent", "guard_secret_quality_agent"] and out["target"] == "QualityAgent"
    assert "assumed-role/hub-review-testcall-role" in c.created_policies[0]["statement"]

def test_testcall_fails_the_review_when_a_secret_is_not_refused():
    c = FakeClients(http=[(200, '{"answer": "ok"}'), (200, '{"answer": "leaked"}')])
    with pytest.raises(RuntimeError, match="was not refused"):
        steps.testcall({**CTX, "target": "QualityAgent"}, c, {**ENV, "TESTCALL_WAIT": "0"})
