"""The hub screen's home page: the counts of hosted agents, reviews and tools from the catalog, each platform part with
the AWS service that runs it, the company policy's mode and the custom guardrail, the hub's alarms, the catalog's
records and the two concept pictures. The AWS clients are the fakes of tests/fakes.py."""
import re

from fastapi.testclient import TestClient

from platform_team.hub_ui import home
from platform_team.hub_ui.app import create_app
from platform_team.shared_code.config import Settings
from tests.fakes import PLATFORM, FakeClients
from tests.hub_ui_pages import panel, panel_elements

S = Settings()
BASE = "http://127.0.0.1:8300"
INTERCEPTOR = {"interceptor": {"lambda": {"arn": PLATFORM.interceptor_arn}}, "interceptionPoints": ["REQUEST", "RESPONSE"],
               "inputConfiguration": {"passRequestHeaders": False}}


def record(name: str, record_type: str, status: str) -> dict:
    return {"name": name, "recordId": f"rec-{name}", "recordType": record_type, "status": status}


def screen(c: FakeClients) -> TestClient:
    return TestClient(create_app(S, c, PLATFORM), base_url=BASE)


def test_home_counts_hosted_agents_reviews_and_tools():
    c = FakeClients(record_status=None)
    c.other_records = [record("release_review", "AGENT", "APPROVED"), record("quality_agent", "AGENT", "APPROVED"),
                       record("docs_adk", "AGENT", "PENDING_APPROVAL"), record("parts-tools", "MCP", "APPROVED"),
                       record("old_agent", "AGENT", "REJECTED"), record("new_agent", "AGENT", "DRAFT"),
                       record("draft-tools", "MCP", "PENDING_APPROVAL")]
    web = screen(c)
    assert home.view(web.app.state.hub)["counts"] == {"ok": True, "value": {"hosted": 2, "in_review": 1, "tools": 1}}
    page = web.get("/").text
    counts = panel(page, "panel-counts")
    assert re.findall(r"\d+", counts)[:3] == ["2", "1", "1"] and "AWS Agent Registry" in counts
    assert panel(page, "badge-reviews") == "1"                          # the menu's badge: agents awaiting approval
    for lang, label in (("ko", "승인 대기 중인 에이전트"), ("en", "Agents awaiting approval")):
        shown = web.get(f"/?lang={lang}").text
        assert label in panel(shown, "panel-counts") and "PENDING_APPROVAL" in panel(shown, "panel-counts")
        badge = next(a for tag, a in panel_elements(shown, "badge-reviews") if tag == "span")
        assert badge["title"] == label


def test_home_names_the_aws_service_of_each_platform_part():
    c = FakeClients(record_status=None)
    c.alarms = [{"AlarmName": "hub-tool-calls", "StateValue": "ALARM"}]
    web = screen(c)
    rows = home.view(web.app.state.hub)["platform"]["value"]
    assert rows == [
        {"key": "agent_gw", "name": "hub-agents", "service": "Amazon Bedrock AgentCore Gateway", "state": "READY"},
        {"key": "tool_gw", "name": "hub-tools", "service": "Amazon Bedrock AgentCore Gateway", "state": "READY"},
        {"key": "engine", "name": "hub_pe", "service": "Policy in Amazon Bedrock AgentCore", "state": "ACTIVE"},
        {"key": "catalog", "name": "hub-registry", "service": "AWS Agent Registry", "state": "READY"},
        {"key": "machine", "name": "hub-review", "service": "AWS Step Functions", "state": "ACTIVE"},
        {"key": "topic", "name": "hub-alerts", "service": "Amazon SNS", "state": "1"}]
    page = web.get("/").text
    platform = panel(page, "panel-platform")
    for service in ("Amazon Bedrock AgentCore Gateway", "Policy in Amazon Bedrock AgentCore", "AWS Agent Registry",
                    "AWS Step Functions", "Amazon SNS"):
        assert service in platform, service
    assert [a for tag, a in panel_elements(page, "panel-platform") if "tech" in a.get("class", "")]   # in class tech
    alarms = panel(page, "panel-alarms")
    assert "Amazon CloudWatch" in alarms and "hub-tool-calls" in alarms and "ALARM" in alarms


def test_a_platform_part_that_is_not_deployed_says_so():
    from dataclasses import replace
    c = FakeClients(record_status=None)
    web = TestClient(create_app(S, c, replace(PLATFORM, machine_arn="")), base_url=BASE)
    rows = {r["key"]: r for r in home.view(web.app.state.hub)["platform"]["value"]}
    assert rows["machine"]["state"] is None and rows["agent_gw"]["state"] == "READY"
    assert ("sfn", "describe_state_machine") not in c.calls
    assert "배포되지 않음" in panel(web.get("/").text, "panel-platform")


def test_home_shows_the_company_policy_mode_and_the_guardrail():
    c = FakeClients(record_status=None, parameters={"/hub/policies/guard_prompt": "LOG_ONLY"})
    c.gateways[PLATFORM.agent_gw["id"]]["interceptorConfigurations"] = [INTERCEPTOR]
    web = screen(c)
    assert home.view(web.app.state.hub)["company"] == {
        "ok": True, "value": {"guard_prompt": "LOG_ONLY", "guardrail_attached": True}}
    company = panel(web.get("/").text, "panel-company")
    assert "기록 모드" in company and "LOG_ONLY" in company and "붙어 있음" in company
    assert "Amazon Bedrock AgentCore Gateway" in company and "AWS Systems Manager" in company

    c = FakeClients(record_status=None, parameters={"/hub/policies/guard_prompt": "ACTIVE"})
    web = screen(c)
    assert home.view(web.app.state.hub)["company"]["value"] == {"guard_prompt": "ACTIVE", "guardrail_attached": False}
    company = panel(web.get("/?lang=en").text, "panel-company")
    assert "Enforced" in company and "Detached" in company

    web = screen(FakeClients(record_status=None))
    assert home.view(web.app.state.hub)["company"]["value"] == {"guard_prompt": None, "guardrail_attached": False}
    assert "꺼짐" in panel(web.get("/").text, "panel-company")


def test_home_lists_the_hubs_alarms_and_the_catalogs_records():
    c = FakeClients(record_status=None)
    c.alarms = [{"AlarmName": "hub-tool-calls", "StateValue": "OK"},
                {"AlarmName": "hub-guardrail-errors", "StateValue": "INSUFFICIENT_DATA"},
                {"AlarmName": "hubble-calls", "StateValue": "ALARM"}]           # another prefix's alarm
    c.other_records = [record("quality_agent", "AGENT", "APPROVED"), record("parts-tools", "MCP", "APPROVED")]
    web = screen(c)
    view = home.view(web.app.state.hub)
    assert view["alarms"]["value"] == [{"name": "hub-guardrail-errors", "state": "INSUFFICIENT_DATA"},
                                       {"name": "hub-tool-calls", "state": "OK"}]
    assert view["catalog"]["value"] == [{"name": "parts-tools", "type": "MCP", "status": "APPROVED"},
                                        {"name": "quality_agent", "type": "AGENT", "status": "APPROVED"}]
    page = web.get("/").text
    assert "hubble-calls" not in page
    catalog = panel(page, "panel-catalog")
    assert "quality_agent" in catalog and "parts-tools" in catalog and "승인" in catalog and "AWS Agent Registry" in catalog


def test_the_reads_of_a_page_are_kept_for_a_few_seconds():
    c = FakeClients(record_status=None)
    web = screen(c)
    web.get("/")
    first = len(c.calls)
    web.get("/")
    assert first and len(c.calls) == first                              # the second page within 5 s reads nothing


def test_home_shows_the_concept_picture():
    web = screen(FakeClients(record_status=None))
    for lang, flow1, flow2 in (("ko", "흐름 1. 호스팅", "흐름 2. 운영"), ("en", "Flow 1. Hosting", "Flow 2. Operations")):
        page = web.get(f"/?lang={lang}").text
        images = [a for tag, a in panel_elements(page, "pictures") if tag == "img"]
        assert [a["src"] for a in images] == ["/static/hosting-hub-flow1-concept.png",
                                              "/static/hosting-hub-flow2-concept.png"]
        assert flow1 in images[0]["alt"] and flow2 in images[1]["alt"]
        links = [a["href"] for tag, a in panel_elements(page, "pictures") if tag == "a"]
        assert links == [a["src"] for a in images]                       # each opens at full size
    for src in ("/static/hosting-hub-flow1-concept.png", "/static/hosting-hub-flow2-concept.png"):
        r = web.get(src)
        assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
