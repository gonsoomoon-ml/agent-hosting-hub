"""Company policies: rolled out to every hosted agent in a mode, switched, removed, reported, given to a newly
approved agent, and forgotten at teardown. Nothing calls AWS: FakeClients stands in, and the CloudWatch reads of
report go to a botocore Stubber."""
import datetime

import boto3
import pytest
from botocore.stub import Stubber

from platform_team.company_policy import policy_rollout
from platform_team.company_policy.cedar_statements import guard_prompt
from platform_team.company_policy.policy_rollout import (MODE_WORDS, POLICIES, apply_to_agent, deployed, forget,
                                                         hosted_agents, remove, report, rollout)
from platform_team.shared_code.config import Settings
from tests.fakes import PLATFORM, FakeClients


def hub(**kw):                      # two hosted agents and one name with no entry target
    return FakeClients(parameters={"/hub/agents/quality_agent/runtime_arn": "…", "/hub/agents/release_review/runtime_arn": "…",
                                   "/hub/agents/ghost/runtime_arn": "…"}, targets={"QualityAgent", "ReleaseReview"}, **kw)


def quiet(line):
    pass


def test_the_policies_and_the_mode_words_are_the_ruled_ones():
    assert list(POLICIES) == ["guard_prompt"]
    assert MODE_WORDS == {"log-only": "LOG_ONLY", "active": "ACTIVE"}


# ------------------------------------------------------------------ rollout

def test_rollout_writes_the_mode_before_it_touches_an_agent():
    c = hub()
    rollout(c, Settings(), PLATFORM, "guard_prompt", "log-only", say=lambda m: None)
    assert c.calls.index(("ssm", "put_parameter")) < c.calls.index(("ctl", "create_policy"))
    assert c.parameters["/hub/policies/guard_prompt"] == "LOG_ONLY"
    # the agents are listed after the write too: an agent approved in between reads the new mode itself
    assert c.calls.index(("ssm", "put_parameter")) < c.calls.index(("ctl", "list_gateway_targets"))


def test_rollout_covers_every_hosted_agent_and_only_those():
    out = rollout(hub(), Settings(), PLATFORM, "guard_prompt", "log-only", say=lambda m: None)
    assert out["agents"] == {"quality_agent": "created", "release_review": "created"}
    assert out["policy"] == "guard_prompt" and out["mode"] == "LOG_ONLY"


def test_each_agent_gets_the_prompt_guard_on_its_own_target_in_the_mode():
    c = hub()
    rollout(c, Settings(), PLATFORM, "guard_prompt", "log-only", say=quiet)
    made = {p["name"]: p for p in c.created_policies}
    assert sorted(made) == ["guard_prompt_quality_agent", "guard_prompt_release_review"]
    quality = made["guard_prompt_quality_agent"]
    assert quality["statement"] == guard_prompt("QualityAgent", PLATFORM.agent_gw["arn"])
    assert quality["kind"] == "policy" and quality["mode"] == "LOG_ONLY"          # a guardrail policy


def test_a_second_rollout_changes_nothing():
    c = hub(); rollout(c, Settings(), PLATFORM, "guard_prompt", "active", say=lambda m: None)
    out = rollout(c, Settings(), PLATFORM, "guard_prompt", "active", say=lambda m: None)
    assert set(out["agents"].values()) == {"unchanged"} and len(c.created_policies) == 2
    assert c.mode_changes == []


def test_raising_the_mode_switches_the_policies_and_makes_none():
    c = hub(); rollout(c, Settings(), PLATFORM, "guard_prompt", "log-only", say=lambda m: None)
    out = rollout(c, Settings(), PLATFORM, "guard_prompt", "active", say=lambda m: None)
    assert set(out["agents"].values()) == {"switched"} and len(c.created_policies) == 2
    assert sorted(c.mode_changes) == [("guard_prompt_quality_agent", "ACTIVE"), ("guard_prompt_release_review", "ACTIVE")]
    assert c.parameters["/hub/policies/guard_prompt"] == "ACTIVE" and c.deleted_policies == []


def test_an_agent_that_fails_is_told_and_the_others_still_get_the_policy():
    # quality_agent's new policy ends CREATE_FAILED; release_review's policy is there in LOG_ONLY and is switched
    c = hub(policy_status="CREATE_FAILED", policy_reasons=["no"], existing_policies={"guard_prompt_release_review"},
            policy_mode="LOG_ONLY")
    said = []
    out = rollout(c, Settings(), PLATFORM, "guard_prompt", "active", say=said.append)
    assert out["agents"] == {"quality_agent": "failed", "release_review": "switched"}
    assert [line for line in said if line.startswith("quality_agent: failed")] == [
        "quality_agent: failed (RuntimeError: policy guard_prompt_quality_agent CREATE_FAILED: ['no'] (deleted))"]
    assert c.parameters["/hub/policies/guard_prompt"] == "ACTIVE"         # the mode stays written


# ------------------------------------------------------------------ off, unknown words

def test_off_removes_the_policies_and_the_mode():
    # guard_prompt_ghost: a policy of this kind on an agent with no entry target goes too; other kinds stay
    c = hub(existing_policies={"guard_prompt_ghost", "entry_permit_quality_agent", "guard_secret_quality_agent"})
    rollout(c, Settings(), PLATFORM, "guard_prompt", "active", say=quiet)
    out = remove(c, Settings(), PLATFORM, "guard_prompt", say=quiet)
    assert out == {"policy": "guard_prompt",
                   "agents": {"ghost": "removed", "quality_agent": "removed", "release_review": "removed"}}
    assert set(c.policies) == {"entry_permit_quality_agent", "guard_secret_quality_agent"}
    assert "/hub/policies/guard_prompt" not in c.parameters
    # the mode goes first: an agent approved while the policies are removed is not given the policy again
    assert c.calls.index(("ssm", "delete_parameter")) < c.calls.index(("ctl", "delete_policy"))
    assert remove(c, Settings(), PLATFORM, "guard_prompt", say=quiet) == {"policy": "guard_prompt", "agents": {}}


@pytest.mark.parametrize("call", [
    lambda c: rollout(c, Settings(), PLATFORM, "guard_everything", "active", say=quiet),
    lambda c: rollout(c, Settings(), PLATFORM, "guard_prompt", "ACTIVE", say=quiet),     # the API's value, not a word
    lambda c: rollout(c, Settings(), PLATFORM, "guard_prompt", "off", say=quiet),        # off is remove
    lambda c: remove(c, Settings(), PLATFORM, "guard_everything", say=quiet),
    lambda c: report(c, Settings(), PLATFORM, "guard_everything"),
    lambda c: apply_to_agent(c, Settings(), PLATFORM, "Bad-Name"),
], ids=["policy", "mode", "off", "remove", "report", "agent"])
def test_an_unknown_policy_or_mode_is_refused_before_anything_changes(call):
    c = hub()
    with pytest.raises(ValueError, match="unknown company policy|unknown mode|agent name"):
        call(c)
    assert c.calls == []


# ------------------------------------------------------------------ what is deployed, which agents are hosted

def test_deployed_reads_only_the_values_directly_under_the_path():
    # the fake matches by plain prefix (wider than SSM): /hub/policiesold/... and deeper names are not read
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "LOG_ONLY", "/hub/policiesold/guard_prompt": "ACTIVE",
                                "/hub/policies/guard_prompt/note": "x", "/hub/agents/quality_agent/runtime_arn": "…"})
    assert deployed(c, Settings()) == {"guard_prompt": "LOG_ONLY"}
    assert deployed(FakeClients(), Settings()) == {}


@pytest.mark.parametrize("name, value", [("/hub/policies/guard_prompt", "LOUD"),
                                         ("/hub/policies/guard_everything", "ACTIVE")])
def test_a_value_rollout_would_not_write_stops_the_reader(name, value):
    with pytest.raises(ValueError, match="not written by rollout"):
        deployed(FakeClients(parameters={name: value}), Settings())


def test_hosted_agents_have_a_value_under_agents_and_an_entry_target():
    c = hub()
    c.parameters["/hub/agentsold/other_agent/runtime_arn"] = "…"          # not under /hub/agents/
    c.targets["OtherAgent"] = "OtherAgent-tid"
    assert hosted_agents(c, Settings(), PLATFORM) == ["quality_agent", "release_review"]


# ------------------------------------------------------------------ one agent at approval, teardown

def test_apply_to_agent_gives_one_agent_every_deployed_policy_in_its_mode():
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "ACTIVE"})
    assert apply_to_agent(c, Settings(), PLATFORM, "quality_agent") == {"guard_prompt": "ACTIVE"}
    assert [(p["name"], p["mode"], p["kind"]) for p in c.created_policies] == [
        ("guard_prompt_quality_agent", "ACTIVE", "policy")]
    assert c.created_policies[0]["statement"] == guard_prompt("QualityAgent", PLATFORM.agent_gw["arn"])


def test_apply_to_agent_does_not_switch_a_policy_found_in_another_mode():
    # rollout switches modes; Approve's role cannot (no UpdatePolicy), so the approval stops and the policy is kept
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "ACTIVE"}, existing_policies={"guard_prompt_quality_agent"},
                    policy_mode="LOG_ONLY")
    with pytest.raises(RuntimeError, match="guard_prompt_quality_agent is LOG_ONLY, but /hub/policies/guard_prompt is "
                                           "ACTIVE: the approval does not switch modes; rollout.sh guard_prompt active does"):
        apply_to_agent(c, Settings(), PLATFORM, "quality_agent")
    assert ("ctl", "update_policy") not in c.calls and c.mode_changes == [] and c.deleted_policies == []
    assert c.policies["guard_prompt_quality_agent"]["mode"] == "LOG_ONLY"


def test_apply_to_agent_keeps_a_policy_already_in_the_mode():
    c = FakeClients(parameters={"/hub/policies/guard_prompt": "LOG_ONLY"}, existing_policies={"guard_prompt_quality_agent"},
                    policy_mode="LOG_ONLY")
    assert apply_to_agent(c, Settings(), PLATFORM, "quality_agent") == {"guard_prompt": "LOG_ONLY"}
    assert c.created_policies == [] and c.mode_changes == []


def test_apply_to_agent_with_nothing_deployed_touches_no_policy():
    c = FakeClients()
    assert apply_to_agent(c, Settings(), PLATFORM, "quality_agent") == {}
    assert [call for call in c.calls if call[0] == "ctl"] == []


def test_forget_removes_the_modes_and_nothing_else():
    c = hub()
    rollout(c, Settings(), PLATFORM, "guard_prompt", "log-only", say=quiet)
    assert forget(c, Settings()) == ["/hub/policies/guard_prompt"]
    assert sorted(c.parameters) == ["/hub/agents/ghost/runtime_arn", "/hub/agents/quality_agent/runtime_arn",
                                    "/hub/agents/release_review/runtime_arn"]
    assert len(c.policies) == 2 and forget(c, Settings()) == []           # the policies go with the agents' cleanup


# ------------------------------------------------------------------ report

class Seen:
    """A Stubber parameter that matches any value and keeps it."""
    def __init__(self):
        self.values = []

    def __eq__(self, other):
        self.values.append(other)
        return True


@pytest.fixture
def cloudwatch(monkeypatch, tmp_path):
    """A real CloudWatch client behind a Stubber: the calls are checked against the service model, no network."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    cw = boto3.client("cloudwatch", region_name="us-west-2", aws_access_key_id="test-access-key",
                      aws_secret_access_key="example")
    with Stubber(cw) as stub:
        yield cw, stub
        stub.assert_no_pending_responses()


def test_report_reads_both_metrics_for_each_agents_policy(cloudwatch):       # Stubber on cloudwatch: the four dimensions, Sum
    c = hub(); rollout(c, Settings(), PLATFORM, "guard_prompt", "log-only", say=quiet)
    c.cw, stub = cloudwatch
    now = datetime.datetime(2026, 11, 22, tzinfo=datetime.timezone.utc)
    sums = {("quality_agent", "LogOnlyMatches"): [3.0, 2.0], ("quality_agent", "LogOnlyDecisionFlips"): [1.0],
            ("release_review", "LogOnlyMatches"): [], ("release_review", "LogOnlyDecisionFlips"): []}
    starts, ends = Seen(), Seen()
    for (agent, metric), values in sums.items():
        stub.add_response("get_metric_statistics", {
            "Label": metric, "Datapoints": [{"Timestamp": now, "Sum": v, "Unit": "Count"} for v in values]}, {
            "Namespace": "AWS/Bedrock-AgentCore", "MetricName": metric,
            "Dimensions": [{"Name": "OperationName", "Value": "AuthorizeAction"},
                           {"Name": "Policy", "Value": f"guard_prompt_{agent}-id"},          # the policy's ID, not its name
                           {"Name": "PolicyEngine", "Value": PLATFORM.engine_id},
                           {"Name": "TargetResource", "Value": PLATFORM.agent_gw["id"]}],
            "StartTime": starts, "EndTime": ends, "Period": 3600, "Statistics": ["Sum"]})
    out = report(c, Settings(), PLATFORM, "guard_prompt")
    assert out == {"quality_agent": {"mode": "LOG_ONLY", "matches": 5, "flips": 1},
                   "release_review": {"mode": "LOG_ONLY", "matches": 0, "flips": 0}}
    assert {e - s for s, e in zip(starts.values, ends.values)} == {datetime.timedelta(minutes=60)}


def test_report_of_a_policy_no_agent_has_reads_no_metric():
    assert report(hub(), Settings(), PLATFORM, "guard_prompt") == {}         # hub() has no cw: a read would fail


# ------------------------------------------------------------------ the command

@pytest.fixture
def command(monkeypatch):
    """main() on a fake hub: the shell gives the prefix and the region."""
    monkeypatch.setenv("DEMO_PREFIX", "hub")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    def run(c, *argv):
        monkeypatch.setattr(policy_rollout.Clients, "for_settings", lambda s: c)
        monkeypatch.setattr(policy_rollout, "load", lambda s, c=None: PLATFORM)
        return policy_rollout.main(list(argv))
    return run


def test_the_command_says_which_hub_first_and_fails_when_an_agent_failed(command, capsys):
    c = hub(policy_status="CREATE_FAILED", existing_policies={"guard_prompt_release_review"}, policy_mode="LOG_ONLY")
    assert command(c, "guard_prompt", "active") == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "company policy guard_prompt: active (prefix hub, region us-west-2)"
    assert "release_review: switched" in lines and any(line.startswith("quality_agent: failed (") for line in lines)
    assert lines[-1] == "guard_prompt is ACTIVE in SSM; 1 of 2 agents failed: run the command again"


def test_the_command_rolls_out_reports_and_turns_off(command, capsys):
    c = hub()
    assert command(c, "guard_prompt", "log-only") == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "quality_agent: created", "release_review: created", "guard_prompt is LOG_ONLY on 2 agents"]
    assert command(c, "guard_prompt", "off") == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "quality_agent: removed", "release_review: removed", "guard_prompt is off: removed from 2 agents"]
    assert c.policies == {} and c.parameters.get("/hub/policies/guard_prompt") is None


@pytest.mark.parametrize("argv", [[], ["guard_prompt"], ["guard_everything", "active"], ["guard_prompt", "loud"],
                                  ["guard_prompt", "active", "now"], ["--forget", "x"]])
def test_the_command_refuses_other_words_and_changes_nothing(command, capsys, argv):
    c = hub()
    assert command(c, *argv) == 2
    assert capsys.readouterr().out.startswith("usage:") and c.calls == []


def test_forget_is_a_command_for_make_destroy(command, capsys):
    c = hub()
    c.parameters["/hub/policies/guard_prompt"] = "ACTIVE"
    assert command(c, "--forget") == 0
    assert capsys.readouterr().out.splitlines() == [
        "removed parameter /hub/policies/guard_prompt", "company policy modes forgotten (prefix hub, region us-west-2): 1 removed"]


def test_the_report_command_prints_each_agent_and_reads_only(command, capsys, monkeypatch):
    c = hub()
    rollout(c, Settings(), PLATFORM, "guard_prompt", "log-only", say=quiet)
    calls = len(c.calls)
    monkeypatch.setattr(policy_rollout, "_sum", lambda c, metric, *a: {"LogOnlyMatches": 4, "LogOnlyDecisionFlips": 1}[metric])
    assert command(c, "guard_prompt", "report") == 0
    assert capsys.readouterr().out.splitlines()[1:] == [
        "quality_agent: LOG_ONLY, LogOnlyMatches 4, LogOnlyDecisionFlips 1 (last 60 minutes)",
        "release_review: LOG_ONLY, LogOnlyMatches 4, LogOnlyDecisionFlips 1 (last 60 minutes)",
        "guard_prompt is on 2 agents"]
    assert c.calls[calls:] == [("ctl", "list_policies")]                  # reads only
