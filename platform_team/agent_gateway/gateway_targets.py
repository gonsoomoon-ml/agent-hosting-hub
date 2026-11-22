"""The hub's gateways and their targets. A hosted agent becomes a Runtime target of the agent gateway."""
import json

from botocore.exceptions import ClientError

from platform_team.shared_code.aws_helpers import all_items, already_exists, wait_status

# The agent's entry point as the gateway sees it: POST /invocations with a prompt.
# Policies name it <Target>___POST:/invocations.
INVOCATION_SCHEMA = {
    "openapi": "3.0.0",
    "info": {"title": "Agent invocation", "version": "1.0.0"},
    "paths": {"/invocations": {"post": {
        "operationId": "invokeAgent",
        "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["prompt"], "properties": {"prompt": {"type": "string"}}}}}},
        "responses": {"200": {"description": "Successful invocation"}},
    }}},
}


def find_gateway(c, name: str) -> dict | None:
    """The full GetGateway answer for the gateway with this name, or None."""
    g = next((g for g in all_items(c.ctl.list_gateways, maxResults=100) if g["name"] == name), None)
    return c.ctl.get_gateway(gatewayIdentifier=g["gatewayId"]) if g else None


def targets(c, gateway_id: str) -> dict[str, dict]:
    return {t["name"]: t for t in all_items(c.ctl.list_gateway_targets, gatewayIdentifier=gateway_id, maxResults=100)}


def ensure_runtime_target(c, gateway_id: str, target: str, runtime_arn: str, wait: int = 300) -> str:
    """Put a Runtime behind the gateway as target `target` and wait up to `wait` seconds until it is READY; return
    the target ID. A target with this name is kept as it is."""
    found = targets(c, gateway_id).get(target)
    if found:
        tid = found["targetId"]
    else:
        try:
            tid = c.ctl.create_gateway_target(
                gatewayIdentifier=gateway_id, name=target, description="hosted agent",
                targetConfiguration={"http": {"agentcoreRuntime": {
                    "arn": runtime_arn, "qualifier": "DEFAULT",
                    "schema": {"source": {"inlinePayload": json.dumps(INVOCATION_SCHEMA)}}}}},
                credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])["targetId"]
        except ClientError as e:
            if not already_exists(e):
                raise
            tid = targets(c, gateway_id)[target]["targetId"]        # made a moment ago by another run
    wait_status(lambda: c.ctl.get_gateway_target(gatewayIdentifier=gateway_id, targetId=tid), ("READY",),
                f"target {target}", timeout=wait, step=3)
    return tid


def drop_target(c, gateway_id: str, target_id: str, target: str, wait: int = 300) -> bool:
    """Delete a target and wait up to `wait` seconds until the gateway no longer has it. A target that is already
    gone is fine: returns False. A target that fails to delete raises RuntimeError with the reasons."""
    def _gone(e: ClientError) -> bool:
        return e.response["Error"]["Code"] == "ResourceNotFoundException"
    try:
        c.ctl.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
    except ClientError as e:
        if _gone(e):
            return False
        raise

    def read() -> dict:
        try:
            return c.ctl.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
        except ClientError as e:
            if _gone(e):
                return {"status": "GONE"}
            raise
    wait_status(read, ("GONE",), f"target {target}", timeout=wait, step=3)
    return True
