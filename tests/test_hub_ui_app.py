"""The hub screen's frame and its safety rules: only this PC's host names, a change only from the screen's own page
with its token, the account ID masked in every body, a page for a hub that is not deployed, one failing read kept to
its panel, the two languages. The AWS clients are the fakes of tests/fakes.py; nothing calls AWS."""
import pathlib
import re

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from platform_team.hub_ui import app as hub_app
from platform_team.hub_ui.app import DEFAULT_PORT, create_app
from platform_team.hub_ui.texts import STRINGS
from platform_team.shared_code.config import Settings
from tests.fakes import ACCOUNT, PLATFORM, FakeClients
from tests.hub_ui_pages import panel, token

S = Settings()
BASE = f"http://127.0.0.1:{DEFAULT_PORT}"
ORIGIN = {"Origin": BASE}
TEMPLATES = pathlib.Path(hub_app.__file__).parent / "templates"


def screen(c=None, platform=PLATFORM, base=BASE) -> TestClient:
    return TestClient(create_app(S, c or FakeClients(record_status=None), platform), base_url=base)


def with_test_route(web: TestClient, ran: list) -> TestClient:
    """A POST route for the tests only: it answers the form field `note`, so it shows that the form reached it."""
    @web.app.post("/test-only")
    async def test_only(request: Request):
        form = await request.form()
        ran.append(form.get("note"))
        return PlainTextResponse(f"note: {form.get('note')}")
    return web


def test_every_page_says_it_is_a_sample_screen():
    web = screen()
    assert "샘플 화면" in web.get("/").text
    english = web.get("/?lang=en")
    assert "Sample screen" in english.text and "샘플 화면" not in english.text
    assert english.cookies.get("hub_lang") == "en"
    again = web.get("/").text                                       # the cookie keeps the choice
    assert "Sample screen" in again and "샘플 화면" not in again
    not_deployed = screen(platform=None)                            # no SSM values: the not-deployed page
    assert "샘플 화면" in not_deployed.get("/").text


def test_a_request_for_another_host_is_refused():
    c = FakeClients(record_status=None)
    for base in ("http://evil.example:8300", "http://127.0.0.1:9999", "http://localhost.evil.example:8300"):
        r = screen(c, platform=None, base=base).get("/")
        assert r.status_code == 403, base
    r = screen(c, platform=None).get("/", headers={"Host": "evil.example:8300"})
    assert r.status_code == 403
    assert c.calls == []                                            # no AWS call for a refused request
    english = screen(c, platform=None, base="http://evil.example:8300").get("/?lang=en")
    assert english.text == "This screen answers on 127.0.0.1:8300 and localhost:8300 only."
    assert screen(c, platform=None, base="http://localhost:8300").get("/").status_code == 200


def test_a_post_from_another_origin_is_refused():
    ran = []
    web = with_test_route(screen(), ran)
    right = token(web.get("/").text)
    cases = [({"Origin": "http://evil.example"}, {"token": right, "note": "a"}),     # another origin
             ({"Origin": "http://127.0.0.1:9999"}, {"token": right, "note": "b"}),   # another port
             ({}, {"note": "c"}),                                                     # no Origin and no token
             ({}, {"token": right, "note": "d"}),                                     # the token without an Origin
             (ORIGIN, {"note": "e"}),                                                 # no token
             (ORIGIN, {"token": right + "x", "note": "f"}),                           # a wrong token
             (ORIGIN, {"token": [right, right], "note": "g"})]                        # two tokens
    for headers, form in cases:
        r = web.post("/test-only", headers=headers, data=form)
        assert r.status_code == 403, (headers, form)
    r = web.post("/test-only", headers=ORIGIN, json={"token": right, "note": "h"})       # not a form
    assert r.status_code == 403
    assert ran == [] and web.app.state.hub.jobs.current() is None


def test_a_post_with_the_page_token_is_let_through():
    ran = []
    web = with_test_route(screen(), ran)
    page = web.get("/").text
    r = web.post("/test-only", headers=ORIGIN, data={"token": token(page), "note": "hello"})
    assert r.status_code == 200 and r.text == "note: hello" and ran == ["hello"]
    r = web.post("/test-only", headers={"Origin": "http://localhost:8300"}, data={"token": token(page), "note": "again"})
    assert r.status_code == 200 and ran == ["hello", "again"]


def test_no_other_site_can_show_the_screen_in_a_frame_and_the_page_loads_nothing_from_elsewhere():
    web = screen()
    for r in (web.get("/"), web.get("/", headers={"Host": "evil.example:8300"})):
        assert r.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
        assert "default-src 'self'" in r.headers["content-security-policy"]
    assert not re.search(r"""(src|href)=["'](https?:)?//""", web.get("/").text)
    assert not re.search(r"@import|url\(", web.get("/").text)


def test_the_account_id_never_leaves_the_app():
    c = FakeClients(record_status=None)
    c.other_records = [{"name": f"agent_{ACCOUNT}", "recordId": "rec-x", "recordType": "AGENT", "status": "APPROVED"}]
    c.alarms = [{"AlarmName": f"hub-calls-{ACCOUNT}", "StateValue": "OK"}]
    web = screen(c)
    hub = web.app.state.hub
    done = hub.jobs.start("test", "masking", lambda say: say(f"made arn:aws:iam::{ACCOUNT}:role/hub-x") or {})
    assert done.wait(5)
    html = web.get("/").text
    assert ACCOUNT not in html and "agent_&lt;ACCOUNT&gt;" in html      # in HTML the mark is text, not a tag
    assert "agent_<ACCOUNT>" in panel(html, "panel-catalog") and "hub-calls-<ACCOUNT>" in panel(html, "panel-alarms")
    assert "arn:aws:iam::<ACCOUNT>:role/hub-x" in panel(html, "panel-job")
    data = web.get(f"/jobs/{done.id}")
    assert ACCOUNT not in data.text
    assert data.json() == {"id": done.id, "kind": "test", "target": "masking", "state": "done",
                           "lines": ["made arn:aws:iam::<ACCOUNT>:role/hub-x"], "error": ""}

    def fail(say):
        raise RuntimeError(f"role arn:aws:iam::{ACCOUNT}:role/hub-x refused")
    failed = hub.jobs.start("test", "failing", fail)
    assert failed.wait(5)
    data = web.get(f"/jobs/{failed.id}")
    assert ACCOUNT not in data.text and data.json()["state"] == "failed"
    assert data.json()["error"] == "RuntimeError: role arn:aws:iam::<ACCOUNT>:role/hub-x refused"
    assert web.get("/jobs/no-such-job").status_code == 404


def test_a_hub_that_is_not_deployed_gets_a_page_that_says_so():
    c = FakeClients(record_status=None)                             # nothing under /hub/platform/
    r = screen(c, platform=None).get("/")
    assert r.status_code == 200
    assert STRINGS["ko"]["not_deployed.title"] in r.text and "/hub/platform/" in r.text
    assert "Traceback" not in r.text and "NotDeployed" not in r.text
    calls = [call for call in c.calls if call[1] != "get_paginator"]
    assert calls == [("ssm", "get_parameters_by_path")]             # the platform values, and nothing else


def test_a_read_of_the_platform_values_that_fails_is_one_line_on_the_page():
    c = FakeClients(record_status=None)
    c.errors[("ssm", "get_parameters_by_path")] = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": f"User: arn:aws:sts::{ACCOUNT}:assumed-role/x is not "
                                                             "authorized to perform: ssm:GetParametersByPath"}},
        "GetParametersByPath")
    r = screen(c, platform=None).get("/")
    assert r.status_code == 502 and "Traceback" not in r.text and ACCOUNT not in r.text
    assert "AccessDeniedException: User: arn:aws:sts::&lt;ACCOUNT&gt;:assumed-role/x is not authorized" in r.text


def test_one_failing_read_does_not_take_the_page_down():
    c = FakeClients(record_status=None)
    c.other_records = [{"name": "quality_agent", "recordId": "rec-q", "recordType": "AGENT", "status": "APPROVED"}]
    c.errors[("cw", "describe_alarms")] = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": f"User: arn:aws:sts::{ACCOUNT}:assumed-role/x\nis not "
                                                      "authorized to perform: cloudwatch:DescribeAlarms"}},
        "DescribeAlarms")
    web = screen(c)
    r = web.get("/")
    assert r.status_code == 200 and ACCOUNT not in r.text
    alarms = panel(r.text, "panel-alarms")
    assert "AccessDenied: User: arn:aws:sts::<ACCOUNT>:assumed-role/x is not authorized" in alarms
    from platform_team.hub_ui import home
    error = home.view(web.app.state.hub)["alarms"]["error"]
    assert "\n" not in error and ACCOUNT not in error                  # one masked line
    assert re.findall(r"\d+", panel(r.text, "panel-counts"))[:3] == ["1", "0", "0"]
    assert "READY" in panel(r.text, "panel-platform")


def test_a_second_press_while_a_job_runs_is_refused_with_the_sentence():
    import threading
    gate = threading.Event()
    web = screen()
    hub = web.app.state.hub

    @web.app.post("/test-job")
    def test_job(request: Request):
        hub.jobs.start("test", "slow", lambda say: gate.wait(5) and {})
        return hub_app.back(request, "/", msg="started")

    right = token(web.get("/").text)
    r = web.post("/test-job", headers=ORIGIN, data={"token": right}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?msg=started"
    first = hub.jobs.current()
    r = web.post("/test-job", headers={**ORIGIN, "Referer": f"{BASE}/?lang=ko&msg=started"}, data={"token": right},
                 follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?lang=ko&err=busy"   # the page it was pressed on
    shown = web.get(r.headers["location"]).text
    assert STRINGS["ko"]["err.busy"] in panel(shown, "page-err") and panel(shown, "panel-job")
    assert STRINGS["ko"]["msg.started"] not in shown
    assert hub.jobs.current() is first and first.state == "running"     # no second job
    for referer in ("http://evil.example/x", f"{BASE}/test-job"):         # another site; the POST path itself
        r = web.post("/test-job", headers={**ORIGIN, "Referer": referer}, data={"token": right}, follow_redirects=False)
        assert r.headers["location"] == "/?err=busy", referer
    gate.set()
    assert first.wait(5)


def test_a_press_goes_back_to_a_page_with_its_sentence_in_both_languages():
    web = screen()

    @web.app.post("/test-refuse")
    def test_refuse(request: Request):
        return hub_app.back(request, "/?lang=en", err="busy")

    @web.app.post("/test-start")
    def test_start(request: Request):
        return hub_app.back(request, "//evil.example/x", msg="started")

    right = token(web.get("/").text)
    r = web.post("/test-refuse", headers=ORIGIN, data={"token": right}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?lang=en&err=busy"
    english = web.get(r.headers["location"]).text
    assert panel(english, "page-err") == STRINGS["en"]["err.busy"]
    assert panel(web.get("/?lang=ko&err=busy").text, "page-err") == STRINGS["ko"]["err.busy"]
    r = web.post("/test-start", headers=ORIGIN, data={"token": right}, follow_redirects=False)
    assert r.headers["location"] == "/evil.example/x?msg=started"           # a path of this screen, never another host
    assert panel(web.get("/?lang=ko&msg=started").text, "page-msg") == STRINGS["ko"]["msg.started"]


def test_a_message_key_that_the_texts_do_not_have_shows_nothing():
    page = screen().get("/", params={"msg": "<script>alert(1)</script>", "err": "nothing-like-this"}).text
    assert 'id="page-msg"' not in page and 'id="page-err"' not in page
    assert "nothing-like-this" not in page and "alert(1)" not in page


def test_markup_in_a_value_is_shown_as_text():
    script, image = "<script>alert(1)</script>", "<img src=x onerror=alert(1)>"
    c = FakeClients(record_status=None)
    c.other_records = [{"name": script, "recordId": "rec-x", "recordType": "AGENT", "status": image}]
    c.alarms = [{"AlarmName": f"hub-{script}", "StateValue": "OK"}]
    c.errors[("sns", "get_topic_attributes")] = ClientError({"Error": {"Code": "AccessDenied", "Message": image}},
                                                            "GetTopicAttributes")
    web = screen(c)
    assert web.app.state.templates.env.autoescape is True             # whatever a template's file name is
    job = web.app.state.hub.jobs.start("test", image, lambda say: say(script) or {})
    assert job.wait(5)
    html = web.get("/").text
    assert script not in html and image not in html and "onerror=alert(1)>" not in html
    escaped_script, escaped_image = "&lt;script&gt;alert(1)&lt;/script&gt;", "&lt;img src=x onerror=alert(1)&gt;"
    for element in ("panel-catalog", "panel-alarms", "panel-job"):
        assert escaped_script in html.split(f'id="{element}"', 1)[1], element
    for element in ("panel-catalog", "panel-job", "panel-platform"):        # status, target, the panel's error
        assert escaped_image in html.split(f'id="{element}"', 1)[1], element
    assert script in panel(html, "panel-catalog") and image in panel(html, "panel-platform")   # shown as text
    data = web.get(f"/jobs/{job.id}").json()
    assert data["target"] == image and data["lines"] == [script]           # the page script writes them as text


def test_an_unknown_path_gets_a_framed_page_that_says_so():
    web = screen()
    for lang in ("ko", "en"):
        r = web.get(f"/no-such-page?lang={lang}")
        assert r.status_code == 404 and STRINGS[lang]["sample"] in r.text
        assert panel(r.text, "main").startswith(STRINGS[lang]["not_found.title"])
    r = web.get("/jobs/no-such-job")
    assert r.status_code == 404 and r.headers["content-type"] == "application/json"   # the page script reads it


def test_the_page_scripts_carry_the_nonce_of_the_policy():
    web = screen()
    pages = [web.get("/"), web.get("/no-such-page"), screen(platform=None).get("/")]
    policy = pages[0].headers["content-security-policy"]
    script_src = re.search(r"script-src ([^;]+)", policy).group(1).split()
    nonce = next(s for s in script_src if s.startswith("'nonce-"))[len("'nonce-"):-1]
    assert "'unsafe-inline'" not in script_src and len(nonce) >= 22
    tags = re.findall(r"<script[^>]*>", pages[0].text)
    assert len(tags) == 2 and all(f'nonce="{nonce}"' in tag for tag in tags)
    assert web.get("/").headers["content-security-policy"] == policy         # one nonce for each start of the app
    for r in pages[1:]:
        assert re.findall(r"<script[^>]*>", r.text) and all("nonce=" in tag for tag in re.findall(r"<script[^>]*>", r.text))
    assert "'nonce-" + nonce not in pages[2].headers["content-security-policy"]   # another start, another nonce
    handlers = [f.name for f in TEMPLATES.glob("*.html") if re.search(r"\son[a-z]+\s*=", f.read_text())]
    assert handlers == []                                                    # no inline event handler attribute


def test_every_client_the_screens_use_is_made_before_the_first_request():
    from platform_team.shared_code.aws_helpers import _SERVICES
    app = create_app(S)                                                      # makes the clients; calls nothing
    assert sorted(app.state.hub.c._clients) == sorted(_SERVICES)


def test_the_app_is_made_and_read_without_boto3_when_clients_and_platform_are_given(monkeypatch):
    def no_boto3(*args, **kw):
        raise AssertionError("boto3 was called")
    monkeypatch.setattr(boto3, "Session", no_boto3)
    monkeypatch.setattr(boto3, "client", no_boto3)
    assert screen().get("/").status_code == 200


def test_the_app_listens_on_this_pc_only(monkeypatch, capsys):
    import uvicorn

    from platform_team.hub_ui import __main__ as entry
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw, app=app))
    monkeypatch.setenv("HUB_UI_PORT", "8411")
    monkeypatch.setenv("HUB_UI_HOST", "0.0.0.0")                        # not read: the host is fixed in the code
    entry.main()
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8411 and seen["app"].state.hub.port == 8411
    assert "http://127.0.0.1:8411" in capsys.readouterr().out


def test_both_languages_have_the_same_keys():
    assert set(STRINGS["ko"]) == set(STRINGS["en"])
    assert [k for lang in STRINGS for k, v in STRINGS[lang].items() if not v.strip()] == []


def test_templates_use_only_keys_that_exist():
    used = set()
    for f in sorted(TEMPLATES.glob("*.html")):
        used |= set(re.findall(r"""\bt\(\s*["']([^"']+)["']\s*[,)]""", f.read_text()))
    assert used and sorted(used - set(STRINGS["ko"])) == []


def test_a_websocket_is_refused():
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with screen().websocket_connect("/"):
            pass
