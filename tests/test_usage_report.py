# tests/test_usage_report.py  (botocore Stubber on cloudwatch)
"""The usage report's reads, checked against the AWS service models on this machine: the clients are real boto3
clients in a botocore Stubber, so every operation and parameter name is validated against the model and every answer
against the operation's output shape. No network and no credentials."""
import datetime

import boto3
import pytest
from botocore.stub import Stubber

from platform_team.agent_monitoring import usage_report
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform

ACCOUNT, REGION = "123456789012", "us-west-2"
NOW = datetime.datetime(2026, 11, 22, 9, 0, tzinfo=datetime.timezone.utc)
S = Settings()
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/hub_quality_agent-Ab12Cd34Ef"
TOOL_GW_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/hub-tools-abcdefghij"
P = Platform(account=ACCOUNT, tool_gw={"id": "hub-tools-abcdefghij", "arn": TOOL_GW_ARN, "url": "u"})


@pytest.fixture
def aws(monkeypatch, tmp_path):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setattr(usage_report, "_now", lambda: NOW)
    c = Clients(boto3.Session(region_name=REGION, aws_access_key_id="test-access-key", aws_secret_access_key="example"))
    stubs = {name: Stubber(getattr(c, name)) for name in ("ctl", "cw")}
    for st in stubs.values():
        st.activate()
    yield c, stubs
    for st in stubs.values():
        st.assert_no_pending_responses()
        st.deactivate()


def _runtime(name, arn):
    return {"agentRuntimeArn": arn, "agentRuntimeId": arn.rsplit("/", 1)[-1], "agentRuntimeVersion": "1",
            "agentRuntimeName": name, "description": "hosted agent", "lastUpdatedAt": NOW, "status": "READY"}


def _list_runtimes(st):
    st.add_response("list_agent_runtimes", {"agentRuntimes": [
        _runtime("hub_quality_agent", RUNTIME_ARN),
        _runtime("other_team_runtime", f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/other_team_runtime-Zz98Yy76Xx"),
        _runtime("hubwhole_quality_agent", f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/hubwhole_quality_agent-Qq11Ww22Ee"),
    ]}, {"maxResults": 100})


def _query(qid, metric, dims):
    return {"Id": qid, "MetricStat": {"Metric": {"Namespace": "AWS/Bedrock-AgentCore", "MetricName": metric,
                                                 "Dimensions": [{"Name": k, "Value": v} for k, v in dims]},
                                      "Period": 60, "Stat": "Sum"}}


def _result(qid, values):
    return {"Id": qid, "Label": qid, "Timestamps": [NOW] * len(values), "Values": values, "StatusCode": "Complete"}


CALL = [("Name", "hub_quality_agent::DEFAULT"), ("Operation", "InvokeAgentRuntime"), ("Resource", RUNTIME_ARN)]
USE = [("Name", "hub_quality_agent::DEFAULT"), ("Resource", RUNTIME_ARN), ("Service", "AgentCore.Runtime")]
RUNTIME_QUERIES = [_query("invocations", "Invocations", CALL), _query("sessions", "Sessions", CALL),
                   _query("errors", "Errors", CALL), _query("cpu_vcpu_hours", "CPUUsed-vCPUHours", USE),
                   _query("memory_gb_hours", "MemoryUsed-GBHours", USE)]
WINDOW = {"StartTime": NOW - datetime.timedelta(minutes=30), "EndTime": NOW}


def test_usage_asks_for_each_agents_runtime_by_name_and_arn(aws):
    """Dimensions for Invocations: Name = "hub_quality_agent::DEFAULT", Operation = "InvokeAgentRuntime", Resource = <runtime ARN>;
    for CPUUsed-vCPUHours: Name, Resource, Service = "AgentCore.Runtime"."""
    c, st = aws
    _list_runtimes(st["ctl"])           # one Runtime of the hub; another team's and another prefix's are not asked for
    st["cw"].add_response("get_metric_data", {"MetricDataResults": [
        _result("invocations", [2.0, 1.0]), _result("sessions", [1.0]), _result("errors", []),
        _result("cpu_vcpu_hours", [0.0004, 0.0002]), _result("memory_gb_hours", [0.0012])]},
        {"MetricDataQueries": RUNTIME_QUERIES, **WINDOW})
    out = usage_report.usage(c, S, P, minutes=30)
    assert list(out) == ["quality_agent"]
    row = out["quality_agent"]
    assert (row["invocations"], row["sessions"], row["errors"]) == (3, 1, 0)
    assert row["cpu_vcpu_hours"] == pytest.approx(0.0006) and row["memory_gb_hours"] == pytest.approx(0.0012)


def test_an_agent_with_no_data_points_reads_zero_not_missing(aws):
    c, st = aws
    _list_runtimes(st["ctl"])
    st["cw"].add_response("get_metric_data", {"MetricDataResults": [_result(q["Id"], []) for q in RUNTIME_QUERIES]},
                          {"MetricDataQueries": RUNTIME_QUERIES, **WINDOW})
    out = usage_report.usage(c, S, P, minutes=30)
    assert out == {"quality_agent": {"invocations": 0, "sessions": 0, "errors": 0, "cpu_vcpu_hours": 0, "memory_gb_hours": 0}}


HARNESS_RUNTIME_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/harness_hub_spec_assistant-Ab12Cd34Ef"


def test_a_harness_agent_is_listed_by_the_runtime_agentcore_runs_it_on(aws):
    """AgentCore runs a harness agent on a Runtime it names harness_<prefix>_<agent> (Settings.harness_runtime_name):
    the report lists that Runtime under the agent's name and asks for its metrics by that Runtime's own name. A harness
    Runtime of another prefix, and one whose rest is not an agent name, are not listed."""
    c, st = aws
    for _ in range(2):              # once for hosted_agents, once for usage
        st["ctl"].add_response("list_agent_runtimes", {"agentRuntimes": [
            _runtime("harness_hub_spec_assistant", HARNESS_RUNTIME_ARN),
            _runtime("harness_hubwhole_spec_assistant",
                     f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/harness_hubwhole_spec_assistant-Qq11Ww22Ee"),
            _runtime("harness_hub_Bad__name", f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/harness_hub_Bad__name-Zz98Yy76Xx"),
        ]}, {"maxResults": 100})
    assert usage_report.hosted_agents(c, S) == {"spec_assistant": HARNESS_RUNTIME_ARN}
    call = [("Name", "harness_hub_spec_assistant::DEFAULT"), ("Operation", "InvokeAgentRuntime"),
            ("Resource", HARNESS_RUNTIME_ARN)]
    use = [("Name", "harness_hub_spec_assistant::DEFAULT"), ("Resource", HARNESS_RUNTIME_ARN),
           ("Service", "AgentCore.Runtime")]
    queries = [_query("invocations", "Invocations", call), _query("sessions", "Sessions", call),
               _query("errors", "Errors", call), _query("cpu_vcpu_hours", "CPUUsed-vCPUHours", use),
               _query("memory_gb_hours", "MemoryUsed-GBHours", use)]
    st["cw"].add_response("get_metric_data", {"MetricDataResults": [
        _result("invocations", [2.0]), _result("sessions", [2.0]), _result("errors", []),
        _result("cpu_vcpu_hours", []), _result("memory_gb_hours", [])]}, {"MetricDataQueries": queries, **WINDOW})
    out = usage_report.usage(c, S, P, minutes=30)
    assert list(out) == ["spec_assistant"] and (out["spec_assistant"]["invocations"], out["spec_assistant"]["sessions"]) == (2, 2)


def test_tool_calls_reads_one_metric_per_catalog_tool(aws):      # Method tools/call, Operation InvokeGateway, Protocol MCP, Resource = tool gateway ARN
    c, st = aws
    tools = ["Parts___get_part_spec", "Parts___get_test_result", "Quality___get_inspection_data", "Release___file_review_request"]
    queries = [_query(f"tool{i}", "Invocations", [("Method", "tools/call"), ("Name", tool), ("Operation", "InvokeGateway"),
                                                  ("Protocol", "MCP"), ("Resource", TOOL_GW_ARN)])
               for i, tool in enumerate(tools)]
    st["cw"].add_response("get_metric_data", {"MetricDataResults": [
        _result("tool0", [3.0]), _result("tool1", []), _result("tool2", [40.0, 7.0]), _result("tool3", [1.0])]},
        {"MetricDataQueries": queries, **WINDOW})
    assert usage_report.tool_calls(c, S, P, minutes=30) == {
        "Parts___get_part_spec": 3, "Parts___get_test_result": 0, "Quality___get_inspection_data": 47,
        "Release___file_review_request": 1}


@pytest.mark.parametrize("argv", [["abc"], ["0"], ["-5"], ["30", "x"]])
def test_the_command_takes_at_most_one_whole_number_of_minutes(argv, capsys):
    assert usage_report.main(argv) == 2
    assert capsys.readouterr().out.strip() == usage_report.USAGE          # nothing was read from AWS


def test_the_report_is_a_table_of_agents_and_a_table_of_tools():
    lines = usage_report.report(
        {"release_review": {"invocations": 3, "sessions": 1, "errors": 0, "cpu_vcpu_hours": 0.0004, "memory_gb_hours": 0}},
        {"Parts___get_part_spec": 2, "Release___file_review_request": 0})
    assert lines == [
        "agent           invocations  sessions  errors  vCPU-hours  GB-hours",
        "release_review            3         1       0    0.000400  0.000000",
        "",
        "tool                           calls",
        "Parts___get_part_spec              2",
        "Release___file_review_request      0"]
    assert usage_report.report({}, {})[0] == "no hosted agent"


def _rows(*rows):
    return {"status": "Complete", "results": [[{"field": k, "value": v} for k, v in row.items()] for row in rows]}


def test_session_summary_counts_each_sessions_spans_most_first(aws, monkeypatch):
    """Spans are read where the AgentCore guide says they go: the stream `spans` of the Runtime's log group, and the
    account's aws/spans, there by the Runtime's ID. The session is the span attribute session.id (attributes.session.id,
    as the spans in aws/spans had it on 2026-11-22). A Runtime's log group that is not there gives no rows."""
    c, st = aws
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    stats = ("filter ispresent(`attributes.session.id`) | stats count(*) as spans, min(@timestamp) as first, "
             "max(@timestamp) as last by `attributes.session.id`")
    window = {"startTime": int((NOW - datetime.timedelta(minutes=30)).timestamp()), "endTime": int(NOW.timestamp())}
    logs = Stubber(c.logs)
    with logs:
        _list_runtimes(st["ctl"])
        logs.add_client_error("start_query", "ResourceNotFoundException", expected_params={
            "logGroupName": "/aws/bedrock-agentcore/runtimes/hub_quality_agent-Ab12Cd34Ef-DEFAULT",
            "queryString": f'filter @logStream = "spans" | {stats}', **window})
        logs.add_response("start_query", {"queryId": "q-1"}, {
            "logGroupName": "aws/spans", "queryString": f'filter @message like "hub_quality_agent-Ab12Cd34Ef" | {stats}',
            **window})
        logs.add_response("get_query_results", {"status": "Running", "results": []}, {"queryId": "q-1"})
        logs.add_response("get_query_results", _rows(
            {"attributes.session.id": "abcdefghij-session-of-the-test-call-01", "spans": "3",
             "first": "2026-11-22 19:10:18.864", "last": "2026-11-22 19:10:18.866"},
            {"attributes.session.id": "usage-report-check-abcdefghij0123456789abcdefghij01", "spans": "9",
             "first": "2026-11-22 19:11:12.312", "last": "2026-11-22 19:11:14.175"}), {"queryId": "q-1"})
        out = usage_report.session_summary(c, S, "quality_agent", minutes=30)
        logs.assert_no_pending_responses()
    assert out == [
        {"session": "usage-report-check-abcdefghij0123456789abcdefghij01", "spans": 9,
         "first": "2026-11-22 19:11:12.312", "last": "2026-11-22 19:11:14.175"},
        {"session": "abcdefghij-session-of-the-test-call-01", "spans": 3,
         "first": "2026-11-22 19:10:18.864", "last": "2026-11-22 19:10:18.866"}]


def test_an_agent_without_a_runtime_has_no_sessions(aws):
    c, st = aws
    _list_runtimes(st["ctl"])
    assert usage_report.session_summary(c, S, "release_review") == []
