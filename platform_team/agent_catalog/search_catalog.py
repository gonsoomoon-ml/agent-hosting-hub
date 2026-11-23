"""Search the catalog the way a developer does, and print what a search finds.

    demo_scenes/search "<query>"

A search finds approved records only. For each one it prints the name and the type, the description and, for a tool
record, the tools with their input fields. Every account ID in it is masked. Exit 0 (also when nothing matches),
1 when the search could not be made, 2 for bad usage.
"""
import json
import sys

from platform_team.agent_catalog.catalog_records import search_records
from platform_team.hosting_review.agent_cleanup import cause
from platform_team.shared_code.aws_helpers import Clients, mask
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import load

USAGE = 'usage: demo_scenes/search "<query>"'


def _payload(c, registry_id: str, record: dict) -> dict:
    """The application or tool description a record carries in its custom descriptor. A search item that came without
    its descriptors is read again with GetRegistryRecord; a descriptor that is not JSON gives {}."""
    descriptors = record.get("descriptors")
    if descriptors is None and record.get("recordId"):
        descriptors = c.reg.get_registry_record(registryId=registry_id, recordId=record["recordId"]).get("descriptors")
    data = ((descriptors or {}).get("custom") or {}).get("data")
    try:
        found = json.loads(data) if data else {}
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _tool_line(tool: dict) -> str:
    fields = ", ".join(((tool.get("inputSchema") or {}).get("properties") or {}))
    return f"  tool {tool.get('name', '?')}: {fields or 'no input'}"


def lines(c, registry_id: str, query: str) -> list[str]:
    """What the search finds, as printed: per record its name and type, its description, and its tools' input fields."""
    out = []
    for r in search_records(c, registry_id, query):
        out.append(f"{r['name']}  ({r.get('recordType', '?')})")
        if r.get("description"):
            out.append(f"  {r['description']}")
        if r.get("recordType") == "MCP":
            out += [_tool_line(t) for t in _payload(c, registry_id, r).get("tools") or [] if isinstance(t, dict)]
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0].strip():
        print(USAGE)
        return 2
    query = argv[0].strip()
    try:
        s = Settings.from_env()
        c = Clients.for_settings(s)
        p = load(s, c)
        if not p.registry_id:
            raise RuntimeError("no catalog in the platform values: run `make deploy` first")
        found = lines(c, p.registry_id, query)
    except Exception as e:          # one line, no traceback (a traceback could print the account ID)
        print(f"search did not finish: {cause(e)}")
        return 1
    print(mask("\n".join(found), p.account) if found else f'no approved record matches "{query}"')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
