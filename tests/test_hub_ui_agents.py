"""The hub screen's agents page: the hosted agents with their usage and stop state, the tool-call alarm with its last 15
minutes as bars, the calls per tool, and the Stop and Resume buttons. The AWS clients are the fakes of
tests/fakes.py; the functions the buttons call are the ones the commands call."""
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from platform_team.agent_stop import stop_agent
from platform_team.hub_ui import agents
from platform_team.hub_ui.app import create_app
from platform_team.hub_ui.texts import STRINGS
from platform_team.shared_code.config import Settings
from tests.fakes import ACCOUNT, PLATFORM, FakeClients
from tests.hub_ui_pages import panel, panel_elements, token

S = Settings()
BASE = "http://127.0.0.1:8300"
ORIGIN = {"Origin": BASE}
NOW = datetime(2026, 11, 23, 9, 20, 30, tzinfo=UTC)
WATCHED = "Parts___get_part_spec"
ALARM = {"AlarmName": "hub-tool-calls", "StateValue": "ALARM", "Threshold": 19.0, "Namespace": "AWS/Bedrock-AgentCore",
         "MetricName": "Invocations", "Period": 60, "Statistic": "Sum",
         "Dimensions": [{"Name": "Method", "Value": "tools/call"}, {"Name": "Name", "Value": WATCHED},
                        {"Name": "Operation", "Value": "InvokeGateway"}, {"Name": "Protocol", "Value": "MCP"},
                        {"Name": "Resource", "Value": PLATFORM.tool_gw["arn"]}]}
# calls of the watched tool in the last 15 minutes (09:06 to 09:20): quiet, then above the threshold of 19
CALLS = [0, 2, 1, 0, 3, 2, 1, 4, 0, 2, 25, 31, 28, 12, 3]


def app_record(name: str, status: str = "APPROVED", team: str = "device", framework: str = "strands") -> dict:
    spec = {"name": name, "team": team, "framework": framework, "tools": [], "code_key": "k", "code_version": "v1"}
    return {"name": name, "recordId": f"rec-{name}", "recordType": "AGENT", "status": status,
            "description": f"{name}: agent of team {team}", "descriptors": {"custom": {"data": json.dumps(spec)}}}


def runtime(c: FakeClients, name: str) -> None:
    c.runtimes[name] = {"id": f"{name}-Ab12Cd34Ef", "arn": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:runtime/{name}-Ab12Cd34Ef",
                        "version": "1", "status": "READY", "config": {}}


def at(minute: int) -> datetime:
    return NOW.replace(second=0) - timedelta(minutes=minute)


def fleet() -> FakeClients:
    """Four hosted agents: three on Runtimes (release_review stopped) and parts_harness, a harness agent."""
    c = FakeClients(record_status=None, targets=["QualityAgent", "ReleaseReview", "DocsAdk"],
                    existing_policies=["stop_agent_release_review"], policy_mode="ACTIVE")
    c.other_records = [app_record("quality_agent", team="appliance"), app_record("release_review", team="release"),
                       app_record("docs_adk", team="docs", framework="adk"),
                       app_record("parts_harness", team="parts", framework="harness")]
    for agent in ("quality_agent", "release_review", "docs_adk"):
        runtime(c, S.runtime_name(agent))
    runtime(c, S.harness_runtime_name("parts_harness"))
    c.alarms = [ALARM]
    c.metric_data = {("Invocations", WATCHED): [(at(14 - i), v) for i, v in enumerate(CALLS)],
                     ("Invocations", f"{S.runtime_name('quality_agent')}::DEFAULT"): [(at(1), 7), (at(2), 5)],
                     ("Errors", f"{S.runtime_name('quality_agent')}::DEFAULT"): [(at(2), 1)],
                     ("Sessions", f"{S.runtime_name('quality_agent')}::DEFAULT"): [(at(2), 2)],
                     ("CPUUsed-vCPUHours", f"{S.runtime_name('quality_agent')}::DEFAULT"): [(at(2), 0.01234)],
                     ("Invocations", "Quality___get_inspection_data"): [(at(3), 4), (at(4), 2)]}
    return c


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(agents, "_now", lambda: NOW)


def screen(c: FakeClients, **kw) -> TestClient:
    return TestClient(create_app(S, c, PLATFORM, zone="UTC", **kw), base_url=BASE)


def test_minute_series_fills_the_minutes_without_data():
    points = {"09:18": 4.0, "09:20": 25.0, "08:00": 9.0}                       # 08:00 is outside the window
    assert agents.minute_series(points, 4, NOW) == [("09:17", 0), ("09:18", 4), ("09:19", 0), ("09:20", 25)]
    assert agents.minute_series({}, 2, NOW) == [("09:19", 0), ("09:20", 0)]
    assert agents.minute_series({"09:20": 2.6}, 1, NOW) == [("09:20", 3)]        # whole calls
    midnight = datetime(2026, 11, 24, 0, 1, 10, tzinfo=UTC)
    assert [m for m, _ in agents.minute_series({}, 3, midnight)] == ["23:59", "00:00", "00:01"]


def row(web, agent: str) -> dict:
    return next(r for r in agents.view(web.app.state.hub)["agents"]["value"] if r["agent"] == agent)


def test_the_page_lists_hosted_agents_with_usage_and_stop_state():
    web = screen(fleet())
    value = agents.view(web.app.state.hub)["agents"]["value"]
    assert [r["agent"] for r in value] == ["docs_adk", "parts_harness", "quality_agent", "release_review"]
    quality = row(web, "quality_agent")
    assert {k: quality[k] for k in ("team", "framework", "status", "hosted_as", "stopped", "can_stop")} == {
        "team": "appliance", "framework": "strands", "status": "APPROVED", "hosted_as": "Runtime", "stopped": False,
        "can_stop": True}
    assert quality["usage"] == {"invocations": 12, "sessions": 2, "errors": 1, "cpu_vcpu_hours": 0.01234,
                                "memory_gb_hours": 0.0}
    assert row(web, "release_review")["stopped"] is True
    harness = row(web, "parts_harness")
    assert (harness["hosted_as"], harness["stopped"], harness["can_stop"]) == ("harness", False, False)
    page = web.get("/agents?lang=ko").text
    text = panel(page, "panel-agents")
    assert "quality_agent appliance strands Runtime" in text and "parts_harness parts harness harness" in text
    assert "12 2 1 0.0123 0.0000" in text                                    # calls whole, hours with four decimals
    assert STRINGS["ko"]["agent.state.stopped"] in text and STRINGS["ko"]["agent.state.running"] in text
    assert STRINGS["ko"]["agent.no_entry"] in text and text.count(STRINGS["ko"]["agent.no_entry"]) == 1
    assert "최근 60분" in text
    actions = {a["action"] for tag, a in panel_elements(page, "panel-agents") if tag == "form"}
    assert actions == {"/agents/docs_adk/stop", "/agents/quality_agent/stop", "/agents/release_review/resume"}
    assert "/agents/parts_harness/stop" not in actions
    english = panel(web.get("/agents?lang=en").text, "panel-agents")
    assert STRINGS["en"]["agent.no_entry"] in english and "Stopped" in english and "Stop" in english


def test_the_alarm_panel_shows_state_threshold_and_bars():
    web = screen(fleet())
    alarm = agents.view(web.app.state.hub)["alarm"]["value"]
    assert (alarm["name"], alarm["state"], alarm["threshold"], alarm["tool"]) == ("hub-tool-calls", "ALARM", 19,
                                                                                 WATCHED)
    assert len(alarm["series"]) == 15 and alarm["series"][0] == ("09:06", 0) and alarm["series"][-1] == ("09:20", 3)
    assert [v for _, v in alarm["series"]] == CALLS
    page = web.get("/agents?lang=ko").text
    text = panel(page, "panel-alarm")
    assert "ALARM" in text and "임계값 19" in text and WATCHED in text and "경보 중" in text
    elements = panel_elements(page, "panel-alarm")
    bars = [a for tag, a in elements if tag == "rect" and "bar" in a.get("class", "").split()]
    assert len(bars) == 15
    assert [("over" in b["class"].split()) for b in bars] == [v > 19 for v in CALLS]       # 25, 31, 28 are over
    assert sum(1 for tag, a in elements if tag == "line" and "threshold" in a.get("class", "").split()) == 1
    assert "09:06" in text and "09:20" in text and "31" in text
    assert any(tag == "svg" and a.get("role") == "img" and a.get("aria-label") for tag, a in elements)
    pills = [a for tag, a in elements if tag == "span" and "pill" in a.get("class", "").split()]
    assert pills and "bad" in pills[0]["class"].split()
    quiet = fleet()
    quiet.alarms = [{**ALARM, "StateValue": "OK"}]
    quiet.metric_data[("Invocations", WATCHED)] = []
    web = screen(quiet)
    assert [v for _, v in agents.view(web.app.state.hub)["alarm"]["value"]["series"]] == [0] * 15
    shown = panel(web.get("/agents?lang=en").text, "panel-alarm")
    assert "OK" in shown and "threshold 19" in shown


def test_no_alarm_is_said_in_its_panel():
    c = fleet()
    c.alarms = []
    web = screen(c)
    assert agents.view(web.app.state.hub)["alarm"] == {"ok": True, "value": None}
    assert STRINGS["ko"]["alarm.none"] in panel(web.get("/agents?lang=ko").text, "panel-alarm")


def test_the_tools_panel_shows_the_calls_per_tool():
    web = screen(fleet())
    tools = agents.view(web.app.state.hub)["tools"]["value"]
    assert tools["Quality___get_inspection_data"] == 6 and tools[WATCHED] == sum(CALLS)
    text = panel(web.get("/agents?lang=ko").text, "panel-tools")
    assert "Quality___get_inspection_data 6" in text and f"{WATCHED} {sum(CALLS)}" in text and "최근 60분" in text


def test_stop_and_resume_call_the_same_functions_as_the_commands(monkeypatch):
    calls = []

    def stop(c, s, p, agent, sessions=None, say=print):
        calls.append(("stop", c, s, p, agent))
        say("blocking the entry")
        return {"agent": agent, "policy": f"stop_agent_{agent}", "stopped": ["s1", "s2"], "ended": ["s3"],
                "failed": {}}

    def resume(c, s, p, agent):
        calls.append(("resume", c, s, p, agent))
        return {"agent": agent, "resumed": True}
    monkeypatch.setattr(stop_agent, "stop", stop)
    monkeypatch.setattr(stop_agent, "resume", resume)
    c = fleet()
    web = screen(c)
    hub = web.app.state.hub
    page = web.get("/agents").text
    for action, agent, line in (("stop", "quality_agent", "sessions: 2 stopped, 1 already ended, 0 not stopped"),
                                ("resume", "release_review", "resumed")):
        r = web.post(f"/agents/{agent}/{action}", headers=ORIGIN, data={"token": token(page)}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/agents?msg=started"
        job = hub.jobs.current()
        assert job.wait(5) and (job.kind, job.target, job.state) == (action, agent, "done"), job.error
        assert job.lines[-1] == line
    assert calls == [("stop", c, S, PLATFORM, "quality_agent"), ("resume", c, S, PLATFORM, "release_review")]
    assert hub.jobs.get(hub.jobs.current().id).lines == ["resumed"]


def test_the_buttons_stop_and_resume_an_agent_on_the_fakes():
    c = fleet()
    c.runtimes[S.runtime_name("docs_adk")]["arn"] = f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:runtime/hub_docs_adk-Ab12Cd34Ef"
    c.parameters[S.ssm("agents", "docs_adk", "runtime_arn")] = c.runtimes[S.runtime_name("docs_adk")]["arn"]
    web = screen(c)
    hub = web.app.state.hub
    page = web.get("/agents").text
    web.post("/agents/docs_adk/stop", headers=ORIGIN, data={"token": token(page)})
    job = hub.jobs.current()
    assert job.wait(5) and job.state == "done", job.error
    assert "stop_agent_docs_adk" in c.policies and any("blocking the entry" in line for line in job.lines)
    assert row(web, "docs_adk")["stopped"] is True
    web.post("/agents/docs_adk/resume", headers=ORIGIN, data={"token": token(page)})
    assert hub.jobs.current().wait(5) and "stop_agent_docs_adk" not in c.policies
    assert hub.jobs.current().lines == ["resumed"]
    web.post("/agents/docs_adk/resume", headers=ORIGIN, data={"token": token(page)})
    assert hub.jobs.current().wait(5) and hub.jobs.current().lines == ["it was not stopped: nothing changed"]
    web.post("/agents/parts_harness/stop", headers=ORIGIN, data={"token": token(page)})        # the function refuses it
    job = hub.jobs.current()
    assert job.wait(5) and job.state == "failed" and "no entry target" in job.error


def test_an_agent_name_the_form_rules_refuse_is_refused():
    c = fleet()
    web = screen(c)
    hub = web.app.state.hub
    right = token(web.get("/agents").text)
    for name in ("Quality_Agent", "no-such", "a" * 40, "x__y"):
        for action in ("stop", "resume"):
            r = web.post(f"/agents/{name}/{action}", headers=ORIGIN, data={"token": right}, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/agents?err=agent", (name, action)
    r = web.post("/agents/../stop", headers=ORIGIN, data={"token": right}, follow_redirects=False)
    assert r.status_code == 404 and STRINGS["ko"]["not_found.title"] in r.text
    assert hub.jobs.current() is None and c.created_policies == []                         # no job, no change
    for lang in ("ko", "en"):
        assert panel(web.get(f"/agents?err=agent&lang={lang}").text, "page-err") == STRINGS[lang]["err.agent"]


def test_the_buttons_wait_while_a_job_runs_and_a_second_press_is_not_taken():
    gate = threading.Event()
    web = screen(fleet())
    hub = web.app.state.hub
    hub.jobs.start("test", "slow", lambda say: gate.wait(5) and {})
    page = web.get("/agents").text
    assert all("disabled" in a for tag, a in panel_elements(page, "panel-agents") if tag == "button")
    r = web.post("/agents/quality_agent/stop", headers={**ORIGIN, "Referer": f"{BASE}/agents"},
                 data={"token": token(page)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/agents?err=busy"
    gate.set()
    assert hub.jobs.current().wait(5)


def denied(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": f"not allowed for {ACCOUNT}"}}, operation)


def test_a_usage_that_cannot_be_read_is_one_line_and_the_agents_still_show():
    c = fleet()
    c.errors[("cw", "get_metric_data")] = denied("GetMetricData")
    page = screen(c).get("/agents?lang=ko").text
    text = panel(page, "panel-agents")
    assert STRINGS["ko"]["panel.error"] in text and "<ACCOUNT>" in text and ACCOUNT not in page
    assert all(name in text for name in ("quality_agent", "release_review", "docs_adk", "parts_harness"))
    assert STRINGS["ko"]["agent.state.stopped"] in text
    assert STRINGS["ko"]["panel.error"] in panel(page, "panel-tools")
    alarm = panel(page, "panel-alarm")
    assert "ALARM" in alarm and STRINGS["ko"]["panel.error"] in alarm              # the state shows, the bars do not
    assert not [1 for tag, a in panel_elements(page, "panel-alarm") if tag == "rect" and "bar" in a.get("class", "")]


def test_one_agents_unreadable_stop_state_stays_on_its_row(monkeypatch):
    real = stop_agent.stopped

    def stopped(c, p, agent):
        if agent == "docs_adk":
            raise denied("ListPolicies")
        return real(c, p, agent)
    monkeypatch.setattr(stop_agent, "stopped", stopped)
    web = screen(fleet())
    docs = row(web, "docs_adk")
    assert docs["stopped"] is None and "AccessDeniedException" in docs["stop_error"] and ACCOUNT not in docs["stop_error"]
    assert row(web, "release_review")["stopped"] is True and row(web, "quality_agent")["stopped"] is False
    page = web.get("/agents?lang=ko").text
    assert "AccessDeniedException" in panel(page, "panel-agents") and "release_review" in panel(page, "panel-agents")
    assert "/agents/docs_adk/stop" not in {a["action"] for tag, a in panel_elements(page, "panel-agents") if tag == "form"}


def test_one_agents_unreadable_application_stays_on_its_row():
    c = fleet()
    c.record_errors["rec-docs_adk"] = denied("GetRegistryRecord")
    web = screen(c)
    docs = row(web, "docs_adk")
    assert docs["team"] == "" and "AccessDeniedException" in docs["app_error"] and docs["status"] == "APPROVED"
    assert row(web, "quality_agent")["team"] == "appliance"


def test_a_failing_list_of_agents_is_one_line_and_the_alarm_shows():
    c = fleet()
    c.errors[("ctl", "list_agent_runtimes")] = denied("ListAgentRuntimes")
    page = screen(c).get("/agents?lang=ko").text
    assert STRINGS["ko"]["panel.error"] in panel(page, "panel-agents")
    assert "ALARM" in panel(page, "panel-alarm") and "Quality___get_inspection_data" in panel(page, "panel-tools")


def test_a_record_with_markup_is_shown_as_text():
    c = fleet()
    c.other_records[0] = app_record("quality_agent", team="<script>alert(1)</script>")
    page = screen(c).get("/agents").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_menu_marks_the_page():
    assert 'aria-current="page" class="active" href="/agents"' in screen(fleet()).get("/agents").text


def test_a_well_formed_name_that_is_not_hosted_is_refused_before_any_job(monkeypatch):
    calls = []
    monkeypatch.setattr(stop_agent, "stop", lambda *a, **kw: calls.append("stop"))
    monkeypatch.setattr(stop_agent, "resume", lambda *a, **kw: calls.append("resume"))
    c = fleet()
    web = screen(c)
    hub = web.app.state.hub
    right = token(web.get("/agents").text)
    for action in ("stop", "resume"):
        r = web.post(f"/agents/ghost/{action}", headers=ORIGIN, data={"token": right}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/agents?err=agent", action
    assert hub.jobs.current() is None and calls == []
    assert panel(web.get("/agents?err=agent&lang=ko").text, "page-err") == STRINGS["ko"]["err.agent"]
    r = web.post("/agents/docs_adk/resume", headers=ORIGIN, data={"token": right}, follow_redirects=False)
    assert r.headers["location"] == "/agents?msg=started" and hub.jobs.current().wait(5)     # a hosted one goes on


def test_a_stop_that_leaves_sessions_running_ends_the_job_failed(monkeypatch):
    def stop(c, s, p, agent, sessions=None, say=print):
        say("session s4: not stopped (denied)")
        return {"agent": agent, "policy": f"stop_agent_{agent}", "stopped": ["s1", "s2"], "ended": [],
                "failed": {"s4": "denied"}}
    monkeypatch.setattr(stop_agent, "stop", stop)
    web = screen(fleet())
    web.post("/agents/quality_agent/stop", headers=ORIGIN, data={"token": token(web.get("/agents").text)})
    job = web.app.state.hub.jobs.current()
    assert job.wait(5) and job.state == "failed"
    assert job.error.endswith("quality_agent is blocked at the entry by stop_agent_quality_agent; 1 of 3 sessions not "
                              "stopped: run stop again, or give the session with --session <ID>"), job.error
    assert job.lines[0] == "session s4: not stopped (denied)" and job.lines[-1].startswith("sessions: 2 stopped")


def test_the_no_entry_sentence_is_shown_only_when_it_is_known_to_be_true():
    c = fleet()
    c.errors[("ctl", "list_gateway_targets")] = denied("ListGatewayTargets")
    web = screen(c)
    assert row(web, "quality_agent")["can_stop"] is None
    page = web.get("/agents?lang=ko").text
    text = panel(page, "panel-agents")
    assert STRINGS["ko"]["agent.no_entry"] not in text and "AccessDeniedException" in text
    assert not [1 for tag, a in panel_elements(page, "panel-agents") if tag == "form"
                and a["action"].endswith("/stop")]
    assert row(screen(fleet()), "parts_harness")["can_stop"] is False


def test_the_bars_use_the_alarms_own_period_and_statistic():
    c = fleet()
    c.alarms = [{**ALARM, "Period": 300, "Statistic": "Maximum"}]
    screen(c).get("/agents")
    stat = c.metric_queries[-1]["MetricStat"] if c.metric_queries else None
    queries = [q["MetricStat"] for q in c.metric_queries if q["Id"] == "calls"]
    assert queries and queries[0]["Period"] == 300 and queries[0]["Stat"] == "Maximum" and stat
