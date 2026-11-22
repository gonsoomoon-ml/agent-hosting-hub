# tests/test_e2e_scripts.py  (the pure parts of the scripts in e2e_checks/: they decide what a check line says)
import datetime as dt

from e2e_checks import check_cleanup, e2e_hosting as e2e
from platform_team.shared_code.config import Settings


def _at(second):
    return dt.datetime(2026, 11, 22, 6, 0, second, tzinfo=dt.timezone.utc)


def _entered(name, second, kind="Task"):
    return {"type": f"{kind}StateEntered", "timestamp": _at(second), "stateEnteredEventDetails": {"name": name}}


def _scheduled(resource_type, second):
    return {"type": "TaskScheduled", "timestamp": _at(second), "taskScheduledEventDetails": {"resourceType": resource_type}}


def test_steps_run_counts_a_retried_step_once_and_names_its_service():
    events = [_entered("Read", 0), _scheduled("lambda", 0), _scheduled("lambda", 2),       # a Lambda retry
              _entered("Scan", 3), _scheduled("codebuild", 3), _entered("Notify", 30), _scheduled("sns", 30),
              _entered("Failed", 31, kind="Fail")]
    assert e2e.steps_run(events) == ["Read:lambda", "Scan:codebuild", "Notify:sns"]
    assert e2e.step_times(events, _at(31)) == "Read 3s, Scan 27s, Notify 1s, Failed 0s"


def test_the_alert_check_reads_agent_and_step_from_the_message():
    envelope = {"Subject": "Hosting review failed at Scan",
                "Message": '{"failedStep": "Scan", "spec": {"name": "quality_agent"}, "error": {"Error": "States.TaskFailed"}}'}
    _, agent, step = e2e.alert_parts(envelope)
    assert (agent, step) == ("quality_agent", "Scan")
    _, agent, step = e2e.alert_parts({"Message": '{"spec": {"name": "quality_agent"}, "error": {}}'})   # before the fix
    assert (agent, step) == ("quality_agent", "")


def test_the_advisory_line_is_a_row_of_pip_audit_not_the_requirement_itself():
    assert e2e.ADVISORY.search("jinja2 2.11.2  PYSEC-2021-66   2.11.3")
    assert e2e.ADVISORY.search("jinja2 2.11.2 GHSA-462w-v97r-4m45 2.11.3")
    assert not e2e.ADVISORY.search("jinja2==2.11.2")
    assert not e2e.ADVISORY.search("Collecting jinja2==2.11.2")


def test_printed_lines_hold_no_account_id_and_no_other_long_number(monkeypatch):
    monkeypatch.setattr(e2e, "ACCOUNT", "111122223333")
    assert e2e.clean("arn:aws:iam::111122223333:role/x 1763791200123") == "arn:aws:iam::<ACCOUNT>:role/x <NUMBER>"


def test_cleanup_check_knows_the_hubs_names_and_no_others():
    s = Settings()
    for name in ("hub-agents", "hub_pe", "hubQualityAgent_default_agent-eHcqNQ7n5v", "AgentCore-hubQualityAgent-default",
                 "/hub/platform/bucket", "hub-e2e-alerts"):
        assert check_cleanup.hub_name(s, name), name
    for name in ("hubwhole-agents", "hubspot", "github-runner", "other_team_runtime", "CDKToolkit",
                 "AgentCore-otherTeam-default", "/hubwhole/x"):
        assert not check_cleanup.hub_name(s, name), name


# ------------------------------------------------------------------ fix round 1: checks 2 and 4 assert what their lines say

REFUSED = ('{"jsonrpc":"2.0","id":1,"error":{"code":-32002,"message":"Tool Execution Denied: Tool call not allowed due to '
           'policy enforcement [No policy applies to the request (denied by default).]"}}')     # the final run's log


def test_check_2_counts_a_policy_refusal_only():
    assert e2e.policy_refusal(REFUSED)
    assert e2e.policy_refusal("event: message\ndata: " + REFUSED)                               # a streamed answer
    assert not e2e.policy_refusal('{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Unknown tool: Parts___get_test_result"}}')
    assert not e2e.policy_refusal('{"jsonrpc":"2.0","id":1,"result":{"isError":true,"content":[{"type":"text","text":"unknown tool"}]}}')
    assert not e2e.policy_refusal('{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\\"error\\": \\"unknown tool\\"}"}]}}')
    assert not e2e.policy_refusal("")


def test_check_4_measures_the_start_from_the_request():
    requested = 1_000.0
    assert e2e.started_in_time(requested, requested + 8)          # the final run: 8 s after the request
    assert e2e.started_in_time(requested, requested + 120)
    assert not e2e.started_in_time(requested, requested + 125)


# ------------------------------------------------------------------ final review M-6: a check that asserts absence reads every page

def test_check_9_finds_a_runtime_on_a_later_page():
    from tests.fakes import PLATFORM, FakeClients
    c = FakeClients()
    pages = {None: {"agentRuntimes": [{"agentRuntimeName": f"other_{i}"} for i in range(100)], "nextToken": "p2"},
             "p2": {"agentRuntimes": [{"agentRuntimeName": "hubQualityAgent_default_agent"}]}}
    c.ctl.list_agent_runtimes = lambda **kw: pages[kw.get("nextToken")]
    assert e2e.nothing_made(c, Settings(), PLATFORM, "quality_agent") == {"Runtime": ["hubQualityAgent_default_agent"]}
