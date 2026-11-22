"""Policies in the hub's policy engine, found by name. Every policy is created with validation IGNORE_ALL_FINDINGS."""
from botocore.exceptions import ClientError

from platform_team.shared_code.aws_helpers import all_items, already_exists, wait_status


def list_policies(c, engine_id: str) -> dict[str, dict]:
    return {p["name"]: p for p in all_items(c.ctl.list_policies, policyEngineId=engine_id, maxResults=100)}


def ensure_policy(c, engine_id: str, name: str, statement: str, guardrail: bool = False, mode: str = "ACTIVE",
                  wait: int = 300) -> str:
    """Make sure a policy with this name is ACTIVE and return its ID. Creates it when there is none; a policy
    with this name is kept as it is (one still CREATING is waited on). A policy that does not become ACTIVE is
    deleted, found or new: a FAILED status raises RuntimeError with the reasons, still not ACTIVE after `wait`
    seconds raises TimeoutError. Guardrail policies (BedrockGuardrails::...) use the definition key `policy`,
    the others `cedar`."""
    found = list_policies(c, engine_id).get(name)
    if found:
        pid = found["policyId"]
    else:
        definition = {"policy" if guardrail else "cedar": {"statement": statement}}
        try:
            pid = c.ctl.create_policy(policyEngineId=engine_id, name=name, validationMode="IGNORE_ALL_FINDINGS",
                                      enforcementMode=mode, definition=definition)["policyId"]
        except ClientError as e:
            if not already_exists(e):
                raise
            pid = list_policies(c, engine_id)[name]["policyId"]     # made a moment ago by another run
    try:
        wait_status(lambda: c.ctl.get_policy(policyEngineId=engine_id, policyId=pid), ("ACTIVE",), f"policy {name}",
                    timeout=wait)
    except (RuntimeError, TimeoutError) as e:                      # leave nothing half-made, and say why
        drop_policy(c, engine_id, pid)
        raise type(e)(f"{e} (deleted)") from None
    return pid


def drop_policy(c, engine_id: str, policy_id: str) -> bool:
    """Delete a policy and wait until it is gone. A policy that is already gone is fine: returns False."""
    try:
        c.ctl.delete_policy(policyEngineId=engine_id, policyId=policy_id)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise
    c.ctl.get_waiter("policy_deleted").wait(policyEngineId=engine_id, policyId=policy_id)
    return True
