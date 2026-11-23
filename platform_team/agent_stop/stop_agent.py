"""Stop one hosted agent and resume it. Its neighbours are not touched.

    platform_team/agent_stop/stop.sh <agent> [--session <ID> ...]
    platform_team/agent_stop/resume.sh <agent>

stop does two things, in this order. First it blocks the agent's entry on the agent gateway: the Cedar forbid
stop_agent_<agent> on <Target>___POST:/invocations, with an exception for the review's test call role, and it waits
until the policy's status is ACTIVE. Then it ends the agent's sessions with StopRuntimeSession. Blocked first, no new
user call through the agent gateway opens a session while the sessions are looked up and ended (a direct call of the
Runtime is not blocked). resume deletes the stop policy and nothing else; neither touches the entry permit, the tool
permits or the company policies.

The sessions, unless they are given, come from the log streams of the Runtime's log group
/aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT: a session writes the stream runtime-logs-<session ID> (seen on
AWS on 2026-11-22, also for a call without the session header, whose ID is a UUID). The stream list does not say which
sessions still run, so every session whose stream is recent is ended (recent_sessions says what recent is).

The Runtime ARN comes from SSM /<prefix>/agents/<agent>/runtime_arn, which the review's deploy role can write. So it is
checked against this agent's Runtime in this account and Region before anything uses it.
"""
import re
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from platform_team.agent_gateway.gateway_targets import targets
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_engine import drop_policy, ensure_policy, list_policies
from platform_team.company_policy.policy_names import stop_agent_name
from platform_team.hosting_review.agent_cleanup import RUNTIME_LOGS, cause, check_name
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"   # a caller's session ID, through the agent gateway too
SESSION_STREAM = "runtime-logs-"        # a session's log stream in its Runtime's log group: runtime-logs-<session ID>
SESSION_ID_LENGTH = (33, 256)           # StopRuntimeSession's runtimeSessionId (service model, botocore 1.44.9)
RECENT_MINUTES = 30
# A stream's creation time is set at once. The service model's documentation says its last event and last ingestion
# times update eventually ("typically ... less than an hour"), so a recent stream is one whose latest time is recent.
STREAM_TIMES = ("creationTime", "lastEventTimestamp", "lastIngestionTime")
QUALIFIER = "DEFAULT"                   # the endpoint the agent gateway's target calls
ENDED = "ResourceNotFoundException"     # StopRuntimeSession for a session that no longer runs (seen 2026-11-22)
POLICY_WAIT = 300                       # s, until the stop policy is ACTIVE
SHOWN = 120                             # characters of a refused SSM value in an error


def runtime_arn(c, s: Settings, p: Platform, agent: str) -> str:
    """The agent's Runtime ARN from SSM /<prefix>/agents/<agent>/runtime_arn. A value that is not the ARN of this
    agent's Runtime in this account and Region raises ValueError."""
    param = s.ssm("agents", agent, "runtime_arn")
    value = c.ssm.get_parameter(Name=param)["Parameter"]["Value"]
    if not re.fullmatch(s.runtime_arn_pattern(agent, p.account), value):
        raise ValueError(f"{param} holds {value[:SHOWN]!r}, which is not the ARN of this agent's Runtime "
                         f"(runtime/{s.runtime_name(agent)}-<10 letters or digits> in this account and Region): "
                         "nothing was changed")
    return value


def log_group(arn: str) -> str:
    """The log group of a Runtime's DEFAULT endpoint: /aws/bedrock-agentcore/runtimes/<Runtime ID>-DEFAULT."""
    return f"{RUNTIME_LOGS}{arn.rsplit('/', 1)[-1]}-{QUALIFIER}"


def recent_sessions(c, s: Settings, runtime_arn: str, minutes: int = RECENT_MINUTES) -> list[str]:
    """The session IDs of the Runtime's log streams runtime-logs-<session ID> whose latest time (creation, last event
    or last ingestion) is in the last `minutes` minutes, newest first. A session that started a minute ago is found by
    its creation time. A name whose ID StopRuntimeSession would not take (SESSION_ID_LENGTH) is left out. No log group
    (the agent was never called) gives no sessions. `s` is not needed today."""
    since = (time.time() - minutes * 60) * 1000
    try:
        streams = [x for page in c.logs.get_paginator("describe_log_streams").paginate(
                       logGroupName=log_group(runtime_arn), logStreamNamePrefix=SESSION_STREAM)    # no orderBy with a prefix
                   for x in page["logStreams"]]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return []
        raise
    low, high = SESSION_ID_LENGTH
    found = []
    for x in streams:
        sid, latest = x["logStreamName"][len(SESSION_STREAM):], max(x.get(k, 0) for k in STREAM_TIMES)
        if low <= len(sid) <= high and latest >= since:
            found.append((latest, sid))
    return [sid for _, sid in sorted(found, reverse=True)]


def _entry_target(c, s: Settings, p: Platform, agent: str) -> str:
    """The agent's entry target on the agent gateway. None raises ValueError: the hub does not host the agent there."""
    target = s.target_name(agent)
    if target not in targets(c, p.agent_gw["id"]):
        raise ValueError(f"{agent} has no entry target {target} on the agent gateway, so the hub does not host it there "
                         "(a harness agent has none) and this command cannot stop it: nothing was changed")
    return target


def _not_sendable(sid: str) -> str:
    """Why StopRuntimeSession would not take this session ID, or ""."""
    low, high = SESSION_ID_LENGTH
    if low <= len(sid) <= high:
        return ""
    return f"a session ID has {low} to {high} characters (StopRuntimeSession), this one {len(sid)}: not sent"


def stop(c, s: Settings, p: Platform, agent: str, sessions: list[str] | None = None, say=print) -> dict:
    """Block the agent's entry (stop_agent_<agent>, waited on until ACTIVE), then end its sessions: the ones given, or
    recent_sessions when `sessions` is None. A session StopRuntimeSession does not find (ResourceNotFoundException, on
    AWS on 2026-11-22 "Session <ID> not found or has been terminated") has already ended: it is reported as ended, not
    as a failure. A session that cannot be stopped for another reason is reported with the reason and the rest go on.
    An agent without an entry target, or whose Runtime ARN in SSM is not its own, raises ValueError before anything is
    made. Returns {"agent", "policy", "stopped": [ID, ...], "ended": [ID, ...], "failed": {ID: reason}}."""
    check_name(agent)
    target = _entry_target(c, s, p, agent)
    arn = runtime_arn(c, s, p, agent)
    policy, role = stop_agent_name(agent), s.role("review-testcall")
    say(f"blocking the entry: {policy} refuses every call to {target} except the review's test call ({role})")
    ensure_policy(c, p.engine_id, policy, cedar.stop_agent(target, p.agent_gw["arn"], p.account, role), mode="ACTIVE",
                  wait=POLICY_WAIT)
    say(f"{policy} is ACTIVE")
    if sessions is None:
        sessions = recent_sessions(c, s, arn)
        say(f"sessions with a log stream in the last {RECENT_MINUTES} minutes ({log_group(arn)}): {len(sessions)}")
    out = {"agent": agent, "policy": policy, "stopped": [], "ended": [], "failed": {}}
    for sid in dict.fromkeys(sessions):
        why = _not_sendable(sid)
        if not why:
            try:
                c.data.stop_runtime_session(runtimeSessionId=sid, agentRuntimeArn=arn, qualifier=QUALIFIER)
            except ClientError as e:
                if e.response["Error"]["Code"] == ENDED:
                    out["ended"].append(sid)
                    say(f"session {sid}: already ended ({cause(e)})")
                    continue
                why = cause(e)
            except BotoCoreError as e:
                why = cause(e)
        if why:
            out["failed"][sid] = why
            say(f"session {sid}: not stopped ({why})")
        else:
            out["stopped"].append(sid)
            say(f"session {sid}: stopped")
    return out


def resume(c, s: Settings, p: Platform, agent: str) -> dict:
    """Delete the agent's stop policy, and nothing else. Not stopped: nothing changes. Returns {"agent", "resumed"}.
    `s` is not needed today."""
    found = list_policies(c, p.engine_id).get(stop_agent_name(check_name(agent)))
    return {"agent": agent, "resumed": bool(found) and drop_policy(c, p.engine_id, found["policyId"])}


def stopped(c, p: Platform, agent: str) -> bool:
    """Whether the agent's stop policy is there, made (status ACTIVE) and deciding (enforcement mode ACTIVE; a
    ListPolicies item may leave the mode out, and the service model says it defaults to ACTIVE)."""
    found = list_policies(c, p.engine_id).get(stop_agent_name(check_name(agent)))
    return bool(found) and found.get("status") == "ACTIVE" and found.get("enforcementMode", "ACTIVE") == "ACTIVE"


# ================================================================== the commands

USAGE = ("usage: platform_team/agent_stop/stop.sh <agent> [--session <ID> ...]\n"
         "       platform_team/agent_stop/resume.sh <agent>")


def _parse(argv: list[str]) -> tuple[str, str, list[str] | None] | None:
    """(action, agent, sessions or None) for `stop <agent> [--session <ID> ...]` or `resume <agent>`; None otherwise."""
    if len(argv) < 2 or argv[0] not in ("stop", "resume"):
        return None
    action, agent, rest = argv[0], argv[1], argv[2:]
    if action == "resume":
        return (action, agent, None) if not rest else None
    if len(rest) % 2 or any(flag != "--session" for flag in rest[::2]):
        return None
    return action, agent, rest[1::2] or None


def main(argv: list[str]) -> int:
    parsed = _parse(argv)
    if parsed is None:
        print(USAGE)
        return 2
    action, agent, sessions = parsed
    hub = "this hub"                # the first line says which hub: its prefix and region
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        print(f"agent {agent}: {action} ({hub})", flush=True)
        c = Clients.for_settings(s)
        p = load(s, c)
        if not p.engine_id or not p.agent_gw.get("id"):
            raise RuntimeError("no policy engine or agent gateway in the platform values: run `make deploy` first")
        if action == "resume":
            done = resume(c, s, p, agent)["resumed"]
            print(f"{agent} is resumed: {stop_agent_name(agent)} removed" if done else
                  f"{agent} was not stopped: nothing changed")
            return 0
        out = stop(c, s, p, agent, sessions)
    except Exception as e:          # say what failed in one line, no traceback
        print(f"{action} of {agent} did not finish ({hub}): {cause(e)}")
        return 1
    if out["failed"]:
        print(f"{agent} is blocked at the entry by {out['policy']}; {len(out['failed'])} of "
              f"{len(out['failed']) + len(out['stopped'])} sessions not stopped: run stop again, or give the session "
              "with --session <ID>")
        return 1
    print(f"{agent} is stopped: {out['policy']} blocks its entry; sessions stopped: {len(out['stopped'])}"
          + (f", already ended: {len(out['ended'])}" if out["ended"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
