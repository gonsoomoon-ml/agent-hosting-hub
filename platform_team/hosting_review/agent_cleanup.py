"""Remove what the hosting review made for an agent. None of it is in Terraform's state.

    python -m platform_team.hosting_review.agent_cleanup        # make destroy, before terraform destroy

What the review makes for an agent: Grant makes the execution role (with its inline policy) and one tool permit per
tool; Deploy (the AgentCore CLI, with CDK) makes a CloudFormation stack that holds the Runtime and writes the Runtime
ARN to SSM; the Runtime writes its own log groups; Entry makes the gateway target, the test call's entry permit and
the guard; Approve makes the users' entry permit.

remove_agent removes one agent's things (reject_agent calls it). clean_agents removes every agent's things and its
catalog record, approved agents too (make destroy calls it): an agent role keeps Terraform from deleting the
permissions boundary policy, and a registry that still has records cannot be deleted.

Every name comes from Settings and company_policy.policy_names for that one agent, never from a pattern wider
than it. A name is not proof enough for the role and the stack, so before anything is deleted check_agent reads
them: the role must carry the hub's agent boundary (Grant can make no other agent role) and have no managed policy
or instance profile, and the stack must hold this agent's Runtime. Anything else is not this hub's, and nothing of
that agent is deleted. A thing that is not there is already gone, so running again is safe; any other error stops
the run and says which step failed.

Kept on purpose: the submitted zip in the submission bucket (the record of what was submitted; the bucket goes with
terraform destroy) and the code CDK uploaded to the account's CDK bootstrap bucket (shared with other stacks).
"""
import json
import re
import sys

from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import name_problems
from platform_team.agent_catalog.catalog_records import drop_record, records
from platform_team.agent_gateway.gateway_targets import drop_target, targets
from platform_team.company_policy.policy_engine import drop_policy, list_policies
from platform_team.company_policy.policy_names import policy_names
from platform_team.sample_tools.tool_schema import TARGETS
from platform_team.shared_code.aws_helpers import Clients, wait_status
from platform_team.shared_code.config import RUNTIME_ID_TAIL, Settings
from platform_team.shared_code.hub_state import Platform, load

TARGET_WAIT = 300        # s, until a deleted gateway target is gone
STACK_WAIT = 900         # s, until a Runtime's stack is deleted
STACK_STEP = 10          # s, between two looks at the stack
# A Runtime's log group is /aws/bedrock-agentcore/runtimes/<Runtime ID>-<endpoint>, and its ID is
# <Runtime name>-<10 letters or digits>. A Runtime name has no "-", so the name and the "-" after it are exact.
RUNTIME_LOGS = "/aws/bedrock-agentcore/runtimes/"
RUNTIME_LOG_TAIL = RUNTIME_ID_TAIL + r"(-.*)?"
RUNTIME_TYPE = "AWS::BedrockAgentCore::Runtime"     # its physical ID in a stack is the Runtime ID (Task 0's run)


class NotOwned(ValueError):
    """A role or stack has the agent's name but is not this hub's as it stands. Nothing of the agent is deleted."""


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
    problems = name_problems(agent)
    if problems:
        raise ValueError(f"agent name {agent!r}: {'; '.join(problems)}")
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


# ================================================================== is it this hub's? (reads only)

def _boundary(c, role: str) -> str | None:
    """The ARN of the role's permissions boundary ("" for none); None when there is no such role."""
    try:
        found = c.iam.get_role(RoleName=role)["Role"]
    except ClientError as e:
        if _code(e) == "NoSuchEntity":
            return None
        raise
    return (found.get("PermissionsBoundary") or {}).get("PermissionsBoundaryArn", "")


def _hub_boundary(s: Settings, arn: str) -> bool:
    return arn.endswith(f":policy/{s.agent_boundary}")


def _check_role(c, s: Settings, agent: str) -> None:
    role = s.agent_role(agent)
    arn = _boundary(c, role)
    if arn is None:
        return
    if not _hub_boundary(s, arn):
        shown = arn.rsplit("/", 1)[-1] if arn else "none"
        raise NotOwned(f"role {role} is not this hub's: its permissions boundary is {shown}, not {s.agent_boundary}")
    attached = [p["PolicyName"] for page in c.iam.get_paginator("list_attached_role_policies").paginate(RoleName=role)
                for p in page["AttachedPolicies"]]
    if attached:
        raise NotOwned(f"role {role} has managed policies {', '.join(attached)} that the hub does not attach: "
                       "detach them first")
    profiles = [p["InstanceProfileName"] for page in c.iam.get_paginator("list_instance_profiles_for_role").paginate(
        RoleName=role) for p in page["InstanceProfiles"]]
    if profiles:
        raise NotOwned(f"role {role} has instance profiles {', '.join(profiles)} that the hub does not make: "
                       "remove the role from them first")


def _stack_gone(e: Exception) -> bool:
    return _code(e) == "ValidationError" and "does not exist" in e.response["Error"].get("Message", "")


def _template_runtimes(c, stack: str) -> list[str]:
    """The Runtime names the stack's template declares."""
    body = c.cfn.get_template(StackName=stack)["TemplateBody"]      # botocore parses a JSON template into a dict
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return []
    return [(r.get("Properties") or {}).get("AgentRuntimeName", "") for r in (body.get("Resources") or {}).values()
            if isinstance(r, dict) and r.get("Type") == RUNTIME_TYPE]


def _check_stack(c, stack: str, runtime: str) -> None:
    """The stack must hold this agent's Runtime: a Runtime resource whose physical ID is <runtime>-<10 characters>,
    or, when no Runtime was made (a deploy that rolled back), a template that declares the Runtime <runtime>."""
    if _stack_status(c, stack)["status"] in ("GONE", "DELETE_COMPLETE"):
        return
    try:
        held = [r.get("PhysicalResourceId") or "" for page in c.cfn.get_paginator("list_stack_resources").paginate(
            StackName=stack) for r in page["StackResourceSummaries"] if r["ResourceType"] == RUNTIME_TYPE]
        own = re.compile(re.escape(runtime) + RUNTIME_ID_TAIL)
        if any(own.fullmatch(h) for h in held):
            return
        made = [h for h in held if h]
        if not made and runtime in _template_runtimes(c, stack):
            return
    except ClientError as e:
        if _stack_gone(e):
            return
        raise
    raise NotOwned(f"stack {stack} does not hold this agent's Runtime {runtime}: it holds "
                   f"{', '.join(made) or 'no Runtime made for it'}")


def check_agent(c, s: Settings, agent: str) -> None:
    """Raise NotOwned when the agent's role or stack exists but is not this hub's as it stands. Reads only."""
    check_name(agent)
    _check_role(c, s, agent)
    try:
        stack, runtime = s.stack_name(agent), s.runtime_name(agent)
    except ValueError:              # no CLI project name for this agent: Deploy could not have made a stack
        return
    _check_stack(c, stack, runtime)


# ================================================================== one agent

def _catalog_tools() -> list[str]:
    """Every tool the review can permit (Read refuses any other)."""
    return sorted(f"{target}___{t['name']}" for target, tools in TARGETS.items() for t in tools)


def _remove_policies(c, p: Platform, agent: str) -> list[str]:
    if not p.engine_id:
        return []                                       # no policy engine, no policies
    try:
        found = list_policies(c, p.engine_id)
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return []                                   # the engine is gone, and its policies with it
        raise
    removed = []
    for name in policy_names(agent, _catalog_tools()):     # entry permits first, the guard last
        policy = found.get(name)
        if policy and drop_policy(c, p.engine_id, policy["policyId"]):
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
        if _stack_gone(e):
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
    own = re.compile(re.escape(f"{RUNTIME_LOGS}{runtime}") + RUNTIME_LOG_TAIL)
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
    listed. check_agent runs first: a role or stack that is not this hub's stops it before anything is deleted. A
    step that fails raises CleanupFailed, and the steps after it do not run."""
    check_name(agent)
    try:
        check_agent(c, s, agent)
    except Exception as e:
        raise CleanupFailed(f"{agent}: checking that its role and stack are this hub's", e, []) from e
    try:
        stack, runtime = s.stack_name(agent), s.runtime_name(agent)
    except ValueError:              # no CLI project name for this agent: Deploy could not have made a stack or Runtime
        stack = runtime = None
    plan = [("policies", lambda: _remove_policies(c, p, agent)),
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


def agent_names(c, s: Settings, p: Platform, say=print) -> list[str]:
    """Every agent the hub may hold something for, whether or not the catalog is still whole: the catalog's AGENT
    records, the SSM values under /<prefix>/agents/<agent>/, and the roles named Settings.agent_role(<agent>) that
    carry the hub's agent boundary. A role with that name but another boundary, or none, is not the hub's: it is
    skipped with one line and its name is not taken as an agent."""
    found = set(_catalog_agents(c, p))
    base = s.ssm("agents") + "/"
    found |= {prm["Name"][len(base):].split("/")[0]
              for page in c.ssm.get_paginator("get_parameters_by_path").paginate(Path=s.ssm("agents"), Recursive=True)
              for prm in page["Parameters"] if prm["Name"].startswith(base)}
    head, tail = s.agent_role("\0").split("\0")         # the role name around the agent's name
    for page in c.iam.get_paginator("list_roles").paginate():
        for role in page["Roles"]:
            name = role["RoleName"]
            agent = name[len(head):len(name) - len(tail)]
            if not (name.startswith(head) and name.endswith(tail) and len(name) > len(head) + len(tail)) \
                    or name_problems(agent):
                continue
            arn = _boundary(c, name)
            if arn is not None and _hub_boundary(s, arn):
                found.add(agent)
            elif arn is not None:
                say(f"skipped {name}: not made by this hub")
    return sorted(a for a in found if not name_problems(a))


def _remove_record(c, p: Platform, agent: str) -> list[str]:
    rec = _catalog_agents(c, p).get(agent)
    if not rec:
        return []
    drop_record(c, p.registry_id, rec["recordId"])
    return [f"record {agent}"]


def clean_agents(s: Settings, c=None, say=print) -> list[str]:
    """Remove every agent's things (remove_agent) and then its catalog record, approved agents too. Runs before
    terraform destroy, so it does not need the platform to be whole. Returns everything removed; a failure raises
    CleanupFailed with everything removed before it. `say` gets one line per role skipped as not this hub's."""
    c = c or Clients.for_settings(s)
    try:
        p = load(s, c)
    except RuntimeError:            # no platform values in SSM: no engine, gateway or catalog to look in
        p = Platform()
    removed = []
    try:
        try:
            agents = agent_names(c, s, p, say)
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
    hub = "this hub"
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        removed = clean_agents(s)
    except Exception as e:          # say what failed in one line, no traceback
        print(f"agents not cleaned ({hub}): {e if isinstance(e, CleanupFailed) else cause(e)}")
        return 1
    for line in removed:
        print(f"removed {line}")
    print(f"agents cleaned ({hub}): {len(removed)} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
