"""The scene command that reads an agent's recent log lines: the newest lines of its Runtime's log group, oldest first,
without the copies in the stream otel-rt-logs, the account masked, and one line when the agent has no log group. It
reads with DescribeLogGroups and FilterLogEvents only. Nothing calls AWS: FakeClients stands in."""
import time

import pytest

from platform_team.agent_monitoring import agent_logs
from platform_team.shared_code.config import Settings
from tests.fakes import ACCOUNT, FakeClients

GROUP = "/aws/bedrock-agentcore/runtimes/hub_quality_agent-Ab12Cd34Ef-DEFAULT"
SESSION = "runtime-logs-" + "s" * 36


def event(minutes_ago, message, stream=SESSION):
    return {"logStreamName": stream, "timestamp": int((time.time() - minutes_ago * 60) * 1000), "message": message}


def hub(lines=(), group=GROUP):
    c = FakeClients()
    c.log_groups.add(group)
    c.log_lines[group] = list(lines)
    return c


def test_logs_prints_the_newest_lines_oldest_first_without_the_copies(monkeypatch, capsys):
    c = hub([event(3, "asking again (3)"), event(1, "asking again (1)"), event(2, "asking again (2)"),
             event(2, "asking again (2)", stream="otel-rt-logs"), event(1, "asking again (1)", stream="otel-rt-logs"),
             event(1, "span", stream="spans")])
    assert agent_logs.recent_lines(c, Settings(), "quality_agent") == ["asking again (3)", "asking again (2)",
                                                                       "asking again (1)"]
    assert {f["logStreamNamePrefix"] for f in c.log_filters} == {"runtime-logs-"}
    monkeypatch.setattr(agent_logs, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    assert agent_logs.main(["quality_agent"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1:] == ["asking again (3)", "asking again (2)", "asking again (1)"]
    assert "quality_agent" in out[0]


def test_logs_shows_the_newest_limit_when_there_are_more():
    c = hub([event(10 - i / 100, f"asking again ({i})") for i in range(300)])
    got = agent_logs.recent_lines(c, Settings(), "quality_agent")
    assert len(got) == 200 and got[0] == "asking again (100)" and got[-1] == "asking again (299)"
    assert agent_logs.recent_lines(c, Settings(), "quality_agent", limit=3) == [f"asking again ({i})" for i in (297, 298, 299)]


def test_logs_reads_only_the_minutes_asked_for():
    c = hub([event(20, "old"), event(4, "inside"), event(0.5, "newest")])
    assert agent_logs.recent_lines(c, Settings(), "quality_agent", minutes=5) == ["inside", "newest"]
    assert agent_logs.recent_lines(c, Settings(), "quality_agent") == ["inside", "newest"]       # 15 minutes by default
    assert agent_logs.recent_lines(c, Settings(), "quality_agent", minutes=30) == ["old", "inside", "newest"]


def test_logs_uses_the_log_group_and_the_filter_call_only():
    c = hub([event(1, "a line")])
    c.log_groups |= {"/aws/bedrock-agentcore/runtimes/hub_quality_agent_v2-Zz99Zz99Zz-DEFAULT",      # another agent's
                     "/aws/bedrock-agentcore/runtimes/hub_quality_agent-Ab12Cd34Ef-OTHER",           # another endpoint
                     "/aws/bedrock-agentcore/runtimes/hub_release_review-Ab12Cd34Ef-DEFAULT"}
    assert agent_logs.recent_lines(c, Settings(), "quality_agent") == ["a line"]
    assert set(c.calls) <= {("logs", "get_paginator"), ("logs", "describe_log_groups"), ("logs", "filter_log_events")}
    assert ("logs", "filter_log_events") in c.calls and not any(s != "logs" for s, _ in c.calls)     # no SSM, no stream list
    assert {f["logGroupName"] for f in c.log_filters} == {GROUP}


def test_logs_reads_a_harness_agents_runtime_too():
    group = "/aws/bedrock-agentcore/runtimes/harness_hub_spec_assistant-Ab12Cd34Ef-DEFAULT"
    c = hub([event(1, "harness line")], group=group)
    assert agent_logs.recent_lines(c, Settings(), "spec_assistant") == ["harness line"]


def test_logs_says_so_when_the_agent_has_no_log_group(monkeypatch, capsys):
    c = FakeClients()
    monkeypatch.setattr(agent_logs, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    with pytest.raises(agent_logs.NoLogGroup):
        agent_logs.recent_lines(c, Settings(), "quality_agent")
    assert agent_logs.main(["quality_agent"]) == 1
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "no log group" in out and "quality_agent" in out and "Traceback" not in out


def test_logs_says_so_when_the_group_has_no_lines_in_the_time(monkeypatch, capsys):
    c = hub([event(40, "long ago")])
    monkeypatch.setattr(agent_logs, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    assert agent_logs.main(["quality_agent", "5"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "no log lines in the last 5 minutes" in out


def test_logs_masks_the_account(monkeypatch, capsys):
    c = hub([event(1, f"role arn:aws:iam::{ACCOUNT}:role/x started")])
    monkeypatch.setattr(agent_logs, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    assert agent_logs.main(["quality_agent"]) == 0
    out = capsys.readouterr().out
    assert ACCOUNT not in out and "arn:aws:iam::<ACCOUNT>:role/x started" in out


@pytest.mark.parametrize("argv", [[], ["a", "5", "6"], ["quality_agent", "soon"], ["quality_agent", "0"], ["quality_agent", "-3"]])
def test_logs_exits_2_for_bad_usage_before_any_call(monkeypatch, capsys, argv):
    c = hub()
    monkeypatch.setattr(agent_logs, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    assert agent_logs.main(argv) == 2
    assert capsys.readouterr().out.startswith("usage: ") and c.calls == []


def test_logs_refuses_an_agent_name_the_form_rules_refuse(monkeypatch, capsys):
    c = hub()
    monkeypatch.setattr(agent_logs, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    assert agent_logs.main(["Quality-Agent"]) == 2
    assert "name must" in capsys.readouterr().out and c.calls == []
