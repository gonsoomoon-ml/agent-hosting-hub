"""Policies in the hub's policy engine, found by name. Every policy is created with validation IGNORE_ALL_FINDINGS."""
from botocore.exceptions import ClientError

from platform_team.shared_code.aws_helpers import all_items, already_exists, wait_status


def list_policies(c, engine_id: str) -> dict[str, dict]:
    return {p["name"]: p for p in all_items(c.ctl.list_policies, policyEngineId=engine_id, maxResults=100)}


def ensure_policy(c, engine_id: str, name: str, statement: str, guardrail: bool = False, mode: str = "ACTIVE") -> str:
    """Create the policy and wait until it is ACTIVE; return its ID. A policy with this name is kept as it is.
    A policy that ends CREATE_FAILED is deleted, and RuntimeError carries the reason.
    Guardrail policies (BedrockGuardrails::...) use the definition key `policy`, the others `cedar`."""
    found = list_policies(c, engine_id).get(name)
    if found:
        return found["policyId"]
    definition = {"policy" if guardrail else "cedar": {"statement": statement}}
    try:
        pid = c.ctl.create_policy(policyEngineId=engine_id, name=name, validationMode="IGNORE_ALL_FINDINGS",
                                  enforcementMode=mode, definition=definition)["policyId"]
    except ClientError as e:
        if not already_exists(e):
            raise
        return list_policies(c, engine_id)[name]["policyId"]      # made a moment ago by another run
    try:
        wait_status(lambda: c.ctl.get_policy(policyEngineId=engine_id, policyId=pid), ("ACTIVE",), f"policy {name}")
    except RuntimeError as e:                                       # leave nothing half-made, and say why
        drop_policy(c, engine_id, pid)
        raise RuntimeError(f"{e} (deleted)") from None
    return pid


def drop_policy(c, engine_id: str, policy_id: str) -> None:
    """Delete a policy and wait until it is gone. A policy that is already gone is fine."""
    try:
        c.ctl.delete_policy(policyEngineId=engine_id, policyId=policy_id)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return
        raise
    c.ctl.get_waiter("policy_deleted").wait(policyEngineId=engine_id, policyId=policy_id)
