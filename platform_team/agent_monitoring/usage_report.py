"""How the hosted agents use the hub, read from CloudWatch: per agent its calls, sessions, errors, CPU and memory; per
catalog tool its calls; per session of one agent the spans it left. Reads only.

    platform_team/agent_monitoring/usage.sh [minutes]          (the last 60 minutes by default)

The metrics are AgentCore's own, in the namespace AWS/Bedrock-AgentCore, with the names and dimensions this account
listed on 2026-11-22:
  calls of a Runtime's endpoint DEFAULT: Invocations, Sessions, Errors with Name=<Runtime name>::DEFAULT,
    Operation=InvokeAgentRuntime, Resource=<Runtime ARN>
  what a Runtime used: CPUUsed-vCPUHours, MemoryUsed-GBHours with Name, Resource and Service=AgentCore.Runtime
  calls of a tool through the tool gateway: Invocations with Method=tools/call, Name=<Target>___<tool>,
    Operation=InvokeGateway, Protocol=MCP, Resource=<tool gateway ARN>
Each is the sum of its one-minute data points in the window; a metric with no data point there reads 0. The AgentCore
developer guide says the Runtime's metrics come in one-minute batches and its resource usage may be up to 60 minutes
late ("AgentCore generated runtime observability data", read on 2026-11-22).

The hosted agents are the Runtimes named <prefix>_<agent> (Settings.runtime_name) whose <agent> is a valid agent
name, so another team's Runtime and another prefix's are not read.
"""
import sys
import time
from datetime import datetime, timedelta, timezone

from platform_team.agent_catalog.application_form import name_problems
from platform_team.hosting_review.agent_cleanup import RUNTIME_LOGS, cause
from platform_team.sample_tools.tool_schema import TARGETS
from platform_team.shared_code.aws_helpers import Clients, all_items
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

NAMESPACE = "AWS/Bedrock-AgentCore"
ENDPOINT = "DEFAULT"                      # the endpoint the agent gateway's target calls
PERIOD = 60                               # s: one data point a minute
# key in the report -> metric name. CALLS count the endpoint's calls; USE is what the Runtime used.
CALLS = {"invocations": "Invocations", "sessions": "Sessions", "errors": "Errors"}
USE = {"cpu_vcpu_hours": "CPUUsed-vCPUHours", "memory_gb_hours": "MemoryUsed-GBHours"}
DEFAULT_MINUTES = 60
# Spans: the AgentCore guide says an agent's spans go to the stream `spans` of its own log group or, for an agent on
# the shared destination, to the account's log group aws/spans ("Add observability to your Amazon Bedrock AgentCore
# resources", read on 2026-11-22). Both are read. On AWS on 2026-11-22 the spans of a hosted agent were in aws/spans
# only (its own `spans` stream stayed empty), and each carried the session ID in attributes.session.id.
SPANS_GROUP, SPANS_STREAM, SESSION_FIELD = "aws/spans", "spans", "attributes.session.id"
QUERY_WAIT, QUERY_STEP = 120, 2           # s, until a Logs Insights query is Complete


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _window(minutes: int) -> dict:
    end = _now()
    return {"StartTime": end - timedelta(minutes=minutes), "EndTime": end}


def _query(qid: str, metric: str, dims: dict) -> dict:
    """One metric's one-minute sums, its dimensions in name order (the order the metric list shows)."""
    return {"Id": qid, "MetricStat": {"Metric": {"Namespace": NAMESPACE, "MetricName": metric,
                                                 "Dimensions": [{"Name": k, "Value": v} for k, v in sorted(dims.items())]},
                                      "Period": PERIOD, "Stat": "Sum"}}


def _sums(c, queries: list[dict], minutes: int) -> dict[str, float]:
    """Each query's data points added up over the last `minutes` minutes, by query ID (every page)."""
    out = {q["Id"]: 0.0 for q in queries}
    for page in c.cw.get_paginator("get_metric_data").paginate(MetricDataQueries=queries, **_window(minutes)):
        for result in page["MetricDataResults"]:
            out[result["Id"]] += sum(result.get("Values", []))
    return out


def hosted_agents(c, s: Settings) -> dict[str, str]:
    """The hub's hosted agents and their Runtime ARNs, by agent name: the Runtimes named <prefix>_<agent> (every page
    of ListAgentRuntimes)."""
    head = s.runtime_name("")
    found = {}
    for runtime in all_items(c.ctl.list_agent_runtimes, maxResults=100):
        name = runtime["agentRuntimeName"]
        if name.startswith(head) and not name_problems(name[len(head):]):
            found[name[len(head):]] = runtime["agentRuntimeArn"]
    return dict(sorted(found.items()))


def usage(c, s: Settings, p: Platform, minutes: int = DEFAULT_MINUTES) -> dict[str, dict]:
    """Per hosted agent, over the last `minutes` minutes: invocations, sessions and errors of its endpoint DEFAULT
    (whole numbers), and the vCPU-hours and GB-hours its Runtime used. `p` is not needed today."""
    out = {}
    for agent, arn in hosted_agents(c, s).items():
        name = f"{s.runtime_name(agent)}::{ENDPOINT}"
        calls = {"Name": name, "Operation": "InvokeAgentRuntime", "Resource": arn}
        use = {"Name": name, "Resource": arn, "Service": "AgentCore.Runtime"}
        sums = _sums(c, [_query(k, m, calls) for k, m in CALLS.items()] + [_query(k, m, use) for k, m in USE.items()],
                     minutes)
        out[agent] = {**{k: round(sums[k]) for k in CALLS}, **{k: sums[k] for k in USE}}
    return out


def catalog_tools() -> list[str]:
    """Every tool an application may name, as <Target>___<tool> (the tool gateway's targets), in name order."""
    return sorted(f"{target}___{tool['name']}" for target, tools in TARGETS.items() for tool in tools)


def tool_calls(c, s: Settings, p: Platform, minutes: int = DEFAULT_MINUTES) -> dict[str, int]:
    """Per catalog tool, its calls through the tool gateway in the last `minutes` minutes, by every caller.
    `s` is not needed today."""
    tools = catalog_tools()
    queries = [_query(f"tool{i}", "Invocations", {"Method": "tools/call", "Name": tool, "Operation": "InvokeGateway",
                                                  "Protocol": "MCP", "Resource": p.tool_gw["arn"]})
               for i, tool in enumerate(tools)]
    sums = _sums(c, queries, minutes)
    return {tool: round(sums[f"tool{i}"]) for i, tool in enumerate(tools)}


# ================================================================== the sessions of one agent, from its spans

def _insights(c, group: str, query: str, minutes: int) -> list[dict]:
    """The rows of one Logs Insights query on one log group, as {field: value}. A group that is not there gives none."""
    end = _now()
    try:
        qid = c.logs.start_query(logGroupName=group, queryString=query,
                                 startTime=int((end - timedelta(minutes=minutes)).timestamp()),
                                 endTime=int(end.timestamp()))["queryId"]
    except c.logs.exceptions.ResourceNotFoundException:
        return []
    t0 = time.monotonic()
    while True:
        out = c.logs.get_query_results(queryId=qid)
        if out["status"] == "Complete":
            return [{f["field"]: f["value"] for f in row} for row in out["results"]]
        if out["status"] in ("Failed", "Cancelled", "Timeout", "Unknown") or time.monotonic() - t0 > QUERY_WAIT:
            raise RuntimeError(f"the Logs Insights query on {group} ended {out['status']}")
        time.sleep(QUERY_STEP)


def session_summary(c, s: Settings, agent: str, minutes: int = DEFAULT_MINUTES) -> list[dict]:
    """The sessions of the agent's Runtime in the last `minutes` minutes, from its spans: per session the number of
    spans and the times of the first and the last (as Logs Insights prints @timestamp, UTC), most spans first. The
    spans in aws/spans are this Runtime's when they name its ID (their resource attributes do). An agent without a
    Runtime has none."""
    arn = hosted_agents(c, s).get(agent)
    if arn is None:
        return []
    rid = arn.rsplit("/", 1)[-1]
    stats = (f"filter ispresent(`{SESSION_FIELD}`) | stats count(*) as spans, min(@timestamp) as first, "
             f"max(@timestamp) as last by `{SESSION_FIELD}`")
    rows = (_insights(c, f"{RUNTIME_LOGS}{rid}-{ENDPOINT}", f'filter @logStream = "{SPANS_STREAM}" | {stats}', minutes)
            + _insights(c, SPANS_GROUP, f'filter @message like "{rid}" | {stats}', minutes))
    merged: dict[str, dict] = {}
    for row in rows:
        sid = row[SESSION_FIELD]
        seen = merged.setdefault(sid, {"session": sid, "spans": 0, "first": row["first"], "last": row["last"]})
        seen["spans"] += int(row["spans"])
        seen["first"], seen["last"] = min(seen["first"], row["first"]), max(seen["last"], row["last"])
    return sorted(merged.values(), key=lambda x: (-x["spans"], x["session"]))


# ================================================================== the command

USAGE = "usage: platform_team/agent_monitoring/usage.sh [minutes]   (a whole number of minutes, 60 if not given)"


def _table(header: list[str], rows: list[list]) -> list[str]:
    """The rows under the header, the first column to the left and the others to the right."""
    cells = [header] + [[str(x) for x in row] for row in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    return ["  ".join(v.ljust(w) if i == 0 else v.rjust(w) for i, (v, w) in enumerate(zip(r, widths))) for r in cells]


def report(agents: dict[str, dict], tools: dict[str, int]) -> list[str]:
    """The two tables: the hosted agents, then the catalog tools."""
    rows = [[a, u["invocations"], u["sessions"], u["errors"], f"{u['cpu_vcpu_hours']:.6f}", f"{u['memory_gb_hours']:.6f}"]
            for a, u in agents.items()]
    lines = _table(["agent", "invocations", "sessions", "errors", "vCPU-hours", "GB-hours"], rows) if rows else \
        ["no hosted agent"]
    return lines + [""] + _table(["tool", "calls"], [[t, n] for t, n in tools.items()])


def main(argv: list[str]) -> int:
    if len(argv) > 1 or (argv and not (argv[0].isdigit() and int(argv[0]) > 0)):
        print(USAGE)
        return 2
    minutes = int(argv[0]) if argv else DEFAULT_MINUTES
    hub = "this hub"
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        c = Clients.for_settings(s)
        p = load(s, c)
        if not p.tool_gw.get("arn"):
            raise RuntimeError("no tool gateway in the platform values: run `make deploy` first")
        agents, tools = usage(c, s, p, minutes), tool_calls(c, s, p, minutes)
    except Exception as e:          # one line, no traceback (a traceback could print the account ID)
        print(f"usage report did not finish ({hub}): {cause(e)}")
        return 1
    print(f"use of the hosted agents in the last {minutes} minutes ({hub})")
    print("\n".join(report(agents, tools)))
    print("Calls come in one-minute batches; CPU and memory may be up to 60 minutes late (AgentCore developer guide).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
