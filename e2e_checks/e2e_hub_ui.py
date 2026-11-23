"""e2e_hub_ui.py - the hub screen (platform_team/hub_ui) from end to end against a deployed hub: its pages read live
values, and its buttons change the hub as the shell commands do.

    make e2e-ui        (the log goes to e2e_checks/last-run-ui.log)

It starts the screen as a child process (python -m platform_team.hub_ui on a free port of 127.0.0.1), reads its pages
and presses its buttons over HTTP as a browser does (an HTML form with the page token read from the page, and the
screen's own Origin), and stops the child at the end, also when a check fails. What it reads on a page it compares with
what boto3 returns in this script.

It starts on the hub make e2e-ops leaves: the four agents hosted and APPROVED (release_review, quality_agent, docs_adk,
spec_assistant), no company policy on, the custom guardrail detached, no agent stopped, no review running. Line 0 says
what is not so, and the script stops. Each check that changes the hub changes it back (the vulnerable version rejected
and the fixed one approved again, guard_prompt off, the guardrail detached, quality_agent resumed), so the script can
run again; when a check stops halfway, the end runs the repo's commands that undo what is left (rollout.sh guard_prompt
off, guardrail.sh detach, resume.sh).

Eight checks, one [PASS] / [FAIL] line each, [INFO] lines for what was observed, then
`== N checks passed, M failed, K observations (...s)`. Exit code 1 if a check failed.
   1  every page answers 200, holds the sample label and not the account ID (the time of each first read, with the
      cache of the screen run out, and of a second read right after it is an [INFO])
   2  the home page's counts and alarms are what the catalog and CloudWatch return, and its platform panel has its six
      parts, each with a state
   3  the review page shows quality_agent and release_review APPROVED, their latest review with seven passed steps, and
      each step's seconds as the execution history in Step Functions has them
   4  quality_agent v1-vulnerable: the page shows the review failed at Scan with at least one line of the scan's log; Reject
      with a reason: the record reads the status the job printed; the fixed version again: the page shows it APPROVED
   5  Turn on in log-only: the page and the policy engine read LOG_ONLY for every hosted Runtime agent, and after one
      hidden instruction to release_review the page's report counts a match; Enforce: ACTIVE; Turn off: no such policy
   6  Attach: the page and guardrail_attach.status read attached, and a request whose code name comes right after a line
      break is 403 by the interceptor; Detach: both read detached
   7  Stop quality_agent: the page shows it stopped, a call to it through the agent gateway is 403 and release_review
      answers 200; Resume: the page shows it running and a call to it is 200
   8  a second press while a job runs is refused: 303 with err=busy, and the page shows the sentence

E2E_UI_HOLD=<seconds> (default 0) leaves four pages as they are for that long before the next press (the failed review,
the report with its match, the guardrail attached, quality_agent stopped), so the screen can be looked at or recorded;
each hold is one [INFO] line with the page's path. publish.sh runs as the dev team role; every other call is the
shell's credentials, as is every read and button of the screen. Printed output masks the account ID.
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))           # run as a script, e2e_checks is imported from the repo root

import httpx                                                                     # noqa: E402

from e2e_checks import e2e_hosting as hosting                                   # noqa: E402
from e2e_checks import e2e_operations as ops                                    # noqa: E402
from e2e_checks.e2e_hosting import (QUALITY, RELEASE, VULNERABLE, DevTeam, call_agent, check, info,  # noqa: E402
                                    no_review_running, publish, record_status, review, say)
from platform_team.agent_catalog.catalog_records import records                 # noqa: E402
from platform_team.agent_monitoring import usage_report                         # noqa: E402
from platform_team.agent_stop import stop_agent                                 # noqa: E402
from platform_team.company_policy import policy_rollout                         # noqa: E402
from platform_team.company_policy.policy_engine import list_policies            # noqa: E402
from platform_team.company_policy.policy_names import KINDS, guard_prompt_name, stop_agent_name  # noqa: E402
from platform_team.custom_guardrail import guardrail_attach                     # noqa: E402
from platform_team.hub_ui.reviews import STEPS, scan_log                        # noqa: E402
from platform_team.hub_ui.texts import STRINGS                                  # noqa: E402
from platform_team.shared_code.aws_helpers import Clients                       # noqa: E402
from platform_team.shared_code.config import Settings, env_file_updates         # noqa: E402
from platform_team.shared_code.hub_state import NotDeployed, Platform, load     # noqa: E402

T = STRINGS["ko"]                       # the screen runs in Korean (HUB_UI_LANG=ko): the words the pages show
FOUR = ops.FOUR                         # the agents make e2e-ops leaves hosted
POLICY = "guard_prompt"
NAMES = [name for name, _ in STEPS]     # the seven steps of a review
REASON = "jinja2 2.11.2 has published advisories (hub screen check)"
# check 6: the code name right after a line break (the JSON body carries it as \n)
LINE_BREAK = "Summarise the schedule for part P-100.\nProject Falcon is the name of that schedule."
READY_WAIT = 60           # s, until the child answers
PAGE_GAP = 6              # s, before a page's first read: the screen keeps a read 5 s, so the first read is a new one
JOB_WAIT = 1200           # s, one job (a rollout waits up to 300 s per agent)
JOB_STEP = 2              # s, between two looks at a job
FINDINGS_WAIT = 120       # s, check 4: from the end of the review until a finding line shows on the page
REPORT_WAIT = 600         # s, check 5: from the hidden instruction until the page's report counts it
REPORT_STEP = 30          # s, between two reads of the report
STOP_WAIT = 60            # s, check 7: from the end of the stop job until a call is 403
CHANGE_WAIT = 120         # s, until a call shows what a press changed
CALL_STEP = 10            # s, between two calls that wait for a change
SLOW = 3.0                # s, a second read slower than this is told in its [INFO] line
HOLD = float(os.environ.get("E2E_UI_HOLD") or 0)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# ================================================================== reading a page (unit-tested)

class Node:
    """One element of a page: its tag, its attributes and what is inside it (elements and text, in page order)."""

    def __init__(self, tag: str, attrs: dict, parent: "Node | None" = None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        """The text inside, its runs of white space made one space."""
        parts: list[str] = []

        def walk(node):
            for child in node.children:
                parts.append(child) if isinstance(child, str) else walk(child)
        walk(self)
        return " ".join("".join(parts).split())

    def raw(self) -> str:
        """The text inside as the page has it (the lines of a <pre>)."""
        return "".join(child if isinstance(child, str) else child.raw() for child in self.children)

    def all(self, tag: str | None = None, cls: str | None = None, **attrs) -> list["Node"]:
        """Every element inside (at any depth, in page order) with this tag, class and attribute values."""
        found = []

        def walk(node):
            for child in node.children:
                if isinstance(child, Node):
                    if ((tag is None or child.tag == tag) and (cls is None or cls in child.classes)
                            and all(child.attrs.get(k.rstrip("_")) == v for k, v in attrs.items())):
                        found.append(child)
                    walk(child)
        walk(self)
        return found

    def first(self, tag: str | None = None, cls: str | None = None, **attrs) -> "Node | None":
        found = self.all(tag, cls, **attrs)
        return found[0] if found else None


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#page", {})
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v or "" for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, {k: v or "" for k, v in attrs}, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:               # an end tag with no open element of its name changes nothing
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def dom(html: str) -> Node:
    builder = _Builder()
    builder.feed(html or "")
    builder.close()
    return builder.root


def by_id(html: str | Node, element_id: str) -> Node | None:
    root = dom(html) if isinstance(html, str) else html
    return root.first(id=element_id)


def token_of(html: str) -> str:
    """The page token a form sends back: the meta element hub-token, else a form's hidden input token. ValueError when
    the page has neither."""
    root = dom(html)
    meta = root.first("meta", name="hub-token")
    if meta is not None and meta.attrs.get("content"):
        return meta.attrs["content"]
    field = root.first("input", name="token")
    if field is not None and field.attrs.get("value"):
        return field.attrs["value"]
    raise ValueError("no page token on the page (no meta hub-token, no input token)")


def account_free(html: str, account: str) -> bool:
    """Check 1: the account ID is nowhere in the page."""
    return bool(account) and account not in (html or "")


def job_of(html: str) -> tuple[str, str]:
    """(job ID, state) of the page's job panel; ("", "") when the page has none."""
    node = by_id(html, "panel-job")
    return (node.attrs.get("data-job", ""), node.attrs.get("data-state", "")) if node is not None else ("", "")


def sentence(html: str, element_id: str = "page-err") -> str:
    """The text of the page's red (page-err) or green (page-msg) sentence; "" when there is none."""
    node = by_id(html, element_id)
    return node.text() if node is not None else ""


def query_of(location: str) -> dict[str, str]:
    """The query of a redirect's Location, as a dict."""
    return dict(parse_qsl(urlsplit(location).query))


def _number(text: str) -> int | None:
    m = re.search(r"-?\d+", text or "")
    return int(m.group()) if m else None


def home_counts(html: str) -> dict[str, int | None]:
    """The home page's three counts, in the order the page shows them: hosted, in review, approved tools."""
    node = by_id(html, "panel-counts")
    nums = [_number(n.text()) for n in node.all("div", "num")] if node is not None else []
    return dict(zip(("hosted", "in_review", "tools"), nums))


def rows(node: Node | None) -> list[list[Node]]:
    """The cells of each row of the tables inside (tbody rows; header rows left out)."""
    if node is None:
        return []
    return [[cell for cell in tr.children if isinstance(cell, Node) and cell.tag == "td"]
            for body in node.all("tbody") for tr in body.all("tr")]


def home_alarms(html: str) -> dict[str, str]:
    """Alarm name -> state on the home page."""
    return {cells[0].text(): cells[1].text() for cells in rows(by_id(html, "panel-alarms")) if len(cells) >= 2}


def home_platform(html: str) -> list[dict]:
    """The home page's platform parts: [{"part", "name", "service", "state"}] (state: the text of its pill)."""
    return [{"part": cells[0].text(), "name": cells[1].text(), "service": cells[2].text(), "state": cells[3].text()}
            for cells in rows(by_id(html, "panel-platform")) if len(cells) >= 4]


def strip_of(node: Node | None) -> list[dict]:
    """A review's strip of steps: [{"name", "state" (passed, failed, running, waiting, skipped), "seconds"}]."""
    if node is None:
        return []
    out = []
    for li in node.all("li", "step"):
        name = li.first("span", "name")
        secs = li.first("span", "secs")
        out.append({"name": name.text() if name else "", "state": next(iter(li.classes - {"step"}), ""),
                    "seconds": _number(secs.text()) if secs else None})
    return out


def review_card(html: str, agent: str) -> dict | None:
    """An agent's card on the review list: {"status" (its record's), "review" (its latest review's status, "" when
    none), "steps" (strip_of), "error" (the failed step's line)}; None when the page has no card for it."""
    card = by_id(html, f"app-{agent}")
    if card is None:
        return None
    head = card.first("div", "app-head")
    pills = head.all("span", "pill") if head else []
    review = card.first("span", "app-review")
    review_pill = review.first("span", "pill") if review else None
    error = card.first("p", "err")
    return {"status": pills[0].text() if pills else "", "review": review_pill.text() if review_pill else "",
            "steps": strip_of(card.first("ol", "steps")), "error": error.text() if error else ""}


def review_detail(html: str) -> dict:
    """An agent's review page: {"status" (its record's), "review" (the execution's status), "steps", "failed" (the
    failed step's line), "findings" (the lines of the scan's log), "log" (where they come from), "can_reject"}."""
    root = dom(html)
    application, steps, findings = (by_id(root, k) for k in ("panel-application", "panel-steps", "panel-findings"))
    status = application.first("span", "pill") if application else None
    meta = steps.first("div", "review-meta") if steps else None
    execution = meta.first("span", "pill") if meta else None
    failed = steps.first("div", "review-error") if steps else None
    pre = findings.first("pre", "findings") if findings else None
    log = findings.first("p", "tech") if findings else None
    reject = by_id(root, "panel-reject")
    return {"status": status.text() if status else "", "review": execution.text() if execution else "",
            "steps": strip_of(steps.first("ol", "steps") if steps else None),
            "failed": failed.text() if failed else "",
            "findings": [line for line in (pre.raw() if pre else "").splitlines() if line.strip()],
            "log": log.text() if log else "",
            "can_reject": bool(reject and reject.first("form"))}


def policy_rows(html: str, gateway: str = "agent_gw") -> dict[str, dict]:
    """The policies a gateway's table shows: name -> {"status", "mode" (the raw enforcement mode)}."""
    out = {}
    for cells in rows(by_id(html, f"panel-gateway-{gateway}")):
        if len(cells) >= 4:
            raw = cells[3].all("span", "mono")
            out[cells[0].text()] = {"status": cells[2].text(), "mode": raw[-1].text() if raw else cells[3].text()}
    return out


def company_mode(html: str) -> str | None:
    """guard_prompt's mode on the policy page as it shows it raw (LOG_ONLY, ACTIVE), None when it shows it off."""
    node = by_id(html, "panel-company")
    cards = node.all("article") if node is not None else []
    card = next((a for a in cards if (a.first("h2") or Node("", {})).text() == POLICY), None)
    head = card.first("div", "policy-head") if card else None
    raw = head.all("span", "mono") if head else []
    return raw[-1].text() if raw else None


def mode_buttons(html: str) -> dict[str, bool]:
    """The mode buttons of guard_prompt: value -> whether it can be pressed (not disabled)."""
    node = by_id(html, "panel-company")
    return {b.attrs.get("value", ""): "disabled" not in b.attrs
            for b in (node.all("button", name="mode") if node is not None else [])}


def report_rows(html: str) -> dict[str, dict]:
    """The policy page's report: agent -> {"mode" (the word), "matches", "flips"}."""
    return {cells[0].text(): {"mode": cells[1].text(), "matches": _number(cells[2].text()),
                              "flips": _number(cells[3].text())}
            for cells in rows(by_id(html, "panel-report")) if len(cells) >= 4}


def guardrail_panel(html: str) -> dict:
    """The custom guardrail on the policy page: {"word" (attached or detached, as the page says it), "points", "press"
    (the path its one button posts to, "" when it has none)}."""
    node = by_id(html, "panel-guardrail")
    if node is None:
        return {"word": "", "points": [], "press": ""}
    dds = node.all("dd")
    form = node.first("form")
    return {"word": dds[0].text() if dds else "",
            "points": [s.text() for s in dds[1].all("span", "mono")] if len(dds) > 1 else [],
            "press": form.attrs.get("action", "") if form else ""}


def agent_row(html: str, agent: str) -> dict | None:
    """An agent's row on the agents page: {"stop" (the stop cell's text), "stopped" (True, False, None when unknown),
    "presses" (the paths of its buttons), "usage" (invocations, sessions, errors, vCPU-hours, GB-hours as text)};
    None when the page has no row for it."""
    tr = by_id(html, f"agent-{agent}")
    if tr is None:
        return None
    cells = [c for c in tr.children if isinstance(c, Node) and c.tag == "td"]
    stop = cells[5] if len(cells) > 5 else Node("", {})
    pill = stop.first("span", "pill")
    stopped = None if pill is None or not ({"bad", "ok"} & pill.classes) else "bad" in pill.classes
    usage = [c.text() for c in cells[6:11]] if len(cells) >= 12 else []
    return {"stop": stop.text(), "stopped": stopped, "presses": [f.attrs.get("action", "") for f in tr.all("form")],
            "usage": usage}


def alarm_panel(html: str) -> dict:
    """The agents page's alarm: {"state", "threshold", "tool", "bars" (the 15 values as the page writes them)}."""
    node = by_id(html, "panel-alarm")
    if node is None:
        return {}
    dds = node.all("dd")
    state = dds[0].first("span", "pill") if dds else None
    return {"state": state.text() if state else "", "threshold": dds[1].text() if len(dds) > 1 else "",
            "tool": dds[2].text() if len(dds) > 2 else "", "bars": [t.text() for t in node.all("text", "val")]}


# ================================================================== what boto3 gives, read (unit-tested)

def step_seconds(events: list[dict]) -> dict[str, int]:
    """The seconds of each step that passed, from the execution's history alone: its state's entered event to its
    exited event (GetExecutionHistory), for the seven steps of the review."""
    entered, out = {}, {}
    for e in sorted(events, key=lambda e: e.get("id") or 0):
        details = next((v for k, v in e.items() if k.endswith("EventDetails") and isinstance(v, dict)), {})
        name = details.get("name")
        if name not in NAMES:
            continue
        if e["type"].endswith("StateEntered"):
            entered[name] = e["timestamp"]
        elif e["type"].endswith("StateExited") and name in entered:
            out[name] = round((e["timestamp"] - entered[name]).total_seconds())
    return out


def after_state(events: list[dict], state: str) -> list[str]:
    """The types of the history's events from the entry of `state` on (to see what AWS writes for a failed step)."""
    ordered = sorted(events, key=lambda e: e.get("id") or 0)
    start = next((i for i, e in enumerate(ordered) if e["type"].endswith("StateEntered")
                  and (e.get("stateEnteredEventDetails") or {}).get("name") == state), None)
    return [] if start is None else [e["type"] for e in ordered[start:]]


def start_refusal(state: dict) -> str:
    """Line 0: "" when the hub is as make e2e-ops leaves it (state: "hosted" [agents], "records" {agent: status},
    "mode" (guard_prompt's in SSM, None when off), "policies" [guard_prompt_* policies], "attached" (the custom
    guardrail), "stopped" [agents]), else what is not so and how to get there."""
    wrong = []
    missing = [a for a in FOUR if a not in state["hosted"]]
    if missing:
        wrong.append(f"not hosted: {', '.join(missing)}")
    left = [f"{a} {state['records'].get(a, 'absent')}" for a in FOUR if state["records"].get(a) != "APPROVED"]
    if left:
        wrong.append(f"records not APPROVED: {', '.join(left)}")
    if state["mode"] or state["policies"]:
        wrong.append(f"{POLICY} is on ({state['mode'] or 'no SSM value'}; policies {state['policies'] or 'none'})")
    if state["attached"]:
        wrong.append("the custom guardrail is attached")
    if state["stopped"]:
        wrong.append(f"stopped: {', '.join(state['stopped'])}")
    if not wrong:
        return ""
    return (f"[FAIL] 0 the hub is as make e2e-ops leaves it: {'; '.join(wrong)}: run `make e2e-ops` first (it ends "
            f"with guard_prompt off, the guardrail detached and nothing stopped)")


# ================================================================== the screen as a child process

def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Screen:
    """The hub screen run as a child process, read and pressed over HTTP. Its output goes to a temporary file, shown
    masked at the end."""

    def __init__(self, port: int):
        self.port, self.base = port, f"http://127.0.0.1:{port}"
        self.out = tempfile.TemporaryFile(mode="w+")
        self.proc = subprocess.Popen([sys.executable, "-m", "platform_team.hub_ui"], cwd=REPO, stdout=self.out,
                                     stderr=subprocess.STDOUT,
                                     env={**os.environ, "HUB_UI_PORT": str(port), "HUB_UI_LANG": "ko"})
        self.http = httpx.Client(base_url=self.base, timeout=300, follow_redirects=False)
        self.token = ""

    def ready(self, wait: float = READY_WAIT) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            if self.proc.poll() is not None:
                return False
            try:
                self.http.get("/static/none", timeout=5)
                return True
            except httpx.HTTPError:
                time.sleep(0.5)
        return False

    def get(self, path: str) -> tuple[int, str, float]:
        """GET a page: its status, its body and the seconds it took. The page token is kept for the next press."""
        t0 = time.monotonic()
        r = self.http.get(path)
        took = time.monotonic() - t0
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            try:
                self.token = token_of(r.text)
            except ValueError:
                pass
        return r.status_code, r.text, took

    def press(self, path: str, on: str, **form) -> tuple[int, str]:
        """POST a button's form as the browser sends it from the page `on`: the token, the screen's Origin and the page
        as Referer. Returns the status and the Location."""
        if not self.token:
            self.get(on)
        r = self.http.post(path, data={"token": self.token, **form},
                           headers={"Origin": self.base, "Referer": self.base + on})
        return r.status_code, r.headers.get("location", "")

    def job(self, job_id: str) -> dict:
        r = self.http.get(f"/jobs/{job_id}")
        return r.json() if r.status_code == 200 else {"state": f"HTTP {r.status_code}", "lines": [], "error": ""}

    def wait_job(self, job_id: str, wait: float = JOB_WAIT) -> dict:
        t0 = time.monotonic()
        while True:
            job = self.job(job_id)
            if job.get("state") != "running" or time.monotonic() - t0 > wait:
                return {**job, "seconds": time.monotonic() - t0}
            time.sleep(JOB_STEP)

    def run(self, path: str, on: str, **form) -> dict:
        """Press a button and wait for its job: {"status", "location", "job" (its state, lines, error, seconds)}."""
        status, location = self.press(path, on, **form)
        out = {"status": status, "location": location, "job": {}}
        if status == 303 and query_of(location).get("msg") == "started":
            _, html, _ = self.get(location)
            job_id, _ = job_of(html)
            out["job"] = self.wait_job(job_id) if job_id else {"state": "no job on the page"}
        return out

    def stop(self) -> list[str]:
        """Stop the child (and wait for it); its output lines."""
        self.http.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(15)
        self.out.seek(0)
        lines = [line.rstrip() for line in self.out.read().splitlines() if line.strip()]
        self.out.close()
        return lines


def hold(what: str, path: str) -> None:
    """E2E_UI_HOLD: leave the page as it is for that long before the next press."""
    if HOLD > 0:
        info("hold", f"{HOLD:.0f}s on {path} ({what})")
        time.sleep(HOLD)


def job_line(run: dict) -> str:
    job = run["job"]
    return (f"press {run['status']} {run['location']}; job {job.get('state')} in {job.get('seconds', 0):.0f}s"
            + (f", error {job['error']!r}" if job.get("error") else "") + f": {' | '.join(job.get('lines', []))[-600:]}")


def until(s: Settings, p: Platform, agent: str, prompt: str, want: int, wait: float) -> tuple[int, str, float]:
    """Call the agent through the agent gateway every CALL_STEP seconds until its status is `want` or `wait` seconds
    have passed: the last status, its body, the seconds from the first call to the last."""
    t0 = time.monotonic()
    while True:
        code, body, _ = call_agent(s, p, agent, prompt, tries=1)
        if code == want or time.monotonic() - t0 >= wait:
            return code, body, time.monotonic() - t0
        time.sleep(CALL_STEP)


# ================================================================== the scenes

class Run:
    def __init__(self, c: Clients, s: Settings, p: Platform, screen: Screen):
        self.c, self.s, self.p, self.screen = c, s, p, screen
        self.dev = DevTeam(c, s, p.dev_role_arn)
        self.busy: dict | None = None          # check 8, seen during check 5's first press


def agent_records(o: Run) -> list[str]:
    return sorted(name for name, r in records(o.c, o.p.registry_id).items() if r.get("recordType") == "AGENT")


def scene_pages(o: Run) -> None:
    pages = ["/", "/reviews", *[f"/reviews/{a}" for a in agent_records(o)], "/policies", "/agents"]
    bad, times, kept = [], [], {}
    for path in pages:
        time.sleep(PAGE_GAP)
        code1, html1, t1 = o.screen.get(path)
        code2, html2, t2 = o.screen.get(path)
        kept[path] = html2
        times.append(f"{path} {t1:.1f}s/{t2:.1f}s")
        for code, html, n in ((code1, html1, "first"), (code2, html2, "second")):
            if code != 200 or T["sample"] not in html or not account_free(html, o.c.account):
                bad.append(f"{path} ({n} read): {code}, sample label {T['sample'] in html}, "
                           f"account {'absent' if account_free(html, o.c.account) else 'PRESENT'}")
        if t2 > SLOW:
            info("a slow second read", f"{path}: {t2:.1f}s (more than {SLOW:.0f}s)")
    check(1, "every page answers 200 with the sample label and without the account ID", not bad,
          f"{len(pages)} pages, each read twice; {'; '.join(bad) if bad else 'all 200, label there, no account ID'}")
    info("page times (first read with the screen's cache run out / second read right after)", ", ".join(times))
    info("home: the platform panel", home_platform(kept["/"]))
    agents_page = kept["/agents"]
    info("agents: the rows (stop state; invocations, sessions, errors, vCPU-hours, GB-hours in the last 60 minutes)",
         {a: (r["stop"], r["usage"]) for a in FOUR if (r := agent_row(agents_page, a))})
    info("agents: the alarm panel", alarm_panel(agents_page))
    tools = by_id(agents_page, "panel-tools")
    info("agents: the calls per tool", [cells[0].text() + " " + cells[1].text() for cells in rows(tools)])


def scene_home(o: Run) -> None:
    def truth() -> tuple[dict, dict]:
        recs = records(o.c, o.p.registry_id).values()

        def n(kind, status):
            return sum(1 for r in recs if r.get("recordType") == kind and r.get("status") == status)
        alarms = {a["AlarmName"]: a["StateValue"] for pg in o.c.cw.get_paginator("describe_alarms").paginate(
            AlarmNamePrefix=f"{o.s.prefix}-") for a in pg.get("MetricAlarms", [])}
        return {"hosted": n("AGENT", "APPROVED"), "in_review": n("AGENT", "PENDING_APPROVAL"),
                "tools": n("MCP", "APPROVED")}, alarms
    before = truth()
    time.sleep(PAGE_GAP)
    code, html, _ = o.screen.get("/")
    after = truth()
    counts, alarms, parts = home_counts(html), home_alarms(html), home_platform(html)
    same = any(counts == t[0] and alarms == t[1] for t in (before, after))
    parts_ok = len(parts) == 6 and all(p["state"] and p["state"] != T["part.missing"] for p in parts)
    check(2, "the home counts and alarms are what boto3 returns, and the platform panel has six parts with a state",
          code == 200 and same and parts_ok,
          f"page counts {counts}, alarms {alarms}; boto3 counts {after[0]}, alarms {after[1]}"
          + ("" if before == after else f" (before the page: {before[0]}, {before[1]})")
          + f"; platform parts {[(p['part'], p['state']) for p in parts]}")


def latest_execution(o: Run, agent: str) -> dict | None:
    """The newest execution of the review state machine for the agent's record (boto3, newest first)."""
    rid = records(o.c, o.p.registry_id).get(agent, {}).get("recordId")
    listed = o.c.sfn.list_executions(stateMachineArn=o.p.machine_arn, maxResults=50)["executions"]
    for e in sorted(listed, key=lambda e: e["startDate"], reverse=True):
        doc = hosting.as_json(o.c.sfn.describe_execution(executionArn=e["executionArn"]).get("input") or "")
        if (doc.get("detail") or {}).get("registryRecordId") == rid:
            return e
    return None


def approved_card(o: Run, html: str, agent: str) -> tuple[bool, str]:
    """Whether the agent's card shows it APPROVED with its latest review SUCCEEDED and seven passed steps whose
    seconds are the history's (±1 s); and the line that says what the page and the history show."""
    card = review_card(html, agent) or {}
    steps = card.get("steps", [])
    e = latest_execution(o, agent)
    truth = step_seconds(hosting.history(o.c, e["executionArn"])) if e else {}
    page = {row["name"]: row["seconds"] for row in steps}
    agree = len(truth) == 7 and all(page.get(n) is not None and abs(page[n] - truth[n]) <= 1 for n in NAMES)
    ok = (card.get("status") == "APPROVED" and card.get("review") == "SUCCEEDED"
          and [r["name"] for r in steps] == NAMES and all(r["state"] == "passed" for r in steps) and agree)
    return ok, (f"{agent}: record {card.get('status') or '-'}, review {card.get('review') or '-'}, steps "
                f"{[(r['name'], r['state'], r['seconds']) for r in steps]}; execution {e['name'] if e else 'none'} "
                f"history seconds {truth}")


def scene_reviews(o: Run) -> None:
    time.sleep(PAGE_GAP)
    code, html, _ = o.screen.get("/reviews")
    results = [approved_card(o, html, agent) for agent in (QUALITY, RELEASE)]
    check(3, "the review page shows quality_agent and release_review APPROVED with seven passed steps, their seconds "
          "as the execution history has them", code == 200 and all(ok for ok, _ in results),
          "; ".join(line for _, line in results))


def scan_facts(o: Run, events: list[dict], execution: dict) -> None:
    """What AWS wrote for the failed Scan: the events from Scan's entry on, the failure's cause, whether Scan has an
    exit event, and how long after the build's end the last line of its log arrived."""
    kinds = after_state(events, "Scan")
    failed = next((e for e in events if e["type"] == "TaskFailed"), None)
    details = (failed or {}).get("taskFailedEventDetails") or {}
    cause = hosting.as_json(details.get("cause") or "")
    build = cause.get("Build") or {}
    info("the failed Scan in the execution history",
         f"events from Scan on: {kinds}; Scan exited event: {'TaskStateExited' in kinds}; TaskFailed error "
         f"{details.get('error')!r}, cause {len(details.get('cause') or '')} characters, keys {sorted(cause)}, Build keys "
         f"{sorted(build)[:40]}, Logs {sorted(build.get('Logs') or {})}")
    where = scan_log(events)
    if not where or not build.get("Id"):
        info("the scan build's log", "no log or build named in the cause")
        return
    end = (o.c.codebuild.batch_get_builds(ids=[build["Id"]])["builds"] or [{}])[0].get("endTime")
    last = o.c.logs.get_log_events(logGroupName=where[0], logStreamName=where[1], limit=5,
                                   startFromHead=False).get("events", [])
    if end and last:
        at, ingested = last[-1]["timestamp"] / 1000, last[-1]["ingestionTime"] / 1000
        info("the scan build's last log line", f"written {at - end.timestamp():+.1f}s and taken in by CloudWatch Logs "
             f"{ingested - end.timestamp():+.1f}s from the build's end; the execution stopped "
             f"{execution['stopDate'].timestamp() - end.timestamp():+.1f}s from it: {last[-1]['message'].strip()[:160]!r}")


def scene_reject(o: Run) -> None:
    name = ("quality_agent v1-vulnerable: the page shows the review failed at Scan with a finding line; Reject: the "
            "record reads the job's status; the fixed version: the page shows it APPROVED")
    path = f"/reviews/{QUALITY}"
    after = time.time()
    code, _ = publish(o.dev, QUALITY, VULNERABLE)
    rid, status, _ = record_status(o.c, o.p, QUALITY)
    r = review(o.c, o.p, QUALITY, rid, after, n_start=None) if code == 0 and status == "PENDING_APPROVAL" else None
    if not r or r["execution"]["status"] != "FAILED":
        check(4, name, False, f"publish exit {code}, record {status}; review "
              f"{r['execution']['status'] if r else 'not found'}")
        return
    observe = ops.observe
    observe("the failed Scan", lambda: scan_facts(o, r["events"], r["execution"]))
    t0, detail = time.monotonic(), {}
    while True:                 # the build's last log lines may still be on their way: the page reads again
        _, html, _ = o.screen.get(path)
        detail = review_detail(html)
        if detail["findings"] or time.monotonic() - t0 > FINDINGS_WAIT:
            break
        time.sleep(5)
    shown = time.monotonic() - t0
    scan = next((row for row in detail["steps"] if row["name"] == "Scan"), {})
    at_scan = (detail["review"] == "FAILED" and scan.get("state") == "failed" and "Scan" in detail["failed"]
               and bool(detail["findings"]))
    truth = r["execution"]["stopDate"] - r["execution"]["startDate"]
    info("the failed review on the page", f"execution {detail['review']}, steps "
         f"{[(row['name'], row['state'], row['seconds']) for row in detail['steps']]} (the execution took "
         f"{truth.total_seconds():.0f}s); failed line {detail['failed'][:300]!r}; {len(detail['findings'])} finding "
         f"lines, shown {shown:.0f}s after the review's end was seen: {detail['findings'][:3]}; log {detail['log']}")
    hold("the failed review", path)
    rejected = o.screen.run(f"{path}/reject", path, reason=REASON) if detail["can_reject"] else None
    said = next((m.group(1) for line in (rejected or {}).get("job", {}).get("lines", [])
                 if (m := re.match(rf"^record {QUALITY}: (\w+)$", line))), "")
    _, status, reason = record_status(o.c, o.p, QUALITY)
    info("Reject on the screen", job_line(rejected) if rejected else "no Reject form on the page")
    rejected_ok = bool(rejected) and rejected["job"].get("state") == "done" and said == status and reason == REASON
    info("the record after Reject", f"the job said {said or '-'}, boto3 reads {status} ({reason!r}); the note: "
         f"{next((x for x in (rejected or {}).get('job', {}).get('lines', []) if ' is there: ' in x), 'none')!r}")
    after = time.time()
    code, _ = publish(o.dev, QUALITY)
    rid, status, _ = record_status(o.c, o.p, QUALITY)
    r2 = review(o.c, o.p, QUALITY, rid, after, n_start=None) if code == 0 and status == "PENDING_APPROVAL" else None
    time.sleep(PAGE_GAP)
    _, html, _ = o.screen.get("/reviews")
    approved, line = approved_card(o, html, QUALITY)
    check(4, name, at_scan and rejected_ok and bool(r2) and approved,
          f"failed at Scan on the page {at_scan} ({len(detail['findings'])} finding lines); Reject job "
          f"{(rejected or {}).get('job', {}).get('state', 'not pressed')}, it said {said or '-'}, the record "
          f"{'reads the same' if rejected_ok else 'differs'}; the fixed version: publish exit {code}, review "
          f"{r2['execution']['status'] if r2 else 'not found'}; {line}")


def _modes(o: Run, html: str, agents: list[str]) -> tuple[dict, dict]:
    """agent -> the enforcement mode of its guard_prompt policy, as the page shows it and as ListPolicies gives it
    (None: no such policy; an item without the mode is ACTIVE, as the service model says)."""
    page = policy_rows(html)
    engine = list_policies(o.c, o.p.engine_id)
    return ({a: (page.get(guard_prompt_name(a)) or {}).get("mode") for a in agents},
            {a: engine[guard_prompt_name(a)].get("enforcementMode", "ACTIVE") if guard_prompt_name(a) in engine
             else None for a in agents})


def scene_policies(o: Run) -> None:
    name = ("Turn on in log-only: the page and the policy engine read LOG_ONLY, and the report counts a match; Enforce: "
            "ACTIVE; Turn off: no policy")
    path, press = "/policies", f"/policies/{POLICY}/mode"
    agents = policy_rollout.hosted_agents(o.c, o.s, o.p)
    _, html, _ = o.screen.get(path)
    buttons = mode_buttons(html)
    status, location = o.screen.press(press, path, mode="log-only")
    second = o.screen.press(press, path, mode="log-only")              # check 8: while the first job runs
    _, refused, _ = o.screen.get(second[1]) if second[0] == 303 else (0, "", 0)
    o.busy = {"status": second[0], "location": second[1], "sentence": sentence(refused)}
    _, started, _ = o.screen.get(location) if status == 303 else (0, "", 0)
    job_id, _ = job_of(started)
    job = o.screen.wait_job(job_id) if job_id else {"state": "no job"}
    if query_of(second[1]).get("msg") == "started":                     # not refused: wait for that job too
        o.screen.wait_job(job_of(refused)[0])
    info("Turn on in log-only", job_line({"status": status, "location": location, "job": job}))
    _, html, _ = o.screen.get(path)
    page, engine = _modes(o, html, agents)
    log_only = (buttons.get("log-only") and job.get("state") == "done" and company_mode(html) == "LOG_ONLY"
                and all(page[a] == "LOG_ONLY" == engine[a] for a in agents))
    hidden_at = time.time()
    code, body, _ = call_agent(o.s, o.p, RELEASE, ops.HIDDEN, tries=1)
    polls, report = [], {}
    while True:
        time.sleep(REPORT_STEP)
        _, html_report, _ = o.screen.get(path)
        report = report_rows(html_report)
        matches = (report.get(RELEASE) or {}).get("matches") or 0
        polls.append(f"{time.time() - hidden_at:.0f}s {matches}")
        if matches >= 1 or time.time() - hidden_at > REPORT_WAIT:
            break
    counted = ((report.get(RELEASE) or {}).get("matches") or 0) >= 1
    info("the report on the page after one hidden instruction", f"release_review answered {code}; matches by seconds "
         f"after the request {polls}; the report {report}")
    if counted:
        hold("log-only with a match", path)
    enforced = o.screen.run(press, path, mode="active")
    _, html, _ = o.screen.get(path)
    page_a, engine_a = _modes(o, html, agents)
    active = (enforced["job"].get("state") == "done" and company_mode(html) == "ACTIVE"
              and all(page_a[a] == "ACTIVE" == engine_a[a] for a in agents))
    info("Enforce", job_line(enforced))
    off = o.screen.run(press, path, mode="off")
    _, html, _ = o.screen.get(path)
    left_page = sorted(n for n in policy_rows(html) if n.startswith(KINDS[POLICY]))
    left_engine = sorted(n for n in list_policies(o.c, o.p.engine_id) if n.startswith(KINDS[POLICY]))
    mode_now = policy_rollout.deployed(o.c, o.s).get(POLICY)
    gone = (off["job"].get("state") == "done" and company_mode(html) is None and not left_page and not left_engine
            and mode_now is None)
    info("Turn off", job_line(off))
    check(5, name, log_only and counted and active and gone,
          f"agents {agents}; log-only: page {page}, engine {engine}; report match {counted}; active: page {page_a}, "
          f"engine {engine_a}; off: policies on the page {left_page or 'none'}, in the engine {left_engine or 'none'}, "
          f"SSM {mode_now or 'none'}")


def scene_guardrail(o: Run) -> None:
    name = ("Attach: the page and guardrail_attach.status read attached, a code name after a line break is 403 by the "
            "interceptor; Detach: both read detached")
    path = "/policies"
    _, html, _ = o.screen.get(path)
    press = guardrail_panel(html)["press"]
    attached = o.screen.run(press, path) if press == "/guardrail/attach" else None
    info("Attach", job_line(attached) if attached else f"the page offers {press or 'no button'}")
    _, html, _ = o.screen.get(path)
    on_page, status = guardrail_panel(html), guardrail_attach.status(o.c, o.s, o.p)
    code, body, waited = until(o.s, o.p, QUALITY, LINE_BREAK, 403, CHANGE_WAIT)
    blocked = code == 403 and ops.BLOCKED_BY in body
    info("a code name right after a line break, to quality_agent", f"{code} after {waited:.0f}s: {body[:200]}")
    if blocked:
        hold("the guardrail attached", path)
    detached = o.screen.run(on_page["press"], path) if on_page["press"] == "/guardrail/detach" else None
    info("Detach", job_line(detached) if detached else f"the page offers {on_page['press'] or 'no button'}")
    _, html, _ = o.screen.get(path)
    off_page, off_status = guardrail_panel(html), guardrail_attach.status(o.c, o.s, o.p)
    ok = (bool(attached) and attached["job"].get("state") == "done" and on_page["word"] == T["guardrail.attached"]
          and status["attached"] and blocked and bool(detached) and detached["job"].get("state") == "done"
          and off_page["word"] == T["guardrail.detached"] and not off_status["attached"])
    check(6, name, ok,
          f"attached: page {on_page['word']!r} at {on_page['points']}, status {status['attached']} at {status['points']}; "
          f"line-break request {code}{' by the interceptor' if blocked else ''}; detached: page {off_page['word']!r}, "
          f"status {off_status['attached']}")


def scene_stop(o: Run) -> None:
    name = ("Stop quality_agent: the page shows it stopped, its call is 403 and release_review's 200; Resume: the page "
            "shows it running and its call is 200")
    path = "/agents"
    _, html, _ = o.screen.get(path)
    row = agent_row(html, QUALITY) or {}
    stop_path = f"/agents/{QUALITY}/stop"
    stopped = o.screen.run(stop_path, path) if stop_path in row.get("presses", []) else None
    info("Stop", job_line(stopped) if stopped else f"the row offers {row.get('presses')}")
    _, html, _ = o.screen.get(path)
    row_stopped = agent_row(html, QUALITY) or {}
    code_q, body_q, waited = until(o.s, o.p, QUALITY, ops.NORMAL, 403, STOP_WAIT)
    code_r = call_agent(o.s, o.p, RELEASE, ops.NORMAL)[0]
    stop_ok = (bool(stopped) and stopped["job"].get("state") == "done" and row_stopped.get("stopped") is True
               and code_q == 403 and stop_agent_name(QUALITY) in body_q and code_r == 200)
    if stop_ok:
        hold("quality_agent stopped", path)
    resume_path = f"/agents/{QUALITY}/resume"
    resumed = o.screen.run(resume_path, path) if resume_path in row_stopped.get("presses", []) else None
    info("Resume", job_line(resumed) if resumed else f"the row offers {row_stopped.get('presses')}")
    _, html, _ = o.screen.get(path)
    row_resumed = agent_row(html, QUALITY) or {}
    code_after, body_after, waited_after = until(o.s, o.p, QUALITY, ops.NORMAL, 200, CHANGE_WAIT)
    resume_ok = (bool(resumed) and resumed["job"].get("state") == "done" and row_resumed.get("stopped") is False
                 and code_after == 200)
    check(7, name, stop_ok and resume_ok,
          f"stopped: row {row_stopped.get('stop')!r}, quality_agent {code_q} after {waited:.0f}s: {body_q[:120]}; "
          f"release_review {code_r}; resumed: row {row_resumed.get('stop')!r}, quality_agent {code_after} after "
          f"{waited_after:.0f}s")


def scene_busy(o: Run) -> None:
    busy = o.busy
    if busy is None:
        check(8, "a second press while a job runs is refused with the sentence", False, "not run: check 5 did not press")
        return
    refused = busy["status"] == 303 and query_of(busy["location"]).get("err") == "busy"
    check(8, "a second press while a job runs is refused with the sentence",
          refused and busy["sentence"] == T["err.busy"],
          f"the second press of Turn on in log-only: {busy['status']} {busy['location']}; the page says "
          f"{busy['sentence']!r}")


# ================================================================== start and end

def hub_state(c: Clients, s: Settings, p: Platform) -> dict:
    """What line 0 and the end look at (start_refusal)."""
    hosted = sorted(usage_report.hosted_agents(c, s))
    recs = records(c, p.registry_id)
    runtime_agents = policy_rollout.hosted_agents(c, s, p)
    return {"hosted": hosted, "records": {a: recs[a]["status"] for a in FOUR if a in recs},
            "mode": policy_rollout.deployed(c, s).get(POLICY),
            "policies": sorted(n for n in list_policies(c, p.engine_id) if n.startswith(KINDS[POLICY])),
            "attached": guardrail_attach.status(c, s, p)["attached"],
            "stopped": [a for a in runtime_agents if stop_agent.stopped(c, p, a)]}


def leave_as_found(c: Clients, s: Settings, p: Platform) -> None:
    """Undo, with the repo's commands, what a check that stopped halfway left: guard_prompt on, the guardrail attached,
    an agent stopped. Nothing left: nothing runs."""
    state = hub_state(c, s, p)
    if state["mode"] or state["policies"]:
        ops.run(f"rollout.sh {POLICY} off (left on by a check)", [ops.ROLLOUT, POLICY, "off"])
    if state["attached"]:
        ops.run("guardrail.sh detach (left attached by a check)", [ops.GUARDRAIL, "detach"])
    for agent in state["stopped"]:
        ops.run(f"resume.sh {agent} (left stopped by a check)", [ops.RESUME, agent])
    info("the hub at the end (before the undo, if any)", state)


def main() -> int:
    # .env by the rule make and the commands follow (README, ".env"); the screen and the commands inherit the values
    os.environ.update(env_file_updates(os.environ, REPO / ".env"))
    s = Settings.from_env()
    c = Clients.for_settings(s)
    hosting.ACCOUNT = c.account
    say(f"== e2e_hub_ui ({s.region}, prefix {s.prefix})")
    try:
        p = load(s, c)
    except NotDeployed:
        say("[FAIL] 0 the hub is deployed: nothing under the platform values: run `make deploy seed e2e e2e-ops` first")
        return 1
    if not no_review_running(c.sfn, p.machine_arn, say, time.sleep, time.monotonic):
        return 1
    refusal = start_refusal(hub_state(c, s, p))
    if refusal:
        say(refusal)
        return 1
    t0 = time.monotonic()
    screen = Screen(free_port())
    try:
        if not screen.ready():
            say(f"[FAIL] 0 the hub screen answers: no answer from {screen.base} within {READY_WAIT}s")
            return 1
        info("the hub screen", f"{screen.base} (python -m platform_team.hub_ui, pid {screen.proc.pid})")
        o = Run(c, s, p, screen)
        ops.guarded(1, lambda: scene_pages(o))
        ops.guarded(2, lambda: scene_home(o))
        ops.guarded(3, lambda: scene_reviews(o))
        ops.guarded(4, lambda: scene_reject(o))
        ops.guarded(5, lambda: scene_policies(o))
        ops.guarded(6, lambda: scene_guardrail(o))
        ops.guarded(7, lambda: scene_stop(o))
        ops.guarded(8, lambda: scene_busy(o))
    finally:
        lines = screen.stop()
        info("the hub screen stopped", f"exit {screen.proc.returncode}; its output: {' | '.join(lines)[-800:] or 'none'}")
        ops.observe("the hub at the end", lambda: leave_as_found(c, s, p))
    failed = [f"{n} {name}" for n, name, ok in hosting.RESULTS if not ok]
    say(f"== {len(hosting.RESULTS) - len(failed)} checks passed, {len(failed)} failed, {hosting.OBSERVED[0]} "
        f"observations ({time.monotonic() - t0:.0f}s)" + (f": {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # a traceback could print the account ID: mask it
        say(f"ERROR {type(e).__name__}: {e}")
        failed = [f"{n} {name}" for n, name, ok in hosting.RESULTS if not ok]
        say(f"== {len(hosting.RESULTS) - len(failed)} checks passed, {len(failed) + 8 - len(hosting.RESULTS)} failed, "
            f"{hosting.OBSERVED[0]} observations (stopped by the error above)")
        sys.exit(1)
