"""The hub screen's hosting review page: each agent application of the catalog with the seven steps of its latest
review (an AWS Step Functions execution), the AWS service that runs each step, its time and its error, the lines of
the scan's log that say why it failed, the console link and the reject button. The AWS clients are the fakes of
tests/fakes.py; the history events and the scan's log are written in the shapes boto3 and the scan give."""
import json
import re
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from platform_team.hosting_review import reject_agent
from platform_team.hosting_review.reject_agent import MAX_REASON
from platform_team.hub_ui import reviews
from platform_team.hub_ui.app import create_app
from platform_team.hub_ui.texts import STRINGS
from platform_team.shared_code.config import Settings
from tests.fakes import ACCOUNT, PLATFORM, SPEC, FakeClients
from tests.hub_ui_pages import panel, panel_elements, token

S = Settings()
BASE = "http://127.0.0.1:8300"
ORIGIN = {"Origin": BASE}
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)          # when the reviews of these tests start
NAMES = [name for name, _ in reviews.STEPS]

# ------------------------------------------------------------------ history events as boto3 gives them

KINDS = {"Reviewable": "Choice", "Skipped": "Succeed", "Failed": "Fail",
         "Extra": "Pass"}                                      # the other states are Task states; Extra is not the hub's
RESOURCES = {"Scan": ("codebuild", "startBuild.sync"), "Deploy": ("codebuild", "startBuild.sync"),
             "Notify": ("sns", "publish")}                                     # the other Task states: lambda invoke
ENDS = {"ExecutionSucceeded": {"executionSucceededEventDetails": {"output": "{}"}},
        "ExecutionFailed": {"executionFailedEventDetails": {
            "error": "ReviewFailed", "cause": "A step of the hosting review failed; the notification holds the error"}}}


def history(states, end=None, start=T0) -> list[dict]:
    """GetExecutionHistory's events (boto3's shape) for states given as (state, entered_at, exited_at | None,
    failed_cause | None), the times in seconds after `start`. A failed Task state has TaskFailed with that cause and
    no exit event; `end` adds the execution's last event (ExecutionSucceeded or ExecutionFailed)."""
    events: list[dict] = []

    def add(kind, at, **details):
        events.append({"id": len(events) + 1, "previousEventId": len(events), "type": kind,
                       "timestamp": start + timedelta(seconds=at), **details})
    add("ExecutionStarted", 0, executionStartedEventDetails={
        "input": json.dumps({"detail": {"registryId": "reg-1", "registryRecordId": "rec-1"}}),
        "roleArn": f"arn:aws:iam::{ACCOUNT}:role/hub-sfn-role"})
    for state, entered, exited, failed in states:
        kind = KINDS.get(state, "Task")
        add(f"{kind}StateEntered", entered, stateEnteredEventDetails={"name": state, "input": "{}"})
        if kind == "Task":
            resource_type, resource = RESOURCES.get(state, ("lambda", "invoke"))
            task = {"resourceType": resource_type, "resource": resource}
            add("TaskScheduled", entered, taskScheduledEventDetails={**task, "region": "us-west-2", "parameters": "{}"})
            add("TaskStarted", entered, taskStartedEventDetails=task)
            if failed is not None:
                add("TaskFailed", exited, taskFailedEventDetails={**task, "error": "States.TaskFailed", "cause": failed})
                continue
            if exited is not None:
                add("TaskSucceeded", exited, taskSucceededEventDetails={**task, "output": "{}"})
        if exited is not None:
            add(f"{kind}StateExited", exited, stateExitedEventDetails={"name": state, "output": "{}"})
    if end:
        add(end, (events[-1]["timestamp"] - start).total_seconds(), **ENDS[end])
    return events


LOG_GROUP, LOG_STREAM = "/aws/codebuild/hub-review-scan", "abcdefghij-c462-419f-ba45-abcdefghij00"
SCAN_COMMAND = ("cd /tmp/audit && PIP_ONLY_BINARY=:all: python3 -I -m pip_audit -r /tmp/audit/requirements.txt "
                "--progress-spinner off")
# The cause of a failed CodeBuild step (.sync): the build record, in the keys the alert of 2026-11-22 showed
BUILD_CAUSE = json.dumps({
    "Build": {"Id": f"hub-review-scan:{LOG_STREAM}",
              "Arn": f"arn:aws:codebuild:us-west-2:{ACCOUNT}:build/hub-review-scan:{LOG_STREAM}",
              "BuildStatus": "FAILED", "CurrentPhase": "COMPLETED",
              "Phases": [{"PhaseType": "SUBMITTED", "PhaseStatus": "SUCCEEDED"},
                         {"PhaseType": "INSTALL", "PhaseStatus": "SUCCEEDED", "Contexts": [{"StatusCode": "", "Message": ""}]},
                         {"PhaseType": "BUILD", "PhaseStatus": "FAILED", "Contexts": [{
                             "StatusCode": "COMMAND_EXECUTION_ERROR",
                             "Message": f"Error while executing command: {SCAN_COMMAND}. Reason: exit status 1"}]},
                         {"PhaseType": "COMPLETED"}],
              "Logs": {"GroupName": LOG_GROUP, "StreamName": LOG_STREAM,
                       "DeepLink": "https://console.aws.amazon.com/cloudwatch/home?region=us-west-2#logEvent:x"}},
    "SdkHttpMetadata": {"HttpStatusCode": 200}, "SdkResponseMetadata": {"RequestId": "abcdefghij"}})
# The cause of a failed Lambda step: the function's error
LAMBDA_CAUSE = json.dumps({"errorMessage": "the normal question was not answered: " + "x" * 400,
                           "errorType": "RuntimeError", "requestId": "abcdefghij", "stackTrace": ["  File ..."]})

PASSED = [("Read", 0, 1, None), ("Reviewable", 1, 1, None), ("Scan", 1, 42, None), ("Grant", 42, 57, None),
          ("Deploy", 57, 314, None), ("Entry", 314, 349, None), ("TestCall", 349, 356, None),
          ("Approve", 356, 371, None)]                         # the times of release_review's review of 2026-11-22
RUNNING = [("Read", 0, 2, None), ("Reviewable", 2, 2, None), ("Scan", 2, 38, None), ("Grant", 38, None, None)]
AT_SCAN = [("Read", 0, 2, None), ("Reviewable", 2, 2, None), ("Scan", 2, 38, BUILD_CAUSE), ("Notify", 38, 38, None),
           ("Failed", 38, None, None)]
SKIPPED = [("Read", 0, 1, None), ("Reviewable", 1, 1, None), ("Skipped", 1, 1, None)]

# What the Scan build of a vulnerable submission prints: the buildspec's commands (CodeBuild's own lines start
# with [Container]), submission_check's line, then pip-audit 2.10.1's summary and its table (Name Version ID Fix
# Versions, one row per advisory; the first row is the one the run of 2026-11-22 found).
SCAN_LOG = [
    "[Container] 2026/11/22 09:00:03.000000 Running command python3 -m pip install --quiet pip-audit==2.10.1",
    "[Container] 2026/11/22 09:00:20.000000 Running command echo \"$(python3 --version), pip-audit ...\"",
    "Python 3.13.7, pip-audit 2.10.1",
    f"scan quality_agent, s3://hub-{ACCOUNT}-us-west-2/submissions/appliance/quality_agent/agent.zip version v1",
    "submission unpacked into /tmp/src: main.py, requirements.txt present; 3 requirement lines written to "
    "/tmp/audit/requirements.txt",
    f"[Container] 2026/11/22 09:00:25.000000 Running command {SCAN_COMMAND}",
    "Found 2 known vulnerabilities in 1 package",
    "Name   Version ID                  Fix Versions",
    "------ ------- ------------------- ------------",
    "jinja2 2.11.2  PYSEC-2021-66       2.11.3",
    "jinja2 2.11.2  GHSA-h5c8-rqwp-cp95 3.1.3",
    "",
    f"[Container] 2026/11/22 09:00:36.000000 Command did not exit successfully {SCAN_COMMAND} exit status 1",
    "[Container] 2026/11/22 09:00:36.000000 Phase complete: BUILD State: FAILED",
    "[Container] 2026/11/22 09:00:36.000000 Phase context status code: COMMAND_EXECUTION_ERROR Message: Error while "
    f"executing command: {SCAN_COMMAND}. Reason: exit status 1",
]


def rows(events, status) -> list[tuple]:
    return [(r["name"], r["runs_on"], r["state"], r["seconds"], r["error"]) for r in reviews.steps_of(events, status)]


def test_steps_of_a_review_that_passed():
    assert rows(history(PASSED, "ExecutionSucceeded"), "SUCCEEDED") == [
        ("Read", "AWS Lambda", "passed", 1, ""), ("Scan", "AWS CodeBuild", "passed", 41, ""),
        ("Grant", "AWS Lambda", "passed", 15, ""), ("Deploy", "AWS CodeBuild", "passed", 257, ""),
        ("Entry", "AWS Lambda", "passed", 35, ""), ("TestCall", "AWS Lambda", "passed", 7, ""),
        ("Approve", "AWS Lambda", "passed", 15, "")]
    assert reviews.STEPS == (("Read", "AWS Lambda"), ("Scan", "AWS CodeBuild"), ("Grant", "AWS Lambda"),
                             ("Deploy", "AWS CodeBuild"), ("Entry", "AWS Lambda"), ("TestCall", "AWS Lambda"),
                             ("Approve", "AWS Lambda"))


def test_steps_of_a_running_review():
    steps = reviews.steps_of(history(RUNNING), "RUNNING")
    assert [(r["name"], r["state"], r["seconds"]) for r in steps] == [
        ("Read", "passed", 2), ("Scan", "passed", 36), ("Grant", "running", None), ("Deploy", "waiting", None),
        ("Entry", "waiting", None), ("TestCall", "waiting", None), ("Approve", "waiting", None)]
    assert steps[2]["started"] == T0 + timedelta(seconds=38)        # the view counts its seconds from here
    assert all(r["error"] == "" for r in steps)


def test_steps_of_a_review_that_failed_at_scan():
    steps = reviews.steps_of(history(AT_SCAN, "ExecutionFailed"), "FAILED")
    assert [r["name"] for r in steps] == NAMES                     # Notify and Failed are not rows
    assert [(r["name"], r["state"], r["seconds"]) for r in steps] == [
        ("Read", "passed", 2), ("Scan", "failed", 36), ("Grant", "waiting", None), ("Deploy", "waiting", None),
        ("Entry", "waiting", None), ("TestCall", "waiting", None), ("Approve", "waiting", None)]
    error = steps[1]["error"]
    assert error.startswith(f"States.TaskFailed: build hub-review-scan:{LOG_STREAM} FAILED: BUILD FAILED: Error while "
                            "executing command: cd /tmp/audit")
    assert len(error) <= 300 and "Sdk" not in error              # the build record told in one line, not its JSON
    assert reviews.scan_log(history(AT_SCAN, "ExecutionFailed")) == (LOG_GROUP, LOG_STREAM)
    assert reviews.scan_log(history(PASSED, "ExecutionSucceeded")) is None

    exited = history(AT_SCAN, "ExecutionFailed")     # the same, if AWS also wrote an exit event for the caught state
    at = next(i for i, e in enumerate(exited) if e["type"] == "TaskFailed")
    exited.insert(at + 1, {"type": "TaskStateExited", "timestamp": exited[at]["timestamp"],
                           "stateExitedEventDetails": {"name": "Scan", "output": "{}"}})
    for i, e in enumerate(exited, 1):
        e["id"] = i
    assert reviews.steps_of(exited, "FAILED") == steps

    at_testcall = PASSED[:6] + [("TestCall", 349, 356, LAMBDA_CAUSE), ("Notify", 356, 356, None),
                                ("Failed", 356, None, None)]
    steps = reviews.steps_of(history(at_testcall, "ExecutionFailed"), "FAILED")
    assert [r["state"] for r in steps] == ["passed"] * 5 + ["failed", "waiting"]
    error = steps[5]["error"]
    assert error.startswith("States.TaskFailed: the normal question was not answered: xxx") and len(error) == 300
    assert reviews.scan_log(history(at_testcall, "ExecutionFailed")) is None


def test_steps_of_a_skipped_review():
    assert [(r["name"], r["state"]) for r in reviews.steps_of(history(SKIPPED, "ExecutionSucceeded"), "SUCCEEDED")] \
        == [("Read", "passed")] + [(name, "skipped") for name in NAMES[1:]]


def test_steps_ignore_events_they_do_not_know():
    known = history(PASSED, "ExecutionSucceeded")
    extra = history(PASSED[:3] + [("Extra", 42, 42, None)] + PASSED[3:], "ExecutionSucceeded")   # a state not its own
    extra.insert(5, {"type": "SomethingNewFromAws", "timestamp": T0 + timedelta(seconds=1)})   # a type, no details
    extra.insert(6, {"type": "MapRunRedriven", "timestamp": T0 + timedelta(seconds=1), "mapRunRedrivenEventDetails": {}})
    for i, e in enumerate(extra, 1):                                   # in the middle of the history
        e["id"] = i
    assert any(e["type"] == "PassStateEntered" for e in extra)
    assert reviews.steps_of(extra, "SUCCEEDED") == reviews.steps_of(known, "SUCCEEDED")
    assert len(reviews.steps_of([], "RUNNING")) == 7                               # no event yet: seven waiting rows


def test_scan_findings_keep_the_lines_that_name_a_vulnerable_package():
    assert reviews.scan_findings(SCAN_LOG) == ["jinja2 2.11.2  PYSEC-2021-66       2.11.3",
                                               "jinja2 2.11.2  GHSA-h5c8-rqwp-cp95 3.1.3"]
    many = [f"package{i} 1.0.{i}  PYSEC-2026-{i}  1.0.{i + 1}\n" for i in range(30)]
    assert reviews.scan_findings(SCAN_LOG[:9] + many) == [line.rstrip() for line in many[:20]]     # at most 20


def test_scan_findings_keep_the_submission_checks_refusal():
    refusals = ["submission refused: missing: main.py",
                "submission refused: requirements.txt: direct references are not allowed (name a package on the "
                "index): requests @ https://example.com/requests.whl"]
    log = SCAN_LOG[:4] + refusals + ["[Container] 2026/11/22 09:00:10.000000 Phase complete: BUILD State: FAILED"]
    assert reviews.scan_findings(log) == refusals
    assert reviews.scan_findings(SCAN_LOG[:6]) == []                # a log of a scan that passed its checks so far


# ------------------------------------------------------------------ the pages

def app_record(name: str, status: str, team: str = "device", tools=(), description: str = "") -> dict:
    """A record whose application (descriptors.custom.data) the fake's GetRegistryRecord gives as it is."""
    app = {"name": name, "team": team, "framework": "strands", "tools": list(tools),
           "code_key": f"submissions/{team}/{name}/agent.zip", "code_version": "v1"}
    return {"name": name, "recordId": f"rec-{name}", "recordType": "AGENT", "status": status,
            "description": description or f"{name}: agent of team {team}",
            "descriptors": {"custom": {"data": json.dumps(app)}}}


def execution(name: str, record: str, status: str, states, end=None, start=T0) -> dict:
    events = history(states, end, start)
    return {"name": name, "record": record, "status": status, "startDate": start, "events": events,
            **({"stopDate": events[-1]["timestamp"]} if status != "RUNNING" else {})}


def screen(c: FakeClients, **kw) -> TestClient:
    return TestClient(create_app(S, c, PLATFORM, **kw), base_url=BASE)


def arn_of(name: str) -> str:
    return f"{PLATFORM.machine_arn.replace(':stateMachine:', ':execution:')}:{name}"


def failed_at_scan() -> FakeClients:
    """quality_agent (rec-1, PENDING_APPROVAL) whose review failed at Scan, with the scan's log."""
    c = FakeClients()
    c.executions = [execution("review-quality-1", "rec-1", "FAILED", AT_SCAN, "ExecutionFailed")]
    c.log_events[(LOG_GROUP, LOG_STREAM)] = SCAN_LOG
    return c


def test_the_page_lists_agent_records_with_their_latest_review():
    c = FakeClients()                                       # quality_agent, rec-1, PENDING_APPROVAL, application SPEC
    c.other_records = [app_record("release_review", "APPROVED", tools=["Release___file_review_request"]),
                       {"name": "parts-tools", "recordId": "rec-parts-tools", "recordType": "MCP", "status": "APPROVED"},
                       app_record("docs_adk", "DRAFT", team="docs")]                       # no review yet
    c.executions = [
        execution("quality-first", "rec-1", "FAILED", AT_SCAN, "ExecutionFailed", start=T0 - timedelta(hours=2)),
        execution("release", "rec-release_review", "SUCCEEDED", PASSED, "ExecutionSucceeded",
                  start=T0 - timedelta(hours=1)),
        execution("parts", "rec-parts-tools", "SUCCEEDED", SKIPPED, "ExecutionSucceeded", start=T0 - timedelta(hours=3)),
        execution("quality-second", "rec-1", "RUNNING", RUNNING)]
    web = screen(c)
    apps = reviews.view(web.app.state.hub)["applications"]["value"]
    assert [a["agent"] for a in apps] == ["quality_agent", "release_review", "docs_adk"]   # newest review first
    quality, release, docs = apps
    assert {k: quality[k] for k in ("record_id", "status", "team", "framework", "tools", "can_reject")} == {
        "record_id": "rec-1", "status": "PENDING_APPROVAL", "team": "appliance", "framework": "strands",
        "tools": SPEC["tools"], "can_reject": True}
    review = quality["review"]
    assert review["name"] == "quality-second" and review["status"] == "RUNNING"         # its latest execution
    assert [r["state"] for r in review["steps"]] == ["passed", "passed", "running"] + ["waiting"] * 4
    assert isinstance(review["steps"][2]["seconds"], int) and review["steps"][2]["seconds"] > 0   # since it started
    assert review["failed_step"] == "" and review["started"] == T0
    assert release["review"]["status"] == "SUCCEEDED" and release["review"]["seconds"] == 371
    assert release["can_reject"] is False and release["description"] == "release_review: agent of team device"
    assert docs["review"] is None and docs["can_reject"] is True

    page = web.get("/reviews").text
    listing = panel(page, "panel-applications")
    assert "quality_agent" in listing and "release_review" in listing and "parts-tools" not in listing
    assert "PENDING_APPROVAL 심사 중" in listing and "APPROVED 승인" in listing and "DRAFT 작성 중" in listing
    for word in ("통과", "진행 중", "대기", "AWS Lambda", "AWS CodeBuild", "AWS Step Functions", "appliance", "strands",
                 "Parts___get_part_spec"):
        assert word in listing, word
    links = [a["href"] for tag, a in panel_elements(page, "panel-applications") if tag == "a"]
    assert {"/reviews/quality_agent", "/reviews/release_review", "/reviews/docs_adk"} <= set(links)
    assert panel(page, "badge-reviews") == "1"              # the menu agrees: AGENT records in PENDING_APPROVAL
    assert "Running" in panel(web.get("/reviews?lang=en").text, "panel-applications")


def test_the_detail_page_shows_each_step_with_its_service_time_and_error_and_the_scans_findings():
    c = failed_at_scan()
    web = screen(c)
    page = web.get("/reviews/quality_agent").text
    steps = panel(page, "panel-steps")
    for text in ("Read", "Scan", "Approve", "AWS Lambda", "AWS CodeBuild", "AWS Step Functions",
                 STRINGS["ko"]["step.does.Scan"], "실패", "통과", "대기", "36초", "review-quality-1",
                 "States.TaskFailed: build hub-review-scan:", "Step Functions 콘솔에서 보기"):
        assert text in steps, text
    assert [a for tag, a in panel_elements(page, "panel-steps") if "tech" in a.get("class", "")]
    findings = panel(page, "panel-findings")
    assert "jinja2 2.11.2 PYSEC-2021-66 2.11.3" in findings and "jinja2 2.11.2 GHSA-h5c8-rqwp-cp95 3.1.3" in findings
    assert "Running command" not in findings and "Amazon CloudWatch Logs" in findings
    assert c.log_reads == [{"logGroupName": LOG_GROUP, "logStreamName": LOG_STREAM, "limit": 200,
                            "startFromHead": False}]       # the last 200 lines, read only for a failed Scan
    english = web.get("/reviews/quality_agent?lang=en").text
    assert "Failed" in panel(english, "panel-steps") and STRINGS["en"]["step.does.Scan"] in panel(english, "panel-steps")
    assert "Open in the Step Functions console" in panel(english, "panel-steps")

    c = FakeClients()
    c.executions = [execution("release", "rec-1", "SUCCEEDED", PASSED, "ExecutionSucceeded")]
    page = screen(c).get("/reviews/quality_agent").text
    assert 'id="panel-findings"' not in page and c.log_reads == []      # nothing to explain: the log is not read


def test_a_log_that_cannot_be_read_is_one_line_and_the_steps_still_show():
    c = failed_at_scan()
    c.errors[("logs", "get_log_events")] = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": f"User: arn:aws:sts::{ACCOUNT}:assumed-role/x is not "
                                                               "authorized to perform: logs:GetLogEvents"}}, "GetLogEvents")
    page = screen(c).get("/reviews/quality_agent").text
    findings = panel(page, "panel-findings")
    assert "AccessDeniedException: User: arn:aws:sts::<ACCOUNT>:assumed-role/x" in findings
    assert STRINGS["ko"]["panel.error"] in findings and ACCOUNT not in page
    assert "실패" in panel(page, "panel-steps") and "Scan" in panel(page, "panel-steps")

    c = failed_at_scan()
    c.log_events = {}                                                    # the stream named in the cause is gone
    assert "ResourceNotFoundException" in panel(screen(c).get("/reviews/quality_agent").text, "panel-findings")


def test_a_failing_read_of_the_reviews_is_one_line_and_the_applications_still_show():
    c = failed_at_scan()
    c.errors[("sfn", "list_executions")] = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized to perform: states:ListExecutions"}},
        "ListExecutions")
    web = screen(c)
    listing = panel(web.get("/reviews").text, "panel-applications")
    assert "AccessDeniedException: not authorized to perform: states:ListExecutions" in listing
    assert "quality_agent" in listing and "appliance" in listing
    assert "states:ListExecutions" in panel(web.get("/reviews/quality_agent").text, "panel-steps")


def test_a_finished_reviews_input_and_history_are_read_once():
    c = FakeClients()
    c.other_records = [app_record("release_review", "APPROVED")]
    c.executions = [execution("quality-first", "rec-1", "FAILED", AT_SCAN, "ExecutionFailed", start=T0 - timedelta(hours=1)),
                    execution("release", "rec-release_review", "SUCCEEDED", PASSED, "ExecutionSucceeded"),
                    execution("quality-second", "rec-1", "RUNNING", RUNNING)]
    web = screen(c, cache_seconds=0)                                         # every page reads AWS again
    for _ in range(3):
        assert web.get("/reviews").status_code == 200
    histories = [call for call in c.calls if call == ("sfn", "get_execution_history")]
    assert c.calls.count(("sfn", "list_executions")) == 3
    assert c.calls.count(("sfn", "describe_execution")) == 3                  # each execution's input, once
    assert len(histories) == 1 + 3                                         # release once; the running one each time
    assert ("logs", "get_log_events") not in c.calls                     # the list does not read the scan's log


def test_a_record_with_markup_is_shown_as_text():
    script, image = "<script>alert(1)</script>", "<img src=x onerror=alert(1)>"
    c = FakeClients(record_status=None)
    c.other_records = [app_record("markup_agent", "PENDING_APPROVAL", team=image, description=script)]
    cause = json.dumps({"errorMessage": f"unexpected answer {script} from arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:"
                                        "runtime/hub_markup_agent-abcdefghij", "errorType": "RuntimeError"})
    c.executions = [execution("markup", "rec-markup_agent", "FAILED",
                              PASSED[:6] + [("TestCall", 349, 356, cause), ("Notify", 356, 356, None),
                                            ("Failed", 356, None, None)], "ExecutionFailed")]
    web = screen(c)
    for path, ids in (("/reviews", ("panel-applications",)), ("/reviews/markup_agent", ("panel-application", "panel-steps"))):
        html = web.get(path).text
        assert script not in html and image not in html and ACCOUNT not in html, path
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "&lt;img src=x onerror=alert(1)&gt;" in html, path
        for element_id in ids:
            assert script in panel(html, element_id) or image in panel(html, element_id), (path, element_id)
    steps = panel(web.get("/reviews/markup_agent").text, "panel-steps")
    assert f"unexpected answer {script} from arn:aws:bedrock-agentcore:us-west-2:<ACCOUNT>:runtime/" in steps


def test_reject_calls_the_same_function_as_the_command(monkeypatch):
    calls = []

    def recorded(c, s, p, agent, reason):
        calls.append((c, s, p, agent, reason))
        return {"status": "REJECTED", "removed": ["role hub-agent-quality_agent-role"]}
    monkeypatch.setattr(reject_agent, "reject", recorded)
    c = failed_at_scan()
    web = screen(c)
    hub = web.app.state.hub
    page = web.get("/reviews/quality_agent").text
    form = next(a for tag, a in panel_elements(page, "panel-reject") if tag == "form")
    assert form["action"] == "/reviews/quality_agent/reject" and form["method"] == "post"
    r = web.post(form["action"], headers=ORIGIN, data={"token": token(page), "reason": "the reason"},
                 follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reviews/quality_agent?msg=started"
    job = hub.jobs.current()
    assert job.wait(5) and (job.kind, job.target, job.state) == ("reject", "quality_agent", "done")
    assert calls == [(c, S, PLATFORM, "quality_agent", "the reason")]
    assert job.lines == ["record quality_agent: REJECTED", "removed role hub-agent-quality_agent-role"]
    assert "removed role hub-agent-quality_agent-role" in panel(web.get(r.headers["location"]).text, "panel-job")

    # the command: reject.sh runs reject_agent.main, which calls the same function with the same arguments
    for name in ("AWS_REGION", "DEMO_PREFIX", "MODEL_ID"):
        monkeypatch.delenv(name, raising=False)                     # the command's settings are then the screen's
    monkeypatch.setattr(reject_agent.Clients, "for_settings", classmethod(lambda cls, s: c))
    monkeypatch.setattr(reject_agent, "load", lambda s, clients: PLATFORM)
    assert reject_agent.main(["quality_agent", "the reason"]) == 0
    assert calls[1] == calls[0]


def test_reject_on_the_screen_marks_the_record_rejected_with_the_reason():
    c = FakeClients(existing_roles={"hub-agent-quality_agent-role"})
    web = screen(c)
    page = web.get("/reviews/quality_agent").text
    web.post("/reviews/quality_agent/reject", headers=ORIGIN, data={"token": token(page), "reason": "  jinja2 2.11.2  "})
    job = web.app.state.hub.jobs.current()
    assert job.wait(5) and job.state == "done", job.error
    assert c.record_status == "REJECTED" and c.status_reason == "jinja2 2.11.2"
    assert job.lines == ["record quality_agent: REJECTED", "removed role hub-agent-quality_agent-role"]
    assert "REJECTED 반려" in panel(web.get("/reviews/quality_agent").text, "panel-application")

    c = FakeClients(record_status="APPROVED")                       # the function refuses; the job shows why
    web = screen(c)
    web.post("/reviews/quality_agent/reject", headers=ORIGIN,
             data={"token": token(web.get("/reviews").text), "reason": "why"})
    job = web.app.state.hub.jobs.current()
    assert job.wait(5) and job.state == "failed" and job.error == "ValueError: approved agents are stopped, not rejected"


def test_reject_refuses_an_empty_or_too_long_reason():
    c = failed_at_scan()
    web = screen(c)
    hub = web.app.state.hub
    right = token(web.get("/reviews/quality_agent").text)
    for form in ({"token": right}, {"token": right, "reason": ""}, {"token": right, "reason": "   "},
                 {"token": right, "reason": "x" * (MAX_REASON + 1)}):
        r = web.post("/reviews/quality_agent/reject", headers=ORIGIN, data=form, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/reviews/quality_agent?err=reason", form
    assert hub.jobs.current() is None and c.record_status == "PENDING_APPROVAL"         # no job
    for lang in ("ko", "en"):
        shown = web.get(f"/reviews/quality_agent?err=reason&lang={lang}").text
        assert panel(shown, "page-err") == STRINGS[lang]["err.reason"]
        assert str(MAX_REASON) in STRINGS[lang]["err.reason"]
    r = web.post("/reviews/No-Such/reject", headers=ORIGIN, data={"token": right, "reason": "why"},
                 follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reviews?err=agent" and hub.jobs.current() is None
    assert panel(web.get(r.headers["location"] + "&lang=ko").text, "page-err") == STRINGS["ko"]["err.agent"]
    r = web.post("/reviews/quality_agent/reject", headers=ORIGIN, data={"token": right, "reason": "x" * MAX_REASON},
                 follow_redirects=False)
    assert r.headers["location"] == "/reviews/quality_agent?msg=started" and hub.jobs.current().wait(5)


def test_the_reject_button_shows_only_when_the_record_can_be_rejected():
    import threading

    def has_form(c) -> bool:
        return any(tag == "form" for tag, _ in panel_elements(screen(c).get("/reviews/quality_agent").text, "panel-reject"))
    for status in ("PENDING_APPROVAL", "REJECTED", "DRAFT"):
        assert has_form(FakeClients(record_status=status)), status
    c = FakeClients(record_status="APPROVED")
    assert not has_form(c)
    assert "APPROVED" in panel(screen(c).get("/reviews/quality_agent").text, "panel-reject")

    gate = threading.Event()
    web = screen(failed_at_scan())
    web.app.state.hub.jobs.start("test", "slow", lambda say: gate.wait(5) and {})
    page = web.get("/reviews/quality_agent").text
    assert not any(tag == "form" for tag, _ in panel_elements(page, "panel-reject"))
    assert STRINGS["ko"]["reject.job_running"] in panel(page, "panel-reject")
    assert reviews.view(web.app.state.hub)["applications"]["value"][0]["can_reject"] is False
    gate.set()
    assert web.app.state.hub.jobs.current().wait(5)

    c = FakeClients()
    c.executions = [execution("quality-running", "rec-1", "RUNNING", RUNNING)]
    page = screen(c).get("/reviews/quality_agent").text                 # the button, and a word on the running review
    assert STRINGS["ko"]["reject.while_running"] in panel(page, "panel-reject")


def test_the_console_link_goes_through_the_app():
    c = failed_at_scan()
    web = screen(c)
    page = web.get("/reviews/quality_agent").text
    links = [a["href"] for tag, a in panel_elements(page, "panel-steps") if tag == "a"]
    assert "/reviews/quality_agent/console" in links
    arn = arn_of("review-quality-1")
    for body in (page, web.get("/reviews").text):
        assert arn not in body and "arn:aws:states" not in body and ":execution:" not in body
    r = web.get("/reviews/quality_agent/console", follow_redirects=False)
    assert r.status_code == 303 and r.text == ""
    assert r.headers["location"].startswith("https://us-west-2.console.aws.amazon.com/states/")
    assert r.headers["location"] == ("https://us-west-2.console.aws.amazon.com/states/home?region=us-west-2"
                                      f"#/v2/executions/details/{arn}")

    r = screen(FakeClients()).get("/reviews/quality_agent/console", follow_redirects=False)    # no review yet
    assert r.status_code == 303 and r.headers["location"] == "/reviews/quality_agent?err=no_review"


def test_a_name_the_form_refuses_or_an_agent_without_a_record_gets_the_framed_404():
    c = failed_at_scan()
    c.other_records = [{"name": "parts_tools", "recordId": "rec-parts", "recordType": "MCP", "status": "APPROVED"}]
    web = screen(c)
    for path in ("/reviews/No-Such", "/reviews/no_such_agent", "/reviews/parts_tools", "/reviews/no_such_agent/console",
                 "/reviews/%3Cscript%3E"):
        r = web.get(path, follow_redirects=False)
        assert r.status_code == 404 and STRINGS["ko"]["not_found.title"] in r.text and "샘플 화면" in r.text, path


def test_every_word_the_pages_build_at_run_time_has_a_text():
    keys = [f"step.{state}" for state in reviews.STATES] + [f"step.does.{name}" for name in NAMES]
    keys += [f"exec.{status}" for status in reviews.EXECUTION_STATUSES]
    for lang in ("ko", "en"):
        assert [k for k in keys if k not in STRINGS[lang]] == [], lang
    assert [STRINGS["ko"][f"step.{s}"] for s in reviews.STATES] == ["대기", "진행 중", "통과", "실패", "건너뜀"]
    assert [STRINGS["en"][f"step.{s}"] for s in reviews.STATES] == ["Waiting", "Running", "Passed", "Failed", "Skipped"]
    assert re.search("Step Functions 콘솔에서 보기", STRINGS["ko"]["reviews.console"])
