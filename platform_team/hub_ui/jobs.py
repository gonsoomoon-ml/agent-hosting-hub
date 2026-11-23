"""The screen's background jobs. A button starts a job: the same function its shell command calls, run in a thread,
so the page answers at once and shows what the function says while it runs. One job at a time: a second start while
one runs raises Busy. The jobs live in memory and are gone when the app stops."""
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from platform_team.hosting_review.agent_cleanup import cause

RUNNING, DONE, FAILED = "running", "done", "failed"


class Busy(RuntimeError):
    """A job runs already; the screen starts one at a time."""


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Job:
    id: str
    kind: str                               # what the button does: reject, rollout, guardrail, stop, resume, ...
    target: str                             # what it does it to: an agent, a policy, attach or detach
    state: str = RUNNING
    lines: list[str] = field(default_factory=list)
    result: dict | None = None              # what the function returned
    error: str = ""                         # the exception it raised, as one line with the account masked
    started: datetime = field(default_factory=_now)
    ended: datetime | None = None
    _finished: threading.Event = field(default_factory=threading.Event, repr=False)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until the job has ended (and the cache is cleared). False if it still runs after `timeout` s."""
        return self._finished.wait(timeout)


class Jobs:
    """The jobs of this app. `on_end` runs when a job ends, before its state shows it (the screen clears its cache
    there, so the page that reloads after the job reads AWS again)."""

    def __init__(self, on_end: Callable[[], None] = lambda: None):
        self._on_end = on_end
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._last: Job | None = None

    def start(self, kind: str, target: str, run: Callable[[Callable[[str], None]], dict | None]) -> Job:
        """Run `run(say)` in a thread; each say(line) adds a line to the job. Busy while another job runs."""
        with self._lock:
            if self._last is not None and self._last.state == RUNNING:
                raise Busy(f"{self._last.kind} {self._last.target} is still running")
            job = Job(id=secrets.token_hex(8), kind=kind, target=target)
            self._jobs[job.id] = job
            self._last = job
        threading.Thread(target=self._run, args=(job, run), name=f"hub-job-{job.id}", daemon=True).start()
        return job

    def _run(self, job: Job, run) -> None:
        # Whatever the function raises ends the job, SystemExit too, so the slot is never held for ever. Ctrl+C
        # (KeyboardInterrupt) goes to the main thread only, not to this one.
        try:
            result, state, error = run(lambda line: job.lines.append(str(line))), DONE, ""
        except BaseException as e:
            result, state, error = None, FAILED, cause(e)
        try:
            self._on_end()
        finally:
            job.result, job.error, job.ended = result, error, _now()
            job.state = state               # last: a page that sees the job ended reads the cleared cache
            job._finished.set()

    def current(self) -> Job | None:
        """The running job, else the last one (None before the first)."""
        return self._last

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)
