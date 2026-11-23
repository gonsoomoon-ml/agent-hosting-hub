#!/usr/bin/env python3
"""spike_operations.py - what AWS does where the operations flow rests on an assumption, seen on a running hub.

Not part of the hub. It runs once on the hub that `make deploy seed e2e` leaves (quality_agent and release_review
APPROVED, no review running), so the operations commands are built on what AWS did, not on what a page says:

    AUTO_APPROVE=1 make deploy seed e2e
    uv run python e2e_checks/spikes/spike_operations.py 2>&1 | tee e2e_checks/spikes/spike_operations.last-run.log

  0 DEPLOY_BUILD    what each deploy build so far did: uv and Python, the package size, created or updated, seconds
                    to READY (the build's log lines)
  1 SEED_EVENT      the reviews started for the seeded shared tool record parts-tools, and where they stopped
  2 NEW_VERSION     a new version of the approved quality_agent, published as the dev team role. Every 30 s during
                    its review: the record's status, the fields of GetRegistryRecord, the code_version of the
                    application it returns, the catalog search. Then the steps' times, the Runtime's version and
                    what its deploy build did (the update path)
  3 SESSION_SOURCE, STOP_EFFECT, LONG_CALL
                    a 180 s request with a session ID header; 30 s in, where that ID shows in the Runtime's logs;
                    StopRuntimeSession 60 s in, and the agent's tick lines in the 60 s after it; what the caller got.
                    Then a short call with the header and one without it (the session IDs the logs show), and,
                    when the stop came before the caller's answer, one more 180 s request that is not stopped
  4 LOOP_RATE       the incident's retry loop for 90 s (the caller gives up after 20 s), started so that one whole
                    clock minute lies inside it: the loop's lines in that minute, the tool Lambda's invocations, and
                    the tool gateway's Invocations metric for that minute (read at the end, the metric lags)
  5 STOP_EXCEPTION  a forbid on quality_agent's entry with an exception for the review's test call role: the users'
                    call must turn 403 and the test call Lambda, invoked directly, must still pass. "unless" first,
                    then "when", else "none". The policy is deleted in a finally block; then the time until 200

The new version is a temporary copy of dev_team/quality_agent with WRAPPER appended to its agent.py ("spike wait <s>"
ticks and calls a tool every 5 s; "spike loop <s>" asks the real agent again and again). The copy keeps agent.json,
so it is the next version of the same catalog record. No file of the repo changes.

Each finding is one line `[OBSERVED] <key>: <value>`; the last line is `== decisions: {...}` (JSON, seven keys). A
decision that could not be settled reads `unknown: <what happened>`. What this script makes has the hub's prefix (the
session IDs hub-spike-..., the policy stop_agent_quality_agent) or lives in the hub's catalog. The output masks the
account ID (e2e_hosting.clean).
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True                     # running it leaves no file behind in the repo
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import boto3                                                                   # noqa: E402
from botocore.config import Config                                             # noqa: E402

from e2e_checks import e2e_hosting as e2e                                      # noqa: E402
from e2e_checks.e2e_hosting import (DevTeam, call_agent, clean, gateway_url, record_status,  # noqa: E402
                                    review, wait_search)
from platform_team.agent_catalog.catalog_records import records, search        # noqa: E402
from platform_team.agent_catalog.publish_agent import publish                  # noqa: E402
from platform_team.agent_catalog.seed_catalog import SHARED_RECORD             # noqa: E402
from platform_team.company_policy.policy_engine import drop_policy, ensure_policy, list_policies  # noqa: E402
from platform_team.shared_code.aws_helpers import Clients, all_items, signed_post  # noqa: E402
from platform_team.shared_code.config import Settings, env_file_updates        # noqa: E402
from platform_team.shared_code.hub_state import load                           # noqa: E402

QUALITY = "quality_agent"
KEYS = ("SEED_EVENT", "NEW_VERSION", "LONG_CALL", "SESSION_SOURCE", "STOP_EFFECT", "LOOP_RATE", "STOP_EXCEPTION")
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
QUALITY_QUERY = "inspection results and part specifications"
STOP_POLICY = "stop_agent_quality_agent"
TOOL = "Quality___get_inspection_data"
POLL = 30                  # s, between two looks during the new version's review
LONG, LONG_CLIENT = 180, 240              # s, the slow request and the caller's limit
LOOK_AT, STOP_AT, AFTER_STOP = 30, 60, 60  # s, from the slow request's start; then the count after the stop
LOOP, LOOP_CLIENT, LOOP_COUNT_AT = 90, 20, 120
LOOP_START_SECOND = 32     # the loop starts at this second of a clock minute, so a whole minute lies inside its 90 s
LOG_LAG = 20               # s, more wait before a count, for log lines on their way to CloudWatch Logs
UNTIL_WAIT = 120           # s, at most, until a user's call turns 403 or 200 after a policy change

WRAPPER = '''
# appended to the temporary copy of agent.py
import time as _time
_run = run
def run(prompt):
    words = prompt.split()
    if words[:2] == ["spike", "wait"]:        # a slow request: one tick and one tool call every 5 s
        end = _time.monotonic() + int(words[2])
        n = 0
        while _time.monotonic() < end:
            n += 1
            print(f"spike tick {n}", flush=True)
            call_tool("Quality___get_inspection_data", {"case_id": "Q-1002"})
            _time.sleep(5)
        return f"waited, {n} ticks", []
    if words[:2] == ["spike", "loop"]:        # the retry of the incident: the real agent, again and again
        end = _time.monotonic() + int(words[2])
        n = 0
        while _time.monotonic() < end:
            n += 1
            print(f"spike loop {n}", flush=True)
            _run("What is the result of inspection Q-1002?")
        return f"looped, {n} rounds", []
    return _run(prompt)
'''

DECISIONS: dict = {k: "unknown: not reached (an earlier step stopped the script)" for k in KEYS}


# ================================================================== output and time

def say(msg) -> None:
    print(clean(msg), flush=True)              # clean reads e2e.ACCOUNT, which main() sets


def observed(key: str, value) -> None:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    say(f"[OBSERVED] {key}: {' '.join(text.split())}")


def decide(key: str, value) -> None:
    DECISIONS[key] = value
    observed(key, value)


def ms(t: float) -> int:
    return int(t * 1000)


def clock(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S")


def sleep_until(t: float) -> None:
    time.sleep(max(0.0, t - time.time()))


def error_text(e: Exception) -> str:
    return e2e.error_of(e)[:400]


# ================================================================== AWS reads

def quality_runtime(c, s: Settings) -> dict | None:
    """The Runtime of quality_agent as GetAgentRuntime gives it, or None."""
    name = s.runtime_name(QUALITY)
    found = next((r for r in all_items(c.ctl.list_agent_runtimes, maxResults=100) if r["agentRuntimeName"] == name), None)
    return c.ctl.get_agent_runtime(agentRuntimeId=found["agentRuntimeId"]) if found else None


def default_endpoint(c, runtime: dict) -> str:
    ep = c.ctl.get_agent_runtime_endpoint(agentRuntimeId=runtime["agentRuntimeId"], endpointName="DEFAULT")
    return f"DEFAULT {ep.get('status')} liveVersion {ep.get('liveVersion')} targetVersion {ep.get('targetVersion')}"


def events_between(c, group: str, start: float, end: float | None = None) -> list[dict]:
    """Every event of the log group between two epoch times (s), every page (a first page can be empty)."""
    kw = {"logGroupName": group, "startTime": ms(start), **({"endTime": ms(end)} if end else {})}
    return [e for page in c.logs.get_paginator("filter_log_events").paginate(**kw) for e in page["events"]]


def streams(c, group: str) -> list[dict]:
    return [x for page in c.logs.get_paginator("describe_log_streams").paginate(logGroupName=group)
            for x in page["logStreams"]]


def numbered(events: list[dict], word: str) -> list[tuple[float, int]]:
    """(epoch s, n) of each "spike <word> <n>" line, in time order; a number seen twice counts once (its first)."""
    first: dict[int, float] = {}
    for ev in events:
        m = re.search(rf"spike {word} (\d+)", ev["message"])
        if m:
            n = int(m.group(1))
            first[n] = min(first.get(n, float("inf")), ev["timestamp"] / 1000)
    return sorted((t, n) for n, t in first.items())


def gaps(found: list[tuple[float, int]]) -> str:
    """A note when the numbers seen are not 1..n (a line lost, or a line that is not the agent's)."""
    ns = sorted(n for _, n in found)
    return "" if ns == list(range(1, len(ns) + 1)) else f" (numbers seen are not 1..{len(ns)}: {ns[:12]}...)"


def tool_calls(c, s: Settings, start: float, end: float) -> int:
    """Invocations of the hub's tool Lambda between two epoch times (s): its REPORT lines."""
    return sum("REPORT RequestId" in ev["message"] for ev in events_between(c, f"/aws/lambda/{s.prefix}-tools", start, end))


def log_lines(c, group: str, stream: str) -> list[str]:
    lines, token = [], None
    while True:
        page = c.logs.get_log_events(logGroupName=group, logStreamName=stream, startFromHead=True,
                                     **({"nextToken": token} if token else {}))
        lines += [ev["message"].rstrip() for ev in page["events"]]
        if not page["events"] or page.get("nextForwardToken") == token:
            return lines
        token = page["nextForwardToken"]


DEPLOY_LINE = re.compile(r"^(Python 3|deploy \S+: Runtime|package uploaded|Runtime \S+ (created|updated)|"
                         r"create_agent_runtime:|the submission's|deploy (failed|refused)|\{\"runtimeArn\"|\$ uv )")


def show_build(c, build: dict, key: str) -> dict:
    """The lines of a deploy build's log that say what it did, one [OBSERVED] line each. Returns what was read."""
    env = {v["name"]: v["value"] for v in (build.get("environment") or {}).get("environmentVariables") or []}
    took = (build["endTime"] - build["startTime"]).total_seconds() if build.get("endTime") else None
    phases = ", ".join(f"{ph['phaseType']} {ph.get('durationInSeconds', '-')}s" for ph in build.get("phases") or []
                       if ph.get("phaseType") in ("INSTALL", "BUILD"))
    observed(key, f"{env.get('AGENT')} build {build.get('buildNumber')} {build.get('buildStatus')} in "
                  f"{took:.0f}s ({phases})" if took is not None else f"{env.get('AGENT')} {build.get('buildStatus')}")
    logs = build.get("logs") or {}
    lines = log_lines(c, logs["groupName"], logs["streamName"]) if logs.get("groupName") and logs.get("streamName") else []
    wanted = [line for line in lines if DEPLOY_LINE.search(line)]
    errors = [line for line in lines if re.search(r"\berror\b", line, re.I) and line not in wanted
              and not line.startswith("[Container]")][:5]
    for line in wanted + errors:
        observed(key, line[:400])
    out = next((json.loads(line) for line in lines if line.startswith('{"runtimeArn"')), {})
    size = next((int(m.group(1)) for line in lines for m in [re.search(r"package uploaded: .* \((\d+) bytes\)", line)]
                 if m), None)
    return {"agent": env.get("AGENT"), "status": build.get("buildStatus"), "seconds": took, "size": size, **out}


# ================================================================== 0 the deploy builds so far

def deploy_builds(c, s: Settings) -> None:
    ids = all_items(c.codebuild.list_builds_for_project, projectName=f"{s.prefix}-review-deploy", sortOrder="ASCENDING")
    builds = c.codebuild.batch_get_builds(ids=ids)["builds"] if ids else []
    observed("DEPLOY_BUILD", f"{len(builds)} deploy builds so far")
    for b in sorted(builds, key=lambda b: b["startTime"]):
        show_build(c, b, "DEPLOY_BUILD")


# ================================================================== 1 the seed's record and the review

TASK_FAILED = ("TaskFailed", "TaskTimedOut", "TaskStartFailed", "TaskSubmitFailed")


def failed_step(events: list[dict]) -> str | None:
    """The state in which the first task failed."""
    current = None
    for h in events:
        if h["type"].endswith("StateEntered"):
            current = h["stateEnteredEventDetails"]["name"]
        elif h["type"] in TASK_FAILED:
            return current
    return None


def task_error(events: list[dict]) -> str:
    """The error and cause of the first failed task, shortened."""
    for h in events:
        if h["type"] in TASK_FAILED:
            d = next((v for k, v in h.items() if k.endswith("EventDetails") and isinstance(v, dict)), {})
            return f"{d.get('error')}: {str(d.get('cause'))[:300]}"
    return "no failed task"


def seed_event(c, p) -> None:
    rec = records(c, p.registry_id).get(SHARED_RECORD)
    if not rec:
        decide("SEED_EVENT", f"unknown: no record {SHARED_RECORD} in the catalog")
        return
    observed("SEED_EVENT record", f"{SHARED_RECORD} {rec.get('recordType')} {rec['status']}")
    found, total = [], 0
    for page in c.sfn.get_paginator("list_executions").paginate(stateMachineArn=p.machine_arn):
        for ex in page["executions"]:
            total += 1
            d = c.sfn.describe_execution(executionArn=ex["executionArn"])
            detail = e2e.as_json(d.get("input") or "").get("detail") or {}
            if detail.get("registryRecordId") != rec["recordId"]:
                continue
            events = e2e.history(c, ex["executionArn"])
            step = failed_step(events)
            took = (d["stopDate"] - d["startDate"]).total_seconds() if d.get("stopDate") else None
            observed("SEED_EVENT execution", f"started {clock(d['startDate'].timestamp())}, {d['status']}"
                     + (f" at {step}" if step else "") + (f" in {took:.0f}s" if took is not None else "")
                     + f"; steps {e2e.steps_run(events)}" + (f"; {task_error(events)}" if step else ""))
            found.append(f"{d['status']} at {step}" if step else d["status"])
    observed("SEED_EVENT executions", f"{total} review executions in all, {len(found)} for {SHARED_RECORD}")
    decide("SEED_EVENT", "none" if not found else "; ".join(found))


# ================================================================== 2 a new version of an approved agent

def application_of(full: dict) -> dict:
    return e2e.as_json(((full.get("descriptors") or {}).get("custom") or {}).get("data") or "")


def current_state(c, machine_arn: str) -> str:
    running = c.sfn.list_executions(stateMachineArn=machine_arn, statusFilter="RUNNING", maxResults=5)["executions"]
    if not running:
        return "no review running"
    events = c.sfn.get_execution_history(executionArn=running[0]["executionArn"], reverseOrder=True,
                                         maxResults=20)["events"]
    return next((h["stateEnteredEventDetails"]["name"] for h in events if h["type"].endswith("StateEntered")), "?")


class Watch(threading.Thread):
    """Every POLL seconds until stopped, with clients of its own: the record, GetRegistryRecord, the search, the
    review's state and the Runtime. Each look is one [OBSERVED] line and one entry of `seen`."""

    def __init__(self, s: Settings, p, dev: DevTeam, record_id: str, new: str, old: str):
        super().__init__(daemon=True)
        self.s, self.p, self.dev, self.rid, self.new, self.old = s, p, dev, record_id, new, old
        self.done, self.seen = threading.Event(), []

    def run(self) -> None:
        c, dc, t0 = Clients.for_settings(self.s), self.dev.clients(), time.time()
        while not self.done.is_set():
            try:
                full = c.reg.get_registry_record(registryId=self.p.registry_id, recordId=self.rid)
                version = application_of(full).get("code_version")
                which = "new" if version == self.new else "old" if version == self.old else f"other ({version})"
                found = QUALITY in search(dc, self.p.registry_id, QUALITY_QUERY)
                rt = quality_runtime(c, self.s) or {}
                look = {"t": round(time.time() - t0), "status": full.get("status"), "code_version": which,
                        "found": found, "state": current_state(c, self.p.machine_arn),
                        "runtime": f"{rt.get('status')} version {rt.get('agentRuntimeVersion')}"}
                self.seen.append(look)
                observed("NEW_VERSION during the review",
                         f"t+{look['t']}s record {look['status']}; GetRegistryRecord fields "
                         f"{sorted(k for k in full if k != 'ResponseMetadata')}; the application's code_version is "
                         f"the {which} one; search {QUALITY_QUERY!r} finds {QUALITY}: {found}; review at "
                         f"{look['state']}; Runtime {look['runtime']}")
            except Exception as e:
                observed("NEW_VERSION during the review", f"a look failed: {error_text(e)}")
            self.done.wait(POLL)


def deploy_build_of(c, r: dict) -> dict | None:
    """The deploy build of a review: the build ID in its output (or in the history's Deploy task), as CodeBuild has it."""
    build_id = (e2e.as_json(r["execution"].get("output") or "").get("deploy") or {}).get("buildId")
    if not build_id:
        for h in r["events"]:
            text = json.dumps(h.get("taskSucceededEventDetails") or h.get("taskFailedEventDetails") or {})
            m = re.search(r"hub[a-z0-9]*-review-deploy:[0-9a-f-]{36}", text)
            build_id = m.group(0) if m else build_id
    found = c.codebuild.batch_get_builds(ids=[build_id])["builds"] if build_id else []
    return found[0] if found else None


def probe_wrapper(s: Settings, p) -> str:
    """Whether the gateway reaches the wrapped code: "spike wait 1" answers "waited, 1 ticks" only there."""
    for i in range(4):
        code, body, took = call_agent(s, p, QUALITY, "spike wait 1", tries=1)
        answer = str(e2e.as_json(body).get("answer", body))
        observed("NEW_VERSION wrapper probe", f"try {i + 1}: {code} in {took:.1f}s: {answer[:160]!r}")
        if code == 200 and answer.startswith("waited"):
            return "yes"
        time.sleep(15)
    return "no"


def new_version(c, s: Settings, p, dev: DevTeam) -> bool:
    """Returns whether the wrapped code is what the gateway reaches afterwards."""
    rid, status, _ = record_status(c, p, QUALITY)
    if status != "APPROVED":
        decide("NEW_VERSION", f"unknown: {QUALITY} is {status}, not APPROVED, before the new version")
        return False
    old = application_of(c.reg.get_registry_record(registryId=p.registry_id, recordId=rid)).get("code_version")
    before = quality_runtime(c, s) or {}
    found, took = wait_search(dev, p, QUALITY_QUERY, QUALITY)
    observed("NEW_VERSION before", f"record {status}; Runtime version {before.get('agentRuntimeVersion')} "
             f"{before.get('status')}; search {QUALITY_QUERY!r} finds {QUALITY}: {QUALITY in found} ({took:.0f}s)")
    tmp = Path(tempfile.mkdtemp(prefix="hub-spike-"))
    try:
        folder = tmp / QUALITY
        shutil.copytree(REPO / "dev_team" / QUALITY, folder, ignore=shutil.ignore_patterns("__pycache__"))
        with open(folder / "agent.py", "a", encoding="utf-8") as f:
            f.write(WRAPPER)
        after = time.time()
        out = publish(folder, s, c=dev.clients())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _, status_now, _ = record_status(c, p, QUALITY)
    observed("NEW_VERSION after submit", f"publish says the record is {out['status']}; record_status says "
             f"{status_now}; code version {'changed' if out['code_version'] != old else 'unchanged'}"
             + (f"; {out['note']}" if out.get("note") else ""))
    watch = Watch(s, p, dev, rid, out["code_version"], old)
    watch.start()
    try:
        r = review(c, p, QUALITY, rid, after, n_start=None)
    finally:
        watch.done.set()
        watch.join(timeout=120)
    if not r:
        decide("NEW_VERSION", {"record_after_submit": out["status"], "review": "unknown: no review started"})
        return False
    d = r["execution"]
    full = c.reg.get_registry_record(registryId=p.registry_id, recordId=rid)
    version_after = application_of(full).get("code_version")
    found, took = wait_search(dev, p, QUALITY_QUERY, QUALITY) if full.get("status") == "APPROVED" else ([], 0.0)
    rt = quality_runtime(c, s) or {}
    observed("NEW_VERSION after the review", f"review {d['status']}; record {full.get('status')} "
             f"({full.get('statusReason')}); the application's code_version is the "
             f"{'new' if version_after == out['code_version'] else 'old'} one; search finds {QUALITY}: "
             f"{QUALITY in found} after {took:.0f}s; Runtime version {rt.get('agentRuntimeVersion')} {rt.get('status')}; "
             f"{default_endpoint(c, rt) if rt else 'no Runtime'}")
    if d["status"] != "SUCCEEDED":
        observed("NEW_VERSION failure", e2e.failure_of(r["events"]))
    build = deploy_build_of(c, r)
    made = show_build(c, build, "NEW_VERSION deploy build") if build else {}
    live = probe_wrapper(s, p) if d["status"] == "SUCCEEDED" else "no"
    seen = [x for x in watch.seen if x["state"] != "no review running"]     # a look after the review ended is not one
    decide("NEW_VERSION", {
        "record_after_submit": out["status"],
        "record_during_review": sorted({x["status"] for x in seen}),
        "record_after_review": full.get("status"),
        "code_version_during_review": sorted({x["code_version"] for x in seen}),
        "found_by_search_during_review": sorted({x["found"] for x in seen}),
        "found_by_search_after_review": f"{QUALITY in found} after {took:.0f}s",
        "review": f"{d['status']} in {r['took']:.0f}s" if r["took"] is not None else f"still {d['status']}",
        "steps": e2e.step_times(r["events"], d.get("stopDate")),
        "runtime_version": f"{before.get('agentRuntimeVersion')} -> {rt.get('agentRuntimeVersion')}",
        "deploy": (f"{'created' if made.get('created') else 'updated'} version {made.get('version')}, READY after "
                   f"{made.get('readySeconds')}s, package {made.get('size')} bytes") if made.get("version") else
                  f"unknown: {made.get('status') or 'no deploy build found'}",
        "gateway_reaches_new_code": live,
        "looks_during_review": len(seen),
    })
    return live == "yes"


# ================================================================== 3 sessions, the stop and a long call

class Call(threading.Thread):
    """One user's call through the agent gateway in a thread of its own: what the caller got, and when."""

    def __init__(self, url: str, prompt: str, region: str, sid: str | None, timeout: int):
        super().__init__(daemon=True)
        self.url, self.prompt, self.region, self.sid, self.timeout = url, prompt, region, sid, timeout
        self.code, self.body, self.took, self.t0 = None, "", None, None

    def start(self) -> None:
        self.t0 = time.time()
        super().start()

    def run(self) -> None:
        try:
            self.code, self.body = signed_post(self.url, {"prompt": self.prompt}, self.region,
                                               headers={SESSION_HEADER: self.sid} if self.sid else None,
                                               timeout=self.timeout)
        except Exception as e:                  # a timeout or a reset is what the caller got, too
            self.code, self.body = 0, f"{type(e).__name__}: {e}"
        self.took = time.time() - self.t0

    def said(self) -> str:
        return f"{self.code} after {self.took:.0f}s: {self.body[:200]!r}" if self.took is not None else "no answer yet"


def where_is(c, group: str, sid: str, start: float) -> tuple[list[str], list[str]]:
    """The log streams whose names hold the ID, and the log lines that hold it (since `start`)."""
    names = [x["logStreamName"] for x in streams(c, group) if sid in x["logStreamName"]]
    lines = [ev["message"] for ev in events_between(c, group, start - 5) if sid in ev["message"]]
    return names, lines


def session_ids_in(events: list[dict]) -> list[str]:
    ids = set()
    for ev in events:
        doc = e2e.as_json(ev["message"])
        if doc.get("sessionId"):
            ids.add(str(doc["sessionId"]))
    return sorted(ids)


def places(names: list[str], lines: list[str]) -> str:
    where = (["in a log stream's name"] if names else []) + ([f"in {len(lines)} log lines"] if lines else [])
    return " and ".join(where) or "nowhere"


def shape(sid: str) -> str:
    kind = "a UUID" if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", sid) else "not a UUID"
    return f"{sid} ({len(sid)} characters, {kind})"


def sessions_and_stop(c, s: Settings, p) -> dict:
    """Step 3. Returns what LONG_CALL needs from it."""
    rt = quality_runtime(c, s)
    groups = sorted(g["logGroupName"] for page in c.logs.get_paginator("describe_log_groups").paginate(
        logGroupNamePrefix=f"/aws/bedrock-agentcore/runtimes/{s.runtime_name(QUALITY)}-") for g in page["logGroups"])
    observed("Runtime log groups", groups)
    observed("Runtime lifecycle", rt.get("lifecycleConfiguration") or "none set")
    group = next((g for g in groups if g.endswith("-DEFAULT")), groups[0] if groups else "")
    if not group:
        for key in ("SESSION_SOURCE", "STOP_EFFECT"):
            decide(key, "unknown: the Runtime has no log group")
        return {}
    url, arn = gateway_url(s, p, QUALITY), rt["agentRuntimeArn"]

    # 3a the slow request with a session ID, the stop 60 s in
    sid = "hub-spike-" + uuid.uuid4().hex
    observed("SESSION_SOURCE session ID sent", f"{sid} ({len(sid)} characters) in {SESSION_HEADER}")
    call = Call(url, f"spike wait {LONG}", s.region, sid, LONG_CLIENT)
    call.start()
    t0 = call.t0
    sleep_until(t0 + LOOK_AT)
    names, lines = where_is(c, group, sid, t0)
    ticks = numbered(events_between(c, group, t0 - 5), "tick")
    running_names, running_lines = names, lines
    observed("SESSION_SOURCE 30 s into the call", f"log streams whose name holds the ID: {names or 'none'}; log lines "
             f"that hold it: {len(lines)}{' (first: ' + lines[0][:200] + ')' if lines else ''}; tick lines so far "
             f"{len(ticks)}; the caller: {call.said()}")
    observed("SESSION_SOURCE log streams of the group", [x["logStreamName"] for x in streams(c, group)][-6:])
    sleep_until(t0 + STOP_AT)
    t_stop = time.time()
    try:
        r = c.data.stop_runtime_session(runtimeSessionId=sid, agentRuntimeArn=arn, qualifier="DEFAULT")
        stopped = f"statusCode {r.get('statusCode')}, HTTP {r['ResponseMetadata']['HTTPStatusCode']}"
    except Exception as e:
        stopped = f"refused: {error_text(e)}"
    observed("STOP_EFFECT StopRuntimeSession", f"{stopped}, {t_stop - t0:.0f}s into the call; the caller then: "
             f"{call.said()}")
    sleep_until(t_stop + AFTER_STOP + LOG_LAG)
    ticks = numbered(events_between(c, group, t0 - 5), "tick")
    before = [x for x in ticks if x[0] <= t_stop]
    after = [x for x in ticks if t_stop < x[0] <= t_stop + AFTER_STOP]
    lam_before, lam_after = tool_calls(c, s, t_stop - AFTER_STOP, t_stop), tool_calls(c, s, t_stop, t_stop + AFTER_STOP)
    step = (before[-1][0] - before[0][0]) / (len(before) - 1) if len(before) > 1 else 5.0
    observed("STOP_EFFECT tick lines", f"{len(before)} before the stop{gaps(ticks)} (one every {step:.1f}s; the last, "
             f"tick {before[-1][1]}, at {before[-1][0] - t_stop:+.1f}s from the stop), {len(after)} in the "
             f"{AFTER_STOP}s after it" + (f" (the last, tick {after[-1][1]}, at {after[-1][0] - t_stop:+.1f}s)" if after
                                         else "")
             + f"; the tool Lambda ran {lam_before} times in the {AFTER_STOP}s before the stop and {lam_after} times "
               f"in the {AFTER_STOP}s after it" if before else f"no tick lines at all; tool Lambda {lam_before}, {lam_after}")
    if after and len(after) >= AFTER_STOP // 5 - 2:
        decide("STOP_EFFECT", {"effect": "continues", "ticks_after_stop": len(after)})
    elif before:
        last = (after or before)[-1][0]
        decide("STOP_EFFECT", {"effect": "ends", "ticks_after_stop": len(after),
                               "last_tick_s": round(last - t_stop, 1),
                               "next_tick_due_s": round(last + step - t_stop, 1)})    # it never came
    else:
        decide("STOP_EFFECT", "unknown: no tick lines in the Runtime's log, before or after the stop")
    call.join(timeout=LONG_CLIENT + 30)
    observed("LONG_CALL the stopped call's caller", call.said())

    # 3b a short call with the header, 3c one without it: which session IDs the logs show
    sid2 = "hub-spike-" + uuid.uuid4().hex
    short = Call(url, "spike wait 1", s.region, sid2, 60)
    short.start()
    short.join(timeout=90)
    sleep_until(short.t0 + short.took + LOG_LAG)
    names2, lines2 = where_is(c, group, sid2, short.t0)
    observed("SESSION_SOURCE a short call with the header", f"caller {short.said()}; log streams whose name holds the "
             f"ID: {names2 or 'none'}; log lines that hold it: {len(lines2)}"
             + (f" (first: {lines2[0][:240]})" if lines2 else ""))
    known = {x["logStreamName"] for x in streams(c, group)}
    bare = Call(url, "spike wait 1", s.region, None, 60)
    bare.start()
    bare.join(timeout=90)
    sleep_until(bare.t0 + bare.took + LOG_LAG)
    evs = events_between(c, group, bare.t0 - 1)
    new_streams = sorted({x["logStreamName"] for x in streams(c, group)} - known)
    ids = [i for i in session_ids_in(evs) if not i.startswith("hub-spike-")]
    observed("SESSION_SOURCE a call without the header", f"caller {bare.said()}; new log streams {new_streams or 'none'}; "
             f"session IDs in its log lines: {[shape(i) for i in ids] or 'none'}")
    if running_names or names2:
        decide("SESSION_SOURCE", "stream-name")
    elif running_lines or lines2:
        decide("SESSION_SOURCE", "log-line")
    else:
        decide("SESSION_SOURCE", "caller")
    observed("SESSION_SOURCE detail", f"the ID sent with the slow request, 30 s in while it ran: "
             f"{places(running_names, running_lines)}; the ID sent with the short call, after it ended: "
             f"{places(names2, lines2)}")

    # 3d when the stop came before the caller's answer, a slow request that nobody stops
    long_call = {"stopped_call": call.said()}
    if call.took is None or call.took >= STOP_AT - 1:
        sid4 = "hub-spike-" + uuid.uuid4().hex
        free = Call(url, f"spike wait {LONG}", s.region, sid4, LONG_CLIENT)
        free.start()
        free.join(timeout=LONG_CLIENT + 30)
        sleep_until(max(free.t0 + LONG + 10, free.t0 + (free.took or 0)) + LOG_LAG)
        ticks4 = numbered(events_between(c, group, free.t0 - 5), "tick")
        t_ans = free.t0 + (free.took or 0)
        later = [x for x in ticks4 if x[0] > t_ans]
        observed("LONG_CALL a slow request that nobody stops", f"caller {free.said()}; {len(ticks4)} tick lines, the "
                 f"last {ticks4[-1][0] - free.t0:.0f}s after the call started; {len(later)} after the caller's answer"
                 if ticks4 else f"caller {free.said()}; no tick lines")
        long_call["caller"] = f"{free.code} after {free.took:.0f}s" if free.took is not None else "no answer"
        long_call["body"] = free.body[:120]
        long_call["ticks_after_answer"] = len(later) if ticks4 else "unknown: no tick lines"
    else:
        later = [x for x in ticks if t0 + call.took < x[0] <= t_stop]
        long_call["caller"] = f"{call.code} after {call.took:.0f}s (before the stop)"
        long_call["body"] = call.body[:120]
        long_call["ticks_after_answer"] = len(later)
    return long_call


# ================================================================== 4 the retry loop

def tool_metric(c, s: Settings, p) -> list[dict]:
    """The tool gateway's Invocations metrics for TOOL (dimension Name), with Method tools/call, on this hub's tool
    gateway (dimension Resource)."""
    found = [m for page in c.cw.get_paginator("list_metrics").paginate(
        Namespace="AWS/Bedrock-AgentCore", MetricName="Invocations", Dimensions=[{"Name": "Name", "Value": TOOL}])
        for m in page["Metrics"]]
    dims = [{d["Name"]: d["Value"] for d in m["Dimensions"]} for m in found]
    return [m for m, d in zip(found, dims) if d.get("Method") == "tools/call" and d.get("Resource") == p.tool_gw["arn"]]


def loop_rate(c, s: Settings, p) -> dict:
    """Step 4. Returns the whole minute inside the loop, for the metric read at the end."""
    group = next(iter(sorted(g["logGroupName"] for page in c.logs.get_paginator("describe_log_groups").paginate(
        logGroupNamePrefix=f"/aws/bedrock-agentcore/runtimes/{s.runtime_name(QUALITY)}-") for g in page["logGroups"]
        if g["logGroupName"].endswith("-DEFAULT"))), "")
    now = time.time()
    wait = (LOOP_START_SECOND - datetime.fromtimestamp(now, timezone.utc).second) % 60
    time.sleep(wait)
    t0 = time.time()
    code, body = 0, ""
    try:
        code, body = signed_post(gateway_url(s, p, QUALITY), {"prompt": f"spike loop {LOOP}"}, s.region, timeout=LOOP_CLIENT)
    except Exception as e:
        body = f"{type(e).__name__}: {e}"
    gave_up = time.time()
    observed("LOOP_RATE the caller", f"started at {clock(t0)}; got {code} after {gave_up - t0:.0f}s: {body[:160]!r}")
    sleep_until(t0 + LOOP_COUNT_AT)
    rounds = numbered(events_between(c, group, t0 - 5), "loop")
    if not rounds:
        decide("LOOP_RATE", "unknown: no loop lines in the Runtime's log")
        return {}
    first, last = rounds[0][0], rounds[-1][0]
    minute = (int(first) // 60 + 1) * 60                    # the first whole clock minute after the first round
    whole = minute + 60 <= last + 1
    in_minute = [x for x in rounds if minute <= x[0] < minute + 60] if whole else []
    lam_minute = tool_calls(c, s, minute, minute + 60) if whole else None
    lam_all = tool_calls(c, s, t0, last + 30)
    observed("LOOP_RATE loop lines", f"{len(rounds)} rounds{gaps(rounds)}, the first {first - t0:.0f}s and the last "
             f"{last - t0:.0f}s after the call started (the caller gave up after {gave_up - t0:.0f}s); the tool Lambda "
             f"ran {lam_all} times from the call's start to 30 s after the last round (every tool, every caller)")
    if whole:
        observed("LOOP_RATE the whole minute inside the loop", f"{clock(minute)} to {clock(minute + 60)}: {len(in_minute)} "
                 f"loop lines, {lam_minute} tool Lambda invocations")
        decide("LOOP_RATE", len(in_minute))
    else:
        rate = round((len(rounds) - 1) * 60 / max(last - first, 1))
        observed("LOOP_RATE no whole minute inside the loop", f"rounds per minute from the first to the last line: {rate}")
        decide("LOOP_RATE", rate)
    return {"minute": minute if whole else None, "rounds_in_minute": len(in_minute) if whole else None,
            "loop_ran_after_caller_gave_up": f"{last - gave_up:.0f}s"}


def read_metric(c, s: Settings, p, minute: float | None, t0: float, rounds: int | None) -> None:
    """The tool gateway's Invocations metric (Sum per minute) around the loop, read late: the metric lags. When the
    metric's whole minute differs from the loop lines of that minute, LOOP_RATE takes the metric (it counts tool
    calls, which is what LOOP_RATE means)."""
    metrics = tool_metric(c, s, p)
    if not metrics:
        observed("LOOP_RATE metric", f"no Invocations metric with Name={TOOL} and Method=tools/call")
        return
    m = metrics[0]
    observed("LOOP_RATE metric dimensions", sorted(d["Name"] for d in m["Dimensions"]))
    start = datetime.fromtimestamp(t0 - 120, timezone.utc)
    end = datetime.fromtimestamp(t0 + 240, timezone.utc)
    deadline = time.time() + 300
    while True:
        pts = sorted(c.cw.get_metric_statistics(Namespace=m["Namespace"], MetricName=m["MetricName"],
                                                Dimensions=m["Dimensions"], StartTime=start, EndTime=end, Period=60,
                                                Statistics=["Sum"])["Datapoints"], key=lambda x: x["Timestamp"])
        hit = [x for x in pts if minute and x["Timestamp"].timestamp() == minute]
        if hit or not minute or time.time() > deadline:
            break
        time.sleep(30)
    observed("LOOP_RATE metric Sum per minute", [f"{clock(x['Timestamp'].timestamp())} {x['Sum']:.0f}" for x in pts])
    if minute:
        observed("LOOP_RATE metric for the whole minute inside the loop",
                 f"{clock(minute)}: {hit[0]['Sum']:.0f}" if hit else f"{clock(minute)}: no datapoint after waiting")
        if hit and rounds is not None and round(hit[0]["Sum"]) != rounds:
            observed("LOOP_RATE metric and loop lines differ", f"{round(hit[0]['Sum'])} tool calls and {rounds} rounds in "
                     "that minute: LOOP_RATE takes the tool calls")
            decide("LOOP_RATE", round(hit[0]["Sum"]))


# ================================================================== 5 the stop policy's exception

def until(fn, want: int, timeout: int = UNTIL_WAIT, step: int = 3) -> tuple[int, str, float]:
    t0 = time.monotonic()
    while True:
        code, body = fn()
        if code == want or time.monotonic() - t0 > timeout:
            return code, body, time.monotonic() - t0
        time.sleep(step)


def remove_stop_policy(c, p) -> str:
    found = list_policies(c, p.engine_id).get(STOP_POLICY)
    if found:
        drop_policy(c, p.engine_id, found["policyId"])
    left = STOP_POLICY in list_policies(c, p.engine_id)
    return f"{'deleted' if found else 'none to delete'}; left afterwards: {'yes' if left else 'none'}"


def stop_exception(c, s: Settings, p) -> None:
    url = gateway_url(s, p, QUALITY)

    def user() -> tuple[int, str]:
        try:
            return signed_post(url, {"prompt": "spike wait 1"}, s.region, timeout=60)
        except Exception as e:
            return 0, f"{type(e).__name__}: {e}"

    principal = f'AgentCore::IamEntity::"arn:aws:sts::{c.account}:assumed-role/{s.prefix}-review-testcall-role"'
    scope = (f'action == AgentCore::Action::"{s.target_name(QUALITY)}___POST:/invocations", '
             f'resource == AgentCore::Gateway::"{p.agent_gw["arn"]}"')
    forms = {"unless": f"forbid (principal, {scope}) unless {{ principal == {principal} }};",
             "when": f"forbid (principal, {scope}) when {{ principal != {principal} }};"}
    lam = boto3.Session(region_name=s.region).client("lambda", config=Config(read_timeout=960, connect_timeout=30,
                                                                               retries={"max_attempts": 0}))
    event = {"spec": {"name": QUALITY}, "target": s.target_name(QUALITY)}
    result = "none"
    try:
        for form, statement in forms.items():
            observed(f"STOP_EXCEPTION {form}", f"statement {statement}")
            t = time.monotonic()
            try:
                ensure_policy(c, p.engine_id, STOP_POLICY, statement)
            except Exception as e:                       # a FAILED policy is deleted by ensure_policy
                observed(f"STOP_EXCEPTION {form}", f"the policy is not ACTIVE: {error_text(e)}")
                continue
            observed(f"STOP_EXCEPTION {form}", f"policy ACTIVE after {time.monotonic() - t:.0f}s")
            code, body, took = until(user, 403)
            observed(f"STOP_EXCEPTION {form} user call", f"{code} after {took:.0f}s: {body[:200]!r}")
            if code != 403:
                observed(f"STOP_EXCEPTION {form}", "the users' call was not refused, so the exception is not tested")
                observed(f"STOP_EXCEPTION {form} removed", remove_stop_policy(c, p))
                continue
            t = time.monotonic()
            try:
                r = lam.invoke(FunctionName=f"{s.prefix}-review-testcall", Payload=json.dumps(event).encode())
                payload, failed = r["Payload"].read().decode("utf-8", "replace"), r.get("FunctionError")
            except Exception as e:
                payload, failed = error_text(e), "invoke failed"
            observed(f"STOP_EXCEPTION {form} test call Lambda", f"{'FunctionError ' + failed if failed else 'no error'} "
                     f"after {time.monotonic() - t:.0f}s: {payload[:300]}")
            code2, body2 = user()
            observed(f"STOP_EXCEPTION {form} user call after the test call", f"{code2}: {body2[:160]!r}")
            if not failed and code2 == 403:
                result = form
                break
            observed(f"STOP_EXCEPTION {form} removed", remove_stop_policy(c, p))
    finally:
        t = time.monotonic()
        observed("STOP_EXCEPTION policy removed", remove_stop_policy(c, p))
        gone = time.monotonic() - t
        code, body, took = until(user, 200)
        observed("STOP_EXCEPTION user call after the removal", f"{code} {gone + took:.0f}s after the delete call "
                 f"({gone:.0f}s until the policy was gone, then {took:.0f}s of calls): {body[:120]!r}")
    decide("STOP_EXCEPTION", result)


# ================================================================== main

def run_step(name: str, fn, *keys: str):
    """Run one step; an error leaves its decisions `unknown: <error>` and the next steps still run."""
    say(f"== {name}")
    try:
        return fn()
    except Exception as e:
        observed(f"{name} stopped", error_text(e))
        for key in keys:
            if str(DECISIONS[key]).startswith("unknown: not reached"):
                DECISIONS[key] = f"unknown: {name} stopped: {error_text(e)}"
        return None


def main() -> int:
    os.environ.update(env_file_updates(os.environ, REPO / ".env"))
    s = Settings.from_env()
    c = Clients.for_settings(s)
    e2e.ACCOUNT = c.account
    p = load(s, c)
    say(f"== spike_operations ({s.region}, prefix {s.prefix}), {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    if not (p.machine_arn and p.registry_id and p.agent_gw.get("id") and p.dev_role_arn and p.engine_id):
        say("== the hub is not deployed: run `make deploy seed e2e` first")
        return 1
    running = c.sfn.list_executions(stateMachineArn=p.machine_arn, statusFilter="RUNNING")["executions"]
    if running:
        say(f"== a review is running ({[x['name'] for x in running]}): wait until it stops, then start again")
        return 1
    dev = DevTeam(c, s, p.dev_role_arn)
    t_start = time.monotonic()
    try:
        run_step("0 deploy builds so far", lambda: deploy_builds(c, s))
        run_step("1 SEED_EVENT", lambda: seed_event(c, p), "SEED_EVENT")
        live = run_step("2 NEW_VERSION", lambda: new_version(c, s, p, dev), "NEW_VERSION")
        long_call, loop = {}, {}
        if live:
            long_call = run_step("3 SESSION_SOURCE, STOP_EFFECT, LONG_CALL", lambda: sessions_and_stop(c, s, p),
                                 "SESSION_SOURCE", "STOP_EFFECT", "LONG_CALL") or {}
            t_loop = time.time()
            loop = run_step("4 LOOP_RATE", lambda: loop_rate(c, s, p), "LOOP_RATE") or {}
        else:
            for key in ("SESSION_SOURCE", "STOP_EFFECT", "LONG_CALL", "LOOP_RATE"):
                DECISIONS[key] = "unknown: the gateway does not reach the wrapped new version, so its steps did not run"
        run_step("5 STOP_EXCEPTION", lambda: stop_exception(c, s, p), "STOP_EXCEPTION")
        if long_call:
            decide("LONG_CALL", {**long_call, "loop_after_the_caller_gave_up": loop.get("loop_ran_after_caller_gave_up",
                                                                                      "unknown: step 4 gave nothing")})
        elif live and str(DECISIONS["LONG_CALL"]).startswith("unknown: not reached"):
            DECISIONS["LONG_CALL"] = "unknown: step 3 gave no long call result"
        if loop:
            run_step("4 LOOP_RATE metric", lambda: read_metric(c, s, p, loop.get("minute"), t_loop,
                                                               loop.get("rounds_in_minute")))
    finally:
        say(f"== stop policy left: {'yes' if STOP_POLICY in list_policies(c, p.engine_id) else 'none'}")
        say(f"== spike_operations took {time.monotonic() - t_start:.0f}s")
        print_decisions()
    return 0


PRINTED = [False]


def print_decisions() -> None:
    if not PRINTED[0]:
        PRINTED[0] = True
        say(f"== decisions: {json.dumps(DECISIONS, ensure_ascii=False, default=str)}")


if __name__ == "__main__":
    try:
        code = main()
    except BaseException as e:                     # a traceback could print the account ID: mask it
        say(f"ERROR {type(e).__name__}: {e}")
        print_decisions()
        code = 1
    sys.exit(code)
