# tests/test_reject.py  (Review Focus 2)
import pytest
from platform_team.hosting_review.reject_agent import reject
from platform_team.shared_code.config import Settings
from tests.fakes import FakeClients, PLATFORM

def test_reject_removes_what_the_review_made():
    c = FakeClients(record_status="PENDING_APPROVAL",
                    existing_policies={"tool_quality_agent_Parts_get_part_spec", "tool_release_review_Release_file_review_request"},
                    existing_roles={"hub-agent-quality_agent-role"})
    out = reject(c, Settings(), PLATFORM, "quality_agent", "jinja2 2.11.2 has published advisories")
    assert out["status"] == "REJECTED" and c.status_reason == "jinja2 2.11.2 has published advisories"
    assert out["removed"] == ["policy tool_quality_agent_Parts_get_part_spec", "role hub-agent-quality_agent-role"]
    assert "tool_release_review_Release_file_review_request" in c.policies      # another agent's permit stays

def test_an_approved_agent_is_not_rejected():
    with pytest.raises(ValueError, match="approved agents are stopped, not rejected"):
        reject(FakeClients(record_status="APPROVED"), Settings(), PLATFORM, "quality_agent", "x")


# ------------------------------------------------------------------ every kind the review makes, and only the agent's own

import os
import pathlib
import re
import subprocess

from botocore.exceptions import ClientError

from platform_team.hosting_review import agent_cleanup, deploy_build, reject_agent, review_steps as steps
from platform_team.hosting_review.agent_cleanup import CleanupFailed, clean_agents, remove_agent
from tests.fakes import ACCOUNT, CTX, ENV, SPEC

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_ID = "Ab12Cd34Ef"          # the 10 characters AgentCore adds to a Runtime's name (the fake adds these)
FOREIGN_LOG = "/aws/bedrock-agentcore/runtimes/other_team_runtime-Zz98Yy76Xx-DEFAULT"
ROLE, RUNTIME = "hub-agent-quality_agent-role", "hub_quality_agent"


def _deploy(c, agent, version="v1", role=None):
    """What the deploy build leaves for the agent: its package in the inbox, its Runtime under the agent's role (or
    `role`), and the Runtime ARN in SSM (deploy_build.deploy on the fake)."""
    s = Settings()
    key = s.package_key(agent, version)
    c.s3.put_object(Bucket=PLATFORM.bucket, Key=key, Body=b"zip")
    env = {"AGENT": agent, "PREFIX": "hub", "AWS_REGION": "us-west-2", "MODEL_ID": s.model_id, "BUCKET": PLATFORM.bucket,
           "TOOL_GW_URL": "https://hub-tools-abcdefghij.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp",
           "ROLE_ARN": f"arn:aws:iam::{ACCOUNT}:role/{role or s.agent_role(agent)}"}
    return deploy_build.deploy(c, env, key)


def _review(c, spec):
    """What the review's steps leave on the fake for this agent: Read, Grant, Deploy (as the build leaves it: the
    package, the Runtime, the Runtime ARN in SSM; and the Runtime's log group), Entry and Approve."""
    s, agent = Settings(), spec["name"]
    c.record_spec = spec                                       # Read reads the record, Approve reads it again
    c.record_status = "PENDING_APPROVAL"                       # as publish leaves it (the fake has one record status)
    ctx = steps.grant(steps.read({"detail": {"registryId": CTX["registryId"], "registryRecordId": CTX["recordId"]}},
                                 c, ENV), c, ENV)
    _deploy(c, agent)
    c.log_groups.add(f"/aws/bedrock-agentcore/runtimes/{s.runtime_name(agent)}-{RUNTIME_ID}-DEFAULT")
    steps.approve(steps.entry(ctx, c, ENV), c, ENV)


def _state(c) -> set[str]:
    """Everything on the fake, named the way `removed` names it."""
    records = c.reg.list_registry_records(registryId=PLATFORM.registry_id)["registryRecords"]
    return ({f"policy {n}" for n in c.policies} | {f"target {n}" for n in c.targets} | {f"Runtime {n}" for n in c.runtimes}
            | {f"log group {n}" for n in c.log_groups} | {f"package {k}" for k in c.objects}
            | {f"role {n}" for n in c.existing_roles | set(c.roles)}
            | {f"parameter {n}" for n in c.parameters} | {f"record {r['name']}" for r in records})


def test_every_kind_the_review_makes_is_removed_in_order_and_a_second_run_finds_nothing():
    c = FakeClients()
    _review(c, SPEC)
    removed = remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert removed == [
        "policy entry_permit_quality_agent", "policy review_permit_quality_agent",
        "policy tool_quality_agent_Parts_get_part_spec",
        "policy tool_quality_agent_Quality_get_inspection_data", "policy guard_secret_quality_agent",
        "target QualityAgent", "Runtime hub_quality_agent",
        f"log group /aws/bedrock-agentcore/runtimes/hub_quality_agent-{RUNTIME_ID}-DEFAULT",
        "package packages/quality_agent/v1.zip", "role hub-agent-quality_agent-role",
        "parameter /hub/agents/quality_agent/runtime_arn"]
    assert _state(c) == {"record quality_agent"}                    # the record stays: it is the team's
    assert remove_agent(c, Settings(), PLATFORM, "quality_agent") == []


def test_removing_quality_leaves_everything_of_quality_agent():
    c = FakeClients()
    _review(c, SPEC)
    _review(c, {**SPEC, "name": "quality"})
    before = _state(c)
    mine = {"policy entry_permit_quality", "policy review_permit_quality",
            "policy tool_quality_Parts_get_part_spec", "policy tool_quality_Quality_get_inspection_data",
            "policy guard_secret_quality", "target Quality", "Runtime hub_quality",
            f"log group /aws/bedrock-agentcore/runtimes/hub_quality-{RUNTIME_ID}-DEFAULT",
            "package packages/quality/v1.zip", "role hub-agent-quality-role", "parameter /hub/agents/quality/runtime_arn"}
    assert set(remove_agent(c, Settings(), PLATFORM, "quality")) == mine
    assert _state(c) == before - mine


def test_removing_quality_leaves_everything_of_review_quality():
    c = FakeClients()
    _review(c, {**SPEC, "name": "review_quality"})      # under the old names, its entry permit had quality's review name
    before = _state(c)
    assert remove_agent(c, Settings(), PLATFORM, "quality") == [] and _state(c) == before


def test_a_runtime_that_does_not_delete_stops_the_run_and_names_the_runtime_and_its_reason():
    c = FakeClients(existing_roles={"hub-agent-quality_agent-role"},
                    runtime_delete_failure="the Runtime's endpoint could not be deleted")
    _deploy(c, "quality_agent")
    c.targets["QualityAgent"] = "QualityAgent-tid"
    with pytest.raises(CleanupFailed) as e:
        remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert "removing the Runtime failed" in str(e.value) and "Runtime hub_quality_agent DELETE_FAILED" in str(e.value)
    assert "the Runtime's endpoint could not be deleted" in str(e.value)
    assert e.value.removed == ["target QualityAgent"]
    assert "hub-agent-quality_agent-role" in c.existing_roles           # the Runtime may still use it
    assert "packages/quality_agent/v1.zip" in c.objects


def test_any_other_aws_error_stops_the_run_with_the_step_named():
    c = FakeClients(existing_roles={"hub-agent-quality_agent-role"})
    c.parameters["/hub/agents/quality_agent/runtime_arn"] = "arn"

    def denied(**kw):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "not allowed"}}, "DeleteRole")
    c.iam.delete_role = denied
    with pytest.raises(CleanupFailed, match="removing the execution role failed .AccessDenied: not allowed"):
        remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert "/hub/agents/quality_agent/runtime_arn" in c.parameters      # later steps did not run


# ------------------------------------------------------------------ reject: statuses and reasons

def test_reject_again_cleans_again_and_keeps_the_record_as_it_is():
    c = FakeClients(existing_roles={"hub-agent-quality_agent-role"})
    reject(c, Settings(), PLATFORM, "quality_agent", "jinja2 2.11.2 has published advisories")
    c.parameters["/hub/agents/quality_agent/runtime_arn"] = "arn"         # left by a run that stopped early
    out = reject(c, Settings(), PLATFORM, "quality_agent", "another reason")
    assert out == {"status": "REJECTED", "removed": ["parameter /hub/agents/quality_agent/runtime_arn"]}
    assert c.record_status == "REJECTED" and c.status_reason == "jinja2 2.11.2 has published advisories"
    assert reject(c, Settings(), PLATFORM, "quality_agent", "another reason")["removed"] == []


@pytest.mark.parametrize("agent, status, reason, message", [
    ("quality_agent", "PENDING_APPROVAL", "  ", "a reason is required"),
    ("quality_agent", "PENDING_APPROVAL", "x" * 256, "at most 255"),
    ("quality_agent", "DRAFT", "x", "record quality_agent is DRAFT: only a record pending approval"),
    ("quality_agent", None, "x", "no agent record named quality_agent"),
    ("Bad-Name", "PENDING_APPROVAL", "x", "agent name 'Bad-Name': name must match"),
])
def test_reject_refuses_and_changes_nothing(agent, status, reason, message):
    c = FakeClients(record_status=status, existing_roles={"hub-agent-quality_agent-role"})
    with pytest.raises(ValueError, match=message):
        reject(c, Settings(), PLATFORM, agent, reason)
    assert c.record_status == status and c.status_reason is None and "hub-agent-quality_agent-role" in c.existing_roles


# ------------------------------------------------------------------ clean_agents: every agent, before terraform destroy

FOREIGN_ROLES = {"other_team_runtime-role", "hub-agents-role", "hub-review-grant-role", "hub-agent-Not-An-Agent-role",
                 "demo-agent-quality_agent-role"}       # the last: an agent role of a hub with another prefix


def test_clean_agents_finds_every_agent_and_leaves_what_the_hub_did_not_make(monkeypatch):
    c = FakeClients(existing_policies={"shared_tool_read"}, existing_roles={"hub-agent-release_review-role", *FOREIGN_ROLES})
    _review(c, SPEC)                                                         # approved, with its record
    c.parameters["/hub/agents/part_inspector/runtime_arn"] = "arn"       # only an SSM value is left
    c.parameters["/hub/platform/registry_id"] = "reg-1"
    c.other_records = [{"name": "parts-tools", "recordId": "rec-tools", "recordType": "MCP", "status": "APPROVED"}]
    c.ctl.create_agent_runtime(agentRuntimeName="other_team_runtime",       # the account's own Runtime
                               roleArn=f"arn:aws:iam::{ACCOUNT}:role/other_team_runtime-role")
    c.s3.put_object(Bucket=PLATFORM.bucket, Key="submissions/appliance/quality_agent/agent.zip", Body=b"zip")
    c.log_groups.add(FOREIGN_LOG)
    monkeypatch.setattr(agent_cleanup, "load", lambda s, c=None: PLATFORM)
    foreign = {"policy shared_tool_read", "parameter /hub/platform/registry_id", "record parts-tools",
               "Runtime other_team_runtime",
               "package submissions/appliance/quality_agent/agent.zip",                 # kept: what was submitted
               f"log group {FOREIGN_LOG}", *(f"role {r}" for r in FOREIGN_ROLES)}
    removed = clean_agents(Settings(), c)
    assert _state(c) == foreign
    assert {"parameter /hub/agents/part_inspector/runtime_arn", "role hub-agent-release_review-role",
            "Runtime hub_quality_agent", "package packages/quality_agent/v1.zip", "record quality_agent"} <= set(removed)
    assert removed.index("parameter /hub/agents/quality_agent/runtime_arn") < removed.index("record quality_agent")
    assert clean_agents(Settings(), c) == []


def test_clean_agents_works_without_the_platform_values(monkeypatch):
    c = FakeClients(existing_roles={"hub-agent-quality_agent-role"})
    _deploy(c, "quality_agent")

    def nothing_deployed(s, c=None):
        raise RuntimeError("nothing under /hub/platform/: run `make deploy` first")
    monkeypatch.setattr(agent_cleanup, "load", nothing_deployed)
    assert clean_agents(Settings(), c) == ["Runtime hub_quality_agent", "role hub-agent-quality_agent-role",
                                           "parameter /hub/agents/quality_agent/runtime_arn"]
    assert list(c.objects) == ["packages/quality_agent/v1.zip"]     # no bucket name: terraform destroy empties it


# ------------------------------------------------------------------ only what this hub made (fix round 1)

def _pending_review(c):
    """quality_agent as a failed review leaves it, everything made, the record pending approval."""
    _review(c, SPEC)
    c.record_status, c.status_reason = "PENDING_APPROVAL", None


def _refused_before_anything_changes(c, message):
    before = _state(c)
    with pytest.raises(ValueError, match=message):
        reject(c, Settings(), PLATFORM, "quality_agent", "jinja2 2.11.2 has published advisories")
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None and _state(c) == before
    with pytest.raises(CleanupFailed, match=message) as e:
        remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert e.value.removed == [] and _state(c) == before and ACCOUNT not in str(e.value)


@pytest.mark.parametrize("change, message", [
    (lambda c: c.role_boundaries.update({ROLE: None}), f"role {ROLE} is not this hub's: its permissions boundary is none"),
    (lambda c: c.role_boundaries.update({ROLE: f"arn:aws:iam::{ACCOUNT}:policy/other-boundary"}),
     f"role {ROLE} is not this hub's: its permissions boundary is other-boundary"),
    (lambda c: c.attached.update({ROLE: ["ReadOnlyAccess"]}), f"role {ROLE} has managed policies ReadOnlyAccess"),
    (lambda c: c.instance_profiles.update({ROLE: ["agent-profile"]}), f"role {ROLE} has instance profiles agent-profile"),
])
def test_a_role_the_hub_did_not_make_as_it_is_stops_reject_and_removal_before_anything_changes(change, message):
    c = FakeClients()
    _pending_review(c)
    change(c)
    _refused_before_anything_changes(c, message)


@pytest.mark.parametrize("role", ["hub-agent-release_review-role",       # another agent's role (the deploy role can pass it)
                                  "other_team_runtime-role"])
def test_cleanup_refuses_a_runtime_of_this_name_that_runs_under_another_role(role):
    c = FakeClients()
    _pending_review(c)
    config = c.runtimes[RUNTIME]["config"]
    config["roleArn"] = f"arn:aws:iam::{ACCOUNT}:role/{role}"
    _refused_before_anything_changes(c, f"Runtime {RUNTIME} is not this hub's: it runs under role {role}, not {ROLE}")


def test_cleanup_refuses_a_runtime_whose_role_is_in_another_account():
    c = FakeClients()
    _pending_review(c)
    c.runtimes[RUNTIME]["config"]["roleArn"] = f"arn:aws:iam::234567890123:role/{ROLE}"
    with pytest.raises(CleanupFailed, match=f"Runtime {RUNTIME} is not this hub's: it runs under role {ROLE} of "
                                            "another account"):
        remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert RUNTIME in c.runtimes


def test_cleanup_deletes_the_agents_runtime_and_its_packages():
    c = FakeClients()
    _review(c, SPEC)
    _deploy(c, "quality_agent", "v2")                                  # a second version: the same Runtime, updated
    c.s3.put_object(Bucket=PLATFORM.bucket, Key="packages/quality_agent/v2.zip", Body=b"again")   # two versions of a key
    _deploy(c, "quality", role="hub-agent-quality-role")                # another agent whose name starts the same
    removed = remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert [r for r in removed if r.split()[0] in ("Runtime", "package")] == [
        "Runtime hub_quality_agent", "package packages/quality_agent/v1.zip", "package packages/quality_agent/v2.zip"]
    assert list(c.runtimes) == ["hub_quality"] and list(c.objects) == ["packages/quality/v1.zip"]
    assert c.runtime_calls[-1] == "delete hub_quality_agent-Ab12Cd34Ef"


def test_clean_agents_skips_a_role_not_made_by_this_hub(monkeypatch):
    c = FakeClients(record_status=None, existing_roles={ROLE})
    c.role_boundaries[ROLE] = None
    _deploy(c, "quality_agent")
    c.parameters.clear()                                                # found by its role only
    monkeypatch.setattr(agent_cleanup, "load", lambda s, c=None: PLATFORM)
    before, said = _state(c), []
    assert clean_agents(Settings(), c, say=said.append) == []
    assert said == [f"skipped {ROLE}: not made by this hub"] and _state(c) == before


def test_the_agent_boundary_is_the_one_terraform_makes():
    assert Settings().agent_boundary == "hub-agent-boundary"
    iam_tf = (ROOT / "platform_team" / "hosting_review" / "terraform" / "iam.tf").read_text()
    assert re.search(r'name\s*=\s*"\$\{var\.prefix\}-agent-boundary"', iam_tf)


@pytest.fixture
def clock(monkeypatch):
    """Fake time: sleeping moves the clock, nothing waits."""
    now = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: now["t"])
    monkeypatch.setattr("time.sleep", lambda seconds: now.update(t=now["t"] + seconds))
    return now


def test_a_deleting_runtime_is_waited_on_until_it_is_gone(clock):
    c = FakeClients(runtime_delete_polls=3)
    _deploy(c, "quality_agent")
    c.objects.clear()
    c.parameters.clear()
    t0 = clock["t"]
    assert remove_agent(c, Settings(), PLATFORM, "quality_agent") == [f"Runtime {RUNTIME}"]
    assert clock["t"] - t0 == 3 * agent_cleanup.RUNTIME_STEP                    # three looks at DELETING


def test_a_runtime_that_is_deleting_already_is_waited_on_and_not_deleted_again(clock):
    c = FakeClients(runtime_delete_polls=2)
    _deploy(c, "quality_agent")
    c.objects.clear()
    c.parameters.clear()
    c.ctl.delete_agent_runtime(agentRuntimeId=f"{RUNTIME}-{RUNTIME_ID}")       # a run before this one stopped here
    assert remove_agent(c, Settings(), PLATFORM, "quality_agent") == [f"Runtime {RUNTIME}"]
    assert c.runtime_calls.count(f"delete {RUNTIME}-{RUNTIME_ID}") == 1


def test_a_runtime_still_deleting_after_the_wait_stops_the_run(clock):
    c = FakeClients(existing_roles={ROLE}, runtime_delete_polls=float("inf"))
    _deploy(c, "quality_agent")
    with pytest.raises(CleanupFailed, match=f"removing the Runtime failed .TimeoutError: Runtime {RUNTIME} not .* "
                                            f"within {agent_cleanup.RUNTIME_WAIT}s"):
        remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert ROLE in c.existing_roles and "packages/quality_agent/v1.zip" in c.objects


# ------------------------------------------------------------------ the commands

def _wire(monkeypatch, module, c):
    monkeypatch.setenv("DEMO_PREFIX", "hub")                        # main() reads Settings.from_env()
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setattr(module, "Clients", type("C", (), {"for_settings": staticmethod(lambda s: c)}))
    monkeypatch.setattr(module, "load", lambda s, c=None: PLATFORM)


def test_reject_main_prints_what_was_removed_one_per_line(monkeypatch, capsys):
    _wire(monkeypatch, reject_agent, FakeClients(existing_roles={"hub-agent-quality_agent-role"}))
    assert reject_agent.main(["quality_agent", "jinja2 2.11.2 has published advisories"]) == 0
    assert capsys.readouterr().out.splitlines() == ["record quality_agent: REJECTED (prefix hub, region us-west-2)",
                                                    "removed role hub-agent-quality_agent-role"]


def test_a_failed_command_prints_one_line_without_the_account(monkeypatch, capsys):
    c = FakeClients(existing_roles={"hub-agent-quality_agent-role"})

    def denied(**kw):
        raise ClientError({"Error": {"Code": "AccessDenied",
                                     "Message": f"User: arn:aws:iam::{ACCOUNT}:user/x is not authorized"}}, "DeleteRole")
    c.iam.delete_role = denied
    _wire(monkeypatch, reject_agent, c)
    _wire(monkeypatch, agent_cleanup, c)
    assert reject_agent.main(["quality_agent", "jinja2 2.11.2 has published advisories"]) == 1
    assert agent_cleanup.main() == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and all("execution role" in l and "AccessDenied" in l and ACCOUNT not in l for l in lines)
    assert lines[0].startswith("record quality_agent is REJECTED (prefix hub, region us-west-2), but")
    assert lines[1].startswith("agents not cleaned (prefix hub, region us-west-2):")


def test_reject_sh_runs_the_module_from_the_repo_whatever_the_current_folder(tmp_path):
    script = ROOT / "platform_team" / "hosting_review" / "reject.sh"
    assert os.access(script, os.X_OK)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text('#!/usr/bin/env bash\necho "$PWD"; printf "%s\\n" "$@"\n')
    (bin_dir / "uv").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    r = subprocess.run([str(script), "quality_agent", "two words"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.stdout.splitlines() == [str(ROOT), "run", "python", "-m", "platform_team.hosting_review.reject_agent",
                                     "quality_agent", "two words"]
    r = subprocess.run([str(script), "quality_agent"], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "usage: reject.sh <agent>" in r.stderr


# The two commands' reading of .env: tests/test_hub_env.py (one rule for make, the commands and the e2e script).


# ------------------------------------------------------------------ final review M-3: what the hub made and did not find

def test_a_tool_permit_for_a_tool_no_longer_in_the_catalog_is_removed_too():
    gone = "tool_quality_agent_Retired_get_old_data"                   # its tool left TARGETS after it was granted
    others = {"tool_quality_agent_x_Parts_get_part_spec", "tool_quality_Parts_get_part_spec",
              "tool_release_review_Release_file_review_request", "shared_tool_read"}
    c = FakeClients(existing_policies={gone, "tool_quality_agent_Parts_get_part_spec", *others})
    removed = remove_agent(c, Settings(), PLATFORM, "quality_agent")
    assert removed == ["policy tool_quality_agent_Parts_get_part_spec", f"policy {gone}"]
    assert set(c.policies) == others                                   # other agents' permits and the shared one stay


def test_reject_refuses_while_a_review_of_the_record_is_running():
    c = FakeClients(existing_roles={ROLE})
    c.running = [("review-of-quality-agent", "rec-1")]
    before = _state(c)
    with pytest.raises(ValueError, match="a review of record quality_agent is still running "
                                         r"\(review-of-quality-agent\): reject after it stops"):
        reject(c, Settings(), PLATFORM, "quality_agent", "jinja2 2.11.2 has published advisories")
    assert c.record_status == "PENDING_APPROVAL" and c.status_reason is None and _state(c) == before


def test_a_review_of_another_record_does_not_stop_reject():
    c = FakeClients(existing_roles={ROLE})
    c.running = [("review-of-release-review", "rec-2")]
    assert reject(c, Settings(), PLATFORM, "quality_agent", "a reason")["removed"] == [f"role {ROLE}"]


def test_teardown_removes_every_record_left_in_the_registry_and_says_each(monkeypatch):
    c = FakeClients(record_status="APPROVED", record_spec={**SPEC, "name": "Bad-Name"})
    c.other_records = [{"name": "parts-tools", "recordId": "rec-tools", "recordType": "MCP", "status": "APPROVED"},
                       {"name": "notes", "recordId": "rec-notes", "recordType": "CUSTOM", "status": "DRAFT"}]
    monkeypatch.setattr(agent_cleanup, "load", lambda s, c=None: PLATFORM)
    said = []
    removed = agent_cleanup.remove_records(Settings(), c, say=said.append)
    assert removed == ["record notes (CUSTOM, DRAFT)", "record parts-tools (MCP, APPROVED)",
                       "record quality_agent (AGENT, APPROVED)"]
    assert said == [f"removed {r}" for r in removed] and _state(c) == set()
    assert agent_cleanup.remove_records(Settings(), c, say=said.append) == []


def test_teardown_of_records_needs_no_platform(monkeypatch):
    def nothing_deployed(s, c=None):
        raise RuntimeError("nothing under /hub/platform/: run `make deploy` first")
    monkeypatch.setattr(agent_cleanup, "load", nothing_deployed)
    assert agent_cleanup.remove_records(Settings(), FakeClients(), say=pytest.fail) == []


def test_make_destroy_removes_the_records_last_after_the_agents_and_the_seed():
    r = subprocess.run(["make", "-n", "destroy", "AUTO_APPROVE=1"], cwd=ROOT, capture_output=True, text=True)
    lines = r.stdout.splitlines()
    def at(text):
        return next(i for i, line in enumerate(lines) if text in line)
    agents, seed = at("platform_team.hosting_review.agent_cleanup ||"), at("seed_catalog --remove")
    records, destroy = at("agent_cleanup --records"), at("destroy -auto-approve")
    assert agents < seed < records < destroy
