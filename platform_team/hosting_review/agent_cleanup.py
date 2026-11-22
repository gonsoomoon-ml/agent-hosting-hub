"""Remove what the hosting review made for an agent. None of it is in Terraform's state.

    python -m platform_team.hosting_review.agent_cleanup              # make destroy, first
    python -m platform_team.hosting_review.agent_cleanup --records    # make destroy, right before terraform destroy

What the review makes for an agent: Grant makes the execution role (with its inline policy) and one tool permit per
tool; Deploy puts the code package in the inbox (packages/<agent>/<code version>.zip), creates or updates the Runtime
<prefix>_<agent> (CreateAgentRuntime, UpdateAgentRuntime) and writes the Runtime ARN to SSM; the Runtime writes its
own log groups; Entry makes the gateway target, the test call's entry permit and the guard; Approve makes the users'
entry permit.

remove_agent removes one agent's things (reject_agent calls it). clean_agents removes every agent's things and its
catalog record, approved agents too (make destroy calls it): an agent role keeps Terraform from deleting the
permissions boundary policy, and a registry that still has records cannot be deleted. remove_records (--records,
make destroy only, after the agents and the seed) deletes whatever record is still in the hub's registry and says
each one: a record of another type, or with a name the rules refuse, is not an agent the steps above find.

Every name comes from Settings and company_policy.policy_names for that one agent, never from a pattern wider
than it. A name is not proof enough for the role and the Runtime, so before anything is deleted check_agent reads
them: the role must carry the hub's agent boundary (Grant can make no other agent role) and have no managed policy
or instance profile, and the Runtime of the agent's name must run under the agent's role in its own account.
Anything else is not this hub's, and nothing of that agent is deleted. A thing that is not there is already gone,
so running again is safe; any other error stops the run and says which step failed.

Kept on purpose: the submitted zip in the inbox (the record of what was submitted; the bucket goes with terraform
destroy). Without the platform values in SSM the bucket's name is not known, and the packages stay for terraform
destroy, which empties the bucket.
"""
import re
import sys

from botocore.exceptions import ClientError

from platform_team.agent_catalog.application_form import name_problems
from platform_team.agent_catalog.catalog_records import drop_record, records
from platform_team.agent_gateway.gateway_targets import drop_target, targets
from platform_team.company_policy.policy_engine import drop_policy, list_policies
from platform_team.company_policy.policy_names import (entry_permit_name, guard_prompt_name, guard_secret_name,
                                                       review_permit_name, stop_agent_name, tool_policy_pattern)
from platform_team.shared_code.aws_helpers import Clients, all_items, wait_status
from platform_team.shared_code.config import PACKAGES, RUNTIME_ID_TAIL, Settings
from platform_team.shared_code.hub_state import Platform, load

TARGET_WAIT = 300        # s, until a deleted gateway target is gone
RUNTIME_WAIT = 600       # s, until a deleted Runtime is gone
RUNTIME_STEP = 5         # s, between two looks at the Runtime
# A Runtime's log group is /aws/bedrock-agentcore/runtimes/<Runtime ID>-<endpoint>, and its ID is
# <Runtime name>-<10 letters or digits>. A Runtime name has no "-", so the name and the "-" after it are exact.
RUNTIME_LOGS = "/aws/bedrock-agentcore/runtimes/"
RUNTIME_LOG_TAIL = RUNTIME_ID_TAIL + r"(-.*)?"
_ROLE_ARN = re.compile(r"arn:aws:iam::([0-9]{12}):role/(.+)")
_RUNTIME_ARN = re.compile(r"arn:aws:bedrock-agentcore:[a-z0-9-]+:([0-9]{12}):runtime/.+")


class NotOwned(ValueError):
    """A role or Runtime has the agent's name but is not this hub's as it stands. Nothing of the agent is deleted."""


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


def _find_runtime(c, name: str) -> dict | None:
    """The Runtime of this name as GetAgentRuntime gives it (with its roleArn), or None. Every page is read."""
    found = next((r for r in all_items(c.ctl.list_agent_runtimes, maxResults=100) if r["agentRuntimeName"] == name), None)
    if found is None:
        return None
    try:
        return c.ctl.get_agent_runtime(agentRuntimeId=found["agentRuntimeId"])
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return None                                 # deleted between the two calls
        raise


def _check_runtime(c, s: Settings, agent: str) -> dict | None:
    """The agent's Runtime, if there is one, after checking it is this hub's: the Runtime named Settings.runtime_name
    runs under Settings.agent_role(agent) of the Runtime's own account. Raises NotOwned otherwise. Reads only."""
    name, role = s.runtime_name(agent), s.agent_role(agent)
    runtime = _find_runtime(c, name)
    if runtime is None:
        return None
    arn, own = _ROLE_ARN.fullmatch(runtime.get("roleArn") or ""), _RUNTIME_ARN.fullmatch(runtime["agentRuntimeArn"])
    if not arn:
        raise NotOwned(f"Runtime {name} is not this hub's: its execution role is not an IAM role ARN")
    if arn.group(2) != role:
        raise NotOwned(f"Runtime {name} is not this hub's: it runs under role {arn.group(2)}, not {role}")
    if not own or arn.group(1) != own.group(1):
        raise NotOwned(f"Runtime {name} is not this hub's: it runs under role {role} of another account")
    return runtime


def check_agent(c, s: Settings, agent: str) -> None:
    """Raise NotOwned when the agent's role or Runtime exists but is not this hub's as it stands. Reads only."""
    check_name(agent)
    _check_role(c, s, agent)
    _check_runtime(c, s, agent)


# ================================================================== one agent

def _remove_policies(c, p: Platform, agent: str) -> list[str]:
    """The agent's policies, entry permits first and the stop policy last. Its tool permits are found by the shape of their
    names (tool_policy_pattern), not by the catalog of this checkout: a permit for a tool since removed from the
    catalog goes too."""
    if not p.engine_id:
        return []                                       # no policy engine, no policies
    try:
        found = list_policies(c, p.engine_id)
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return []                                   # the engine is gone, and its policies with it
        raise
    tool_permit = re.compile(tool_policy_pattern(agent))
    names = [entry_permit_name(agent), review_permit_name(agent),
             *sorted(n for n in found if tool_permit.fullmatch(n)), guard_secret_name(agent),
             guard_prompt_name(agent), stop_agent_name(agent)]
    removed = []
    for name in names:
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


def _runtime_status(c, rid: str) -> dict:
    """The deleted Runtime's status as the wait reads it: GONE when it is not found. Only DELETE_FAILED means the
    delete failed; a Runtime a failed deploy left CREATE_FAILED or UPDATE_FAILED may still show that status, which
    reads as still deleting."""
    try:
        r = c.ctl.get_agent_runtime(agentRuntimeId=rid)
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return {"status": "GONE"}
        raise
    status = r["status"]
    if status.endswith("FAILED") and status != "DELETE_FAILED":
        status = f"{status}, deleting"
    return {"status": status, "statusReason": r.get("failureReason")}


def _remove_runtime(c, s: Settings, agent: str) -> list[str]:
    """Delete the agent's Runtime (checked again: _check_runtime) and wait until it is gone. DELETE_FAILED raises
    with the Runtime's failureReason. A Runtime that is DELETING already is waited on, not deleted again."""
    runtime = _check_runtime(c, s, agent)
    if runtime is None:
        return []
    name, rid = runtime["agentRuntimeName"], runtime["agentRuntimeId"]
    if runtime["status"] != "DELETING" and not _delete(lambda: c.ctl.delete_agent_runtime(agentRuntimeId=rid),
                                                       "ResourceNotFoundException"):
        return []
    wait_status(lambda: _runtime_status(c, rid), ("GONE",), f"Runtime {name}", timeout=RUNTIME_WAIT, step=RUNTIME_STEP)
    return [f"Runtime {name}"]


def _remove_log_groups(c, runtime: str) -> list[str]:
    prefix = f"{RUNTIME_LOGS}{runtime}-"
    own = re.compile(re.escape(f"{RUNTIME_LOGS}{runtime}") + RUNTIME_LOG_TAIL)
    names = sorted(g["logGroupName"] for page in c.logs.get_paginator("describe_log_groups").paginate(
        logGroupNamePrefix=prefix) for g in page["logGroups"])
    return [f"log group {n}" for n in names
            if own.fullmatch(n) and _delete(lambda n=n: c.logs.delete_log_group(logGroupName=n),
                                            "ResourceNotFoundException")]


def _remove_packages(c, p: Platform, agent: str) -> list[str]:
    """Every version (and delete marker) of the agent's code packages in the inbox: packages/<agent>/. The inbox keeps
    versions, so deleting the current one only would leave the others."""
    if not p.bucket:
        return []                                       # no platform values: terraform destroy empties the bucket
    prefix = f"{PACKAGES}{agent}/"
    try:
        found = [(o["Key"], o["VersionId"]) for page in c.s3.get_paginator("list_object_versions").paginate(
            Bucket=p.bucket, Prefix=prefix) for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
            if o["Key"].startswith(prefix)]
    except ClientError as e:
        if _code(e) == "NoSuchBucket":
            return []                                   # the bucket is gone, and the packages with it
        raise
    for key, version in found:
        c.s3.delete_object(Bucket=p.bucket, Key=key, VersionId=version)
    return [f"package {key}" for key in sorted({key for key, _ in found})]


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
    until it is gone), its Runtime (waits until it is gone), the Runtime's log groups, its code packages, its
    execution role, and its SSM values. Returns what was removed, as "<kind> <name>"; what was not there is not
    listed. check_agent runs first: a role or Runtime that is not this hub's stops it before anything is deleted. A
    step that fails raises CleanupFailed, and the steps after it do not run."""
    check_name(agent)
    try:
        check_agent(c, s, agent)
    except Exception as e:
        raise CleanupFailed(f"{agent}: checking that its role and Runtime are this hub's", e, []) from e
    plan = [("policies", lambda: _remove_policies(c, p, agent)),
            ("gateway target", lambda: _remove_target(c, s, p, agent)),
            ("Runtime", lambda: _remove_runtime(c, s, agent)),
            ("Runtime log groups", lambda: _remove_log_groups(c, s.runtime_name(agent))),
            ("code packages", lambda: _remove_packages(c, p, agent)),
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


# ================================================================== every record left (make destroy only)

def remove_records(s: Settings, c=None, say=print) -> list[str]:
    """Teardown only: make destroy runs it after clean_agents and after the seed removed its own record, right before
    terraform destroy deletes the registry (which fails while the registry holds a record). It deletes every record
    still in the hub's registry, whatever its type or name (an MCP record, a name the rules refuse), and says each
    one as it goes. reject and remove_agent never call it. Returns "record <name> (<type>, <status>)" per record."""
    c = c or Clients.for_settings(s)
    try:
        p = load(s, c)
    except RuntimeError:            # no platform values in SSM: no catalog to look in
        return []
    if not p.registry_id:
        return []
    try:
        left = sorted(all_items(c.reg.list_registry_records, registryId=p.registry_id, maxResults=100),
                      key=lambda r: (r.get("name", ""), r["recordId"]))
    except ClientError as e:
        if _code(e) == "ResourceNotFoundException":
            return []               # the registry is gone, and its records with it
        raise
    removed = []
    for r in left:
        line = f"record {r.get('name')} ({r.get('recordType')}, {r.get('status')})"
        try:
            drop_record(c, p.registry_id, r["recordId"])
        except Exception as e:
            raise CleanupFailed(f"removing the catalog {line}", e, removed) from e
        say(f"removed {line}")
        removed.append(line)
    return removed


USAGE = "usage: python -m platform_team.hosting_review.agent_cleanup [--records]"


def main(argv: list[str] | None = None) -> int:
    """No argument: every agent's things and records (clean_agents). --records: every record still in the
    registry (remove_records), the last step of make destroy before terraform destroy."""
    argv = list(argv or [])
    if argv not in ([], ["--records"]):
        print(USAGE)
        return 2
    hub, what = "this hub", "catalog records" if argv else "agents"
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        if argv:
            removed = remove_records(s)                  # says each record as it goes
        else:
            removed = clean_agents(s)
            for line in removed:
                print(f"removed {line}")
    except Exception as e:          # say what failed in one line, no traceback
        print(f"{what} not cleaned ({hub}): {e if isinstance(e, CleanupFailed) else cause(e)}")
        return 1
    print(f"{what} cleaned ({hub}): {len(removed)} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
