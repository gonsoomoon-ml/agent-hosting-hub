"""The agents page: the hosted agents with their usage over the last hour and whether they are stopped, the tool-call
alarm (its state, its threshold and its last 15 minutes of the watched tool's calls as bars), the calls per tool, and
the Stop and Resume buttons. A button starts one job that calls the function its shell command calls:
stop_agent.stop or resume."""
from datetime import UTC, datetime, timedelta

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Request

from platform_team.agent_catalog.application_form import name_problems
from platform_team.agent_gateway.gateway_targets import targets
from platform_team.agent_monitoring import usage_report
from platform_team.agent_stop import stop_agent
from platform_team.hosting_review.agent_cleanup import cause
from platform_team.hub_ui import jobs
from platform_team.hub_ui.app import Hub, back, catalog, page, panel
from platform_team.hub_ui.reviews import application
from platform_team.hub_ui.timefmt import zone

router = APIRouter()

MINUTES = usage_report.DEFAULT_MINUTES      # the usage and the calls per tool cover the last hour
ALARM_MINUTES = 15                          # the bars
ALARM_SUFFIX = "tool-calls"                 # the alarm is <prefix>-tool-calls (agent_monitoring/terraform/main.tf)
RUNTIME, HARNESS = "Runtime", "harness"
SERVICES = {"runtime": "Amazon Bedrock AgentCore Runtime", "harness": "Amazon Bedrock AgentCore Harness",
            "catalog": "AWS Agent Registry", "metrics": "Amazon CloudWatch", "alarm": "Amazon CloudWatch alarm",
            "engine": "Policy in Amazon Bedrock AgentCore", "gateway": "Amazon Bedrock AgentCore Gateway"}


def _now() -> datetime:
    return datetime.now(UTC)


def minute_series(points: dict[str, float], minutes: int, now: datetime) -> list[tuple[str, int]]:
    """One (HH:MM, calls) per minute of the last `minutes` minutes, the last one being the minute of `now`, oldest first.
    `points` is the data points by their HH:MM (in the zone of `now`); a minute with no point is 0, a point outside
    the window is left out, and the calls are whole numbers."""
    labels = [(now - timedelta(minutes=i)).strftime("%H:%M") for i in range(minutes - 1, -1, -1)]
    return [(label, round(points.get(label, 0))) for label in labels]


def _alarm_series(hub: Hub, alarm: dict) -> list[tuple[str, int]]:
    """The alarm's own metric (its namespace, metric and dimensions) as one-minute sums for the last ALARM_MINUTES
    minutes (CloudWatch GetMetricData), one value per minute."""
    now = _now().astimezone(zone(hub.zone))
    start = (now - timedelta(minutes=ALARM_MINUTES - 1)).replace(second=0, microsecond=0)
    query = {"Id": "calls", "MetricStat": {"Metric": {"Namespace": alarm["Namespace"], "MetricName": alarm["MetricName"],
                                                      "Dimensions": alarm["Dimensions"]},
                                           "Period": alarm.get("Period", 60), "Stat": alarm.get("Statistic", "Sum")}}
    pages = hub.c.cw.get_paginator("get_metric_data").paginate(MetricDataQueries=[query], StartTime=start, EndTime=now)
    points: dict[str, float] = {}
    for pg in pages:
        for result in pg["MetricDataResults"]:
            for at, value in zip(result.get("Timestamps", []), result.get("Values", [])):
                label = at.astimezone(zone(hub.zone)).strftime("%H:%M")
                points[label] = points.get(label, 0) + value
    return minute_series(points, ALARM_MINUTES, now)


def _alarm(hub: Hub) -> dict | None:
    """The alarm <prefix>-tool-calls: {"name", "state", "threshold", "tool", "series": [(HH:MM, calls)] * 15,
    "series_error"}. A series that cannot be read leaves series empty and says why in series_error; the alarm's state
    still shows. None when AWS has no such alarm."""
    name = f"{hub.s.prefix}-{ALARM_SUFFIX}"
    found = hub.c.cw.describe_alarms(AlarmNames=[name])["MetricAlarms"]
    alarm = next((a for a in found if a["AlarmName"] == name), None)
    if alarm is None:
        return None
    threshold = alarm.get("Threshold")
    out = {"name": name, "state": alarm.get("StateValue", ""),
           "threshold": int(threshold) if isinstance(threshold, float) and threshold.is_integer() else threshold,
           "tool": next((d["Value"] for d in alarm.get("Dimensions", []) if d["Name"] == "Name"), ""),
           "series": [], "series_error": ""}
    try:
        out["series"] = _alarm_series(hub, alarm)
    except Exception as e:              # the bars only: the state and the threshold stay
        out["series_error"] = hub.mask(cause(e))
    return out


def _row(hub: Hub, agent: str, arn: str, records: dict, entries: dict | None, entries_error: str) -> dict:
    """One agent: its catalog record's status, team and framework, how it is hosted, whether it is stopped (True or
    False as stop_agent.stopped reads it; None when it is not read: a harness agent, which has no entry to block, or
    a read that failed) and whether it can be stopped here. What one read cannot give stays on this row (app_error,
    stop_error)."""
    hosted_as = HARNESS if arn.rsplit("/", 1)[-1].startswith(hub.s.harness_runtime_name("")) else RUNTIME
    record = records.get(agent)
    row = {"agent": agent, "team": "", "framework": "", "status": (record or {}).get("status", ""),
           "hosted_as": hosted_as, "stopped": None, "stop_error": entries_error, "app_error": "",
           "can_stop": None if entries is None else hub.s.target_name(agent) in entries, "usage": None}
    if record is not None:
        try:
            app = application(hub, record)
            row["team"], row["framework"] = str(app.get("team") or ""), str(app.get("framework") or "")
        except Exception as e:          # this agent's application only
            row["app_error"] = hub.mask(cause(e))
    if hosted_as == RUNTIME:            # a harness agent has no entry to block
        try:
            row["stopped"] = stop_agent.stopped(hub.c, hub.platform(), agent)
        except Exception as e:          # this agent's stop state only: neither Stop nor Resume is offered
            row["stopped"], row["stop_error"] = None, hub.mask(cause(e))
    return row


def _agents(hub: Hub) -> list[dict]:
    """The hosted agents (usage_report.hosted_agents), by name, without their usage."""
    hosted = usage_report.hosted_agents(hub.c, hub.s)
    records = catalog(hub) if hosted else {}
    try:
        entries, entries_error = targets(hub.c, hub.platform().agent_gw["id"]), ""
    except Exception as e:              # every row says so; the rows still show
        entries, entries_error = None, hub.mask(cause(e))
    return [_row(hub, agent, arn, records, entries, entries_error) for agent, arn in sorted(hosted.items())]


def view(hub: Hub, minutes: int = MINUTES) -> dict:
    """The page's reads, each a panel (a failing read is one line there): agents (one row per hosted agent; their usage
    over `minutes` minutes comes from one read: when it fails the rows show without it and the panel carries
    usage_error), tools ({tool: calls} over `minutes`) and alarm (None when there is none)."""
    hub.platform()                      # NotDeployed: the page that says so, before any panel
    rows = panel(hub, "agents.list", lambda: _agents(hub))
    usage = panel(hub, f"agents.usage.{minutes}", lambda: usage_report.usage(hub.c, hub.s, hub.platform(), minutes))
    if rows["ok"]:
        # a copy: the cache keeps the rows without usage
        agents = [{**r, "usage": usage["value"].get(r["agent"]) if usage["ok"] else None} for r in rows["value"]]
        rows = {"ok": True, "value": agents, "usage_error": "" if usage["ok"] else usage["error"]}
    job = hub.jobs.current()
    return {"agents": rows,
            "tools": panel(hub, f"agents.tools.{minutes}",
                           lambda: usage_report.tool_calls(hub.c, hub.s, hub.platform(), minutes)),
            "alarm": panel(hub, "agents.alarm", lambda: _alarm(hub)),
            "busy": job is not None and job.state == jobs.RUNNING}


@router.get("/agents")
def agents_page(request: Request):
    return page(request, "agents.html", view=view(request.app.state.hub), services=SERVICES, minutes=MINUTES,
                alarm_minutes=ALARM_MINUTES)


def _stop_job(hub: Hub, agent: str, say) -> dict:
    """What stop.sh does: stop_agent.stop (its lines go to the job), then one line for the sessions."""
    out = stop_agent.stop(hub.c, hub.s, hub.platform(), agent, say=say)
    say(f"sessions: {len(out['stopped'])} stopped, {len(out['ended'])} already ended, {len(out['failed'])} not stopped")
    if out["failed"]:                   # the command exits 1 here, with this line
        raise RuntimeError(f"{agent} is blocked at the entry by {out['policy']}; {len(out['failed'])} of "
                           f"{len(out['failed']) + len(out['stopped'])} sessions not stopped: run stop again, or give "
                           "the session with --session <ID>")
    return out


def _resume_job(hub: Hub, agent: str, say) -> dict:
    """What resume.sh does: stop_agent.resume, and one line for what it returned."""
    out = stop_agent.resume(hub.c, hub.s, hub.platform(), agent)
    say("resumed" if out["resumed"] else "it was not stopped: nothing changed")
    return out


def _press(request: Request, agent: str, kind: str, run):
    hub: Hub = request.app.state.hub
    if name_problems(agent):
        return back(request, "/agents", err="agent")        # a name the form refuses
    try:
        hosted = usage_report.hosted_agents(hub.c, hub.s)
    except (ClientError, BotoCoreError):                     # a POST never renders a page: back, with the sentence
        return back(request, "/agents", err="unread")
    if agent not in hosted:
        return back(request, "/agents", err="agent")        # no hosted agent of that name
    hub.jobs.start(kind, agent, lambda say: run(hub, agent, say))       # jobs.Busy: the app answers
    return back(request, "/agents", msg="started")


@router.post("/agents/{agent}/stop")
def stop(request: Request, agent: str):
    """Start the job that blocks the agent's entry and ends its recent sessions."""
    return _press(request, agent, "stop", _stop_job)


@router.post("/agents/{agent}/resume")
def resume(request: Request, agent: str):
    """Start the job that lets the agent's requests in again."""
    return _press(request, agent, "resume", _resume_job)
