import types
import urllib.error
import pytest
from botocore.exceptions import ClientError
from platform_team.hosting_review import lambda_handler, review_steps as steps
from platform_team.shared_code.aws_helpers import Deadline, OutOfTime
from tests.fakes import FakeClients, ENV, CTX, EVENT, PLATFORM, SPEC, read_input

# What Approve gets for the record SPEC: Read's context with what Entry adds (target) and what Grant saw (no entry
# permit before the review)
AT_APPROVE = {**CTX, "target": "QualityAgent", "entryPermitBefore": False}

# The ARN the deploy build writes for quality_agent: runtime/<Settings.runtime_name>-<10 letters or digits>
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-Ab12Cd34Ef"

@pytest.fixture(autouse=True)
def patched_post(monkeypatch):
    """The steps' signed_post answers from the FakeClients built in the test."""
    monkeypatch.setattr(steps, "signed_post", lambda *a, **kw: FakeClients.latest.post(*a, **kw))

def test_read_refuses_an_application_with_an_unknown_tool():       # Review Focus 3
    c = FakeClients(record_spec={"name": "quality_agent", "team": "appliance", "framework": "strands",
                                 "tools": ["Parts___nope"], "code_key": "k", "code_version": "v"})
    with pytest.raises(ValueError, match="tool not in the catalog: Parts___nope"):
        steps.read(read_input({"detail": {"registryId": "r", "registryRecordId": "x"}}), c, ENV)

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
    c = FakeClients(runtime_arn=RUNTIME_ARN)
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
        steps.approve(AT_APPROVE, c, ENV, deadline=lambda_deadline(lambda_handler.MARGIN))
    assert c.created_policies == [] and c.record_status == "PENDING_APPROVAL"

def test_entry_shares_one_deadline_between_the_target_and_its_policies(clock):
    c = FakeClients(runtime_arn=RUNTIME_ARN,
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
    out = steps.approve(AT_APPROVE, c, ENV)
    assert out["recordStatus"] == "APPROVED" and [p["name"] for p in c.created_policies] == ["entry_permit_quality_agent"]

def test_approve_refuses_a_record_that_changed_after_the_review_started():
    c = FakeClients(record_spec={**SPEC, "code_version": "v2"})                     # changed after Read
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None and c.created_policies == []

# ------------------------------------------------------------------ final review I-5: a second run keeps what the first made

def _counting(c, client, method):
    calls = []
    original = getattr(getattr(c, client), method)
    def counted(**kw):
        calls.append(kw)
        return original(**kw)
    setattr(getattr(c, client), method, counted)
    return calls

def test_grant_run_again_keeps_the_role_and_its_permits():                 # Review Focus 1
    c = FakeClients()
    created = _counting(c, "iam", "create_role")
    first = steps.grant(dict(CTX), c, ENV)
    second = steps.grant(dict(CTX), c, ENV)
    assert len(created) == 1 and list(c.roles) == ["hub-agent-quality_agent-role"]
    assert first["roleArn"] == second["roleArn"] and first["toolPolicies"] == second["toolPolicies"]
    assert len(c.created_policies) == 2 and c.deleted_policies == []

def test_entry_run_again_keeps_the_target_and_its_policies():              # Review Focus 1
    c = FakeClients(runtime_arn=RUNTIME_ARN)
    created = _counting(c, "ctl", "create_gateway_target")
    first = steps.entry({**CTX, "roleArn": "r"}, c, ENV)
    second = steps.entry({**CTX, "roleArn": "r"}, c, ENV)
    assert len(created) == 1 and list(c.targets) == ["QualityAgent"] and first["targetId"] == second["targetId"]
    assert [p["name"] for p in c.created_policies] == ["review_permit_quality_agent", "guard_secret_quality_agent"]
    assert (first["reviewPolicy"], first["guardPolicy"]) == (second["reviewPolicy"], second["guardPolicy"])

# ------------------------------------------------------------------ final review M-2: Entry trusts no Runtime ARN but this agent's

@pytest.mark.parametrize("arn", [
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_release_review-Ab12Cd34Ef",       # another agent
    "arn:aws:bedrock-agentcore:us-west-2:234567890123:runtime/hub_quality_agent-Ab12Cd34Ef",        # another account
    "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/hub_quality_agent-Ab12Cd34Ef",        # another Region
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-Ab12Cd34",          # no Runtime ID
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-Ab12Cd34Ef/x",
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality-Ab12Cd34Ef",              # a name that starts the same
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hubQualityAgent_default_agent-Ab12Cd34Ef",  # the CLI's name
    "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-x",
    "",
])
def test_entry_refuses_a_runtime_arn_that_is_not_this_agents(arn):
    c = FakeClients(runtime_arn=arn)
    with pytest.raises(ValueError, match="is not the ARN of this agent's Runtime"):
        steps.entry({**CTX, "roleArn": "r"}, c, ENV)
    assert c.targets == {} and c.created_policies == []

def test_entry_refuses_a_target_of_this_name_that_points_to_another_runtime():
    c = FakeClients(runtime_arn=RUNTIME_ARN)
    other = RUNTIME_ARN.replace("Ab12Cd34Ef", "Zz98Yy76Xx")               # an older Runtime of the same agent, say
    c.targets["QualityAgent"], c.target_arns["QualityAgent"] = "QualityAgent-tid", other
    with pytest.raises(RuntimeError, match=f"target QualityAgent already exists and points to {other}"):
        steps.entry({**CTX, "roleArn": "r"}, c, ENV)
    assert c.target_arns == {"QualityAgent": other} and c.created_policies == []

# ------------------------------------------------------------------ final review I-1: Read binds the application to its record

def test_read_refuses_an_application_whose_name_is_not_the_records():
    c = FakeClients(record_name="foo")                       # record foo, application quality_agent
    with pytest.raises(ValueError, match="the application's name quality_agent is not the record's name foo"):
        steps.read(read_input(), c, ENV)

@pytest.mark.parametrize("record_type, framework", [("MCP", "strands"), ("AGENT", "harness")])
def test_read_skips_a_record_the_review_does_not_host(record_type, framework):
    out = steps.read(read_input(), FakeClients(record_type=record_type, record_spec={**SPEC, "framework": framework}), ENV)
    assert set(out) == {"skip"} and out["skip"]

@pytest.mark.parametrize("record_type, application", [
    ("AGENT", {"name": "spec_assistant", "team": "parts", "framework": "harness", "tools": ["Parts___get_part_spec"]}),
    ("MCP", {"server": "parts-tools", "tools": ["nope"]}),
])
def test_the_skip_comes_before_every_check_of_the_application(record_type, application):
    """A skipped record has no place for code (a harness), or is no agent's application at all (a shared tool)."""
    out = steps.read(read_input(), FakeClients(record_type=record_type, record_spec=application), ENV)
    assert set(out) == {"skip"} and out["skip"]

def test_a_record_that_is_not_an_agent_is_never_approved():
    # Read skips such a record (above). Approve reads the record through application(), which still refuses it.
    c = FakeClients()
    ctx = steps.read(read_input(), c, ENV)
    c.record_type = "MCP"                                   # the record changed its type during the review
    with pytest.raises(ValueError, match="record type is MCP, not AGENT"):
        steps.application(c.reg.get_registry_record(registryId="reg-1", recordId="rec-1"), ENV)
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve({**ctx, "target": "QualityAgent", "entryPermitBefore": False}, c, ENV)
    assert c.record_status == "PENDING_APPROVAL" and c.created_policies == []

def test_an_agent_role_may_call_its_model_and_no_other():
    trust, perms = steps._execution_role({**ENV, "MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0"},
                                         "quality_agent")
    model = next(s for s in perms["Statement"] if "bedrock:InvokeModel" in s["Action"])
    assert sorted(model["Resource"]) == [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:us-west-2:123456789012:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"]

def test_grant_gives_the_agent_role_the_model_of_its_environment():
    # A model ID without a cross-Region prefix (us., eu., ...) names a foundation model of the hub's Region.
    c = FakeClients()
    steps.grant(dict(CTX), c, {**ENV, "MODEL_ID": "anthropic.claude-haiku-4-5-20251001-v1:0"})
    statements = c.roles["hub-agent-quality_agent-role"]["permissions"]["Statement"]
    [model] = [s for s in statements if "bedrock:InvokeModel" in s["Action"]]
    assert model["Resource"] == ["arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"]

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
        steps.read(read_input(), c, ENV)

def test_read_keeps_its_error_short_whatever_the_record_holds():       # it travels in the review's state to the alert
    c = FakeClients(record_spec={**SPEC, "name": "a" * 100_000, "tools": ["x" * 1000] * 100}, record_name="b" * 100_000)
    with pytest.raises(ValueError) as e:
        steps.read(read_input(), c, ENV)
    assert len(str(e.value)) <= steps.MAX_ERROR and "is not the record's name" in str(e.value)

def test_read_passes_on_the_reviewed_fields_only():
    c = FakeClients(record_spec={**SPEC, "description": "an agent", "notes": "x" * 5000})
    out = steps.read(read_input(), c, ENV)
    assert out["spec"] == SPEC and sorted(out["spec"]) == sorted(steps.REVIEWED_FIELDS)
    assert out["record"] == "quality_agent" and (out["registryId"], out["recordId"]) == ("reg-1", "rec-1")

def test_approve_reads_the_record_through_the_same_check_as_read():
    c = FakeClients(record_spec={**SPEC, "description": "an agent"})
    ctx = steps.read(read_input(), c, ENV)
    assert steps.approve({**ctx, "target": "QualityAgent", "entryPermitBefore": False}, c, ENV)["recordStatus"] == "APPROVED"

@pytest.mark.parametrize("change", [
    lambda c: setattr(c, "record_spec", {**c.record_spec, "description": "changed"}),   # a field Read does not pass on
    lambda c: setattr(c, "record_name", "foo"),                                         # the record no longer binds it
    lambda c: setattr(c, "record_spec", {**c.record_spec, "tools": "Parts___get_part_spec"}),
])
def test_approve_refuses_a_record_that_changed_in_any_way_after_read(change):
    c = FakeClients(record_spec={**SPEC, "description": "an agent"})
    ctx = steps.read(read_input(), c, ENV)
    change(c)
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve({**ctx, "target": "QualityAgent", "entryPermitBefore": False}, c, ENV)
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None and c.created_policies == []

# ------------------------------------------------------------------ final review I-2: Approve requires the record to be pending

@pytest.mark.parametrize("status", ["REJECTED", "DRAFT", "APPROVED"])
def test_approve_refuses_a_record_that_is_no_longer_pending(status):
    c = FakeClients(record_status=status)              # rejected while the review ran, changed, or approved already
    with pytest.raises(RuntimeError, match=f"record quality_agent is {status}, not PENDING_APPROVAL"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.created_policies == [] and c.record_status == status and c.status_reason is None

def _changes_while_the_entry_permit_waits(c, change):
    """The fake's create_policy, followed by a change to the record (the policy wait sits between the two checks)."""
    create = c.ctl.create_policy
    def create_then_change(**kw):
        out = create(**kw)
        change(c)
        return out
    c.ctl.create_policy = create_then_change

@pytest.mark.parametrize("change, message", [
    (lambda c: setattr(c, "record_status", "REJECTED"), "record quality_agent is REJECTED, not PENDING_APPROVAL"),
    (lambda c: setattr(c, "record_spec", {**SPEC, "code_version": "v2"}), "the record changed after the review started"),
])
def test_approve_checks_the_record_again_right_before_approving(change, message):     # ledger 184: the second check
    c = FakeClients()
    _changes_while_the_entry_permit_waits(c, change)
    with pytest.raises(RuntimeError, match=message):
        steps.approve(AT_APPROVE, c, ENV)
    assert [p["name"] for p in c.created_policies] == ["entry_permit_quality_agent"]    # made between the checks
    assert c.status_reason is None                                                        # never approved

# ------------------------------------------------------------------ the company policies the platform team deployed

def test_approve_gives_a_new_agent_the_deployed_policies_in_their_mode():
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "LOG_ONLY"})
    out = steps.approve(AT_APPROVE, c, ENV)       # the ctx the existing approve tests pass
    made = [(p["name"], p["mode"], p["kind"]) for p in c.created_policies]
    assert made == [("guard_prompt_quality_agent", "LOG_ONLY", "policy"), ("entry_permit_quality_agent", "ACTIVE", "cedar")]
    assert out["companyPolicies"] == {"guard_prompt": "LOG_ONLY"} and out["recordStatus"] == "APPROVED"
    assert 'AgentCore::Gateway::"%s"' % ENV["AGENT_GW_ARN"] in c.created_policies[0]["statement"]
    assert '"QualityAgent___POST:/invocations"' in c.created_policies[0]["statement"]

def test_approve_with_no_company_policy_deployed_makes_only_the_entry_permit():
    c = FakeClients()
    out = steps.approve(AT_APPROVE, c, ENV)
    assert [p["name"] for p in c.created_policies] == ["entry_permit_quality_agent"]
    assert out["companyPolicies"] == {} and out["recordStatus"] == "APPROVED"

def test_approve_checks_the_record_before_the_company_policies():
    c = FakeClients(record_spec={**SPEC, "code_version": "v2"}, parameters={"/hub/policies/guard_prompt": "ACTIVE"})
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.created_policies == [] and ("ssm", "get_parameters_by_path") not in c.calls

def test_approve_runs_record_check_company_policies_entry_permit_record_check_approval():
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "ACTIVE"})
    steps.approve(AT_APPROVE, c, ENV)
    order = [call for call in c.calls if call in {("reg", "get_registry_record"), ("ssm", "get_parameters_by_path"),
                                                  ("ctl", "create_policy"), ("reg", "update_registry_record_status")}]
    assert order == [("reg", "get_registry_record"), ("ssm", "get_parameters_by_path"), ("ctl", "create_policy"),
                     ("ctl", "create_policy"), ("reg", "get_registry_record"), ("reg", "update_registry_record_status")]
    assert [p["name"] for p in c.created_policies] == ["guard_prompt_quality_agent", "entry_permit_quality_agent"]

def test_approve_stops_at_a_company_policy_in_another_mode_and_opens_nothing():
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "ACTIVE"}, existing_policies={"guard_prompt_quality_agent"},
                    policy_mode="LOG_ONLY")
    with pytest.raises(RuntimeError, match="the approval does not switch modes"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.created_policies == [] and c.mode_changes == [] and c.record_status == "PENDING_APPROVAL"

def test_company_policies_made_before_a_stopped_approval_stay():
    # the record is rejected while the policies wait: approval stops at the second check; a forbid harms nothing,
    # while the entry permit this approval made is taken back (it would let users in)
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "LOG_ONLY"})
    _changes_while_the_entry_permit_waits(c, lambda c: setattr(c, "record_status", "REJECTED"))
    with pytest.raises(RuntimeError, match="is REJECTED, not PENDING_APPROVAL"):
        steps.approve(AT_APPROVE, c, ENV)
    assert set(c.policies) == {"guard_prompt_quality_agent"} and c.deleted_policies == ["entry_permit_quality_agent-id"]
    assert c.status_reason is None

# ------------------------------------------------------------------ the review of a new version

EXECUTIONS = PLATFORM.machine_arn.replace(":stateMachine:", ":execution:")     # arn:...:execution:hub-review

def test_read_refuses_while_an_earlier_review_of_the_record_runs():
    c = FakeClients(running=[("older", "rec-1"), ("this-one", "rec-1")])
    with pytest.raises(RuntimeError, match="already running: older"):
        steps.read({"event": EVENT, "execution": f"{EXECUTIONS}:this-one", "machine": PLATFORM.machine_arn}, c, ENV)
    assert ("sfn", "list_executions") in c.calls

@pytest.mark.parametrize("running", [
    [("this-one", "rec-1"), ("newer", "rec-1")],           # the later review stops at its own Read
    [("older", "rec-2"), ("this-one", "rec-1")],           # a review of another record
    [],
])
def test_read_goes_on_when_no_earlier_review_of_the_record_runs(running):
    out = steps.read(read_input(execution="this-one"), FakeClients(running=running), ENV)
    assert out["spec"] == SPEC and out["recordId"] == "rec-1"

def test_read_counts_every_other_review_of_the_record_as_earlier_while_it_does_not_see_itself():
    # ListExecutions is eventually consistent: a review that just started may not be listed yet
    c = FakeClients(running=[("older", "rec-1"), ("another", "rec-1")])
    with pytest.raises(RuntimeError, match="a review of this record is already running: older, another"):
        steps.read(read_input(execution="this-one"), c, ENV)

def test_a_skipped_record_never_raises_already_running():
    c = FakeClients(record_type="MCP", running=[("older", "rec-1"), ("this-one", "rec-1")])
    assert set(steps.read(read_input(), c, ENV)) == {"skip"}
    assert [call for call in c.calls if call[0] == "sfn"] == []

def test_read_looks_for_an_earlier_review_before_it_checks_the_application():
    c = FakeClients(record_spec={**SPEC, "tools": ["Parts___nope"]}, running=[("older", "rec-1"), ("this-one", "rec-1")])
    with pytest.raises(RuntimeError, match="already running: older"):
        steps.read(read_input(), c, ENV)

def test_grant_removes_the_permit_of_a_tool_the_new_version_dropped():
    c = FakeClients(existing_policies={"tool_quality_agent_Parts_get_part_spec", "tool_quality_agent_Parts_get_test_result",
                                       "tool_quality_Parts_get_test_result"}, existing_roles={"hub-agent-quality_agent-role"})
    out = steps.grant({**CTX, "spec": {**SPEC, "tools": ["Parts___get_part_spec"]}}, c, ENV)
    assert out["removedToolPolicies"] == ["tool_quality_agent_Parts_get_test_result"]
    assert "tool_quality_Parts_get_test_result" in c.policies            # another agent's permit stays
    assert "tool_quality_agent_Parts_get_part_spec" in c.policies and "tool_quality_agent_Parts_get_test_result" not in c.policies
    assert c.deleted_policies == ["tool_quality_agent_Parts_get_test_result-id"]

def test_grant_of_a_first_version_removes_nothing():
    c = FakeClients(existing_policies={"tool_quality_Parts_get_test_result", "entry_permit_quality_agent"})
    assert steps.grant(dict(CTX), c, ENV)["removedToolPolicies"] == [] and c.deleted_policies == []

def _changes_after_the_first_record_check(c, change):
    """The fake's get_registry_record; after its first answer the record changes (Approve reads it twice)."""
    get, answered = c.reg.get_registry_record, []
    def get_then_change(**kw):
        out = get(**kw)
        if not answered:
            answered.append(out)
            change(c)
        return out
    c.reg.get_registry_record = get_then_change

def test_approve_takes_back_the_entry_permit_it_made_when_the_record_changed():
    c = FakeClients()
    _changes_after_the_first_record_check(c, lambda c: setattr(c, "record_spec", {**SPEC, "code_version": "v2"}))
    with pytest.raises(RuntimeError, match="the record changed after the review started"):
        steps.approve(AT_APPROVE, c, ENV)
    assert [p["name"] for p in c.created_policies] == ["entry_permit_quality_agent"]      # made between the checks
    assert c.policies == {} and c.deleted_policies == ["entry_permit_quality_agent-id"]   # and taken back
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None

def test_approve_leaves_an_entry_permit_that_was_there_before():
    # an approved version runs: its entry permit was there before this review and stays
    c = FakeClients(existing_policies={"entry_permit_quality_agent"})
    _changes_after_the_first_record_check(c, lambda c: setattr(c, "record_status", "DRAFT"))
    with pytest.raises(RuntimeError, match="record quality_agent is DRAFT, not PENDING_APPROVAL"):
        steps.approve({**AT_APPROVE, "entryPermitBefore": True}, c, ENV)
    assert set(c.policies) == {"entry_permit_quality_agent"} and c.deleted_policies == [] and c.created_policies == []

def test_approve_takes_back_the_entry_permit_when_the_second_record_check_cannot_read_the_record():
    c = FakeClients()
    def unreadable(c):
        def throttled(**kw):
            raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "GetRegistryRecord")
        c.reg.get_registry_record = throttled
    _changes_after_the_first_record_check(c, unreadable)
    with pytest.raises(ClientError, match="ThrottlingException"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.policies == {} and c.deleted_policies == ["entry_permit_quality_agent-id"] and c.status_reason is None

def test_a_failed_take_back_still_says_why_the_approval_stopped():
    c = FakeClients()
    _changes_after_the_first_record_check(c, lambda c: setattr(c, "record_status", "REJECTED"))
    def denied(**kw):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not allowed"}}, "DeletePolicy")
    c.ctl.delete_policy = denied
    with pytest.raises(RuntimeError) as e:
        steps.approve(AT_APPROVE, c, ENV)
    assert "record quality_agent is REJECTED, not PENDING_APPROVAL" in str(e.value)
    assert "taking back entry_permit_quality_agent" in str(e.value) and "AccessDeniedException" in str(e.value)
    assert c.status_reason is None

# ------------------------------------------------------------------ fix round 1: every failure after the entry permit takes it back

def _status_update_fails(c):
    def unavailable(**kw):
        raise ClientError({"Error": {"Code": "ServiceUnavailableException", "Message": "try later"}},
                          "UpdateRegistryRecordStatus")
    c.reg.update_registry_record_status = unavailable

def test_a_failed_status_update_takes_back_the_entry_permit_this_review_made():
    c = FakeClients()
    _status_update_fails(c)
    with pytest.raises(ClientError, match="ServiceUnavailableException"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.policies == {} and c.deleted_policies == ["entry_permit_quality_agent-id"]
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None

def test_a_failed_status_update_leaves_an_entry_permit_that_was_there_before_the_review():
    c = FakeClients(existing_policies={"entry_permit_quality_agent"})
    _status_update_fails(c)
    with pytest.raises(ClientError, match="ServiceUnavailableException"):
        steps.approve({**AT_APPROVE, "entryPermitBefore": True}, c, ENV)
    assert set(c.policies) == {"entry_permit_quality_agent"} and c.deleted_policies == []

def test_a_retried_approval_that_fails_takes_back_the_permit_an_earlier_attempt_made():
    # the earlier attempt made the permit and stopped without taking it back (here: the permit is in the fake);
    # the retry gets the same input, so it knows the permit was not there before the review
    c = FakeClients(existing_policies={"entry_permit_quality_agent"})
    _changes_after_the_first_record_check(c, lambda c: setattr(c, "record_status", "DRAFT"))
    with pytest.raises(RuntimeError, match="record quality_agent is DRAFT, not PENDING_APPROVAL"):
        steps.approve(AT_APPROVE, c, ENV)
    assert c.policies == {} and c.deleted_policies == ["entry_permit_quality_agent-id"] and c.created_policies == []

def test_a_retried_approval_that_passes_approves_and_keeps_the_permit():
    c = FakeClients(existing_policies={"entry_permit_quality_agent"})
    out = steps.approve(AT_APPROVE, c, ENV)
    assert out["recordStatus"] == "APPROVED" and c.record_status == "APPROVED"
    assert set(c.policies) == {"entry_permit_quality_agent"} and c.deleted_policies == [] and c.created_policies == []

def test_a_failure_while_the_entry_permit_is_made_takes_back_what_was_made():
    # the wait for ACTIVE raises an AWS error, which ensure_policy does not clean up after
    c = FakeClients()
    get = c.ctl.get_policy
    def throttled(**kw):
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "GetPolicy")
    c.ctl.get_policy = throttled
    with pytest.raises(ClientError, match="ThrottlingException"):
        steps.approve(AT_APPROVE, c, ENV)
    assert [p["name"] for p in c.created_policies] == ["entry_permit_quality_agent"] and c.policies == {}
    assert get                                                           # the fake's own get_policy is not needed

@pytest.mark.parametrize("existing, before", [((), False), (("entry_permit_quality_agent",), True)])
def test_grant_says_whether_the_entry_permit_was_there_before_the_review(existing, before):
    c = FakeClients(existing_policies={*existing, "entry_permit_quality"})       # another agent's permit
    assert steps.grant(dict(CTX), c, ENV)["entryPermitBefore"] is before

@pytest.mark.parametrize("ctx", [{**CTX, "target": "QualityAgent"}, {**AT_APPROVE, "entryPermitBefore": "no"}])
def test_approve_refuses_an_input_that_does_not_say_whether_the_entry_permit_was_there(ctx):
    c = FakeClients()
    with pytest.raises(ValueError, match="entryPermitBefore"):
        steps.approve(ctx, c, ENV)
    assert c.calls == [] and c.created_policies == [] and c.record_status == "PENDING_APPROVAL"
