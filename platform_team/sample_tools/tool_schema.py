"""MCP tool schemas, grouped by gateway target. The tool name seen by agents is <Target>___<tool>."""


def _tool(name: str, description: str, **properties: str) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in properties.items()},
            "required": list(properties),
        },
    }


TARGETS = {
    "Quality": [
        _tool("get_inspection_data", "Read an inspection case with its result and the id of the inspector.",
              case_id="Inspection case id, for example Q-1001."),
    ],
    "Parts": [
        _tool("get_part_spec", "Read the specification of a part.", part_id="Part id, for example P-100."),
        _tool("get_test_result", "Read the test result of a part and the id of the inspector.",
              part_id="Part id, for example P-100."),
    ],
    "Release": [
        _tool("file_review_request", "File a review request for a change and return its request id.",
              change_id="Change id, for example C-7.", summary="One-line summary of the change."),
    ],
}

# Read-only tools the catalog approves for every agent.
SHARED_READ = ["Parts___get_part_spec"]
