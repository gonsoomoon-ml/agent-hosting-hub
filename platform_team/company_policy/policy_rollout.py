"""Company policies: one policy per hosted agent that the platform team turns on for every agent, first in log-only
mode (it records what it would refuse), then in active mode.

    platform_team/company_policy/rollout.sh <policy> log-only|active|off|report
    python -m platform_team.company_policy.policy_rollout --forget        # make destroy, before the agents' cleanup

The mode a company policy is in is kept in SSM, /<prefix>/policies/<policy> = LOG_ONLY or ACTIVE (no value: off).
The hosting review's Approve step reads it there and gives a newly approved agent every deployed company policy in
its mode (apply_to_agent). So rollout writes the mode first and lists the agents after: an agent approved before
the write has its entry target already, so rollout finds it and gives it the policy; one approved after the write
reads the new mode itself. remove deletes the value first, then the policies: an approval that reads the mode after
the delete gives no policy, but one that read it just before can still make the policy after remove listed the
agents, and running remove again deletes that one.

A hosted agent has a value under /<prefix>/agents/<agent>/ and an entry target on the agent gateway (the review's
Entry step makes it). A harness has no entry target, so no company policy reaches it.
"""
import datetime
import sys
from typing import Callable, NamedTuple

from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import name_problems
from platform_team.agent_gateway.gateway_targets import targets
from platform_team.company_policy import cedar_statements as cedar
from platform_team.company_policy.policy_engine import MODES, drop_policy, ensure_policy, list_policies
from platform_team.company_policy.policy_names import guard_prompt_name
from platform_team.hosting_review.agent_cleanup import cause, check_name
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

POLICY_WAIT = 300           # s, until a new or switched policy is ACTIVE
REPORT_MINUTES = 60         # report reads the metrics of the last hour
METRICS = "AWS/Bedrock-AgentCore"
MATCHES, FLIPS = "LogOnlyMatches", "LogOnlyDecisionFlips"


class CompanyPolicy(NamedTuple):
    name: Callable[[str], str]                  # agent -> the policy's name (policy_names)
    statement: Callable[[str, str], str]        # (entry target, agent gateway ARN) -> the Cedar statement
    guardrail: bool = True                      # a guardrail policy (definition key `policy`)


POLICIES = {"guard_prompt": CompanyPolicy(guard_prompt_name, cedar.guard_prompt)}
MODE_WORDS = {"log-only": "LOG_ONLY", "active": "ACTIVE"}


def _policy(key: str) -> CompanyPolicy:
    if key not in POLICIES:
        raise ValueError(f"unknown company policy {key!r}: one of {', '.join(POLICIES)}")
    return POLICIES[key]


def _under(c, path: str, recursive: bool = False) -> list[dict]:
    """The SSM values whose names start with <path>/ (every page). The path is passed as the IAM policy names it."""
    kw = {"Recursive": True} if recursive else {}
    return [prm for page in c.ssm.get_paginator("get_parameters_by_path").paginate(Path=path, **kw)
            for prm in page["Parameters"] if prm["Name"].startswith(path + "/")]


def _delete_parameter(c, name: str) -> bool:
    """Delete one SSM value. False when it was not there."""
    try:
        c.ssm.delete_parameter(Name=name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ParameterNotFound":
            raise
        return False
    return True


def deployed(c, s: Settings) -> dict[str, str]:
    """The company policies that are on, and their modes: the values directly under /<prefix>/policies/.
    A value rollout would not write (a policy or a mode this hub does not know) raises ValueError."""
    base = s.ssm("policies") + "/"
    out = {}
    for prm in _under(c, s.ssm("policies")):
        key = prm["Name"][len(base):]
        if "/" in key:
            continue                            # not directly under the path (SSM does not list it without Recursive)
        if key not in POLICIES or prm["Value"] not in MODES:
            raise ValueError(f"{prm['Name']} holds {prm['Value'][:40]!r}: not written by rollout (a policy of "
                             f"{', '.join(POLICIES)}, a mode of {', '.join(MODES)})")
        out[key] = prm["Value"]
    return out


def hosted_agents(c, s: Settings, p: Platform) -> list[str]:
    """The agents with a value under /<prefix>/agents/<agent>/ and an entry target on the agent gateway, sorted."""
    base = s.ssm("agents") + "/"
    named = {prm["Name"][len(base):].split("/")[0] for prm in _under(c, s.ssm("agents"), recursive=True)}
    entries = targets(c, p.agent_gw["id"])
    return sorted(a for a in named if not name_problems(a) and s.target_name(a) in entries)


def _ensure(c, s: Settings, p: Platform, policy: CompanyPolicy, agent: str, mode: str, wait: int) -> str:
    return ensure_policy(c, p.engine_id, policy.name(agent), policy.statement(s.target_name(agent), p.agent_gw["arn"]),
                         guardrail=policy.guardrail, mode=mode, wait=wait)


def rollout(c, s: Settings, p: Platform, key: str, mode_word: str, say=print) -> dict:
    """Turn a company policy on in this mode (MODE_WORDS) for every hosted agent. The mode is written to SSM first,
    then each hosted agent's policy is made in it or switched to it. Returns {"policy", "mode", "agents": {agent:
    "created" | "switched" | "unchanged" | "failed"}}. An agent that fails is told through `say` with the cause and
    the others still get the policy; the mode stays written, so the next rollout or approval uses it. An unknown
    policy or mode raises ValueError before anything changes."""
    policy = _policy(key)
    if mode_word not in MODE_WORDS:
        raise ValueError(f"unknown mode {mode_word!r}: one of {', '.join(MODE_WORDS)} (off removes the policy)")
    mode = MODE_WORDS[mode_word]
    c.ssm.put_parameter(Name=s.ssm("policies", key), Value=mode, Type="String", Overwrite=True)
    agents = hosted_agents(c, s, p)
    before = list_policies(c, p.engine_id)
    out = {}
    for agent in agents:
        found = before.get(policy.name(agent))
        try:
            _ensure(c, s, p, policy, agent, mode, POLICY_WAIT)
        except Exception as e:                  # one agent's failure does not keep the policy from the others
            out[agent] = "failed"
            say(f"{agent}: failed ({cause(e)})")
            continue
        out[agent] = ("created" if not found else
                      "switched" if found.get("enforcementMode", mode) != mode else "unchanged")
        say(f"{agent}: {out[agent]}")
    return {"policy": key, "mode": mode, "agents": out}


def _with_policy(c, p: Platform, policy: CompanyPolicy) -> dict[str, dict]:
    """agent -> the policy engine's entry for this company policy, for every agent name the rules allow."""
    prefix = policy.name("")
    found = {}
    for name, entry in list_policies(c, p.engine_id).items():
        agent = name[len(prefix):]
        if name.startswith(prefix) and not name_problems(agent) and policy.name(agent) == name:
            found[agent] = entry
    return dict(sorted(found.items()))


def remove(c, s: Settings, p: Platform, key: str, say=print) -> dict:
    """Turn a company policy off: delete its SSM value first (an approval that reads the mode from now on gives no
    policy; see the module docstring for one that read it just before), then the policy of every agent that has it,
    hosted or not. Returns {"policy", "agents": {agent: "removed"}}."""
    policy = _policy(key)
    _delete_parameter(c, s.ssm("policies", key))
    out = {}
    for agent, entry in _with_policy(c, p, policy).items():
        if drop_policy(c, p.engine_id, entry["policyId"]):
            out[agent] = "removed"
            say(f"{agent}: removed")
    return {"policy": key, "agents": out}


def apply_to_agent(c, s: Settings, p: Platform, agent: str, wait: int = POLICY_WAIT) -> dict[str, str]:
    """Give one agent every deployed company policy in its mode (the review's Approve step calls it); each policy
    waits up to `wait` seconds until it is ACTIVE. A policy of its name that is there in the mode is kept. One there
    in another mode is not switched: rollout switches modes, and the Approve role cannot (it has no UpdatePolicy), so
    that raises RuntimeError and the policy stays as it is. Returns {policy: mode}; nothing deployed, nothing done."""
    check_name(agent)
    on = deployed(c, s)
    found = list_policies(c, p.engine_id) if on else {}
    for key, mode in on.items():
        policy = POLICIES[key]
        have = found.get(policy.name(agent), {}).get("enforcementMode", mode)
        if have != mode:
            word = next(w for w, m in MODE_WORDS.items() if m == mode)
            raise RuntimeError(f"policy {policy.name(agent)} is {have}, but {s.ssm('policies', key)} is {mode}: the "
                               f"approval does not switch modes; rollout.sh {key} {word} does")
        _ensure(c, s, p, policy, agent, mode, wait)
    return on


def forget(c, s: Settings) -> list[str]:
    """Delete every value under /<prefix>/policies/ and return their names (make destroy, before the agents' cleanup,
    which removes the policies with the agents)."""
    names = sorted(prm["Name"] for prm in _under(c, s.ssm("policies")))
    return [name for name in names if _delete_parameter(c, name)]


def _sum(c, metric: str, dimensions: list[dict], start, end, period: int) -> int:
    points = c.cw.get_metric_statistics(Namespace=METRICS, MetricName=metric, Dimensions=dimensions, StartTime=start,
                                        EndTime=end, Period=period, Statistics=["Sum"])["Datapoints"]
    return int(round(sum(d.get("Sum", 0) for d in points)))


def report(c, s: Settings, p: Platform, key: str, minutes: int = REPORT_MINUTES) -> dict[str, dict]:
    """For every agent that has this company policy: its mode and, over the last `minutes`, the sums of
    LogOnlyMatches and LogOnlyDecisionFlips (namespace AWS/Bedrock-AgentCore; dimensions OperationName=AuthorizeAction,
    Policy=<policy ID>, PolicyEngine=<engine ID>, TargetResource=<agent gateway ID>).
    Returns {agent: {"mode", "matches", "flips"}}."""
    policy = _policy(key)
    if not isinstance(minutes, int) or minutes < 1:
        raise ValueError(f"minutes must be a whole number of at least 1: {minutes!r}")
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(minutes=minutes)
    out = {}
    for agent, entry in _with_policy(c, p, policy).items():
        dims = [{"Name": "OperationName", "Value": "AuthorizeAction"}, {"Name": "Policy", "Value": entry["policyId"]},
                {"Name": "PolicyEngine", "Value": p.engine_id}, {"Name": "TargetResource", "Value": p.agent_gw["id"]}]
        out[agent] = {"mode": entry.get("enforcementMode"),
                      "matches": _sum(c, MATCHES, dims, start, end, minutes * 60),
                      "flips": _sum(c, FLIPS, dims, start, end, minutes * 60)}
    return out


# ================================================================== the command

ACTIONS = (*MODE_WORDS, "off", "report")
USAGE = (f"usage: platform_team/company_policy/rollout.sh <policy> {'|'.join(ACTIONS)}"
         f"  (policies: {', '.join(POLICIES)})\n"
         "       python -m platform_team.company_policy.policy_rollout --forget")


def _forget_command() -> int:
    hub = "this hub"
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        gone = forget(Clients.for_settings(s), s)
    except Exception as e:          # say what failed in one line, no traceback
        print(f"company policy modes not forgotten ({hub}): {cause(e)}")
        return 1
    for name in gone:
        print(f"removed parameter {name}")
    print(f"company policy modes forgotten ({hub}): {len(gone)} removed")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["--forget"]:
        return _forget_command()
    if len(argv) != 2 or argv[0] not in POLICIES or argv[1] not in ACTIONS:
        print(USAGE)
        return 2
    key, action = argv
    hub = "this hub"                # the first line says which hub: its prefix and region
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        print(f"company policy {key}: {action} ({hub})", flush=True)
        c = Clients.for_settings(s)
        p = load(s, c)
        if not p.engine_id or not p.agent_gw.get("id"):
            raise RuntimeError("no policy engine or agent gateway in the platform values: run `make deploy` first")
        if action == "report":
            found = report(c, s, p, key)
            for agent, r in found.items():
                print(f"{agent}: {r['mode']}, {MATCHES} {r['matches']}, {FLIPS} {r['flips']} "
                      f"(last {REPORT_MINUTES} minutes)")
            print(f"{key} is on {len(found)} agents" if found else f"no agent has {key}")
            return 0
        if action == "off":
            out = remove(c, s, p, key)
            print(f"{key} is off: removed from {len(out['agents'])} agents")
            return 0
        out = rollout(c, s, p, key, action)
    except Exception as e:          # say what failed in one line, no traceback
        print(f"{action} of {key} stopped ({hub}): {e if isinstance(e, ValueError) else cause(e)}")
        return 1
    failed = [a for a, word in out["agents"].items() if word == "failed"]
    if failed:
        print(f"{key} is {out['mode']} in SSM; {len(failed)} of {len(out['agents'])} agents failed: "
              "run the command again")
        return 1
    print(f"{key} is {out['mode']} on {len(out['agents'])} agents")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
