"""Put the shared tool in the catalog and approve it, so a developer's first search finds it (picture step 1).

    python -m platform_team.agent_catalog.seed_catalog             # make seed
    python -m platform_team.agent_catalog.seed_catalog --remove    # make destroy, before terraform destroy

The record lives outside Terraform's state, and a registry that still has records cannot be deleted.
"""
import argparse

from botocore.exceptions import ClientError

from platform_team.agent_catalog.catalog_records import drop_record, put_record, records, set_status, submit
from platform_team.sample_tools.tool_schema import TARGETS
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import load

SHARED_RECORD = "parts-tools"
SHARED_TARGET = "Parts"
DESCRIPTION = "Shared in-house tools for part data: get_part_spec reads the specification of a part."


def seed(s: Settings, c: Clients | None = None) -> dict:
    """Create the shared tool record, ask for approval and approve it. An approved record is kept as it is."""
    c = c or Clients.for_settings(s)
    registry_id = load(s, c).registry_id
    rec = records(c, registry_id).get(SHARED_RECORD)
    if rec and rec["status"] == "APPROVED":
        return {"record": SHARED_RECORD, "record_id": rec["recordId"], "status": "APPROVED", "changed": False}
    rid = put_record(c, registry_id, SHARED_RECORD, "MCP", DESCRIPTION,
                     {"target": SHARED_TARGET, "tools": TARGETS[SHARED_TARGET]})
    if records(c, registry_id)[SHARED_RECORD]["status"] == "DRAFT":    # a run that stopped after submit left it pending
        submit(c, registry_id, rid)
    status = set_status(c, registry_id, rid, "APPROVED", "shared tool, approved by the platform team")
    return {"record": SHARED_RECORD, "record_id": rid, "status": status, "changed": True}


def remove(s: Settings, c: Clients | None = None) -> list[str]:
    """Delete the records seed() made. Nothing deployed, or nothing seeded, is fine."""
    c = c or Clients.for_settings(s)
    try:
        registry_id = load(s, c).registry_id
        rec = records(c, registry_id).get(SHARED_RECORD) if registry_id else None
    except RuntimeError:                         # no platform values in SSM: nothing was deployed
        return []
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return []
        raise
    if not rec:
        return []
    drop_record(c, registry_id, rec["recordId"])
    return [SHARED_RECORD]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="delete the seeded records")
    args = parser.parse_args(argv)
    s = Settings.from_env()
    if args.remove:
        print(f"catalog records removed: {', '.join(remove(s)) or 'none'}")
    else:
        out = seed(s)
        print(f"catalog record {out['record']}: {out['status']}" + ("" if out["changed"] else " (kept)"))


if __name__ == "__main__":
    main()
