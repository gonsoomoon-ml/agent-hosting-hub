"""The hub screen's background jobs: one at a time, what the function says is kept line by line, a failure is one
masked line, and a finished job makes the next read load again. The screen's reads go through a short cache."""
import threading

import pytest
from botocore.exceptions import ClientError

from platform_team.hub_ui.app import create_app
from platform_team.hub_ui.jobs import Busy, Jobs
from platform_team.hub_ui.reads import Cache
from platform_team.shared_code.config import Settings
from tests.fakes import ACCOUNT, PLATFORM, FakeClients


def test_a_job_collects_what_its_function_says():
    jobs = Jobs()

    def run(say):
        say("first line")
        say("second line")
        return {"agents": 2}
    job = jobs.start("rollout", "guard_prompt", run)
    assert job.wait(5)
    assert job.lines == ["first line", "second line"] and job.state == "done" and job.result == {"agents": 2}
    assert job.error == "" and job.kind == "rollout" and job.target == "guard_prompt"
    assert job.ended >= job.started and job.started.tzinfo is not None
    assert jobs.current() is job and jobs.get(job.id) is job and jobs.get("other") is None


def test_a_second_job_is_refused_while_one_runs():
    jobs, gate = Jobs(), threading.Event()

    def slow(say):
        say("started")
        gate.wait(5)
        say("finished")
        return {"ok": True}
    first = jobs.start("stop", "quality_agent", slow)
    with pytest.raises(Busy):
        jobs.start("resume", "quality_agent", lambda say: {"never": True})
    assert jobs.current() is first and first.state == "running"
    gate.set()
    assert first.wait(5)
    assert first.lines == ["started", "finished"] and first.state == "done" and first.result == {"ok": True}
    assert jobs.current() is first


def test_a_job_that_raises_is_shown_failed_and_frees_the_slot():
    jobs = Jobs()

    def denied(say):
        say("updating the agent gateway")
        raise ClientError({"Error": {"Code": "AccessDeniedException",
                                     "Message": f"User: arn:aws:sts::{ACCOUNT}:assumed-role/x\n  is not authorized"}},
                          "UpdateGateway")
    job = jobs.start("guardrail", "attach", denied)
    assert job.wait(5)
    assert job.state == "failed" and job.result is None and job.lines == ["updating the agent gateway"]
    assert job.error == "AccessDeniedException: User: arn:aws:sts::<ACCOUNT>:assumed-role/x is not authorized"
    assert job.ended is not None
    after = jobs.start("guardrail", "detach", lambda say: {"attached": False})
    assert after.wait(5) and after.state == "done" and jobs.current() is after


def test_a_job_whose_function_raises_anything_ends_and_frees_the_slot():
    jobs = Jobs()

    def exits(say):
        say("about to exit")
        raise SystemExit(3)
    job = jobs.start("stop", "quality_agent", exits)
    assert job.wait(5)
    assert job.state == "failed" and job.error == "SystemExit: 3" and job.ended is not None
    assert jobs.start("resume", "quality_agent", lambda say: {}).wait(5)


def test_a_finished_job_clears_the_cache():
    hub = create_app(Settings(), FakeClients(record_status=None), PLATFORM).state.hub
    loads = []

    def load():
        loads.append(len(loads) + 1)
        return loads[-1]
    assert hub.cache.get("counts", load) == 1 and hub.cache.get("counts", load) == 1     # kept for its seconds
    assert hub.jobs.start("rollout", "guard_prompt", lambda say: None).wait(5)
    assert hub.cache.get("counts", load) == 2                                            # the next read loads again


def test_a_read_is_kept_for_its_seconds_and_a_failed_read_is_not_kept():
    now = [100.0]
    cache, loads = Cache(5, clock=lambda: now[0]), []
    assert cache.get("k", lambda: loads.append(1) or "first") == "first"
    now[0] += 4.9
    assert cache.get("k", lambda: "second") == "first"
    now[0] += 0.2
    assert cache.get("k", lambda: "second") == "second"

    def fails():
        raise RuntimeError("read failed")
    with pytest.raises(RuntimeError):
        cache.get("other", fails)
    assert cache.get("other", lambda: "now it works") == "now it works"


def test_a_read_that_ends_after_a_clear_is_not_kept():
    """A job that ends while a page reads clears the cache; what that read brings back is from before the job."""
    cache = Cache(60)

    def read_during_the_job():
        cache.clear()                   # the job ends while this read runs
        return "before the job"
    assert cache.get("k", read_during_the_job) == "before the job"
    assert cache.get("k", lambda: "after the job") == "after the job"
