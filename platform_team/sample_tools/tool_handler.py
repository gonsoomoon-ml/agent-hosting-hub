"""Lambda handler for every gateway target. Standard library only; keeps no state."""
import hashlib

from platform_team.sample_tools.tool_data import INSPECTIONS, PARTS, TEST_RESULTS


def _error(message: str) -> dict:
    return {"error": message, "synthetic": True}


def _lookup(table: dict, key: str, what: str) -> dict:
    row = table.get(key)
    if row is None:
        return _error(f"unknown {what}: {key}")
    return {**row, "synthetic": True}


def _file_review_request(event: dict) -> dict:
    change_id, summary = str(event.get("change_id") or ""), str(event.get("summary") or "")
    if not change_id or not summary:
        return _error("change_id and summary are required")
    digest = hashlib.sha256(f"{change_id}|{summary}".encode()).hexdigest()[:8].upper()
    return {"request_id": f"RR-{digest}", "change_id": change_id, "status": "FILED", "synthetic": True}


# Keyed on the full gateway tool name, <Target>___<tool>.
TOOLS = {
    "Quality___get_inspection_data": lambda e: _lookup(INSPECTIONS, e.get("case_id"), "case_id"),
    "Parts___get_part_spec": lambda e: _lookup(PARTS, e.get("part_id"), "part_id"),
    "Parts___get_test_result": lambda e: _lookup(TEST_RESULTS, e.get("part_id"), "part_id"),
    "Release___file_review_request": _file_review_request,
}


def handler(event, context) -> dict:
    """The gateway sends the arguments as the event and the tool name as <Target>___<tool>."""
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    full_name = custom.get("bedrockAgentCoreToolName")
    if not full_name:
        return _error("missing tool name")
    if full_name not in TOOLS:
        return _error(f"unknown tool: {full_name}")
    return TOOLS[full_name](event or {})
