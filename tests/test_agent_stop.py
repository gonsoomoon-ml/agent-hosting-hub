"""Stopping one hosted agent and resuming it: the entry is blocked before any session is ended, only this agent's
things are touched, the sessions come from its Runtime's log streams, and resume removes the stop policy and nothing
else. Nothing calls AWS: FakeClients stands in."""
import time

import pytest
from botocore.exceptions import ClientError

from platform_team.agent_stop import stop_agent
from platform_team.agent_stop.stop_agent import recent_sessions, resume, runtime_arn, stop, stopped
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_names import policy_names
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform
from tests.fakes import ACCOUNT, PLATFORM, FakeClients

ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-Ab12Cd34Ef"
GROUP = "/aws/bedrock-agentcore/runtimes/hub_quality_agent-Ab12Cd34Ef-DEFAULT"     # its log group (DEFAULT endpoint)
TOOLS = ["Parts___get_part_spec", "Quality___get_inspection_data"]


def quiet(line):
    pass


def stream(sid, created=1, last_event=None, last_ingestion=None):
    """A LogStream of DescribeLogStreams for the session `sid`, made `created` minutes ago; the event times are
    there only when given (minutes ago), as for a new stream whose times the service has not updated yet."""
    now = time.time() * 1000
    x = {"logStreamName": f"runtime-logs-{sid}", "creationTime": int(now - created * 60_000)}
    for key, minutes in (("lastEventTimestamp", last_event), ("lastIngestionTime", last_ingestion)):
        if minutes is not None:
            x[key] = int(now - minutes * 60_000)
    return x


def test_stop_blocks_the_entry_before_it_ends_a_session():
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    out = stop(c, Settings(), PLATFORM, "quality_agent", sessions=["s" * 40], say=lambda m: None)
    assert c.calls.index(("ctl", "create_policy")) < c.calls.index(("data", "stop_runtime_session"))
    assert out["policy"] == "stop_agent_quality_agent" and out["stopped"] == ["s" * 40]
    assert c.stopped_sessions == [(ARN, "s" * 40)]


@pytest.mark.parametrize("arn", [ARN.replace("hub_quality_agent", "hub_release_review"), ARN.replace("123456789012", "234567890123"), "x"])
def test_stop_refuses_an_arn_that_is_not_this_agents_runtime(arn):
    c = FakeClients(runtime_arn=arn, targets={"QualityAgent"})
    with pytest.raises(ValueError):
        stop(c, Settings(), PLATFORM, "quality_agent", sessions=[], say=lambda m: None)
    assert c.created_policies == [] and c.stopped_sessions == []


def test_runtime_arn_gives_the_value_of_this_agents_runtime():
    c = FakeClients(parameters={"/hub/agents/quality_agent/runtime_arn": ARN})
    assert runtime_arn(c, Settings(), PLATFORM, "quality_agent") == ARN
    with pytest.raises(ValueError, match="not the ARN of this agent's Runtime"):
        runtime_arn(c, Settings(), Platform(account="234567890123"), "quality_agent")      # the hub is in another account


@pytest.mark.parametrize("targets", [set(), {"ReleaseReview"}, {"Quality"}])
def test_stop_refuses_an_agent_the_hub_does_not_host(targets):
    """No entry target of its name on the agent gateway (a harness agent has none): nothing is made or ended."""
    c = FakeClients(runtime_arn=ARN, targets=targets)
    with pytest.raises(ValueError, match="no entry target QualityAgent"):
        stop(c, Settings(), PLATFORM, "quality_agent", sessions=["s" * 40], say=quiet)
    assert c.created_policies == [] and c.stopped_sessions == []


@pytest.mark.parametrize("agent", ["Quality_Agent", "quality-agent", "qa", ""])
def test_stop_refuses_a_name_the_application_form_refuses_before_any_call(agent):
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    with pytest.raises(ValueError, match="agent name"):
        stop(c, Settings(), PLATFORM, agent, sessions=["s" * 40], say=quiet)
    assert c.calls == []


def test_the_stop_policy_names_this_agents_entry_and_lets_the_reviews_test_call_through():
    """STOP_EXCEPTION is "unless": the forbid has an exception for the review's test call role, so the review of a
    fixed version can make its test call while the agent is stopped."""
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    stop(c, Settings(), PLATFORM, "quality_agent", sessions=[], say=quiet)
    (made,) = c.created_policies
    assert made["name"] == "stop_agent_quality_agent" and made["kind"] == "cedar" and made["mode"] == "ACTIVE"
    assert made["statement"] == cedar.stop_agent("QualityAgent", PLATFORM.agent_gw["arn"], ACCOUNT, "hub-review-testcall-role")
    assert made["statement"].startswith('forbid (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations"')
    assert made["statement"].endswith(
        'unless { principal == AgentCore::IamEntity::"arn:aws:sts::123456789012:assumed-role/hub-review-testcall-role" };')


def test_stop_only_adds_the_stop_policy():
    """STOP_EFFECT is "ends": ending the sessions is enough, so the entry permit, the tool permits, the guards and
    the company policies stay as they are."""
    others = policy_names("quality_agent", TOOLS)[:-1]
    c = FakeClients(existing_policies=others, runtime_arn=ARN, targets={"QualityAgent"})
    stop(c, Settings(), PLATFORM, "quality_agent", sessions=["s" * 40], say=quiet)
    assert [p["name"] for p in c.created_policies] == ["stop_agent_quality_agent"]
    assert c.deleted_policies == [] and c.mode_changes == [] and set(c.policies) == {*others, "stop_agent_quality_agent"}


def test_a_stop_policy_that_does_not_become_active_ends_no_session():
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"}, policy_status="CREATE_FAILED", policy_reasons=["no"])
    with pytest.raises(RuntimeError, match="stop_agent_quality_agent CREATE_FAILED"):
        stop(c, Settings(), PLATFORM, "quality_agent", sessions=["s" * 40], say=quiet)
    assert c.stopped_sessions == [] and c.policies == {}          # the half-made policy is deleted, nothing is ended


def test_stop_twice_keeps_one_policy():
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    for _ in range(2):
        out = stop(c, Settings(), PLATFORM, "quality_agent", sessions=["s" * 40], say=quiet)
    assert [p["name"] for p in c.created_policies] == ["stop_agent_quality_agent"]
    assert list(c.policies) == ["stop_agent_quality_agent"] and c.deleted_policies == []
    assert out["stopped"] == ["s" * 40] and len(c.stopped_sessions) == 2           # the sessions are ended again


def test_a_session_that_cannot_be_stopped_is_reported_and_the_rest_go_on():
    """One refused by the service, one too short to send (StopRuntimeSession takes 33 to 256 characters): both are
    reported with the reason, and the sessions after them are still stopped."""
    a, b, d = "a" * 36, "b" * 36, "d" * 36
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    c.session_errors[b] = ClientError({"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
                                      "StopRuntimeSession")
    lines = []
    out = stop(c, Settings(), PLATFORM, "quality_agent", sessions=[a, b, "short", d], say=lines.append)
    assert out["stopped"] == [a, d] and c.stopped_sessions == [(ARN, a), (ARN, d)]
    assert out["failed"][b] == "ThrottlingException: Rate exceeded"
    assert "33 to 256 characters" in out["failed"]["short"] and list(out["failed"]) == [b, "short"]
    assert c.calls.count(("data", "stop_runtime_session")) == 3                  # the short one is not sent
    assert f"session {b}: not stopped (ThrottlingException: Rate exceeded)" in lines


ENDED = "Session {} not found or has been terminated"       # what StopRuntimeSession answered for an ended session


def test_a_session_that_has_already_ended_is_reported_and_is_not_a_failure():
    """2026-11-22 on AWS: StopRuntimeSession answers ResourceNotFoundException "Session <ID> not found or has been
    terminated" for a session whose stream is recent but which no longer runs. Nothing runs there to stop, so it is
    reported as ended, apart from the ones stopped, and the stop does not fail for it."""
    a, b = "a" * 36, "b" * 36
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    c.session_errors[b] = ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": ENDED.format(b)}},
                                      "StopRuntimeSession")
    lines = []
    out = stop(c, Settings(), PLATFORM, "quality_agent", sessions=[a, b], say=lines.append)
    assert out["stopped"] == [a] and out["ended"] == [b] and out["failed"] == {}
    assert f"session {b}: already ended (ResourceNotFoundException: {ENDED.format(b)})" in lines


def test_the_stop_command_succeeds_when_the_other_sessions_had_already_ended(command, capsys):
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    c.log_streams = {GROUP: [stream("a" * 36), stream("b" * 36, created=2)]}
    c.session_errors["b" * 36] = ClientError({"Error": {"Code": "ResourceNotFoundException",
                                                        "Message": ENDED.format("b" * 36)}}, "StopRuntimeSession")
    assert command(c, "stop", "quality_agent") == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "quality_agent is stopped: stop_agent_quality_agent blocks its entry; sessions stopped: 1, already ended: 1")


def test_a_session_given_twice_is_stopped_once():
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    out = stop(c, Settings(), PLATFORM, "quality_agent", sessions=["a" * 36, "a" * 36], say=quiet)
    assert out["stopped"] == ["a" * 36] and len(c.stopped_sessions) == 1


def test_stop_of_quality_leaves_quality_agent_alone():      # two hosted agents whose names share a start
    quality_arn = ARN.replace("hub_quality_agent", "hub_quality")
    c = FakeClients(parameters={"/hub/agents/quality/runtime_arn": quality_arn, "/hub/agents/quality_agent/runtime_arn": ARN},
                    targets={"Quality", "QualityAgent"})
    c.log_streams = {GROUP.replace("hub_quality_agent", "hub_quality"): [stream("q" * 36)], GROUP: [stream("a" * 36)]}
    out = stop(c, Settings(), PLATFORM, "quality", say=quiet)
    assert out == {"agent": "quality", "policy": "stop_agent_quality", "stopped": ["q" * 36], "ended": [],
                   "failed": {}}
    assert list(c.policies) == ["stop_agent_quality"] and c.stopped_sessions == [(quality_arn, "q" * 36)]
    assert '"Quality___POST:/invocations"' in c.created_policies[0]["statement"]
    assert stopped(c, PLATFORM, "quality") and not stopped(c, PLATFORM, "quality_agent")
    stop(c, Settings(), PLATFORM, "quality_agent", say=quiet)
    assert resume(c, Settings(), PLATFORM, "quality") == {"agent": "quality", "resumed": True}
    assert list(c.policies) == ["stop_agent_quality_agent"] and stopped(c, PLATFORM, "quality_agent")


def test_resume_removes_the_stop_policy_and_nothing_else():
    names = [*policy_names("quality_agent", TOOLS), "stop_agent_quality", "entry_permit_release_review"]
    c = FakeClients(existing_policies=names, runtime_arn=ARN, targets={"QualityAgent"})
    assert resume(c, Settings(), PLATFORM, "quality_agent") == {"agent": "quality_agent", "resumed": True}
    assert c.deleted_policies == ["stop_agent_quality_agent-id"] and c.created_policies == []
    assert set(c.policies) == set(names) - {"stop_agent_quality_agent"}
    assert {service for service, _ in c.calls} == {"ctl"} and c.stopped_sessions == []    # no session, no parameter


def test_resume_of_an_agent_that_is_not_stopped_changes_nothing():
    c = FakeClients(existing_policies={"entry_permit_quality_agent", "stop_agent_quality"})
    assert resume(c, Settings(), PLATFORM, "quality_agent") == {"agent": "quality_agent", "resumed": False}
    assert c.deleted_policies == [] and c.calls == [("ctl", "list_policies")]


def test_stopped_says_whether_the_stop_policy_decides():
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    assert not stopped(c, PLATFORM, "quality_agent")
    stop(c, Settings(), PLATFORM, "quality_agent", sessions=[], say=quiet)
    assert stopped(c, PLATFORM, "quality_agent")
    resume(c, Settings(), PLATFORM, "quality_agent")
    assert not stopped(c, PLATFORM, "quality_agent")
    # a stop policy in log-only mode only records what it would refuse: the agent is not stopped
    assert not stopped(FakeClients(existing_policies={"stop_agent_quality_agent"}, policy_mode="LOG_ONLY"), PLATFORM,
                       "quality_agent")


# ------------------------------------------------------------------ the sessions (SESSION_SOURCE is "stream-name")

def test_recent_sessions_are_the_session_streams_of_this_runtime_newest_first():
    c = FakeClients()
    c.log_streams = {GROUP: [
        stream("a" * 36, created=10),                               # a call without the header: a UUID's length
        stream("b" * 42, created=1),                                # started a minute ago: no event time yet
        stream("c" * 36, created=120),                              # nothing for two hours
        stream("d" * 36, created=300, last_event=5),                # a long session that still writes
        stream("e" * 36, created=300, last_ingestion=7),
        stream("short", created=1),                                 # too short for StopRuntimeSession
        {"logStreamName": "spans", "creationTime": int(time.time() * 1000)}],
        GROUP.replace("Ab12Cd34Ef", "Zz98Yy76Xx"): [stream("f" * 36)]}      # another Runtime's group
    assert recent_sessions(c, Settings(), ARN) == ["b" * 42, "d" * 36, "e" * 36, "a" * 36]
    assert recent_sessions(c, Settings(), ARN, minutes=3) == ["b" * 42]


def test_a_runtime_that_was_never_called_has_no_sessions():
    assert recent_sessions(FakeClients(), Settings(), ARN) == []        # its log group does not exist


def test_stop_without_sessions_ends_the_recent_ones_and_looks_for_them_after_the_block():
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    c.log_streams = {GROUP: [stream("a" * 36, created=3), stream("b" * 36, created=1), stream("c" * 36, created=90)]}
    lines = []
    out = stop(c, Settings(), PLATFORM, "quality_agent", say=lines.append)
    assert out == {"agent": "quality_agent", "policy": "stop_agent_quality_agent", "stopped": ["b" * 36, "a" * 36],
                   "ended": [], "failed": {}}
    # looked for once no new user call can come in, so a session opened during the stop is found too
    assert c.calls.index(("ctl", "create_policy")) < c.calls.index(("logs", "describe_log_streams"))
    assert f"sessions with a log stream in the last 30 minutes ({GROUP}): 2" in lines


# ------------------------------------------------------------------ the commands

@pytest.fixture
def command(monkeypatch):
    """main() on a fake hub: the shell gives the prefix and the region."""
    monkeypatch.setenv("DEMO_PREFIX", "hub")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    def run(c, *argv):
        monkeypatch.setattr(stop_agent.Clients, "for_settings", lambda s: c)
        monkeypatch.setattr(stop_agent, "load", lambda s, c=None: PLATFORM)
        return stop_agent.main(list(argv))
    return run


def test_the_stop_command_says_which_hub_first_and_stops_the_sessions_it_is_given(command, capsys):
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    c.log_streams = {GROUP: [stream("z" * 36)]}                         # not looked at: sessions are given
    assert command(c, "stop", "quality_agent", "--session", "a" * 36, "--session", "b" * 36) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "agent quality_agent: stop (prefix hub, region us-west-2)"
    assert lines[-1] == "quality_agent is stopped: stop_agent_quality_agent blocks its entry; sessions stopped: 2"
    assert c.stopped_sessions == [(ARN, "a" * 36), (ARN, "b" * 36)] and ("logs", "describe_log_streams") not in c.calls


def test_the_stop_command_fails_when_a_session_was_not_stopped(command, capsys):
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    c.log_streams = {GROUP: [stream("a" * 36), stream("b" * 36, created=2)]}
    c.session_errors["b" * 36] = ClientError({"Error": {"Code": "ValidationException", "Message": "no"}}, "StopRuntimeSession")
    assert command(c, "stop", "quality_agent") == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "quality_agent is blocked at the entry by stop_agent_quality_agent; 1 of 2 sessions not stopped: "
        "run stop again, or give the session with --session <ID>")


def test_the_resume_command_removes_the_stop_policy_once(command, capsys):
    c = FakeClients(existing_policies={"stop_agent_quality_agent", "entry_permit_quality_agent"})
    assert command(c, "resume", "quality_agent") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["agent quality_agent: resume (prefix hub, region us-west-2)",
                     "quality_agent is resumed: stop_agent_quality_agent removed"]
    assert command(c, "resume", "quality_agent") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "quality_agent was not stopped: nothing changed"
    assert list(c.policies) == ["entry_permit_quality_agent"]


def test_a_refused_stop_says_why_in_one_line_with_the_account_masked(command, capsys):
    c = FakeClients(runtime_arn=ARN.replace("hub_quality_agent", "hub_release_review"), targets={"QualityAgent"})
    assert command(c, "stop", "quality_agent") == 1
    out = capsys.readouterr().out
    assert out.splitlines()[-1].startswith("stop of quality_agent did not finish (prefix hub, region us-west-2): ValueError: ")
    assert ACCOUNT not in out and "<ACCOUNT>" in out and c.created_policies == []


@pytest.mark.parametrize("argv", [[], ["stop"], ["resume"], ["pause", "quality_agent"], ["stop", "quality_agent", "--session"],
                                  ["stop", "quality_agent", "a" * 36], ["stop", "quality_agent", "--sessions", "a" * 36],
                                  ["resume", "quality_agent", "--session", "a" * 36], ["resume", "quality_agent", "now"]])
def test_the_command_refuses_other_words_and_changes_nothing(command, capsys, argv):
    c = FakeClients(runtime_arn=ARN, targets={"QualityAgent"})
    assert command(c, *argv) == 2
    assert capsys.readouterr().out.startswith("usage:") and c.calls == []
