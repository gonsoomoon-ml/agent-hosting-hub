"""Remove what the hosting review made for an agent. None of it is in Terraform's state.

    python -m platform_team.hosting_review.agent_cleanup        # make destroy, before terraform destroy

What the review makes for an agent: Grant makes the execution role (with its inline policy) and one tool permit per
tool; Deploy (the AgentCore CLI, with CDK) makes a CloudFormation stack that holds the Runtime and writes the Runtime
ARN to SSM; the Runtime writes its own log groups; Entry makes the gateway target, the test call's entry permit and
the guard; Approve makes the users' entry permit.

remove_agent removes one agent's things (reject_agent calls it). clean_agents removes every agent's things and its
catalog record, approved agents too (make destroy calls it): an agent role keeps Terraform from deleting the
permissions boundary policy, and a registry that still has records cannot be deleted.

Every name comes from Settings and the review's own naming functions for that one agent, never from a pattern
wider than it. A thing that is not there is already gone, so running again is safe; any other error stops the
run and says which step failed.

Kept on purpose: the submitted zip in the submission bucket (the record of what was submitted; the bucket goes with
terraform destroy) and the code CDK uploaded to the account's CDK bootstrap bucket (shared with other stacks).
"""
import re
import sys

from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import NAME_PATTERN
from platform_team.agent_catalog.catalog_records import drop_record, records
from platform_team.agent_gateway.gateway_targets import drop_target, targets
from platform_team.company_policy.cedar_statements import entry_action
from platform_team.company_policy.policy_engine import drop_policy, list_policies
from platform_team.hosting_review import review_steps as steps
from platform_team.sample_tools.tool_schema import TARGETS
from platform_team.shared_code.aws_helpers import Clients, wait_status
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

TARGET_WAIT = 300        # s, until a deleted gateway target is gone
STACK_WAIT = 900         # s, until a Runtime's stack is deleted
STACK_STEP = 10          # s, between two looks at the stack
# A Runtime's log group is /aws/bedrock-agentcore/runtimes/<Runtime ID>-<endpoint>, and its ID is
# <Runtime name>-<10 letters or digits>. A Runtime name has no "-", so the name and the "-" after it are exact.
RUNTIME_LOGS = "/aws/bedrock-agentcore/runtimes/"
RUNTIME_ID_TAIL = r"[A-Za-z0-9]{10}(-.*)?"


class CleanupFailed(RuntimeError):
    """A removal failed. Says where, why, and what this run removed before it (`removed`)."""

    def __init__(self, where: str, error: Exception, removed: list[str]):
        super().__init__(where)
        self.where, self.error, self.removed = where, error, list(removed)

    def __str__(self) -> str:
        return f"{self.where} failed ({cause(self.error)}); removed before it: {', '.join(self.removed) or 'nothing'}"


def cause(e: Exception) -> str:
    """An error as one line, with any 12-digit account ID masked."""
    err = e.response.get("Error") if isinstance(e, ClientError) else None
    text = f"{err.get('Code')}: {err.get('Message', '')}" if err else f"{type(e).__name__}: {e}"
    return re.sub(r"(?<![0-9])[0-9]{12}(?![0-9])", "<ACCOUNT>", " ".join(text.split()))


def check_name(agent: str) -> str:
    """The agent's name, if it is one the application form allows; every name below is built from it."""
    if not isinstance(agent, str) or not re.fullmatch(NAME_PATTERN, agent):
        raise ValueError(f"agent name {agent!r} must match {NAME_PATTERN}")
    return agent


def _code(e: Exception) -> str:
    return e.response.get("Error", {}).get("Code", "") if isinstance(e, ClientError) else ""


def _delete(call, *gone: str) -> bool:
    """Run a delete call. False when the thing was already gone (the error code is one of `gone`)."""
    try:
        call()
    except ClientError as e:
        if _code(e) in gone:
            return False
        raise
    return True


# ================================================================== one agent

def policy_names(agent: str) -> list[str]:
    """Every policy name the review can make for this agent, from the review's naming functions and the catalog's
    tools (Read refuses any other tool): the entry permits first, the tool permits, the guard last, so no call gets
    in unguarded while they go."""
    tools = sorted(f"{target}___{t['name']}" for target, tools in TARGETS.items() for t in tools)
    return [steps.entry_name(agent), steps.entry_review_name(agent),
            *(steps.tool_permit_name(agent, t) for t in tools), steps.guard_name(agent)]


def _statement(policy: dict) -> str:
    definition = policy.get("definition") or {}
    return (definition.get("cedar") or definition.get("policy") or {}).get("statement", "")


def _remove_policies(c, s: Settings, p: Platform, agent: str) -> list[str]:
    if not p.engine_id:
        return []                                       # no policy engine, no policies
    try:
        found = list_policies(c, p.engine_id)
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return []                                   # the engine is gone, and its policies with it
        raise
    # entry_permit_<a> and entry_permit_review_<b> are one name when a is review_<b>, the only names two agents can
    # share. Those two are removed only when their statement names this agent's target.
    shared, action = {steps.entry_name(agent), steps.entry_review_name(agent)}, entry_action(s.target_name(agent))
    removed = []
    for name in policy_names(agent):
        policy = found.get(name)
        if not policy or (name in shared and action not in _statement(policy)):
            continue
        if drop_policy(c, p.engine_id, policy["policyId"]):
            removed.append(f"policy {name}")
    return removed


def _remove_target(c, s: Settings, p: Platform, agent: str) -> list[str]:
    gateway, name = p.agent_gw.get("id"), s.target_name(agent)
    if not gateway:
        return []
    try:
        found = targets(c, gateway).get(name)
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return []                                   # the gateway is gone, and its targets with it
        raise
    if not found or not drop_target(c, gateway, found["targetId"], name, wait=TARGET_WAIT):
        return []
    return [f"target {name}"]


def _stack_status(c, name: str) -> dict:
    try:
        stack = c.cfn.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as e:
        if _code(e) == "ValidationError" and "does not exist" in e.response["Error"].get("Message", ""):
            return {"status": "GONE"}
        raise
    return {"status": stack["StackStatus"], "statusReason": stack.get("StackStatusReason")}


def _remove_stack(c, name: str) -> list[str]:
    """Delete the stack that holds the Runtime and wait until it is gone. DELETE_FAILED raises with the reason."""
    gone = ("GONE", "DELETE_COMPLETE")
    if _stack_status(c, name)["status"] in gone:
        return []
    c.cfn.delete_stack(StackName=name)
    wait_status(lambda: _stack_status(c, name), gone, f"stack {name}", timeout=STACK_WAIT, step=STACK_STEP)
    return [f"stack {name}"]


def _remove_log_groups(c, runtime: str) -> list[str]:
    prefix = f"{RUNTIME_LOGS}{runtime}-"
    own = re.compile(re.escape(prefix) + RUNTIME_ID_TAIL)
    names = sorted(g["logGroupName"] for page in c.logs.get_paginator("describe_log_groups").paginate(
        logGroupNamePrefix=prefix) for g in page["logGroups"])
    return [f"log group {n}" for n in names
            if own.fullmatch(n) and _delete(lambda n=n: c.logs.delete_log_group(logGroupName=n),
                                            "ResourceNotFoundException")]


def _remove_role(c, name: str) -> list[str]:
    """Delete the execution role, its inline policies first. Its permissions boundary is attached, not owned."""
    try:
        inline = [n for page in c.iam.get_paginator("list_role_policies").paginate(RoleName=name)
                  for n in page["PolicyNames"]]
    except ClientError as e:
        if _code(e) == "NoSuchEntity":
            return []
        raise
    for policy in inline:
        _delete(lambda policy=policy: c.iam.delete_role_policy(RoleName=name, PolicyName=policy), "NoSuchEntity")
    return [f"role {name}"] if _delete(lambda: c.iam.delete_role(RoleName=name), "NoSuchEntity") else []


def _remove_parameters(c, s: Settings, agent: str) -> list[str]:
    path = s.ssm("agents", agent)
    names = sorted(prm["Name"] for page in c.ssm.get_paginator("get_parameters_by_path").paginate(
        Path=path, Recursive=True) for prm in page["Parameters"] if prm["Name"].startswith(path + "/"))
    return [f"parameter {n}" for n in names if _delete(lambda n=n: c.ssm.delete_parameter(Name=n), "ParameterNotFound")]


def remove_agent(c, s: Settings, p: Platform, agent: str) -> list[str]:
    """Remove what the hosting review made for this agent, in this order: its policies, its gateway target (waits
    until it is gone), the stack that holds its Runtime (waits until it is gone), the Runtime's log groups, its
    execution role, and its SSM values. Returns what was removed, as "<kind> <name>"; what was not there is not
    listed. A step that fails raises CleanupFailed, and the steps after it do not run."""
    check_name(agent)
    try:
        stack, runtime = s.stack_name(agent), s.runtime_name(agent)
    except ValueError:              # no CLI project name for this agent: Deploy could not have made a stack or Runtime
        stack = runtime = None
    plan = [("policies", lambda: _remove_policies(c, s, p, agent)),
            ("gateway target", lambda: _remove_target(c, s, p, agent)),
            ("Runtime stack", lambda: _remove_stack(c, stack) if stack else []),
            ("Runtime log groups", lambda: _remove_log_groups(c, runtime) if runtime else []),
            ("execution role", lambda: _remove_role(c, s.agent_role(agent))),
            ("SSM values", lambda: _remove_parameters(c, s, agent))]
    removed = []
    for step, run in plan:
        try:
            removed += run()
        except Exception as e:
            raise CleanupFailed(f"{agent}: removing the {step}", e, removed) from e
    return removed


# ================================================================== every agent (make destroy)

def _catalog_agents(c, p: Platform) -> dict[str, dict]:
    """The AGENT records of the catalog; none when there is no catalog (any more)."""
    if not p.registry_id:
        return {}
    try:
        return {name: r for name, r in records(c, p.registry_id).items() if r.get("recordType") == "AGENT"}
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return {}
        raise


def agent_names(c, s: Settings, p: Platform) -> list[str]:
    """Every agent the hub may hold something for, whether or not the catalog is still whole: the catalog's AGENT
    records, the SSM values under /<prefix>/agents/<agent>/, and the roles named Settings.agent_role(<agent>)."""
    found = set(_catalog_agents(c, p))
    base = s.ssm("agents") + "/"
    found |= {prm["Name"][len(base):].split("/")[0]
              for page in c.ssm.get_paginator("get_parameters_by_path").paginate(Path=s.ssm("agents"), Recursive=True)
              for prm in page["Parameters"] if prm["Name"].startswith(base)}
    head, tail = s.agent_role("\0").split("\0")         # the role name around the agent's name
    for page in c.iam.get_paginator("list_roles").paginate():
        for role in page["Roles"]:
            name = role["RoleName"]
            if name.startswith(head) and name.endswith(tail) and len(name) > len(head) + len(tail):
                found.add(name[len(head):len(name) - len(tail)])
    return sorted(a for a in found if re.fullmatch(NAME_PATTERN, a))


def _remove_record(c, p: Platform, agent: str) -> list[str]:
    rec = _catalog_agents(c, p).get(agent)
    if not rec:
        return []
    drop_record(c, p.registry_id, rec["recordId"])
    return [f"record {agent}"]


def clean_agents(s: Settings, c=None) -> list[str]:
    """Remove every agent's things (remove_agent) and then its catalog record, approved agents too. Runs before
    terraform destroy, so it does not need the platform to be whole. Returns everything removed; a failure raises
    CleanupFailed with everything removed before it."""
    c = c or Clients.for_settings(s)
    try:
        p = load(s, c)
    except RuntimeError:            # no platform values in SSM: no engine, gateway or catalog to look in
        p = Platform()
    removed = []
    try:
        try:
            agents = agent_names(c, s, p)
        except Exception as e:
            raise CleanupFailed("finding the agents", e, []) from e
        for agent in agents:
            removed += remove_agent(c, s, p, agent)
            try:
                removed += _remove_record(c, p, agent)
            except Exception as e:
                raise CleanupFailed(f"{agent}: removing the catalog record", e, []) from e
    except CleanupFailed as e:
        e.removed[:0] = removed
        raise
    return removed


def main() -> int:
    try:
        removed = clean_agents(Settings.from_env())
    except Exception as e:          # say what failed in one line, no traceback
        print(f"agents not cleaned: {e if isinstance(e, CleanupFailed) else cause(e)}")
        return 1
    for line in removed:
        print(f"removed {line}")
    print(f"agents cleaned: {len(removed)} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
