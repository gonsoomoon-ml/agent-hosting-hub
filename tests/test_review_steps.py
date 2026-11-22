import types
import urllib.error
import pytest
from platform_team.hosting_review import lambda_handler, review_steps as steps
from platform_team.shared_code.aws_helpers import Deadline, OutOfTime
from tests.fakes import FakeClients, ENV, CTX, SPEC

@pytest.fixture(autouse=True)
def patched_post(monkeypatch):
    """The steps' signed_post answers from the FakeClients built in the test."""
    monkeypatch.setattr(steps, "signed_post", lambda *a, **kw: FakeClients.latest.post(*a, **kw))

def test_read_refuses_an_application_with_an_unknown_tool():       # Review Focus 3
    c = FakeClients(record_spec={"name": "quality_agent", "team": "appliance", "framework": "strands",
                                 "tools": ["Parts___nope"], "code_key": "k", "code_version": "v"})
    with pytest.raises(ValueError, match="tool not in the catalog: Parts___nope"):
        steps.read({"detail": {"registryId": "r", "registryRecordId": "x"}}, c, ENV)

def test_grant_creates_the_role_and_one_permit_per_tool():
    c = FakeClients()
    out = steps.grant(dict(CTX), c, ENV)
    assert out["roleArn"].endswith(":role/hub-agent-quality_agent-role")
    assert [p["name"] for p in c.created_policies] == ["tool_quality_agent_Parts_get_part_spec",
                                                        "tool_quality_agent_Quality_get_inspection_data"]
    assert 'action == AgentCore::Action::"Parts___get_part_spec"' in c.created_policies[0]["statement"]

def test_policy_conflict_is_kept():                                  # Review Focus 1
    c = FakeClients(existing_policies={"tool_quality_agent_Parts_get_part_spec"})
    steps.grant(dict(CTX), c, ENV)
    assert "tool_quality_agent_Parts_get_part_spec" not in [p["name"] for p in c.created_policies]

def test_failed_policy_is_removed_and_reason_raised():               # Review Focus 2
    c = FakeClients(policy_status="CREATE_FAILED", policy_reasons=["Insufficient permissions to call gateway"])
    with pytest.raises(RuntimeError, match="Insufficient permissions to call gateway"):
        steps.grant(dict(CTX), c, ENV)
    assert c.deleted_policies == [c.created_policies[0]["id"]]

def test_entry_lets_only_the_test_call_in_before_approval():
    c = FakeClients(runtime_arn="arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/hub_quality_agent-x")
    out = steps.entry({**CTX, "roleArn": "r"}, c, ENV)
    names = [p["name"] for p in c.created_policies]
    assert names == ["review_permit_quality_agent", "guard_secret_quality_agent"] and out["target"] == "QualityAgent"
    assert "assumed-role/hub-review-testcall-role" in c.created_policies[0]["statement"]

def test_testcall_fails_the_review_when_a_secret_is_not_refused():
    c = FakeClients(http=[(200, '{"answer": "ok"}'), (200, '{"answer": "leaked"}')])
    with pytest.raises(RuntimeError, match="was not refused"):
        steps.testcall({**CTX, "target": "QualityAgent"}, c, {**ENV, "TESTCALL_WAIT": "0"})

def test_testcall_retries_a_call_that_raises_a_network_error():
    c = FakeClients(http=[urllib.error.URLError("connection reset"), TimeoutError("timed out"),
                          (200, '{"answer": "ok"}'), (403, "refused")])
    out = steps.testcall({**CTX, "target": "QualityAgent"}, c, {**ENV, "TESTCALL_WAIT": "0"})
    assert out["testCall"]["normal"] == 200 and out["testCall"]["with_secret"] == 403
    assert len(c.posts) == 4

# ------------------------------------------------------------------ the step's deadline (fix round 1)

class Clock:
    """Fake time: sleep moves the clock, nothing waits."""
    def __init__(self):
        self.t = 1000.0
    def now(self):
        return self.t
    def sleep(self, seconds):
        self.t += seconds

@pytest.fixture
def clock(monkeypatch):
    k = Clock()
    monkeypatch.setattr("time.monotonic", k.now)
    monkeypatch.setattr("time.sleep", k.sleep)
    return k

def lambda_deadline(seconds_left):
    """The deadline the Lambda handler gives a step that has this much Lambda time left."""
    return Deadline(seconds_left - lambda_handler.MARGIN)

def test_a_policy_that_would_outlast_the_lambda_is_dropped_with_the_steps_own_error(clock):
    c, t0, lambda_left = FakeClients(policy_status="CREATING"), clock.t, 260     # the policy never becomes ACTIVE
    with pytest.raises(TimeoutError, match="deleted"):
        steps.grant(dict(CTX), c, ENV, deadline=lambda_deadline(lambda_left))
    assert [p["name"] for p in c.created_policies] == ["tool_quality_agent_Parts_get_part_spec"]
    assert c.deleted_policies == [c.created_policies[0]["id"]]                      # ensure_policy's cleanup ran
    assert clock.t - t0 < lambda_left                                               # before Lambda would stop the step

def test_no_time_left_stops_the_step_before_it_makes_anything(clock):
    c = FakeClients()
    with pytest.raises(OutOfTime, match="no time left"):
        steps.approve({**CTX, "target": "QualityAgent"}, c, ENV, deadline=lambda_deadline(lambda_handler.MARGIN))
    assert c.created_policies == [] and c.record_status == "PENDING_APPROVAL"

def test_entry_shares_one_deadline_between_the_target_and_its_policies(clock):
    c = FakeClients(runtime_arn="arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/hub_quality_agent-x",
                    policy_status="CREATING")
    t0, lambda_left = clock.t, 300           # less than the target's and the policies' ceilings together
    with pytest.raises(TimeoutError, match="deleted"):
        steps.entry({**CTX, "roleArn": "r"}, c, ENV, deadline=lambda_deadline(lambda_left))
    assert clock.t - t0 < lambda_left and len(c.created_policies) == 1 and c.deleted_policies == [c.created_policies[0]["id"]]

def test_testcall_stops_retrying_before_the_lambda_deadline(clock):
    c, t0, lambda_left = FakeClients(http=[(503, "not ready")]), clock.t, 160
    with pytest.raises(RuntimeError, match="test call failed: 503"):
        steps.testcall({**CTX, "target": "QualityAgent"}, c, ENV, deadline=lambda_deadline(lambda_left))
    assert 1 < len(c.posts) < steps.NORMAL_ATTEMPTS and clock.t - t0 < lambda_left - lambda_handler.MARGIN + 1

def test_the_normal_path_has_every_wait_at_its_ceiling(clock):
    out = steps.grant(dict(CTX), FakeClients(), ENV, deadline=lambda_deadline(900))
    assert out["toolPolicies"] == steps.grant(dict(CTX), FakeClients(), ENV)["toolPolicies"]

def test_the_handler_gives_the_step_the_lambda_time_left_minus_the_margin(clock, monkeypatch):
    seen = {}
    monkeypatch.setattr(lambda_handler, "STEPS", {"read": lambda event, c, env, deadline: seen.update(left=deadline.left())})
    for k, v in {**ENV, "ACTION": "read"}.items():
        monkeypatch.setenv(k, v)
    lambda_handler.handler({}, types.SimpleNamespace(get_remaining_time_in_millis=lambda: 300_000))
    assert seen["left"] == 300 - lambda_handler.MARGIN and lambda_handler.MARGIN >= 45

# ------------------------------------------------------------------ the agent role's boundary, approve re-reads (fix round 1)

def test_grant_creates_the_agent_role_under_the_boundary():
    c = FakeClients()
    steps.grant(dict(CTX), c, ENV)
    assert c.roles["hub-agent-quality_agent-role"]["boundary"] == ENV["AGENT_BOUNDARY"]

def test_approve_approves_a_record_that_did_not_change():
    c = FakeClients()
    out = steps.approve({**CTX, "target": "QualityAgent"}, c, ENV)
    assert out["recordStatus"] == "APPROVED" and [p["name"] for p in c.created_policies] == ["entry_permit_quality_agent"]

def test_approve_refuses_a_record_that_changed_after_the_review_started():
    c = FakeClients(record_spec={**SPEC, "code_version": "v2"})                     # changed after Read
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve({**CTX, "target": "QualityAgent"}, c, ENV)
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None and c.created_policies == []

# ------------------------------------------------------------------ final review I-1: Read binds the application to its record

EVENT = {"detail": {"registryId": "reg-1", "registryRecordId": "rec-1"}}

def test_read_refuses_an_application_whose_name_is_not_the_records():
    c = FakeClients(record_name="foo")                       # record foo, application quality_agent
    with pytest.raises(ValueError, match="the application's name quality_agent is not the record's name foo"):
        steps.read(EVENT, c, ENV)

def test_read_refuses_a_record_that_is_not_an_agent():
    c = FakeClients(record_type="MCP")
    with pytest.raises(ValueError, match="record type is MCP, not AGENT"):
        steps.read(EVENT, c, ENV)

@pytest.mark.parametrize("change, message", [
    ({"code_key": "agents/quality_agent/code.zip"}, "code_key must be a key under submissions/"),
    ({"code_key": 7}, "code_key must be a key under submissions/"),
    ({"code_key": "submissions/"}, "code_key must be a key under submissions/"),
    ({"code_version": 3}, "code_version must be a string"),
    ({"code_version": ""}, "missing: code_version"),
    ({"team": 5}, "team must be a string of 1 to 64 characters"),
    ({"framework": ["strands"]}, "framework must be a string of 1 to 64 characters"),
    ({"team": "t" * 65}, "team must be a string of 1 to 64 characters"),
    ({"tools": {"Parts___get_part_spec": 1}}, "tools must be a list of tool names"),
    ({"tools": "Parts___get_part_spec"}, "tools must be a list of tool names"),
])
def test_read_refuses_a_field_of_the_wrong_shape(change, message):
    c = FakeClients(record_spec={**SPEC, **change})
    with pytest.raises(ValueError, match=message):
        steps.read(EVENT, c, ENV)

def test_read_keeps_its_error_short_whatever_the_record_holds():       # it travels in the review's state to the alert
    c = FakeClients(record_spec={**SPEC, "name": "a" * 100_000, "tools": ["x" * 1000] * 100}, record_name="b" * 100_000)
    with pytest.raises(ValueError) as e:
        steps.read(EVENT, c, ENV)
    assert len(str(e.value)) <= steps.MAX_ERROR and "is not the record's name" in str(e.value)

def test_read_passes_on_the_reviewed_fields_only():
    c = FakeClients(record_spec={**SPEC, "description": "an agent", "notes": "x" * 5000})
    out = steps.read(EVENT, c, ENV)
    assert out["spec"] == SPEC and sorted(out["spec"]) == sorted(steps.REVIEWED_FIELDS)
    assert out["record"] == "quality_agent" and (out["registryId"], out["recordId"]) == ("reg-1", "rec-1")

def test_approve_reads_the_record_through_the_same_check_as_read():
    c = FakeClients(record_spec={**SPEC, "description": "an agent"})
    ctx = steps.read(EVENT, c, ENV)
    assert steps.approve({**ctx, "target": "QualityAgent"}, c, ENV)["recordStatus"] == "APPROVED"

@pytest.mark.parametrize("change", [
    lambda c: setattr(c, "record_spec", {**c.record_spec, "description": "changed"}),   # a field Read does not pass on
    lambda c: setattr(c, "record_name", "foo"),                                         # the record no longer binds it
    lambda c: setattr(c, "record_spec", {**c.record_spec, "tools": "Parts___get_part_spec"}),
])
def test_approve_refuses_a_record_that_changed_in_any_way_after_read(change):
    c = FakeClients(record_spec={**SPEC, "description": "an agent"})
    ctx = steps.read(EVENT, c, ENV)
    change(c)
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve({**ctx, "target": "QualityAgent"}, c, ENV)
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None and c.created_policies == []
