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


# ------------------------------------------------------------------ checks 2 and 4 assert what their lines say

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


# ------------------------------------------------------------------ a check that asserts absence reads every page

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


@pytest.mark.parametrize("script", ["check_platform.py", "check_cleanup.py", "e2e_operations.py",
                                    "e2e_hub_ui.py"])
def test_a_check_script_reads_the_env_file_before_it_builds_its_settings(script):
    """Each calls os.environ.update(env_file_updates(os.environ, REPO / ".env")) before Settings.from_env(), as e2e_hosting.py does."""
    text = (pathlib.Path(__file__).resolve().parents[1] / "e2e_checks" / script).read_text()
    main = text[text.index("def main()"):]
    assert 'os.environ.update(env_file_updates(os.environ, REPO / ".env"))' in main
    assert main.index("env_file_updates(") < main.index("Settings.from_env()")


# ------------------------------------------------------------------ e2e_operations.py: the parts that decide its lines

def test_the_employee_id_and_the_mask_are_found_in_an_answer():
    """Checks 4 and 5: every ID that starts EMP- (sorted, once each) and whether the custom guardrail's mask is there."""
    from e2e_checks import e2e_operations as ops
    assert ops.employee_marks("Inspector ID: EMP-204817; part P-100") == (["EMP-204817"], False)
    assert ops.employee_marks('{"answer": "- **Inspector ID:** {employee_id}"}') == ([], True)
    assert ops.employee_marks("EMP-318425, EMP-204817 and EMP-204817 again")[0] == ["EMP-204817", "EMP-318425"]
    assert ops.employee_marks("cut short: EMP-")[0] == ["EMP-"]          # check 5 wants no EMP- at all
    assert ops.employee_marks("") == ([], False)


def test_the_alarm_name_and_its_new_state_are_read_from_the_alert():
    """Check 8: a CloudWatch alarm's alert is an SNS envelope whose Message is the alarm's JSON; any other alert names
    no alarm."""
    import json
    from e2e_checks import e2e_operations as ops
    alarm = {"Type": "Notification", "Subject": 'ALARM: "hub-tool-calls" in US West (Oregon)', "Message": json.dumps({
        "AlarmName": "hub-tool-calls", "NewStateValue": "ALARM", "OldStateValue": "OK",
        "NewStateReason": "Threshold Crossed: 1 out of the last 1 datapoints [41.0] was greater than the threshold (19.0)"})}
    assert ops.alarm_of(alarm) == ("hub-tool-calls", "ALARM")
    review = {"Subject": "Hosting review failed at Scan", "Message": '{"failedStep": "Scan", "spec": {"name": "quality_agent"}}'}
    assert ops.alarm_of(review) == ("", "")
    assert ops.alarm_of({"Message": "not JSON"}) == ("", "") and ops.alarm_of(None) == ("", "")


def _log(epoch_s, text, stream="runtime-logs-hub-ops-incident-abcdefghij"):
    return {"timestamp": int(epoch_s * 1000), "message": text, "logStreamName": stream}


T0 = _at(0).timestamp()


OTHER = "runtime-logs-0b6c2f3e-1111-2222-3333-abcdefghij01"     # another session's stream of the same Runtime


def test_the_incident_loops_lines_are_read_one_per_line_without_the_otel_copy():
    """Each `asking again (<n>)` line is one line (epoch s, stream, n), in time order, also when its number was seen
    before (a loop that starts again counts from 1). The copy of the agent's stdout in the stream otel-rt-logs is left
    out; other lines are not rounds. Lines per clock minute (UTC) for LOOP_RATE."""
    from e2e_checks import e2e_operations as ops
    events = [_log(T0 + 61, "asking again (3)"), _log(T0 + 1, "asking again (1)\n"), _log(T0 + 2, "asking again (2)"),
              _log(T0 + 2, "asking again (2)", stream="otel-rt-logs"), _log(T0 + 3, "Invocation completed successfully"),
              _log(T0 + 62, "[trace_id=abcdefghij span_id=abcdefghij] asking again (4)"),
              _log(T0 + 70, "asking again (1)", stream=OTHER)]                  # a loop that started again
    lines = ops.loop_lines(events)
    assert [(t - T0, n) for t, _, n in lines] == [(1, 1), (2, 2), (61, 3), (62, 4), (70, 1)]
    assert lines[-1][1] == OTHER and all(stream != "otel-rt-logs" for _, stream, _ in lines)
    assert ops.per_minute(lines) == {"06:00": 2, "06:01": 3}
    assert ops.loop_lines([]) == [] and ops.per_minute([]) == {}


def test_check_9_fails_on_any_loop_line_newer_than_the_settle_point():
    """Quiet means no `asking again` line newer than the settle point (the stop plus STOP_SETTLE), in any stream of the
    Runtime but the otel-rt-logs copy. A later `asking again (1)` (a new invocation after the stop) fails the check
    though its number was seen before; a line from before the settle point that arrives late does not."""
    from e2e_checks import e2e_operations as ops
    settle = T0 + 120
    stopped = [_log(T0 + n, f"asking again ({n})") for n in range(1, 82)]                # 81 rounds, the last at T0+81
    assert ops.no_new_lines(ops.loop_lines(stopped), settle)
    assert not ops.no_new_lines(ops.loop_lines(stopped + [_log(settle + 40, "asking again (1)", stream=OTHER)]), settle)
    assert not ops.no_new_lines(ops.loop_lines(stopped + [_log(settle + 1, "asking again (82)")]), settle)
    assert ops.no_new_lines(ops.loop_lines(stopped + [_log(settle + 5, "asking again (81)", stream="otel-rt-logs")]),
                            settle)                                                     # the copy, written late
    assert ops.no_new_lines([], settle)


def test_what_stop_sh_said_for_each_session_is_read_from_its_lines():
    from e2e_checks import e2e_operations as ops
    incident, ended = "hub-ops-incident-abcdefghij0123456789abcdefghij", "0b6c2f3e-1111-2222-3333-abcdefghij01"
    refused = "0b6c2f3e-4444-5555-6666-abcdefghij02"
    out = "\n".join([
        "agent quality_agent: stop (prefix hub, region us-west-2)",
        "blocking the entry: stop_agent_quality_agent refuses every call to QualityAgent except the review's test call "
        "(hub-review-testcall-role)",
        "stop_agent_quality_agent is ACTIVE",
        "sessions with a log stream in the last 30 minutes (/aws/bedrock-agentcore/runtimes/hub_quality_agent-Ab12Cd34Ef-"
        "DEFAULT): 2",
        f"session {incident}: stopped",
        f"session {ended}: already ended (ResourceNotFoundException: Session {ended} not found or has been terminated)",
        f"session {refused}: not stopped (ThrottlingException: Rate exceeded (try later))",
        "quality_agent is blocked at the entry by stop_agent_quality_agent; 1 of 2 sessions not stopped: run stop again, "
        "or give the session with --session <ID>"])
    assert ops.stop_report(out) == {
        "found": 2, "stopped": [incident],
        "ended": {ended: f"ResourceNotFoundException: Session {ended} not found or has been terminated"},
        "failed": {refused: "ThrottlingException: Rate exceeded (try later)"}}
    assert ops.stop_report("stop of quality_agent did not finish (prefix hub, region us-west-2): boom") == {
        "found": None, "stopped": [], "ended": {}, "failed": {}}


def test_the_log_only_report_is_read_per_agent():
    from e2e_checks import e2e_operations as ops
    out = "\n".join(["company policy guard_prompt: report (prefix hub, region us-west-2)",
                     "quality_agent: LOG_ONLY, LogOnlyMatches 0, LogOnlyDecisionFlips 0 (last 60 minutes)",
                     "release_review: LOG_ONLY, LogOnlyMatches 2, LogOnlyDecisionFlips 1 (last 60 minutes)",
                     "guard_prompt is on 2 agents"])
    assert ops.report_counts(out) == {"quality_agent": {"mode": "LOG_ONLY", "matches": 0, "flips": 0},
                                      "release_review": {"mode": "LOG_ONLY", "matches": 2, "flips": 1}}
    assert ops.report_counts("no agent has guard_prompt") == {}


def test_the_usage_report_is_read_back_into_its_two_tables():
    """What usage.sh prints (usage_report.report between its first and last line) reads back as the agents' rows and
    the tools' calls."""
    from e2e_checks import e2e_operations as ops
    from platform_team.agent_monitoring import usage_report
    row = {"invocations": 5, "sessions": 3, "errors": 0, "cpu_vcpu_hours": 0.0, "memory_gb_hours": 0.0}
    agents = {"docs_adk": row, "quality_agent": {**row, "invocations": 61}, "release_review": row, "spec_assistant": row}
    tools = {"Parts___get_part_spec": 4, "Parts___get_test_result": 0, "Quality___get_inspection_data": 183,
             "Release___file_review_request": 0}
    out = "\n".join(["use of the hosted agents in the last 60 minutes (prefix hub, region us-west-2)",
                     *usage_report.report(agents, tools),
                     "Calls come in one-minute batches; CPU and memory may be up to 60 minutes late (AgentCore developer guide)."])
    rows, calls = ops.usage_tables(out)
    assert sorted(rows) == sorted(agents) and rows["quality_agent"] == ["61", "3", "0", "0.000000", "0.000000"]
    assert calls == tools
    assert ops.usage_tables("\n".join(usage_report.report({}, tools))) == ({}, tools)


def test_an_invoke_harness_stream_is_read_into_text_tool_calls_and_results():
    """The shapes are InvokeHarness's event stream (service model): a toolUse block start names the tool, a toolResult
    block start carries the status and its deltas the result; text deltas are the answer; error events are kept."""
    from e2e_checks import e2e_operations as ops
    spec = '{"part_id":"P-100","spec":"M4 x 12 mm, steel","synthetic":true}'
    events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": "t1", "name": "Parts___get_part_spec"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": '{"part_id": "P-100"}'}}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"messageStart": {"role": "user"}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolResult": {"toolUseId": "t1", "status": "success"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolResult": [{"text": spec}]}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolResult": {"toolUseId": "t2", "status": "error"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolResult": [{"json": {"error": "denied"}}]}}},
        {"contentBlockStop": {"contentBlockIndex": 1}},
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "The spec of P-100 is "}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "M4 x 12 mm."}}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 775}}},
        {"runtimeClientError": {"message": "something went wrong"}}]
    assert ops.read_stream(events) == {
        "text": "The spec of P-100 is M4 x 12 mm.", "tool_uses": ["Parts___get_part_spec"],
        "tool_results": [{"status": "success", "text": spec}, {"status": "error", "text": '{"error": "denied"}'}],
        "errors": ["runtimeClientError: something went wrong"]}


def test_line_0_says_what_the_start_needs():
    """The operations run starts where make e2e ends: the hub deployed and its two agents APPROVED."""
    from e2e_checks import e2e_operations as ops
    from platform_team.shared_code.hub_state import Platform
    from tests.fakes import PLATFORM
    approved = {"release_review": "APPROVED", "quality_agent": "APPROVED"}
    assert ops.start_refusal(PLATFORM, approved) == ""
    said = ops.start_refusal(PLATFORM, {**approved, "quality_agent": "PENDING_APPROVAL"})
    assert said.startswith("[FAIL] 0 ") and "quality_agent PENDING_APPROVAL" in said and "make e2e" in said
    said = ops.start_refusal(Platform(account="123456789012", registry_id="reg-1"), approved)
    assert said.startswith("[FAIL] 0 ") and "the agent gateway" in said and "make deploy seed e2e" in said


def test_a_scene_that_raises_fails_its_own_check_and_the_run_goes_on(monkeypatch, capsys):
    """Before its line: the check fails with the error, account masked. After its line: one [INFO], no second line."""
    from botocore.exceptions import ClientError
    from e2e_checks import e2e_operations as ops
    monkeypatch.setattr(e2e, "RESULTS", [])
    monkeypatch.setattr(e2e, "ACCOUNT", "123456789012")

    def denied():
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "arn:aws:iam::123456789012:role/x is "
                                     "not authorized"}}, "CreatePolicy")
    assert ops.guarded(6, denied, default="kept") == "kept"
    assert e2e.RESULTS == [(6, "the scene of check 6", False)]

    def after_its_line():
        e2e.check(7, "the review SUCCEEDED", True, "ok")
        raise RuntimeError("later")
    ops.guarded(7, after_its_line)
    assert e2e.RESULTS[-1] == (7, "the review SUCCEEDED", True) and len(e2e.RESULTS) == 2
    out = capsys.readouterr().out.splitlines()
    assert out[0] == ("[FAIL] 6 the scene of check 6: stopped by AccessDeniedException: arn:aws:iam::<ACCOUNT>:role/x "
                      "is not authorized")
    assert out[-1] == "[INFO] the scene of check 7 stopped after its line: RuntimeError: later"


# ------------------------------------------------------------------ e2e_hub_ui.py: what it reads on the screen's pages
# Each reader runs on a page the screen renders (tests/fakes.py for AWS), so it reads the templates as they are.

def test_the_screen_check_reads_the_page_token_from_the_meta_or_the_form():
    from e2e_checks import e2e_hub_ui as ui
    from tests.fakes import FakeClients
    from tests.test_hub_ui_home import screen
    assert ui.token_of('<head><meta name="hub-token" content="abc123"></head>') == "abc123"
    assert ui.token_of('<form method="post"><input type="hidden" name="token" value="def456"></form>') == "def456"
    with pytest.raises(ValueError):
        ui.token_of("<p>no token here</p>")
    web = screen(FakeClients(record_status=None))
    page = web.get("/").text
    assert ui.token_of(page) == web.app.state.hub.token                 # the token the screen checks on a press


def test_the_screen_check_reads_the_home_counts_alarms_and_platform_parts():
    from e2e_checks import e2e_hub_ui as ui
    from tests.fakes import ACCOUNT, FakeClients
    from tests.test_hub_ui_home import record, screen
    c = FakeClients(record_status=None)
    c.other_records = [record("release_review", "AGENT", "APPROVED"), record("quality_agent", "AGENT", "APPROVED"),
                       record("docs_adk", "AGENT", "PENDING_APPROVAL"), record("parts-tools", "MCP", "APPROVED"),
                       record("old_agent", "AGENT", "REJECTED")]
    c.alarms = [{"AlarmName": "hub-tool-calls", "StateValue": "ALARM"},
                {"AlarmName": "hub-guardrail-errors", "StateValue": "OK"}]
    page = screen(c).get("/").text
    assert ui.home_counts(page) == {"hosted": 2, "in_review": 1, "tools": 1}
    assert ui.home_alarms(page) == {"hub-guardrail-errors": "OK", "hub-tool-calls": "ALARM"}
    parts = ui.home_platform(page)
    assert [(p["name"], p["state"]) for p in parts] == [
        ("hub-agents", "READY"), ("hub-tools", "READY"), ("hub_pe", "ACTIVE"), ("hub-registry", "READY"),
        ("hub-review", "ACTIVE"), ("hub-alerts", "확인된 구독 1")]
    assert parts[0]["service"] == "Amazon Bedrock AgentCore Gateway"
    assert ui.account_free(page, ACCOUNT) and not ui.account_free(page + ACCOUNT, ACCOUNT)
    assert not ui.account_free(page, "")                                # no account known: not proven free


def test_the_screen_check_reads_a_review_card_and_the_failed_scan_on_the_detail_page():
    from datetime import timedelta
    from e2e_checks import e2e_hub_ui as ui
    from tests.test_hub_ui_reviews import (AT_SCAN, PASSED, T0, app_record, execution, failed_at_scan, history,
                                           screen)
    c = failed_at_scan()                                    # quality_agent (rec-1, PENDING_APPROVAL), failed at Scan
    c.other_records = [app_record("release_review", "APPROVED")]
    c.executions.append(execution("release", "rec-release_review", "SUCCEEDED", PASSED, "ExecutionSucceeded",
                                  start=T0 - timedelta(hours=1)))
    web = screen(c)
    listing = web.get("/reviews").text
    release = ui.review_card(listing, "release_review")
    assert release["status"] == "APPROVED" and release["review"] == "SUCCEEDED" and release["error"] == ""
    assert release["steps"] == [{"name": n, "state": "passed", "seconds": s} for n, s in (
        ("Read", 1), ("Scan", 41), ("Grant", 15), ("Deploy", 257), ("Entry", 35), ("TestCall", 7), ("Approve", 15))]
    # the history alone gives the same seconds (what check 3 compares the page with)
    assert ui.step_seconds(history(PASSED, "ExecutionSucceeded")) == {r["name"]: r["seconds"] for r in release["steps"]}
    quality = ui.review_card(listing, "quality_agent")
    assert quality["status"] == "PENDING_APPROVAL" and quality["review"] == "FAILED"
    assert [r["state"] for r in quality["steps"]] == ["passed", "failed"] + ["waiting"] * 5
    assert "Scan" in quality["error"] and ui.review_card(listing, "docs_adk") is None

    detail = ui.review_detail(web.get("/reviews/quality_agent").text)
    assert detail["status"] == "PENDING_APPROVAL" and detail["review"] == "FAILED" and detail["can_reject"]
    assert detail["steps"][1] == {"name": "Scan", "state": "failed", "seconds": 36}
    assert "Scan" in detail["failed"] and "States.TaskFailed" in detail["failed"]
    assert detail["findings"] == ["jinja2 2.11.2  PYSEC-2021-66       2.11.3", "jinja2 2.11.2  GHSA-h5c8-rqwp-cp95 3.1.3"]
    assert detail["log"].startswith("/aws/codebuild/hub-review-scan ")
    assert not ui.review_detail(web.get("/reviews/release_review").text)["can_reject"]     # APPROVED: no Reject form
    # the events from the failed Scan's entry on, as check 4 printed them on 2026-11-23 (both runs): Scan's own six,
    # its exit event included, then Notify's, FailStateEntered and ExecutionFailed; the fixture writes that shape
    assert ui.after_state(history(AT_SCAN, "ExecutionFailed"), "Scan") == [
        "TaskStateEntered", "TaskScheduled", "TaskStarted", "TaskSubmitted", "TaskFailed", "TaskStateExited",
        "TaskStateEntered", "TaskScheduled", "TaskStarted", "TaskSucceeded", "TaskStateExited", "FailStateEntered",
        "ExecutionFailed"]
    assert ui.after_state([], "Scan") == []


def test_the_screen_check_reads_the_policy_modes_the_report_and_the_guardrail():
    from e2e_checks import e2e_hub_ui as ui
    from tests.fakes import PLATFORM
    from tests.test_hub_ui_policies import INTERCEPTOR, fleet, screen
    c = fleet("LOG_ONLY")
    c.statistics = {("LogOnlyMatches", "guard_prompt_quality_agent-id"): 3}       # by the policy's ID, as the fake keys it
    page = screen(c).get("/policies").text
    found = ui.policy_rows(page)
    assert found["guard_prompt_quality_agent"] == {"status": "ACTIVE", "mode": "LOG_ONLY"}
    assert "shared_tool_read" not in found and "shared_tool_read" in ui.policy_rows(page, "tool_gw")
    assert ui.company_mode(page) == "LOG_ONLY"
    assert ui.mode_buttons(page) == {"log-only": False, "active": True, "off": True}    # the mode it is in: not pressable
    report = ui.report_rows(page)
    assert report["quality_agent"]["mode"] == "기록 모드" and report["quality_agent"]["flips"] == 0
    assert report["quality_agent"]["matches"] == 3                    # the number check 5 passes on
    assert ui.guardrail_panel(page) == {"word": "떨어져 있음", "points": [], "press": "/guardrail/attach"}
    c.gateways[PLATFORM.agent_gw["id"]]["interceptorConfigurations"] = [INTERCEPTOR]
    assert ui.company_mode(screen(fleet(None)).get("/policies").text) is None             # off
    attached = screen(c).get("/policies").text
    assert ui.guardrail_panel(attached) == {"word": "붙어 있음", "points": ["REQUEST", "RESPONSE"],
                                            "press": "/guardrail/detach"}


def test_the_screen_check_reads_an_agents_stop_state_its_buttons_and_the_alarm():
    from e2e_checks import e2e_hub_ui as ui
    from tests.test_hub_ui_agents import fleet, screen
    page = screen(fleet()).get("/agents").text            # release_review stopped, parts_harness a harness agent
    release, quality, harness = (ui.agent_row(page, a) for a in ("release_review", "quality_agent", "parts_harness"))
    assert release["stopped"] is True and release["presses"] == ["/agents/release_review/resume"]
    assert quality["stopped"] is False and quality["presses"] == ["/agents/quality_agent/stop"]
    assert "멈춤" in release["stop"] and "동작 중" in quality["stop"]
    assert harness["presses"] == [] and ui.agent_row(page, "nobody") is None
    assert len(quality["usage"]) == 5
    alarm = ui.alarm_panel(page)
    assert alarm["state"] == "ALARM" and "Parts___get_part_spec" in alarm["tool"] and len(alarm["bars"]) == 15


def test_the_screen_check_reads_a_refused_press_and_the_job_of_a_page():
    import threading
    from e2e_checks import e2e_hub_ui as ui
    from platform_team.hub_ui.texts import STRINGS
    from tests.fakes import FakeClients
    from tests.test_hub_ui_home import BASE, screen
    web = screen(FakeClients(record_status=None))
    hub, release = web.app.state.hub, threading.Event()
    job = hub.jobs.start("rollout", "guard_prompt", lambda say: release.wait(5) and None)
    page = web.get("/policies").text
    assert ui.job_of(page) == (job.id, "running")
    second = web.post("/policies/guard_prompt/mode", data={"token": ui.token_of(page), "mode": "log-only"},
                      headers={"Origin": BASE, "Referer": f"{BASE}/policies"}, follow_redirects=False)
    assert second.status_code == 303 and ui.query_of(second.headers["location"]) == {"err": "busy"}
    assert ui.sentence(web.get(second.headers["location"]).text) == STRINGS["ko"]["err.busy"]
    release.set()
    job.wait(5)
    assert ui.sentence(web.get("/").text) == "" and ui.job_of("<p>no job</p>") == ("", "")


def test_line_0_of_the_screen_check_says_what_is_not_as_e2e_ops_leaves_it():
    from e2e_checks import e2e_hub_ui as ui
    four = ["docs_adk", "quality_agent", "release_review", "spec_assistant"]
    left = {"hosted": four, "records": dict.fromkeys(four, "APPROVED"), "mode": None, "policies": [], "attached": False,
            "stopped": []}
    assert ui.start_refusal(left) == ""
    said = ui.start_refusal({**left, "hosted": four[:3], "mode": "LOG_ONLY", "policies": ["guard_prompt_docs_adk"],
                             "attached": True, "stopped": ["quality_agent"],
                             "records": {**left["records"], "quality_agent": "PENDING_APPROVAL"}})
    assert said.startswith("[FAIL] 0 ") and "make e2e-ops" in said
    for part in ("not hosted: spec_assistant", "quality_agent PENDING_APPROVAL", "guard_prompt is on (LOG_ONLY",
                 "guard_prompt_docs_adk", "the custom guardrail is attached", "stopped: quality_agent"):
        assert part in said, part
    # make e2e-ops refuses a hub whose quality_agent is not APPROVED: the record is put back first, then make e2e-ops
    assert said.index("dev_team/agent_template/publish.sh dev_team/quality_agent") < said.index("run `make e2e-ops`")


def test_line_0_names_the_command_that_puts_a_record_back_not_make_e2e_ops():
    """What a check 4 that stopped halfway leaves (quality_agent REJECTED or PENDING_APPROVAL, nothing else) is told
    with the one command that puts the record back, and the wait for its review; make e2e-ops would refuse that hub."""
    from e2e_checks import e2e_hub_ui as ui
    four = ["docs_adk", "quality_agent", "release_review", "spec_assistant"]
    left = {"hosted": four, "records": dict.fromkeys(four, "APPROVED"), "mode": None, "policies": [], "attached": False,
            "stopped": []}
    for status in ("REJECTED", "PENDING_APPROVAL"):
        said = ui.start_refusal({**left, "records": {**left["records"], "quality_agent": status}})
        assert said.startswith("[FAIL] 0 ") and f"quality_agent {status}" in said
        assert ("`dev_team/agent_template/publish.sh dev_team/quality_agent`, then wait until the hosting review page "
                "or `make e2e-ui`'s line 0 reads it APPROVED") in said
        assert "run `make e2e-ops`" not in said
    said = ui.start_refusal({**left, "records": {**left["records"], "release_review": "REJECTED"}})
    assert "publish.sh dev_team/release_review" in said and "run `make e2e-ops`" not in said
    said = ui.start_refusal({**left, "records": {**left["records"], "docs_adk": "REJECTED"}})    # make preload's agent
    assert "publish.sh" not in said and "run `make e2e-ops`" in said


def test_the_end_of_the_screen_check_names_the_command_for_a_record_left_not_approved():
    from e2e_checks import e2e_hub_ui as ui
    assert ui.record_left("quality_agent", "APPROVED") == ""
    for status in ("REJECTED", "PENDING_APPROVAL", "absent"):
        said = ui.record_left("quality_agent", status)
        assert said.startswith(f"{status}, not APPROVED: put it back with ")
        assert said.endswith("`dev_team/agent_template/publish.sh dev_team/quality_agent`, then wait until the hosting "
                             "review page or `make e2e-ui`'s line 0 reads it APPROVED")


def test_check_5_needs_at_least_one_agent_to_read_the_mode():
    from e2e_checks import e2e_hub_ui as ui
    assert ui.read_as({"a": "LOG_ONLY"}, {"a": "LOG_ONLY"}, ["a"], "LOG_ONLY")
    assert not ui.read_as({"a": "LOG_ONLY"}, {"a": "ACTIVE"}, ["a"], "LOG_ONLY")
    assert not ui.read_as({"a": None}, {"a": None}, ["a"], "LOG_ONLY")
    assert not ui.read_as({}, {}, [], "LOG_ONLY")                    # no agent: nothing was read, so it does not pass
