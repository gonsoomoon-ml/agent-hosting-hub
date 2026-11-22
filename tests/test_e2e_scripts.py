# tests/test_e2e_scripts.py  (the pure parts of the scripts in e2e_checks/: they decide what a check line says)
import datetime as dt
import pathlib

import pytest

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
    monkeypatch.setattr(e2e, "ACCOUNT", "123456789012")
    assert e2e.clean("arn:aws:iam::123456789012:role/x 1763791200123") == "arn:aws:iam::<ACCOUNT>:role/x <NUMBER>"


def test_cleanup_check_knows_the_hubs_names_and_no_others():
    s = Settings()
    for name in ("hub-agents", "hub_pe", "hub_quality_agent", "hub_quality_agent-eHcqNQ7n5v-DEFAULT",
                 "/hub/platform/bucket", "hub-e2e-alerts",
                 "hubQualityAgent_default_agent-eHcqNQ7n5v", "AgentCore-hubQualityAgent-default"):     # the CLI's names
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
             "p2": {"agentRuntimes": [{"agentRuntimeName": "hub_quality_agent"}]}}
    c.ctl.list_agent_runtimes = lambda **kw: pages[kw.get("nextToken")]
    assert e2e.nothing_made(c, Settings(), PLATFORM, "quality_agent") == {"Runtime": ["hub_quality_agent"]}


def _observed(capsys, c):
    from tests.fakes import PLATFORM
    capsys.readouterr()                                  # what the fake review printed before
    before = e2e.OBSERVED[0]
    e2e.observe_leftovers(c, Settings(), PLATFORM, "quality_agent")
    return e2e.OBSERVED[0] - before, capsys.readouterr().out.splitlines()


def test_observation_b_names_the_runtime_its_workload_identity_log_groups_and_packages(capsys):
    from tests.fakes import SPEC, FakeClients
    from tests.test_reject import _review
    c = FakeClients()
    _review(c, SPEC)
    c.workload_identities = ["hub_quality_agent-abcdefghij", "other_team_runtime-abcdefghij"]
    n, lines = _observed(capsys, c)
    assert n == 4 and lines == [
        "[INFO] Runtime hub_quality_agent: hub_quality_agent-Ab12Cd34Ef version 1 READY",
        "[INFO] workload identities named after hub_quality_agent: ['hub_quality_agent-abcdefghij']",
        "[INFO] log groups of hub_quality_agent: ['/aws/bedrock-agentcore/runtimes/hub_quality_agent-Ab12Cd34Ef-DEFAULT']",
        "[INFO] code packages of quality_agent in the inbox: ['packages/quality_agent/v1.zip (0 bytes)']"]


def test_observation_b_reports_an_error_as_an_observation_and_does_not_raise(capsys):
    from botocore.exceptions import ClientError
    from tests.fakes import FakeClients
    c = FakeClients()

    def denied(**kw):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "not allowed"}}, "ListWorkloadIdentities")
    c.ctl.list_workload_identities = denied
    n, lines = _observed(capsys, c)
    assert lines[0] == "[INFO] Runtime hub_quality_agent: none"
    assert lines[1] == "[INFO] observation B stopped: AccessDeniedException: not allowed" and n == 2


def test_check_9_sees_every_kind_a_passed_review_makes():
    from tests.fakes import PLATFORM, SPEC, FakeClients
    from tests.test_reject import _review
    c = FakeClients()
    _review(c, SPEC)                                 # what a passed review leaves for quality_agent
    assert sorted(e2e.nothing_made(c, Settings(), PLATFORM, "quality_agent")) == sorted(e2e.MADE_BY_A_REVIEW)
    assert e2e.nothing_made(c, Settings(), PLATFORM, "release_review") == {}


@pytest.mark.parametrize("script", ["check_platform.py", "check_cleanup.py"])
def test_a_check_script_reads_the_env_file_before_it_builds_its_settings(script):
    """Each calls os.environ.update(env_file_updates(os.environ, REPO / ".env")) before Settings.from_env(), as e2e_hosting.py does."""
    text = (pathlib.Path(__file__).resolve().parents[1] / "e2e_checks" / script).read_text()
    main = text[text.index("def main()"):]
    assert 'os.environ.update(env_file_updates(os.environ, REPO / ".env"))' in main
    assert main.index("env_file_updates(") < main.index("Settings.from_env()")
