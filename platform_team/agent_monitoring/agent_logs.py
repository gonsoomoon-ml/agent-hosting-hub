"""Read the newest log lines of a hosted agent's Runtime.

    demo_scenes/logs <agent> [minutes]          # 15 minutes if not given

The Runtime's log group is /aws/bedrock-agentcore/runtimes/<Runtime name>-<10 characters>-DEFAULT, found with
DescribeLogGroups (no SSM read) and read with FilterLogEvents, for the streams runtime-logs-<session ID> only. The
stream otel-rt-logs, which on 2026-11-22 held a copy of the same lines, and the other streams (spans, build-logs-*)
are left out. Prints the newest 200 lines of the time, oldest first, the account masked. Exit 0, 1 when the lines
could not be read or the agent has no log group, 2 for bad usage.
"""
import re
import sys
import time

from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import name_problems
from platform_team.agent_stop.stop_agent import QUALIFIER, SESSION_STREAM
from platform_team.hosting_review.agent_cleanup import RUNTIME_LOGS, cause
from platform_team.shared_code.aws_helpers import Clients, mask
from platform_team.shared_code.config import RUNTIME_ID_TAIL, Settings

USAGE = "usage: demo_scenes/logs <agent> [minutes]"
DEFAULT_MINUTES = 15
LIMIT = 200


class NoLogGroup(LookupError):
    """The agent has no Runtime log group: it was never called, or the hub does not host it."""


def _log_groups(c, s: Settings, agent: str) -> list[str]:
    """The DEFAULT-endpoint log groups of the agent's Runtime (a harness agent's Runtime is harness_<prefix>_<agent>)."""
    names = (s.runtime_name(agent), s.harness_runtime_name(agent))
    own = [re.compile(re.escape(f"{RUNTIME_LOGS}{n}") + RUNTIME_ID_TAIL + f"-{QUALIFIER}") for n in names]
    found = {g["logGroupName"] for n in names for page in c.logs.get_paginator("describe_log_groups").paginate(
        logGroupNamePrefix=f"{RUNTIME_LOGS}{n}-") for g in page["logGroups"]}
    return sorted(n for n in found if any(p.fullmatch(n) for p in own))


def recent_lines(c, s: Settings, agent: str, minutes: int = DEFAULT_MINUTES, limit: int = LIMIT) -> list[str]:
    """The newest `limit` log lines of the agent's Runtime from the last `minutes` minutes, oldest first, only from the
    streams runtime-logs-<session ID>. No log group raises NoLogGroup. A line is its message without the line end."""
    groups = _log_groups(c, s, agent)
    if not groups:
        raise NoLogGroup(f"no log group for {agent} (the Runtime {s.runtime_name(agent)}-<10 characters> "
                         f"has not been called, or this hub does not host it)")
    since = int((time.time() - minutes * 60) * 1000)
    events = []
    for group in groups:
        try:
            events += [e for page in c.logs.get_paginator("filter_log_events").paginate(
                           logGroupName=group, startTime=since, logStreamNamePrefix=SESSION_STREAM)
                       for e in page["events"]]
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":      # a group deleted since the listing
                raise
    events.sort(key=lambda e: e["timestamp"])
    return [e["message"].rstrip("\n") for e in events][-limit:]


def main(argv: list[str]) -> int:
    if not 1 <= len(argv) <= 2 or (len(argv) == 2 and not (argv[1].isdigit() and int(argv[1]) > 0)):
        print(USAGE)
        return 2
    agent, minutes = argv[0], int(argv[1]) if len(argv) == 2 else DEFAULT_MINUTES
    problems = name_problems(agent)
    if problems:
        print(f"agent name {agent!r}: {'; '.join(problems)}")
        return 2
    try:
        s = Settings.from_env()
        c = Clients.for_settings(s)
        found = recent_lines(c, s, agent, minutes)
        account = c.account
    except NoLogGroup as e:
        print(e)
        return 1
    except Exception as e:          # one line, no traceback (a traceback could print the account ID)
        print(f"logs of {agent} did not finish: {cause(e)}")
        return 1
    if not found:
        print(f"no log lines in the last {minutes} minutes for {agent}")
        return 0
    print(mask("\n".join([f"{agent}: the newest {len(found)} log lines of the last {minutes} minutes", *found]), account))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
