import types
import pytest
from botocore.exceptions import ClientError
from platform_team.company_policy.policy_engine import ensure_policy

REASON = "Insufficient permissions to call gateway"

class FakeCtl:
    """The policy calls of bedrock-agentcore-control. get_policy answers `statuses` in turn; the last one repeats."""
    def __init__(self, existing=(), statuses=("ACTIVE",), conflict=False):
        self.policies = {n: {"policyId": f"{n}-id", "name": n} for n in existing}
        self.statuses, self.conflict, self.created, self.deleted, self.reads = list(statuses), conflict, [], [], 0
    def list_policies(self, **kw):
        return {"policies": list(self.policies.values())}
    def create_policy(self, name, **kw):
        if self.conflict:                                   # another run made it a moment ago
            self.policies[name] = {"policyId": f"{name}-id", "name": name}
            raise ClientError({"Error": {"Code": "ConflictException", "Message": "already exists"}}, "CreatePolicy")
        self.policies[name] = {"policyId": f"{name}-id", "name": name}
        self.created.append(name)
        return {"policyId": f"{name}-id"}
    def get_policy(self, policyId, **kw):
        self.reads += 1
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"policyId": policyId, "status": status, "statusReasons": [REASON] if status.endswith("FAILED") else []}
    def delete_policy(self, policyId, **kw):
        self.deleted.append(policyId)
        self.policies = {n: p for n, p in self.policies.items() if p["policyId"] != policyId}
    def get_waiter(self, name):
        return types.SimpleNamespace(wait=lambda **kw: None)

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

def test_an_active_policy_of_the_same_name_is_kept():
    c = types.SimpleNamespace(ctl=FakeCtl(existing=["p"]))
    assert ensure_policy(c, "e", "p", "permit (...);") == "p-id" and c.ctl.created == [] and c.ctl.deleted == []

def test_a_failed_policy_of_the_same_name_is_dropped_and_the_reason_raised():
    c = types.SimpleNamespace(ctl=FakeCtl(existing=["p"], statuses=["CREATE_FAILED"]))
    with pytest.raises(RuntimeError, match=REASON):
        ensure_policy(c, "e", "p", "permit (...);")
    assert c.ctl.deleted == ["p-id"]

def test_a_policy_of_the_same_name_still_creating_is_waited_on():
    c = types.SimpleNamespace(ctl=FakeCtl(existing=["p"], statuses=["CREATING", "CREATING", "ACTIVE"]))
    assert ensure_policy(c, "e", "p", "permit (...);") == "p-id" and c.ctl.reads == 3 and c.ctl.deleted == []

def test_a_policy_another_run_just_made_is_checked_too():
    c = types.SimpleNamespace(ctl=FakeCtl(conflict=True, statuses=["CREATE_FAILED"]))
    with pytest.raises(RuntimeError, match=REASON):
        ensure_policy(c, "e", "p", "permit (...);")
    assert c.ctl.deleted == ["p-id"]

def test_a_timeout_does_not_leave_the_new_policy_behind():
    c = types.SimpleNamespace(ctl=FakeCtl(statuses=["CREATING"]))
    with pytest.raises(TimeoutError, match="deleted"):
        ensure_policy(c, "e", "p", "permit (...);", wait=0)
    assert c.ctl.created == ["p"] and c.ctl.deleted == ["p-id"]


# ------------------------------------------------------------------ the enforcement mode

from platform_team.company_policy.policy_engine import MODES, set_mode
from tests.fakes import FakeClients


def test_an_existing_policy_in_another_mode_is_switched_not_made_again():
    c = FakeClients(existing_policies={"guard_prompt_quality_agent"}, policy_mode="LOG_ONLY")
    ensure_policy(c, "engine-1", "guard_prompt_quality_agent", "forbid ...;", guardrail=True, mode="ACTIVE")
    assert c.mode_changes == [("guard_prompt_quality_agent", "ACTIVE")] and c.created_policies == []


def test_an_existing_policy_already_in_the_mode_is_left_alone():
    c = FakeClients(existing_policies={"guard_prompt_quality_agent"}, policy_mode="LOG_ONLY")
    ensure_policy(c, "engine-1", "guard_prompt_quality_agent", "forbid ...;", guardrail=True, mode="LOG_ONLY")
    assert c.mode_changes == [] and c.created_policies == []


def test_a_new_policy_is_made_in_the_mode_asked_for():
    c = FakeClients()
    ensure_policy(c, "engine-1", "guard_prompt_quality_agent", "forbid ...;", guardrail=True, mode="LOG_ONLY")
    assert [(p["name"], p["mode"]) for p in c.created_policies] == [("guard_prompt_quality_agent", "LOG_ONLY")]


def test_an_unknown_mode_is_refused():
    c = FakeClients()
    with pytest.raises(ValueError, match="mode"):
        ensure_policy(c, "engine-1", "x", "permit ...;", mode="DRY_RUN")
    assert c.created_policies == [] and c.calls == []                  # refused before AWS is asked anything


def test_set_mode_updates_the_policy_and_waits_for_it_to_be_active():
    c = FakeClients(existing_policies={"p"}, policy_mode="ACTIVE")
    set_mode(c, "engine-1", "p-id", "LOG_ONLY")
    assert c.mode_changes == [("p", "LOG_ONLY")]
    assert c.calls[-2:] == [("ctl", "update_policy"), ("ctl", "get_policy")]
    with pytest.raises(ValueError, match="mode"):
        set_mode(c, "engine-1", "p-id", "DRY_RUN")


def test_the_modes_are_the_two_the_service_knows():
    assert MODES == ("ACTIVE", "LOG_ONLY")
