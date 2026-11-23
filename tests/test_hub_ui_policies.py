"""The hub screen's company policy page: the policies of the two gateways with their status and enforcement mode
apart, the company policy guard_prompt with its mode and its log-only counts per agent, the custom guardrail, and the
buttons that turn the policy on, enforce it, turn it off, and attach or detach the guardrail. The AWS clients are the
fakes of tests/fakes.py; the functions the buttons call are the ones the commands call."""
import threading

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from platform_team.company_policy import policy_names, policy_rollout
from platform_team.custom_guardrail import guardrail_attach
from platform_team.hub_ui import policies
from platform_team.hub_ui.app import create_app
from platform_team.hub_ui.texts import STRINGS
from platform_team.shared_code.config import Settings
from tests.fakes import PLATFORM, FakeClients
from tests.hub_ui_pages import panel, panel_elements, token

S = Settings()
BASE = "http://127.0.0.1:8300"
ORIGIN = {"Origin": BASE}
INTERCEPTOR = {"interceptor": {"lambda": {"arn": PLATFORM.interceptor_arn}}, "interceptionPoints": ["REQUEST", "RESPONSE"],
               "inputConfiguration": {"passRequestHeaders": False}}
NAMES = ["entry_permit_quality_agent", "review_permit_quality_agent", "tool_quality_agent_Parts_get_part_spec",
         "guard_secret_quality_agent", "guard_prompt_quality_agent", "stop_agent_quality_agent",
         "guard_secret_release_review", "shared_tool_read", "some_other_policy"]


def screen(c: FakeClients, **kw) -> TestClient:
    return TestClient(create_app(S, c, PLATFORM, **kw), base_url=BASE)


def fleet(mode: str | None = "LOG_ONLY") -> FakeClients:
    """The policies of NAMES in the engine; guard_prompt in `mode` and the SSM value of that mode (None: off, no policy)."""
    c = FakeClients(record_status=None, existing_policies=NAMES)
    if mode is None:
        del c.policies["guard_prompt_quality_agent"]
    else:
        c.policies["guard_prompt_quality_agent"]["mode"] = mode
        c.parameters[S.ssm("policies", "guard_prompt")] = mode
    return c


def test_kind_of_sorts_every_policy_name_to_its_gateway():
    assert set(policy_names.KINDS) == {"entry_permit", "review_permit", "tool", "guard_secret", "guard_prompt",
                                       "stop_agent"}
    assert policies.kind_of("entry_permit_quality_agent") == ("entry_permit", "agent_gw")
    assert policies.kind_of("review_permit_quality_agent") == ("review_permit", "agent_gw")
    assert policies.kind_of("tool_quality_agent_Parts_get_part_spec") == ("tool", "tool_gw")
    assert policies.kind_of("guard_secret_quality_agent") == ("guard_secret", "agent_gw")
    assert policies.kind_of("guard_prompt_quality_agent") == ("guard_prompt", "agent_gw")
    assert policies.kind_of("stop_agent_quality_agent") == ("stop_agent", "agent_gw")
    assert policies.kind_of("shared_tool_read") == ("shared_read", "tool_gw")
    assert policies.kind_of("some_other_policy") == ("other", "")
    assert policies.kind_of("") == ("other", "")


def test_the_page_shows_status_and_enforcement_mode_apart():
    c = fleet("LOG_ONLY")
    c.policies["stop_agent_quality_agent"].update(mode="ACTIVE", status="CREATING")
    web = screen(c)
    value = policies.view(web.app.state.hub)["gateways"]["value"]
    assert [g["key"] for g in value] == ["agent_gw", "tool_gw", "other"]
    agent_gw, tool_gw, other = value
    assert {p["name"] for p in tool_gw["policies"]} == {"tool_quality_agent_Parts_get_part_spec", "shared_tool_read"}
    assert [p["name"] for p in other["policies"]] == ["some_other_policy"]
    row = next(p for p in agent_gw["policies"] if p["name"] == "guard_prompt_quality_agent")
    assert row == {"name": "guard_prompt_quality_agent", "kind": "guard_prompt", "status": "ACTIVE", "mode": "LOG_ONLY"}
    page = web.get("/policies?lang=ko").text
    agents = panel(page, "panel-gateway-agent_gw")
    assert "이름 종류 상태 적용 모드" in agents
    assert "guard_prompt_quality_agent 프롬프트 공격 차단 ACTIVE 기록 모드 LOG_ONLY" in agents       # status, then mode
    assert "stop_agent_quality_agent 에이전트 멈춤 CREATING 적용 모드 ACTIVE" in agents
    assert "tool_quality_agent_Parts_get_part_spec" in panel(page, "panel-gateway-tool_gw")
    assert "shared_tool_read 공유 읽기 도구 허용" in panel(page, "panel-gateway-tool_gw")
    assert "some_other_policy" in panel(page, "panel-other") and "그 밖의 정책" in panel(page, "panel-other")
    english = panel(web.get("/policies?lang=en").text, "panel-gateway-agent_gw")
    assert "Name Kind Status Enforcement mode" in english
    assert "guard_prompt_quality_agent Prompt-attack guard ACTIVE Log-only LOG_ONLY" in english


def test_the_company_panel_shows_both_policies_in_each_mode():
    for mode, word in ((None, "꺼짐"), ("LOG_ONLY", "기록 모드"), ("ACTIVE", "적용 모드")):
        web = screen(fleet(mode))
        company = policies.view(web.app.state.hub)["company"]["value"]
        assert company["guard_secret"] == {"key": "guard_secret", "fixed": True, "agents": 2}
        assert company["guard_prompt"] == {"key": "guard_prompt", "mode": mode}
        text = panel(web.get("/policies?lang=ko").text, "panel-company")
        assert STRINGS["ko"]["policy.guard_secret.says"] in text and STRINGS["ko"]["policy.guard_prompt.says"] in text
        assert f"guard_prompt {word}" in text, (mode, text)
        assert "guard_secret 적용 모드 2" not in text and STRINGS["ko"]["policy.guard_secret.fixed"] in text
    text = panel(screen(fleet("ACTIVE")).get("/policies?lang=en").text, "panel-company")
    assert "guard_prompt Enforced" in text and STRINGS["en"]["policy.guard_prompt.says"] in text


def test_the_report_shows_matches_and_flips_per_agent():
    c = fleet("LOG_ONLY")
    pid = "guard_prompt_quality_agent-id"
    c.statistics = {("LogOnlyMatches", pid): 1, ("LogOnlyDecisionFlips", pid): 0}
    web = screen(c)
    assert policies.view(web.app.state.hub)["report"]["value"] == {
        "quality_agent": {"mode": "LOG_ONLY", "matches": 1, "flips": 0}}
    text = panel(web.get("/policies?lang=ko").text, "panel-report")
    assert "걸린 요청 LogOnlyMatches" in text and "막았을 요청 LogOnlyDecisionFlips" in text
    assert "quality_agent 기록 모드 1 0" in text and "최근 60분" in text
    off = panel(screen(fleet(None)).get("/policies?lang=ko").text, "panel-report")
    assert STRINGS["ko"]["report.none"] in off
    assert "quality_agent 기록 모드 1 0" in panel(screen(c).get("/policies?lang=ko").text, "panel-report")


def read_back(agent: str, mode: str) -> str:
    return STRINGS["ko"]["job.read_back"].format(agent=agent, mode=mode)


def forms(page: str, element_id: str) -> list[tuple[dict, list[dict]]]:
    """Each form of a panel with its attributes and the attributes of its inputs and buttons."""
    out = []
    for tag, attrs in panel_elements(page, element_id):
        if tag == "form":
            out.append((attrs, []))
        elif tag in ("input", "button") and out:
            out[-1][1].append({"tag": tag, **attrs})
    return out


def test_mode_buttons_call_rollout_and_remove(monkeypatch):
    calls = []

    def rollout(c, s, p, key, word, say=print):
        calls.append(("rollout", c, s, p, key, word))
        say("quality_agent: created")
        return {"policy": key, "mode": policy_rollout.MODE_WORDS[word], "agents": {"quality_agent": "created"},
                "read": {"quality_agent": policy_rollout.MODE_WORDS[word]}}

    def remove(c, s, p, key, say=print):
        calls.append(("remove", c, s, p, key))
        say("quality_agent: removed")
        return {"policy": key, "agents": {"quality_agent": "removed"}, "read": {"quality_agent": None}}
    monkeypatch.setattr(policy_rollout, "rollout", rollout)
    monkeypatch.setattr(policy_rollout, "remove", remove)
    c = fleet(None)
    web = screen(c)
    hub = web.app.state.hub
    page = web.get("/policies").text
    (form, controls), = forms(page, "panel-company")
    assert form["action"] == "/policies/guard_prompt/mode" and form["method"] == "post"
    buttons = {b["value"]: b for b in controls if b["tag"] == "button"}
    assert set(buttons) == {"log-only", "active", "off"} and all(b["name"] == "mode" for b in buttons.values())
    assert "disabled" in buttons["off"] and "disabled" not in buttons["log-only"]       # it is off now
    assert [b for b in controls if b["tag"] == "input"] == [{"tag": "input", "type": "hidden", "name": "token",
                                                              "value": token(page)}]
    for word, kind in (("log-only", "rollout"), ("active", "rollout"), ("off", "remove")):
        r = web.post(form["action"], headers=ORIGIN, data={"token": token(page), "mode": word}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/policies?msg=started", word
        job = hub.jobs.current()
        assert job.wait(5) and (job.kind, job.target, job.state) == ("rollout", "guard_prompt", "done"), job.error
        assert calls[-1][0] == kind and calls[-1][1:5] == (c, S, PLATFORM, "guard_prompt")
        if kind == "rollout":
            assert calls[-1][5] == word
    assert [x[0] for x in calls] == ["rollout", "rollout", "remove"]
    assert job.lines == ["quality_agent: removed", read_back("quality_agent", "꺼짐")]
    shown = panel(web.get("/policies?lang=ko").text, "panel-job")
    assert "quality_agent: removed" in shown and read_back("quality_agent", "꺼짐") in shown
    assert hub.jobs.get(hub.jobs.current().id).lines == job.lines


def test_the_job_says_the_mode_each_agent_reads_back(monkeypatch):
    def rollout(c, s, p, key, word, say=print):
        say("quality_agent: switched")
        return {"policy": key, "mode": "ACTIVE", "agents": {"quality_agent": "switched", "docs_adk": "failed"},
                "read": {"quality_agent": "ACTIVE", "docs_adk": None}}
    monkeypatch.setattr(policy_rollout, "rollout", rollout)
    web = screen(fleet("LOG_ONLY"))
    web.post("/policies/guard_prompt/mode", headers=ORIGIN, data={"token": token(web.get("/policies").text),
                                                                 "mode": "active"})
    job = web.app.state.hub.jobs.current()
    assert job.wait(5)
    assert job.lines == ["quality_agent: switched", read_back("quality_agent", "적용 모드 (ACTIVE)"),
                         read_back("docs_adk", "꺼짐")]


def test_the_buttons_do_what_the_command_does():
    c = fleet(None)
    web = screen(c)
    page = web.get("/policies").text
    web.post("/policies/guard_prompt/mode", headers=ORIGIN, data={"token": token(page), "mode": "log-only"})
    assert web.app.state.hub.jobs.current().wait(5) and web.app.state.hub.jobs.current().state == "done"
    assert c.parameters[S.ssm("policies", "guard_prompt")] == "LOG_ONLY"
    web.post("/policies/guard_prompt/mode", headers=ORIGIN, data={"token": token(page), "mode": "off"})
    assert web.app.state.hub.jobs.current().wait(5)
    assert S.ssm("policies", "guard_prompt") not in c.parameters
    assert "guard_prompt_quality_agent" not in c.policies


def test_an_unknown_policy_or_mode_is_refused():
    c = fleet("LOG_ONLY")
    web = screen(c)
    hub = web.app.state.hub
    right = token(web.get("/policies").text)
    for path, form, err in (("/policies/guard_prompt/mode", {"token": right, "mode": "loud"}, "mode"),
                            ("/policies/guard_prompt/mode", {"token": right}, "mode"),
                            ("/policies/guard_prompt/mode", {"token": right, "mode": "ACTIVE"}, "mode"),
                            ("/policies/guard_secret/mode", {"token": right, "mode": "active"}, "policy"),
                            ("/policies/nothing/mode", {"token": right, "mode": "off"}, "policy"),
                            ("/guardrail/explode", {"token": right}, "action")):
        r = web.post(path, headers=ORIGIN, data=form, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/policies?err={err}", (path, form)
    assert hub.jobs.current() is None and c.mode_changes == [] and c.created_policies == []      # no job, no change
    for lang in ("ko", "en"):
        for err in ("mode", "policy", "action"):
            assert panel(web.get(f"/policies?err={err}&lang={lang}").text, "page-err") == STRINGS[lang][f"err.{err}"]


def guardrail(attached: bool) -> FakeClients:
    c = fleet("LOG_ONLY")
    if attached:
        c.gateways[PLATFORM.agent_gw["id"]]["interceptorConfigurations"] = [INTERCEPTOR]
    return c


def test_the_guardrail_panel_shows_its_state_and_only_the_button_that_applies():
    for attached, button, word in ((False, "attach", "떨어져 있음"), (True, "detach", "붙어 있음")):
        web = screen(guardrail(attached))
        assert policies.view(web.app.state.hub)["guardrail"]["value"] == {
            "attached": attached, "points": ["REQUEST", "RESPONSE"] if attached else [], "gateway_status": "READY"}
        page = web.get("/policies?lang=ko").text
        text = panel(page, "panel-guardrail")
        assert word in text and "READY" in text and "Amazon Bedrock Guardrails" in text
        (form, controls), = forms(page, "panel-guardrail")
        assert form["action"] == f"/guardrail/{button}" and form["method"] == "post"
        assert [b["tag"] for b in controls if b["tag"] == "button"] == ["button"]
        assert ("REQUEST" in text and "RESPONSE" in text) is attached


def test_guardrail_buttons_call_attach_and_detach(monkeypatch):
    calls = []
    for name in ("attach", "detach"):
        def fn(c, s, p, _name=name):
            calls.append((_name, c, s, p))
            return {"attached": _name == "attach", "changed": True}
        monkeypatch.setattr(guardrail_attach, name, fn)
    c = guardrail(False)
    web = screen(c)
    hub = web.app.state.hub
    for action in ("attach", "detach"):
        page = web.get("/policies").text
        r = web.post(f"/guardrail/{action}", headers=ORIGIN, data={"token": token(page)}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/policies?msg=started"
        job = hub.jobs.current()
        assert job.wait(5) and (job.kind, job.target, job.state) == ("guardrail", action, "done"), job.error
        assert job.lines == [f"guardrail {'attached' if action == 'attach' else 'detached'}: changed"]
    assert calls == [("attach", c, S, PLATFORM), ("detach", c, S, PLATFORM)]


def test_a_second_press_while_a_job_runs_is_not_taken_and_the_buttons_wait():
    gate = threading.Event()
    web = screen(fleet("LOG_ONLY"))
    hub = web.app.state.hub
    hub.jobs.start("test", "slow", lambda say: gate.wait(5) and {})
    page = web.get("/policies").text
    assert all("disabled" in b for _, controls in forms(page, "panel-company") + forms(page, "panel-guardrail")
               for b in controls if b["tag"] == "button")
    r = web.post("/policies/guard_prompt/mode", headers={**ORIGIN, "Referer": f"{BASE}/policies"},
                 data={"token": token(page), "mode": "active"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/policies?err=busy"
    gate.set()
    assert hub.jobs.current().wait(5)


def denied(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not allowed on arn:aws:iam::123456789012:x"}},
                       operation)


def test_one_failing_read_is_one_line_and_the_other_panels_show():
    c = fleet("LOG_ONLY")
    c.errors[("ctl", "list_policies")] = denied("ListPolicies")
    page = screen(c).get("/policies?lang=ko").text
    for element_id in ("panel-gateway-agent_gw", "panel-gateway-tool_gw", "panel-report"):
        assert STRINGS["ko"]["panel.error"] in panel(page, element_id), element_id
    assert "123456789012" not in page and "<ACCOUNT>" in panel(page, "panel-report")
    assert "기록 모드" in panel(page, "panel-company") and "guard_secret" in panel(page, "panel-company")
    assert "떨어져 있음" in panel(page, "panel-guardrail")

    c = fleet("LOG_ONLY")
    c.errors[("ctl", "get_gateway")] = denied("GetGateway")
    page = screen(c).get("/policies?lang=ko").text
    assert STRINGS["ko"]["panel.error"] in panel(page, "panel-guardrail")
    assert "guard_prompt_quality_agent" in panel(page, "panel-gateway-agent_gw")

    c = fleet("LOG_ONLY")
    c.errors[("ssm", "get_parameters_by_path")] = denied("GetParametersByPath")
    page = screen(c).get("/policies?lang=ko").text
    assert STRINGS["ko"]["panel.error"] in panel(page, "panel-company")
    assert "guard_prompt_quality_agent" in panel(page, "panel-gateway-agent_gw")


def test_the_menu_marks_the_page():
    assert 'aria-current="page" class="active" href="/policies"' in screen(fleet("LOG_ONLY")).get("/policies").text
