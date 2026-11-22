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
                 "hubQualityAgent_default_agent-eHcqNQ7n5v", "AgentCore-hubQualityAgent-default",   # the CLI's names
                 # the Runtime behind a harness, its workload identity and log group (AgentCore names them)
                 "harness_hub_spec_assistant", "harness_hub_spec_assistant-Ab12Cd34Ef",
                 "harness_hub_spec_assistant-Ab12Cd34Ef-DEFAULT"):
        assert check_cleanup.hub_name(s, name), name
    for name in ("hubwhole-agents", "hubspot", "github-runner", "other_team_runtime", "CDKToolkit",
                 "AgentCore-otherTeam-default", "/hubwhole/x", "harness_hubwhole_x", "harness_other_team",
                 "harness_my_agent-Ab12Cd34Ef"):
        assert not check_cleanup.hub_name(s, name), name


def test_cleanup_check_lists_the_log_deliveries_and_the_gateway_log_groups(monkeypatch, tmp_path):
    """Delivery sources and destinations by name, deliveries by the name of their source, and the log groups under
    /aws/vendedlogs/bedrock-agentcore/; the hub's are the names hub_name takes. The calls are checked against the
    service model (a real logs client in a botocore Stubber)."""
    import boto3
    from botocore.stub import Stubber
    from platform_team.shared_code.aws_helpers import Clients
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    s = Settings()
    c = Clients(boto3.Session(region_name="us-west-2", aws_access_key_id="test-access-key", aws_secret_access_key="example"))
    kinds = check_cleanup.kinds(s, c)
    gw = "arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/hub-agents-abcdefghij"
    with Stubber(c.logs) as st:
        st.add_response("describe_delivery_sources", {"deliverySources": [
            {"name": "hub-agents-logs", "resourceArns": [gw], "logType": "APPLICATION_LOGS"},
            {"name": "other_runtime-abcdefghij-traces-source", "logType": "TRACES"}]}, {})
        st.add_response("describe_delivery_destinations", {"deliveryDestinations": [
            {"name": "hub-agents-traces", "deliveryDestinationType": "XRAY"}, {"name": "someone-elses"}]}, {})
        st.add_response("describe_deliveries", {"deliveries": [
            {"id": "abcdefghij123456", "deliverySourceName": "hub-tools-logs"},
            {"id": "abcdefghij654321", "deliverySourceName": "other_runtime-abcdefghij-traces-source"}]}, {})
        for prefix in ("/aws/lambda/", "/aws/codebuild/", "/aws/vendedlogs/states/", "/aws/vendedlogs/bedrock-agentcore/",
                       "/aws/bedrock-agentcore/runtimes/"):
            groups = [{"logGroupName": "/aws/vendedlogs/bedrock-agentcore/hub-tools"}] if "bedrock-agentcore/" in prefix \
                and "vendedlogs" in prefix else []
            st.add_response("describe_log_groups", {"logGroups": groups}, {"logGroupNamePrefix": prefix})
        found = {kind: kinds[kind]() for kind in ("log delivery sources", "log delivery destinations", "log deliveries",
                                                  "log groups")}
        st.assert_no_pending_responses()
    assert found["log delivery sources"] == ["hub-agents-logs", "other_runtime-abcdefghij-traces-source"]
    assert [n for n in found["log delivery destinations"] if check_cleanup.hub_name(s, n)] == ["hub-agents-traces"]
    assert [n for n in found["log deliveries"] if check_cleanup.hub_name(s, n)] == ["hub-tools-logs"]
    assert found["log groups"] == ["/aws/vendedlogs/bedrock-agentcore/hub-tools"]
    assert check_cleanup.hub_name(s, found["log groups"][0].rsplit("/", 1)[-1])


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


# ------------------------------------------------------------------ check 0: a review still running is waited for

class _Clock:
    """Fake time for the start guard: sleep moves the clock and records the wait; after_sleep runs after each."""
    def __init__(self, after_sleep=lambda: None):
        self.t, self.sleeps, self.after_sleep = 1000.0, [], after_sleep
    def now(self):
        return self.t
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds
        self.after_sleep()


def test_the_start_guard_goes_on_at_once_when_no_review_runs():
    from tests.fakes import PLATFORM, FakeClients
    c, clock, said = FakeClients(), _Clock(), []
    assert e2e.no_review_running(c.sfn, PLATFORM.machine_arn, said.append, clock.sleep, clock.now) is True
    assert clock.sleeps == [] and said == []


def test_the_start_guard_waits_for_a_review_that_ends_and_says_so():
    # the review make seed starts for the shared tool record ends in Skipped within seconds (2026-11-22: 1.7 s)
    from tests.fakes import PLATFORM, FakeClients
    c = FakeClients()
    c.running = [("seed-review", "rec-9")]
    clock = _Clock(after_sleep=c.running.clear)                      # gone at the second look
    said = []
    assert e2e.no_review_running(c.sfn, PLATFORM.machine_arn, said.append, clock.sleep, clock.now) is True
    assert clock.sleeps == [e2e.RUNNING_STEP] and len(said) == 1
    assert "waited" in said[0] and "seed-review" in said[0] and "[FAIL]" not in said[0]


def test_the_start_guard_fails_after_the_bound_and_the_cleanup_does_not_run(monkeypatch, capsys):
    from tests.fakes import PLATFORM, FakeClients
    c = FakeClients()
    c.running = [("long-review", "rec-9")]                           # never ends
    c.account = "123456789012"
    clock = _Clock()
    monkeypatch.setattr(e2e, "ACCOUNT", "")
    monkeypatch.setattr(e2e, "env_file_updates", lambda env, path: {})
    monkeypatch.setattr(e2e.Clients, "for_settings", lambda s: c)
    monkeypatch.setattr(e2e, "load", lambda s, clients: PLATFORM)
    monkeypatch.setattr(e2e, "known_state", lambda *a: pytest.fail("the cleanup ran while a review was running"))
    monkeypatch.setattr("time.sleep", clock.sleep)
    monkeypatch.setattr("time.monotonic", clock.now)
    assert e2e.main() == 1
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == ("[FAIL] 0 no review is running: ['long-review'] still running. Cleaning up now would race its "
                       "steps: wait until it stops (Step Functions console), then start again")
    assert sum(clock.sleeps) == e2e.RUNNING_WAIT == 60 and set(clock.sleeps) == {e2e.RUNNING_STEP}


@pytest.mark.parametrize("script", ["check_platform.py", "check_cleanup.py"])
def test_a_check_script_reads_the_env_file_before_it_builds_its_settings(script):
    """Each calls os.environ.update(env_file_updates(os.environ, REPO / ".env")) before Settings.from_env(), as e2e_hosting.py does."""
    text = (pathlib.Path(__file__).resolve().parents[1] / "e2e_checks" / script).read_text()
    main = text[text.index("def main()"):]
    assert 'os.environ.update(env_file_updates(os.environ, REPO / ".env"))' in main
    assert main.index("env_file_updates(") < main.index("Settings.from_env()")
