"""e2e_hosting.py - flow 1 (hosting) from end to end on real AWS: scenes 1-1 to 2-3 of the demo story.

    make deploy seed && AWS_REGION=us-west-2 uv run python e2e_checks/e2e_hosting.py 2>&1 | tee e2e_checks/last-run.log

Twelve checks, one [PASS] / [FAIL] line each, [INFO] lines for what was observed (timings, answers, the alert),
then `== N checks passed, M failed, K observations`. Exit code 1 if a check failed.
   1  as the dev team role, a catalog search finds the shared tool record parts-tools           (picture 1)
   2  as the dev team role, the shared read tool answers and another tool is refused by policy  (D15)
      (JSON-RPC error -32002, "policy enforcement"; any other error does not count)
   3  as the dev team role, publish.sh dev_team/release_review: the record is PENDING_APPROVAL  (picture 2)
   4  the review starts within 120 s of the request (timed from just before publish.sh)         (picture 3)
   5  the review SUCCEEDED with the steps Read:lambda .. Approve:lambda in order                (pictures 4 5 6)
   6  the record is APPROVED and a catalog search finds it                                      (picture 6)
   7  a user calls release_review through the agent gateway: 200, and a change that breaks a rule
      makes it use Release___file_review_request
   8  quality_agent v1-vulnerable: the review FAILED at Scan; an alert arrives that names the agent and the step;
      the scan build's log, found from what the alert carries, has the jinja2 advisory line    (picture 4-1)
   9  that submission made no role, policy, gateway target or Runtime
  10  reject.sh: the record is REJECTED
  11  the fixed version (no variant) again: a new review starts, SUCCEEDED, and the record is APPROVED
  12  quality_agent answers with both its tools (an EMP- employee ID in the answer is an [INFO]: plan 2 masks it)

The dev team's steps run as the dev team role (<prefix>-dev-role), the platform team's (reject.sh) and the user's
calls with the credentials of the shell. publish.sh and reject.sh are the repo's own commands.
Before the checks, the two agents are brought back to a known state with the repo's own cleanup (remove_agent, then
the agent's catalog record), so the script can start again after a failed run; it refuses to start while a review
is still running. Alerts are read through a temporary SQS queue <prefix>-e2e-alerts subscribed to the alert topic;
the queue and the subscription are removed at the end, also when a check fails. Everything this script makes or
changes has a name that starts with the hub's prefix, or lives in the hub's catalog and policy engine.
Printed output masks the account ID.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from platform_team.agent_catalog.catalog_records import drop_record, records, search
from platform_team.agent_catalog.seed_catalog import SHARED_RECORD
from platform_team.agent_gateway.gateway_targets import targets
from platform_team.company_policy.policy_engine import list_policies
from platform_team.company_policy.policy_names import policy_names
from platform_team.hosting_review.agent_cleanup import remove_agent
from platform_team.sample_tools.tool_data import INSPECTIONS, PARTS, TEST_RESULTS
from platform_team.sample_tools.tool_schema import SHARED_READ, TARGETS
from platform_team.shared_code.aws_helpers import Clients, all_items, mask, retry, signed_post
from platform_team.shared_code.config import PACKAGES, Settings, env_file_updates
from platform_team.shared_code.hub_state import Platform, load

REPO = Path(__file__).resolve().parents[1]
PUBLISH = REPO / "dev_team" / "agent_template" / "publish.sh"
REJECT = REPO / "platform_team" / "hosting_review" / "reject.sh"
RELEASE, QUALITY, VULNERABLE = "release_review", "quality_agent", "v1-vulnerable"
STEPS = ["Read:lambda", "Scan:codebuild", "Grant:lambda", "Deploy:codebuild", "Entry:lambda", "TestCall:lambda",
         "Approve:lambda"]
FILE_TOOL = "Release___file_review_request"
QUALITY_TOOLS = ["Quality___get_inspection_data", "Parts___get_part_spec"]
OTHER_TOOL = "Parts___get_test_result"
SHARED_QUERY = "part specification tool"
RELEASE_QUERY = "release rules review request"
VIOLATION = ("Change C-7 rolls out to every region at once and skips the canary stage. "
             "It has a rollback plan and all its tests pass.")
COMPLIANT = "Change C-8 goes through the canary stage first, has a rollback plan, and all its tests pass."
QUESTION = "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"
REASON = "jinja2 2.11.2 has published advisories"
ADVISORY = re.compile(r"\bjinja2\s+2\.11\.2\s+(GHSA-|PYSEC-|CVE-)", re.I)    # a row of pip-audit's table
START_WAIT = 120         # s, check 4: from the request to the start of the review
LATE_LOOK = 60           # s, how long after START_WAIT a late review is still looked for (to say how late it was)
REVIEW_WAIT = 2700       # s, one review (the deploy build alone may take up to 30 min)
ALERT_WAIT = 180         # s, after the review stopped
SEARCH_WAIT = 180        # s, the search index follows an approval
COMMAND_WAIT = 900       # s, publish.sh or reject.sh
MADE_BY_A_REVIEW = ("Runtime", "policies", "role", "target")      # the kinds check 9 looks for, after Scan

RESULTS: list[tuple[int, str, bool]] = []
OBSERVED = [0]
ACCOUNT = ""


# ================================================================== output

def clean(text) -> str:
    """The account ID as <ACCOUNT>, and any other run of 12 or more digits as <NUMBER>."""
    text = mask(str(text), ACCOUNT) if ACCOUNT else str(text)
    return re.sub(r"[0-9]{12,}", "<NUMBER>", text)


def say(msg) -> None:
    print(clean(msg), flush=True)


def check(n: int, name: str, ok: bool, note: str) -> bool:
    RESULTS.append((n, name, bool(ok)))
    say(f"[{'PASS' if ok else 'FAIL'}] {n} {name}: {note}")
    return bool(ok)


def info(what: str, note) -> None:
    OBSERVED[0] += 1
    say(f"[INFO] {what}: {' '.join(str(note).split())}")


def as_json(text: str) -> dict:
    """The JSON body of an answer; a streamed answer carries it on a data: line."""
    for line in (text or "").splitlines():
        if line.startswith("data:"):
            text = line[5:].strip()
    try:
        doc = json.loads(text)
        return doc if isinstance(doc, dict) else {}
    except (TypeError, ValueError):
        return {}


def error_of(e: Exception) -> str:
    err = e.response.get("Error", {}) if isinstance(e, ClientError) else {}
    return f"{err.get('Code')}: {err.get('Message', '')}" if err else f"{type(e).__name__}: {e}"


# ================================================================== who calls

class DevTeam:
    """The dev team role. Credentials are taken again for each use: a run lasts longer than a session's hour."""

    def __init__(self, c: Clients, s: Settings, role_arn: str):
        self.c, self.s, self.role_arn = c, s, role_arn

    def _creds(self) -> dict:
        return retry(lambda: self.c.sts.assume_role(RoleArn=self.role_arn, RoleSessionName="developer",
                                                    DurationSeconds=3600)["Credentials"])

    def clients(self) -> Clients:
        r = self._creds()
        return Clients(boto3.Session(aws_access_key_id=r["AccessKeyId"], aws_secret_access_key=r["SecretAccessKey"],
                                     aws_session_token=r["SessionToken"], region_name=self.s.region))

    def env(self) -> dict:
        """The environment of a command run as the dev team role."""
        r = self._creds()
        env = {k: v for k, v in os.environ.items() if k not in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")}
        return {**env, "AWS_ACCESS_KEY_ID": r["AccessKeyId"], "AWS_SECRET_ACCESS_KEY": r["SecretAccessKey"],
                "AWS_SESSION_TOKEN": r["SessionToken"], "AWS_REGION": self.s.region, "AWS_DEFAULT_REGION": self.s.region}


def run_command(what: str, cmd: list[str], env: dict) -> tuple[int, str]:
    """Run one of the repo's commands; its output becomes one [INFO] line."""
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=COMMAND_WAIT, cwd=REPO)
        code, out = r.returncode, "\n".join(x for x in (r.stdout.strip(), r.stderr.strip()) if x)
    except subprocess.TimeoutExpired:
        code, out = -1, f"no answer after {COMMAND_WAIT}s"
    lines = [line for line in out.splitlines() if line.strip() and not line.startswith(("Uninstalled", "Installed",
                                                                                       "Resolved", "Prepared", "Audited"))]
    info(what, f"exit {code} in {time.monotonic() - t0:.0f}s: {' | '.join(lines)[-1500:]}")
    return code, out


def publish(dev: DevTeam, agent: str, variant: str | None = None) -> tuple[int, str]:
    cmd = [str(PUBLISH), str(REPO / "dev_team" / agent)] + ([variant] if variant else [])
    return run_command(f"publish.sh dev_team/{agent}{' ' + variant if variant else ''} (dev team role)", cmd, dev.env())


def gateway_url(s: Settings, p: Platform, agent: str) -> str:
    return f"https://{p.agent_gw['id']}.gateway.bedrock-agentcore.{s.region}.amazonaws.com/{s.target_name(agent)}/invocations"


def call_agent(s: Settings, p: Platform, agent: str, prompt: str, tries: int = 3) -> tuple[int, str, float]:
    """A user's call through the agent gateway (the shell's credentials). Returns status, body and seconds."""
    for i in range(tries):
        t0 = time.monotonic()
        try:
            code, body = signed_post(gateway_url(s, p, agent), {"prompt": prompt}, s.region, timeout=180)
        except OSError as e:
            code, body = 0, f"{type(e).__name__}: {e}"
        took = time.monotonic() - t0
        if code == 200 or i == tries - 1:
            return code, body, took
        info(f"call to {agent}", f"attempt {i + 1}: {code} {body[:200]}; trying again in 15s")
        time.sleep(15)
    return 0, "", 0.0


def policy_refusal(text: str) -> bool:
    """Check 2: the tool gateway refused the call by policy: JSON-RPC error -32002 "Tool Execution Denied: Tool call
    not allowed due to policy enforcement [...]". Any other error (an unknown tool, a failed tool) is not a refusal."""
    err = as_json(text).get("error")
    return isinstance(err, dict) and err.get("code") == -32002 and "policy enforcement" in str(err.get("message", ""))


def mcp(url: str, method: str, params: dict, region: str, creds) -> tuple[int, str]:
    return signed_post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, region,
                       headers={"Accept": "application/json, text/event-stream"}, creds=creds)


def hub_tools_module():
    """dev_team/agent_template/hub_tools.py, the agents' own tool client, to read a gateway answer as they do."""
    spec = importlib.util.spec_from_file_location("hub_tools", REPO / "dev_team" / "agent_template" / "hub_tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ================================================================== the review

def started_in_time(requested_at: float, started_at: float, limit: float = START_WAIT) -> bool:
    """Check 4: the review started no later than `limit` seconds after the request (both epoch s)."""
    return started_at - requested_at <= limit


def execution_for(c: Clients, machine_arn: str, record_id: str, after: float, timeout: int) -> tuple[dict | None, float]:
    """The review execution started for this record at or after `after` (epoch s, taken just before publish.sh makes
    the request). Returns it and its delay from `after`. It looks until `timeout` seconds after `after` and a little
    longer (LATE_LOOK), so a review that starts late is found and its delay shown, not taken for a missing one."""
    seen = set()
    while True:
        for e in c.sfn.list_executions(stateMachineArn=machine_arn, maxResults=20)["executions"]:
            if e["executionArn"] in seen or e["startDate"].timestamp() < after - 5:
                continue
            seen.add(e["executionArn"])
            d = c.sfn.describe_execution(executionArn=e["executionArn"])
            if (as_json(d.get("input") or "").get("detail") or {}).get("registryRecordId") == record_id:
                return d, e["startDate"].timestamp() - after
        if time.time() - after > timeout + LATE_LOOK:
            return None, time.time() - after
        time.sleep(3)


def wait_done(c: Clients, arn: str, timeout: int = REVIEW_WAIT) -> dict:
    t0 = time.monotonic()
    while True:
        d = c.sfn.describe_execution(executionArn=arn)
        if d["status"] != "RUNNING" or time.monotonic() - t0 > timeout:
            return d
        time.sleep(10)


def history(c: Clients, arn: str) -> list[dict]:
    return [h for page in c.sfn.get_paginator("get_execution_history").paginate(executionArn=arn)
            for h in page["events"]]


def steps_run(events: list[dict]) -> list[str]:
    """Each Task state entered, with the service that ran it: Read:lambda, Scan:codebuild, ... (a retry counts once)."""
    out, current = [], None
    for h in events:
        if h["type"] == "TaskStateEntered":
            current = h["stateEnteredEventDetails"]["name"]
        elif h["type"] == "TaskScheduled" and current:
            out.append(f"{current}:{h['taskScheduledEventDetails']['resourceType']}")
            current = None
    return out


def step_times(events: list[dict], stop) -> str:
    """How long each state took: from its entry to the next state's entry (the last one to the execution's stop)."""
    entered = [(h["stateEnteredEventDetails"]["name"], h["timestamp"]) for h in events if h["type"].endswith("StateEntered")]
    ends = [t for _, t in entered[1:]] + [stop]
    return ", ".join(f"{name} {(end - t).total_seconds():.0f}s" for (name, t), end in zip(entered, ends) if end)


def failure_of(events: list[dict]) -> str:
    """The error and cause of the last failed task, shortened."""
    for h in reversed(events):
        for key, d in h.items():
            if key.endswith("FailedEventDetails") and isinstance(d, dict):
                return f"{h['type']}: {d.get('error')}: {str(d.get('cause'))[:600]}"
    return "no failed task in the history"


def review(c: Clients, p: Platform, agent: str, record_id: str, after: float, n_start: int | None) -> dict | None:
    """Find the review of this record, wait until it stops, and say what it did. With n_start, check 4 is recorded."""
    ex, delay = execution_for(c, p.machine_arn, record_id, after, START_WAIT)
    if n_start:
        check(n_start, "the review starts within 120 s",
              ex is not None and started_in_time(after, ex["startDate"].timestamp()),
              f"execution {ex['name']} started {delay:.0f}s after the request" if ex else f"no execution for {agent} "
              f"within {START_WAIT + LATE_LOOK}s of the request")
    if not ex:
        return None
    d = wait_done(c, ex["executionArn"])
    events = history(c, ex["executionArn"])
    took = (d["stopDate"] - d["startDate"]).total_seconds() if d.get("stopDate") else None
    info(f"review of {agent}", f"{d['status']} in {took:.0f}s; steps {step_times(events, d.get('stopDate'))}"
         if took is not None else f"still {d['status']} after {REVIEW_WAIT}s")
    return {"execution": d, "events": events, "steps": steps_run(events), "took": took}


def record_status(c: Clients, p: Platform, agent: str) -> tuple[str, str, str]:
    """(record ID, status, status reason) of the agent's record; ("", "absent", "") when there is none."""
    rec = records(c, p.registry_id).get(agent)
    if not rec:
        return "", "absent", ""
    full = c.reg.get_registry_record(registryId=p.registry_id, recordId=rec["recordId"])
    return rec["recordId"], full.get("status", rec["status"]), full.get("statusReason") or ""


def wait_search(dev: DevTeam, p: Platform, query: str, name: str) -> tuple[list[str], float]:
    c, found, t0 = dev.clients(), [], time.monotonic()
    while time.monotonic() - t0 < SEARCH_WAIT:
        found = search(c, p.registry_id, query)
        if name in found:
            break
        time.sleep(10)
    return found, time.monotonic() - t0


# ================================================================== alerts through a temporary queue

class AlertInbox:
    """A temporary SQS queue <prefix>-e2e-alerts subscribed to the alert topic. Not raw: the SNS envelope keeps the
    subject, so a message reads as an email subscriber would get it. close() removes the subscription and the queue."""

    def __init__(self, c: Clients, s: Settings, topic_arn: str):
        self.c, self.name, self.topic = c, f"{s.prefix}-e2e-alerts", topic_arn
        self.url = self.sub = None
        self.kept: list[dict] = []

    def open(self) -> None:
        self.url = retry(lambda: self.c.sqs.create_queue(QueueName=self.name)["QueueUrl"], wait=15,
                         on=("ClientError", "QueueDeletedRecently"))     # a queue deleted < 60 s ago cannot be made
        arn = self.c.sqs.get_queue_attributes(QueueUrl=self.url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        self.c.sqs.set_queue_attributes(QueueUrl=self.url, Attributes={"Policy": json.dumps({
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": "sns.amazonaws.com"}, "Action": "sqs:SendMessage",
                "Resource": arn, "Condition": {"ArnEquals": {"aws:SourceArn": self.topic}}}]})})
        self.sub = self.c.sns.subscribe(TopicArn=self.topic, Protocol="sqs", Endpoint=arn,
                                        ReturnSubscriptionArn=True)["SubscriptionArn"]
        self._drain()          # a queue left by a run that was stopped hard may hold old messages
        self.kept.clear()
        info("alert inbox", f"temporary queue {self.name} subscribed to the alert topic")

    def _drain(self) -> None:
        while True:
            msgs = self.c.sqs.receive_message(QueueUrl=self.url, MaxNumberOfMessages=10, WaitTimeSeconds=2).get("Messages", [])
            if not msgs:
                return
            for m in msgs:
                self.kept.append(as_json(m["Body"]))
                self.c.sqs.delete_message(QueueUrl=self.url, ReceiptHandle=m["ReceiptHandle"])

    def wait(self, contains: str, timeout: int = ALERT_WAIT) -> dict | None:
        """The first SNS envelope whose message holds `contains`, received within `timeout` seconds."""
        t0 = time.monotonic()
        while True:
            self._drain()
            hit = next((m for m in self.kept if contains in str(m.get("Message", ""))), None)
            if hit or time.monotonic() - t0 > timeout:
                return hit
            time.sleep(5)

    def close(self) -> None:
        done = []
        if self.sub:
            try:
                self.c.sns.unsubscribe(SubscriptionArn=self.sub)
                done.append("subscription")
            except ClientError as e:
                info("alert inbox", f"subscription not removed: {error_of(e)}")
        if self.url:
            try:
                self.c.sqs.delete_queue(QueueUrl=self.url)
                done.append(f"queue {self.name}")
            except ClientError as e:
                info("alert inbox", f"queue not removed: {error_of(e)}")
        if done:
            info("alert inbox", f"removed {' and '.join(done)}")


# ================================================================== the scenes

def known_state(c: Clients, s: Settings, p: Platform) -> None:
    """Remove what an earlier run left for the two agents, with the repo's own cleanup, and their records."""
    for agent in (RELEASE, QUALITY):
        t0 = time.monotonic()
        removed = remove_agent(c, s, p, agent)
        rec = records(c, p.registry_id).get(agent)
        if rec:
            drop_record(c, p.registry_id, rec["recordId"])
            removed.append(f"record {agent} ({rec['status']})")
        info(f"known state for {agent}", f"removed in {time.monotonic() - t0:.0f}s: {', '.join(removed)}" if removed
             else "nothing left from an earlier run")


def scene_search(dev: DevTeam, p: Platform) -> None:
    found, took = wait_search(dev, p, SHARED_QUERY, SHARED_RECORD)
    check(1, "as the dev team role, a catalog search finds parts-tools", SHARED_RECORD in found,
          f"search {SHARED_QUERY!r} returned {found} after {took:.0f}s")


def scene_dev_tools(dev: DevTeam, s: Settings, p: Platform) -> None:
    creds = dev.clients().session.get_credentials().get_frozen_credentials()
    url = p.tool_gw["url"]
    code_ok, ok = mcp(url, "tools/call", {"name": SHARED_READ[0], "arguments": {"part_id": "P-100"}}, s.region, creds)
    code_no, no = mcp(url, "tools/call", {"name": OTHER_TOOL, "arguments": {"part_id": "P-100"}}, s.region, creds)
    doc_ok = as_json(ok)
    answered = PARTS["P-100"]["spec"] in ok and not (doc_ok.get("result") or {}).get("isError")
    refused = TEST_RESULTS["P-100"]["inspector_id"] not in no and policy_refusal(no)
    check(2, "as the dev team role, the shared tool answers and another tool is refused", answered and refused,
          f"{SHARED_READ[0]} -> {code_ok} {ok[:140]}; {OTHER_TOOL} -> {code_no} {no[:200]}")
    info("a refused tool call as hub_tools.call_tool reads it", f"HTTP {code_no}; call_tool returns "
         f"{hub_tools_module().parse_tool_response(no)[:200]!r}")


def scene_release(c: Clients, s: Settings, p: Platform, dev: DevTeam) -> None:
    after = time.time()
    code, out = publish(dev, RELEASE)
    rid, status, _ = record_status(c, p, RELEASE)
    if not check(3, "as the dev team role, publish release_review: PENDING_APPROVAL",
                 code == 0 and status == "PENDING_APPROVAL", f"publish.sh exit {code}; record {status}"):
        for n, name in ((4, "the review starts within 120 s"), (5, "the review SUCCEEDED in the design order"),
                        (6, "the record is APPROVED and found"), (7, "a user calls release_review")):
            check(n, name, False, "not run: release_review was not submitted")
        return
    r = review(c, p, RELEASE, rid, after, n_start=4)
    if not r:
        for n, name in ((5, "the review SUCCEEDED in the design order"), (6, "the record is APPROVED and found"),
                        (7, "a user calls release_review")):
            check(n, name, False, "not run: no review started")
        return
    d = r["execution"]
    passed = d["status"] == "SUCCEEDED" and r["steps"] == STEPS
    check(5, "the review SUCCEEDED in the design order", passed,
          f"{d['status']}; steps {r['steps']}" + ("" if passed else f"; {failure_of(r['events'])}"))
    if d["status"] == "SUCCEEDED":
        out = as_json(d.get("output") or "")
        info("TestCall of release_review", json.dumps(out.get("testCall"))[:500])
    _, status, reason = record_status(c, p, RELEASE)
    found, took = wait_search(dev, p, RELEASE_QUERY, RELEASE) if status == "APPROVED" else ([], 0.0)
    check(6, "the record is APPROVED and found", status == "APPROVED" and RELEASE in found,
          f"record {status} ({reason}); search {RELEASE_QUERY!r} returned {found} after {took:.0f}s")
    if status != "APPROVED":
        check(7, "a user calls release_review", False, "not run: release_review is not approved")
        return
    code, body, took = call_agent(s, p, RELEASE, VIOLATION)
    answer = as_json(body)
    used = answer.get("tools_used") or []
    filed = re.search(r"Review request: RR-[0-9A-F]{8}\b", str(answer.get("answer", "")))    # the ID only the tool makes
    check(7, "a user calls release_review: 200, and a broken rule files a review request",
          code == 200 and FILE_TOOL in used and bool(filed),
          f"{code} in {took:.1f}s; tools {used}; answer {str(answer.get('answer', body))[:300]!r}")
    code2, body2, took2 = call_agent(s, p, RELEASE, COMPLIANT)
    answer2 = as_json(body2)
    info("release_review on a change that keeps the rules", f"{code2} in {took2:.1f}s; tools "
         f"{answer2.get('tools_used')}; answer {str(answer2.get('answer', body2))[:200]!r}")


def alert_parts(envelope: dict) -> tuple[dict, str, str]:
    """(the message as JSON, the agent it names, the step it names) of an alert envelope."""
    message = as_json(envelope.get("Message", ""))
    spec = message.get("spec") or {}
    agent = spec.get("name") or message.get("record") or ""
    step = str(message.get("failedStep") or "")
    return message, agent, step


def scan_log_lines(c: Clients, message: dict) -> tuple[str, list[str]]:
    """The scan build's log, found from the build record the alert's error carries: (where, lines)."""
    build = (as_json((message.get("error") or {}).get("Cause", "")).get("Build")) or {}
    logs = build.get("Logs") or {}
    group, stream = logs.get("GroupName"), logs.get("StreamName")
    if not (group and stream) and build.get("Id"):        # the build ID is enough to find the log
        found = c.codebuild.batch_get_builds(ids=[build["Id"]])["builds"]
        logs = (found[0].get("logs") or {}) if found else {}
        group, stream = logs.get("groupName"), logs.get("streamName")
    if not (group and stream):
        return "no build log named in the alert", []
    lines, token = [], None
    while True:
        page = c.logs.get_log_events(logGroupName=group, logStreamName=stream, startFromHead=True,
                                     **({"nextToken": token} if token else {}))
        lines += [e["message"].rstrip() for e in page["events"]]
        if not page["events"] or page.get("nextForwardToken") == token:
            break
        token = page["nextForwardToken"]
    return f"{group} {stream}", lines


def nothing_made(c: Clients, s: Settings, p: Platform, agent: str) -> dict[str, list[str]]:
    """What exists for the agent of the kinds the review makes after Scan (MADE_BY_A_REVIEW): role, policies, target,
    Runtime."""
    found: dict[str, list[str]] = {}
    try:
        c.iam.get_role(RoleName=s.agent_role(agent))
        found["role"] = [s.agent_role(agent)]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
    tools = [f"{t}___{x['name']}" for t, xs in TARGETS.items() for x in xs]
    found["policies"] = sorted(set(policy_names(agent, tools)) & set(list_policies(c, p.engine_id)))
    found["target"] = [n for n in targets(c, p.agent_gw["id"]) if n == s.target_name(agent)]
    found["Runtime"] = [r["agentRuntimeName"] for r in all_items(c.ctl.list_agent_runtimes, maxResults=100)
                        if r["agentRuntimeName"] == s.runtime_name(agent)]          # every page: it asserts absence
    return {k: v for k, v in found.items() if v}


def scene_quality(c: Clients, s: Settings, p: Platform, dev: DevTeam, inbox: AlertInbox) -> None:
    after = time.time()
    code, _ = publish(dev, QUALITY, VULNERABLE)
    rid, status, _ = record_status(c, p, QUALITY)
    r = review(c, p, QUALITY, rid, after, n_start=None) if code == 0 and status == "PENDING_APPROVAL" else None
    if not r:
        check(8, "quality_agent v1-vulnerable fails at Scan with an alert", False,
              f"not run: publish exit {code}, record {status}, no review found")
        for n, name in ((9, "that submission made nothing"), (10, "reject.sh: REJECTED"),
                        (11, "the fixed version passes a new review"), (12, "quality_agent answers with both tools")):
            check(n, name, False, "not run: the vulnerable version was not reviewed")
        return
    d = r["execution"]
    at_scan = d["status"] == "FAILED" and r["steps"][:2] == STEPS[:2] and "Grant:lambda" not in r["steps"]
    envelope = inbox.wait(rid)
    message, agent, step = alert_parts(envelope) if envelope else ({}, "", "")
    where, lines = scan_log_lines(c, message) if envelope else ("no alert", [])
    advisory = next((line for line in lines if ADVISORY.search(line)), "")
    check(8, "quality_agent v1-vulnerable: FAILED at Scan; the alert names agent and step; the scan log has jinja2",
          at_scan and bool(envelope) and agent == QUALITY and step == "Scan" and bool(advisory),
          f"{d['status']}; steps {r['steps']}; alert {'received' if envelope else 'missing after %ds' % ALERT_WAIT}: "
          f"agent {agent or '-'}, step {step or '-'}; scan log {where}: {advisory.strip() or 'no jinja2 advisory line'}")
    if envelope:
        info("the alert's subject", envelope.get("Subject"))
        info("the alert's top-level keys", sorted(message))
        error = message.get("error") or {}
        build = as_json(error.get("Cause", "")).get("Build") or {}
        failed = [f"{ph.get('PhaseType')} {ph.get('PhaseStatus')} {[x.get('Message') for x in ph.get('Contexts') or []]}"
                  for ph in build.get("Phases") or [] if ph.get("PhaseStatus") == "FAILED"]
        info("the alert's error", f"{error.get('Error')}; its cause is the build record ({len(error.get('Cause', ''))} "
             f"characters, keys {sorted(as_json(error.get('Cause', '')))}): build {build.get('Id')} {build.get('BuildStatus')}, "
             f"failed phase {failed}, log {(build.get('Logs') or {}).get('GroupName')} {(build.get('Logs') or {}).get('StreamName')}")
    if not at_scan:
        info("why the vulnerable review did not stop at Scan", failure_of(r["events"]))

    left = nothing_made(c, s, p, QUALITY)
    control = nothing_made(c, s, p, RELEASE)       # the same look finds what a passed review made
    sees = sorted(control) == list(MADE_BY_A_REVIEW)
    check(9, "that submission made no role, policy, target or Runtime", not left and sees,
          f"found {left or 'nothing'} for {QUALITY}; the same look finds {sorted(control) or 'nothing'} for {RELEASE}")

    code, _ = run_command("reject.sh quality_agent (platform team)", [str(REJECT), QUALITY, REASON], dict(os.environ))
    _, status, reason = record_status(c, p, QUALITY)
    check(10, "reject.sh: the record is REJECTED", code == 0 and status == "REJECTED",
          f"reject.sh exit {code}; record {status} ({reason!r})")

    after = time.time()
    code, out = publish(dev, QUALITY)
    rid, status, _ = record_status(c, p, QUALITY)
    r = review(c, p, QUALITY, rid, after, n_start=None) if code == 0 and status == "PENDING_APPROVAL" else None
    d = r["execution"] if r else {}
    _, status_now, reason = record_status(c, p, QUALITY)
    passed = bool(r) and d["status"] == "SUCCEEDED" and r["steps"] == STEPS and status_now == "APPROVED"
    check(11, "the fixed version: a new review starts, SUCCEEDED, record APPROVED", passed,
          f"publish exit {code}, record {status} after publish; review "
          f"{d.get('status', 'not started') if r else 'not started within %ds' % START_WAIT}; record {status_now} ({reason})"
          + ("" if passed or not r else f"; {failure_of(r['events'])}"))
    if not (r and status_now == "APPROVED"):
        check(12, "quality_agent answers with both tools", False, "not run: quality_agent is not approved")
        return
    code, body, took = call_agent(s, p, QUALITY, QUESTION)
    answer = as_json(body)
    text, used = str(answer.get("answer", body)), answer.get("tools_used") or []
    has_data = PARTS["P-100"]["spec"].split(",")[0] in text and INSPECTIONS["Q-1001"]["result"] in text
    check(12, "quality_agent answers with both tools", code == 200 and set(QUALITY_TOOLS) <= set(used) and has_data,
          f"{code} in {took:.1f}s; tools {used}; answer {text[:400]!r}")
    ids = sorted(set(re.findall(r"EMP-\d+", text)))
    info("employee ID in quality_agent's answer", f"{ids} as the tool gave it (plan 2 masks it)" if ids else "none")


def observe_leftovers(c: Clients, s: Settings, p: Platform, agent: str) -> None:
    """Observation B: what a deploy leaves for one agent: its Runtime (ID, version, status), the workload identities
    and log groups named after the Runtime, and its code packages in the inbox. It only observes: an error is one
    more [INFO] line, and the checks' summary and exit code stay as they are."""
    try:
        _observe_leftovers(c, s, p, agent)
    except Exception as e:
        info("observation B stopped", error_of(e))


def _observe_leftovers(c: Clients, s: Settings, p: Platform, agent: str) -> None:
    name = s.runtime_name(agent)
    runtime = next((r for r in all_items(c.ctl.list_agent_runtimes, maxResults=100) if r["agentRuntimeName"] == name),
                   None)
    info(f"Runtime {name}", f"{runtime['agentRuntimeId']} version {runtime['agentRuntimeVersion']} {runtime['status']}"
         if runtime else "none")
    wis = [w["name"] for w in all_items(c.ctl.list_workload_identities, maxResults=20) if name in w["name"]]
    info(f"workload identities named after {name}", wis or "none")
    groups = [g["logGroupName"] for page in c.logs.get_paginator("describe_log_groups").paginate(
        logGroupNamePrefix=f"/aws/bedrock-agentcore/runtimes/{name}-") for g in page["logGroups"]]
    info(f"log groups of {name}", groups or "none")
    packages = [f"{o['Key']} ({o.get('Size', 0)} bytes)" for page in c.s3.get_paginator("list_object_versions").paginate(
        Bucket=p.bucket, Prefix=f"{PACKAGES}{agent}/") for o in page.get("Versions", [])]
    info(f"code packages of {agent} in the inbox", packages or "none")


# ================================================================== main

def main() -> int:
    global ACCOUNT
    # .env by the rule make and the two commands follow (README, ".env"); the commands this script runs inherit the
    # values chosen here and the mark that .env was read, so the checks and the commands use one hub.
    os.environ.update(env_file_updates(os.environ, REPO / ".env"))
    s = Settings.from_env()
    c = Clients.for_settings(s)
    ACCOUNT = c.account
    p = load(s, c)
    say(f"== e2e_hosting ({s.region}, prefix {s.prefix})")
    if not (p.machine_arn and p.bucket and p.registry_id and p.agent_gw.get("id") and p.dev_role_arn):
        say("[FAIL] 0 the hub is deployed: run `make deploy seed` first")
        return 1
    running = [e["name"] for e in c.sfn.list_executions(stateMachineArn=p.machine_arn, statusFilter="RUNNING")["executions"]]
    if running:
        say(f"[FAIL] 0 no review is running: {running} still running. Cleaning up now would race its steps: "
            "wait until it stops (Step Functions console), then start again")
        return 1
    t0 = time.monotonic()
    known_state(c, s, p)
    dev = DevTeam(c, s, p.dev_role_arn)
    inbox = AlertInbox(c, s, p.topic_arn)
    try:
        inbox.open()
        scene_search(dev, p)
        scene_dev_tools(dev, s, p)
        scene_release(c, s, p, dev)
        scene_quality(c, s, p, dev, inbox)
        observe_leftovers(c, s, p, QUALITY)
    finally:
        inbox.close()
    failed = [f"{n} {name}" for n, name, ok in RESULTS if not ok]
    say(f"== {len(RESULTS) - len(failed)} checks passed, {len(failed)} failed, {OBSERVED[0]} observations"
        + f" ({time.monotonic() - t0:.0f}s)" + (f": {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # a traceback could print the account ID: mask it
        say(f"ERROR {type(e).__name__}: {e}")
        failed = [f"{n} {name}" for n, name, ok in RESULTS if not ok]
        say(f"== {len(RESULTS) - len(failed)} checks passed, {len(failed) + 12 - len(RESULTS)} failed, "
            f"{OBSERVED[0]} observations (stopped by the error above)")
        sys.exit(1)
