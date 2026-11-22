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
