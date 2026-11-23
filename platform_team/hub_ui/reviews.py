"""The hosting review page: each agent application of the catalog (an AGENT record) with the seven steps of its latest
review, one AWS Step Functions execution of the state machine <prefix>-review. Next to each step stand the AWS service
that runs it, how long it took and why it failed; for a review that failed at Scan, the lines of the scan build's log
that say why; and the Reject button, which calls reject_agent.reject, the function reject.sh calls.

What AWS gives is read in pure functions of this module, so it can be checked against real events in one place:
steps_of (the execution's history -> one row per step), scan_log (where the failed scan build's log is, from the same
history) and scan_findings (the scan build's log -> the lines that say why it failed)."""
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from platform_team.agent_catalog.application_form import name_problems
from platform_team.hosting_review import reject_agent
from platform_team.hosting_review.agent_cleanup import CleanupFailed
from platform_team.hosting_review.reject_agent import MAX_REASON, REJECTABLE
from platform_team.hosting_review.review_steps import _application_of
from platform_team.hub_ui import jobs
from platform_team.hub_ui.app import Hub, back, catalog, page, panel

router = APIRouter()

# The steps of the state machine (hosting_review/terraform/review_machine.asl.json.tftpl) and the service that runs
# each. Reviewable (a Choice), Skipped, Notify and Failed are states of the machine, not steps of the review.
STEPS = (("Read", "AWS Lambda"), ("Scan", "AWS CodeBuild"), ("Grant", "AWS Lambda"), ("Deploy", "AWS CodeBuild"),
         ("Entry", "AWS Lambda"), ("TestCall", "AWS Lambda"), ("Approve", "AWS Lambda"))
WAITING, RUNNING, PASSED, FAILED, SKIPPED = "waiting", "running", "passed", "failed", "skipped"
STATES = (WAITING, RUNNING, PASSED, FAILED, SKIPPED)
EXECUTION_STATUSES = ("RUNNING", "SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "PENDING_REDRIVE")
CAUGHT = "Notify"           # every step's Catch goes here (and sets failedStep): the step entered before it failed
SKIP = "Skipped"            # Reviewable sends a record the review does not host here, right after Read
SCAN = "Scan"
MAX_ERROR = 300             # characters of a step's error on the page
MAX_FINDINGS = 20           # lines of the scan's log on the page
LOG_LINES = 200             # the last lines of the scan build's log that are read
MAX_EXECUTIONS = 50         # the newest executions of the state machine that are looked at
SERVICES = {"machine": "AWS Step Functions", "catalog": "AWS Agent Registry", "build": "AWS CodeBuild",
            "logs": "Amazon CloudWatch Logs"}
# A row of pip-audit's table (Name Version ID Fix Versions): a package, its version and an advisory ID
_ADVISORY = re.compile(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*\s+\S+\s+(?:PYSEC|GHSA|CVE)-[A-Za-z0-9-]+(?:\s|$)")
_REFUSED = "submission refused: "       # what submission_check prints for each problem of a submission
_STATE_PILLS = {PASSED: "ok", RUNNING: "pending", FAILED: "bad"}


# ------------------------------------------------------------------ what AWS gives, read (pure)

def _details(event: dict) -> dict:
    """An event's details member (stateEnteredEventDetails, taskFailedEventDetails, ...); {} when it has none."""
    return next((v for k, v in event.items() if k.endswith("EventDetails") and isinstance(v, dict)), {})


def _in_order(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: e.get("id") or 0)


def _seconds(start: datetime | None, end: datetime | None) -> int | None:
    return round((end - start).total_seconds()) if start and end else None


def _json(text: Any) -> Any:
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def _told(cause: Any) -> str:
    """A failure's cause in one line. A CodeBuild step's cause is the build record: its ID and status, and the first
    phase that did not succeed with its messages. A Lambda step's cause is the function's error: its message. Any
    other cause is its own text."""
    doc = _json(cause)
    build = doc.get("Build") if isinstance(doc, dict) else None
    if isinstance(build, dict):
        told = f"build {build.get('Id', '')} {build.get('BuildStatus', '')}"
        for phase in build.get("Phases") or []:
            if isinstance(phase, dict) and phase.get("PhaseStatus") not in (None, "SUCCEEDED"):
                messages = "; ".join(str(x["Message"]) for x in phase.get("Contexts") or []
                                     if isinstance(x, dict) and x.get("Message"))
                told += f": {phase.get('PhaseType')} {phase['PhaseStatus']}" + (f": {messages}" if messages else "")
                break
        return told
    if isinstance(doc, dict) and "errorMessage" in doc:
        return str(doc["errorMessage"])
    return str(cause or "")


def _error(details: dict) -> str:
    """A failure event's error and cause as one line of at most MAX_ERROR characters."""
    text = ": ".join(part for part in (str(details.get("error") or ""), _told(details.get("cause"))) if part)
    return " ".join(text.split())[:MAX_ERROR]


def steps_of(events: list[dict], execution_status: str) -> list[dict]:
    """One row per step of STEPS from an execution's history (GetExecutionHistory's events): {"name", "runs_on" (the
    AWS service that runs it), "state", "seconds", "error", "started" (when it was entered)}.

    A step runs from its state's entered event to its exited event (passed, seconds between the two). A step that
    the review left for Notify (its Catch) failed: seconds until then, and the error and cause of the last failure
    event it had (TaskFailed, TaskTimedOut, ...). Once Reviewable has sent the review to Skipped, the steps not run are
    skipped; the steps not reached are waiting. A step still in progress is running while the execution runs (seconds
    None: the page counts them from `started`), and failed when the execution has ended (aborted, timed out). Events
    of other types and of other states change nothing."""
    rows = [{"name": name, "runs_on": runs_on, "state": WAITING, "seconds": None, "error": "", "started": None}
            for name, runs_on in STEPS]
    step = {row["name"]: row for row in rows}
    last, failure, ended, at = None, "", "", None        # the step entered last, its last failure, the execution's end
    for event in _in_order(events):
        kind, details, at = str(event.get("type") or ""), _details(event), event.get("timestamp") or at
        name = details.get("name")
        if kind.endswith("StateEntered"):
            if name in step:
                last, failure = step[name], ""
                last.update(state=RUNNING, started=at, seconds=None, error="")
            elif name == CAUGHT and last is not None:
                if last["state"] == RUNNING:
                    last["seconds"] = _seconds(last["started"], at)
                last.update(state=FAILED, error=failure)
            elif name == SKIP:
                for row in rows:
                    if row["state"] == WAITING:
                        row["state"] = SKIPPED
        elif kind.endswith("StateExited"):
            if last is not None and name == last["name"] and last["state"] == RUNNING:
                last.update(state=PASSED, seconds=_seconds(last["started"], at))
        elif "error" in details or "cause" in details:
            if kind.startswith("Execution"):
                ended = _error(details)
            elif last is not None and last["state"] == RUNNING:
                failure = _error(details)
    if last is not None and last["state"] == RUNNING and execution_status != "RUNNING":
        last.update(state=FAILED, seconds=_seconds(last["started"], at), error=failure or ended)
    return rows


def scan_log(events: list[dict]) -> tuple[str, str] | None:
    """The log group and stream of the Scan build, as the cause of a failed Scan names them: the build record's Logs
    (GroupName and StreamName, or the same in Logs.CloudWatchLogs). None when Scan did not fail or names no log."""
    state, found = None, None
    for event in _in_order(events):
        kind, details = str(event.get("type") or ""), _details(event)
        if kind.endswith("StateEntered"):
            state = details.get("name")
        elif state == SCAN and "cause" in details and not kind.startswith("Execution"):
            doc = _json(details["cause"])
            build = doc.get("Build") if isinstance(doc, dict) else None
            logs = (build.get("Logs") if isinstance(build, dict) else None) or {}
            for where in (logs, logs.get("CloudWatchLogs") or {}):
                if isinstance(where, dict) and where.get("GroupName") and where.get("StreamName"):
                    found = (str(where["GroupName"]), str(where["StreamName"]))
                    break
    return found


def scan_findings(lines: list[str]) -> list[str]:
    """The lines of a Scan build's log that say why it failed, at most MAX_FINDINGS: the rows of pip-audit's table
    (a package, its version, an advisory ID, the fix versions) and the lines of submission_check's refusal."""
    found = [line.rstrip() for line in lines if _ADVISORY.match(line) or line.lstrip().startswith(_REFUSED)]
    return found[:MAX_FINDINGS]


# ------------------------------------------------------------------ the reads

def application(hub: Hub, record: dict) -> dict:
    """The application an agent's record holds (the JSON object in its descriptors.custom.data, read as the review's
    Read step reads it), {} when it holds none. ListRegistryRecords does not give the descriptors, so this is
    GetRegistryRecord, through the cache."""
    full = hub.cache.get(f"record.{record['recordId']}", lambda: hub.c.reg.get_registry_record(
        registryId=hub.platform().registry_id, recordId=record["recordId"]))
    return _application_of(full) or {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _applications(hub: Hub, agent: str | None) -> list[dict]:
    """The AGENT records (only the one named `agent`, when given) with what their application asks for, by name."""
    found = []
    for rec in sorted(catalog(hub).values(), key=lambda r: r["name"]):
        if rec.get("recordType") != "AGENT" or agent not in (None, rec["name"]):
            continue
        app = application(hub, rec)
        tools = app.get("tools")
        found.append({"agent": rec["name"], "record_id": rec["recordId"], "status": rec.get("status", ""),
                      "team": _text(app.get("team")), "framework": _text(app.get("framework")),
                      "tools": [str(t) for t in tools] if isinstance(tools, list) else [],
                      "description": _text(rec.get("description"))})
    return found


def _kept(hub: Hub, key: str, load):
    """A value that never changes once AWS has it (an execution's input, a finished execution's history): read once
    and kept while the app runs, not in the cache that a job clears."""
    if key not in hub.kept:
        hub.kept[key] = load()
    return hub.kept[key]


def _record_of(execution_input: Any) -> str:
    """The record ID in an execution's input: the Registry's event, detail.registryRecordId ("" when there is none)."""
    doc = _json(execution_input)
    detail = doc.get("detail") if isinstance(doc, dict) else None
    return _text(detail.get("registryRecordId")) if isinstance(detail, dict) else ""


def _history(hub: Hub, arn: str) -> list[dict]:
    pages = hub.c.sfn.get_paginator("get_execution_history").paginate(executionArn=arn)
    return [event for pg in pages for event in pg["events"]]


def _latest_reviews(hub: Hub) -> dict[str, dict]:
    """The latest review of each record among the state machine's MAX_EXECUTIONS newest executions: record ID ->
    {"execution": its ListExecutions entry, "events": its history}. Which record an execution reviews is in its input
    (DescribeExecution), as reject_agent.running_reviews reads it."""
    machine = hub.platform().machine_arn
    if not machine:
        return {}
    listed = hub.c.sfn.list_executions(stateMachineArn=machine, maxResults=MAX_EXECUTIONS)["executions"]
    latest: dict[str, dict] = {}
    for e in sorted(listed, key=lambda e: e["startDate"], reverse=True):
        arn = e["executionArn"]
        record_id = _kept(hub, f"input.{arn}",
                          lambda: _record_of(hub.c.sfn.describe_execution(executionArn=arn).get("input")))
        if not record_id or record_id in latest:
            continue
        events = _history(hub, arn) if e["status"] == "RUNNING" else _kept(hub, f"history.{arn}",
                                                                            lambda: _history(hub, arn))
        latest[record_id] = {"execution": e, "events": events}
    return latest


def _findings(hub: Hub, events: list[dict]) -> dict:
    """Where the failed scan build's log is (scan_log) and the lines of its last LOG_LINES that say why it failed
    (CloudWatch Logs GetLogEvents, scan_findings)."""
    where = scan_log(events)
    if where is None:
        return {"log": "", "lines": []}
    group, stream = where
    answer = hub.c.logs.get_log_events(logGroupName=group, logStreamName=stream, limit=LOG_LINES, startFromHead=False)
    lines = [line for e in answer.get("events", []) for line in str(e.get("message", "")).splitlines()]
    return {"log": f"{group} {stream}", "lines": scan_findings(lines)}


def _review(hub: Hub, found: dict, with_findings: bool) -> dict:
    """A review for the page: the execution's name, status, start and seconds, its steps (a running step's seconds
    count from its start), the failed step and its error, and, with_findings and when it failed at Scan, the scan's
    findings as a panel."""
    e, events, now = found["execution"], found["events"], datetime.now(UTC)
    steps = steps_of(events, e["status"])
    for row in steps:
        if row["state"] == RUNNING:
            row["seconds"] = _seconds(row["started"], now)
    failed = next((row for row in steps if row["state"] == FAILED), None)
    findings = None
    if with_findings and failed is not None and failed["name"] == SCAN:
        findings = panel(hub, f"reviews.findings.{e['executionArn']}", lambda: _findings(hub, events))
    return {"name": e["name"], "status": e["status"], "started": e["startDate"],
            "seconds": _seconds(e["startDate"], e.get("stopDate") or now), "steps": steps,
            "failed_step": failed["name"] if failed else "", "error": failed["error"] if failed else "",
            "findings": findings}


def view(hub: Hub, agent: str | None = None) -> dict:
    """The page's two reads, each a panel. applications: the AGENT records, each with its application, can_reject
    (its status is one reject takes and no job runs) and its latest review (None when there is none), newest review
    first; with `agent`, that agent only, and its review's findings when it failed at Scan. reviews: the read of the
    state machine's executions (a failure is one line on the page; the applications still show)."""
    hub.platform()                      # NotDeployed: the page that says so, before any panel
    applications = panel(hub, f"reviews.applications.{agent or ''}", lambda: _applications(hub, agent))
    reviews = panel(hub, "reviews.latest", lambda: _latest_reviews(hub))
    if applications["ok"]:
        job = hub.jobs.current()
        busy = job is not None and job.state == jobs.RUNNING
        latest = reviews["value"] if reviews["ok"] else {}
        apps = [{**a, "can_reject": a["status"] in REJECTABLE and not busy,
                 "review": _review(hub, latest[a["record_id"]], agent is not None) if a["record_id"] in latest else None}
                for a in applications["value"]]
        apps.sort(key=lambda a: -a["review"]["started"].timestamp() if a["review"] else math.inf)
        applications = {"ok": True, "value": apps}
    return {"applications": applications, "reviews": reviews}


# ------------------------------------------------------------------ the routes

def _context() -> dict:
    return {"services": SERVICES, "state_pills": _STATE_PILLS, "max_reason": MAX_REASON, "rejectable": REJECTABLE}


@router.get("/reviews")
def reviews_page(request: Request):
    return page(request, "reviews.html", view=view(request.app.state.hub), **_context())


@router.get("/reviews/{agent}")
def review_page(request: Request, agent: str):
    """One application: 404 (the framed page) for a name the application form refuses or with no AGENT record."""
    if name_problems(agent):
        raise HTTPException(status_code=404)
    found = view(request.app.state.hub, agent)
    if found["applications"]["ok"] and not found["applications"]["value"]:
        raise HTTPException(status_code=404)
    return page(request, "review.html", view=found, agent=agent, **_context())


def _reject(hub: Hub, agent: str, reason: str, say) -> dict:
    """What reject.sh does, its lines said to the job: reject_agent.reject, then the record's status, each thing
    removed and the note."""
    try:
        out = reject_agent.reject(hub.c, hub.s, hub.platform(), agent, reason)
    except CleanupFailed as e:          # the record is REJECTED (or kept a DRAFT) by now; a second press finishes
        say(f"record {agent} is {getattr(e, 'record_status', 'REJECTED')}, but not everything was removed: {e}. "
            "Press Reject again to finish.")
        raise
    say(f"record {agent}: {out['status']}")
    for line in out["removed"]:
        say(f"removed {line}")
    if out.get("note"):
        say(out["note"])
    elif not out["removed"]:
        say("nothing left to remove")
    return out


@router.post("/reviews/{agent}/reject")
async def reject(request: Request, agent: str):
    """Start the job that rejects the agent's submission with the form's reason (1 to MAX_REASON characters). The
    function decides the rest (the record's status, a review still running) as it does for reject.sh."""
    hub: Hub = request.app.state.hub
    if name_problems(agent):
        return back(request, "/reviews", err="agent")
    reason = _text((await request.form()).get("reason")).strip()
    if not 1 <= len(reason) <= MAX_REASON:
        return back(request, f"/reviews/{agent}", err="reason")
    hub.jobs.start("reject", agent, lambda say: _reject(hub, agent, reason, say))       # jobs.Busy: the app answers
    return back(request, f"/reviews/{agent}", msg="started")


@router.get("/reviews/{agent}/console")
def console(request: Request, agent: str):
    """303 to the Step Functions console's page of the agent's latest review in the hub's Region. The URL holds the
    execution's ARN (and so the account ID): it is built here and is in no page."""
    hub: Hub = request.app.state.hub
    if name_problems(agent):
        raise HTTPException(status_code=404)
    rec = catalog(hub).get(agent)
    if not rec or rec.get("recordType") != "AGENT":
        raise HTTPException(status_code=404)
    found = hub.cache.get("reviews.latest", lambda: _latest_reviews(hub)).get(rec["recordId"])
    if not found:
        return back(request, f"/reviews/{agent}", err="no_review")
    region, arn = hub.s.region, found["execution"]["executionArn"]
    return RedirectResponse(f"https://{region}.console.aws.amazon.com/states/home?region={region}"
                            f"#/v2/executions/details/{arn}", status_code=303)
