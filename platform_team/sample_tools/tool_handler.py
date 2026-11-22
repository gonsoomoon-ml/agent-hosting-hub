"""Lambda handler for every gateway target. Standard library only; keeps no state."""
import hashlib

from platform_team.sample_tools.tool_data import INSPECTIONS, PARTS, TEST_RESULTS


def _lookup(table: dict, key: str, what: str) -> dict:
    row = table.get(key)
    if row is None:
        return {"error": f"unknown {what}: {key}"}
    return {**row, "synthetic": True}


def _file_review_request(event: dict) -> dict:
    change_id, summary = str(event.get("change_id", "")), str(event.get("summary", ""))
    digest = hashlib.sha256(f"{change_id}|{summary}".encode()).hexdigest()[:8].upper()
    return {"request_id": f"RR-{digest}", "change_id": change_id, "status": "FILED", "synthetic": True}


TOOLS = {
    "get_inspection_data": lambda e: _lookup(INSPECTIONS, e.get("case_id"), "case_id"),
    "get_part_spec": lambda e: _lookup(PARTS, e.get("part_id"), "part_id"),
    "get_test_result": lambda e: _lookup(TEST_RESULTS, e.get("part_id"), "part_id"),
    "file_review_request": _file_review_request,
}


def handler(event, context) -> dict:
    """The gateway sends the arguments as the event and the tool name as <Target>___<tool>."""
    full_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool = full_name.split("___", 1)[-1]
    if tool not in TOOLS:
        return {"error": f"unknown tool: {full_name}"}
    return TOOLS[tool](event or {})
