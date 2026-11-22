"""Reject a submission that failed the hosting review, and remove what the review made for it.

    python -m platform_team.hosting_review.reject_agent <agent> "<reason>"     # platform_team/hosting_review/reject.sh

A review that fails stops where it failed: the record stays PENDING_APPROVAL, and what the earlier steps made stays
too. Rejecting marks the record REJECTED with the reason, which the team reads on its record, and removes those
things (agent_cleanup.remove_agent). Reject only after the review has stopped: steps still running would make
things again.
"""
import sys

from platform_team.agent_catalog.catalog_records import records, set_status
from platform_team.hosting_review.agent_cleanup import CleanupFailed, cause, check_agent, check_name, remove_agent
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

MAX_REASON = 255        # statusReason of UpdateRegistryRecordStatus


def reject(c, s: Settings, p: Platform, agent: str, reason: str) -> dict:
    """Mark the agent's record REJECTED with the reason, then remove what the review made for the agent.
    Returns {"status": "REJECTED", "removed": [...]}.

    The registry rejects a record that is pending approval. A record already REJECTED keeps its status and reason
    and is cleaned again (a run after one that stopped part way). An APPROVED record is refused: approved agents are
    stopped, not rejected. Any other status, a missing record or a blank reason is refused too, and so is an agent
    whose role or stack is not this hub's (agent_cleanup.check_agent); then nothing changes."""
    check_name(agent)
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a reason is required: the team reads it on its record")
    if len(reason) > MAX_REASON:
        raise ValueError(f"the reason has {len(reason)} characters; the catalog keeps at most {MAX_REASON}")
    rec = records(c, p.registry_id).get(agent)
    if not rec or rec.get("recordType") != "AGENT":
        raise ValueError(f"no agent record named {agent} in the catalog")
    status = rec["status"]
    if status == "APPROVED":
        raise ValueError("approved agents are stopped, not rejected")
    if status not in ("PENDING_APPROVAL", "REJECTED"):
        raise ValueError(f"record {agent} is {status}: only a record pending approval can be rejected")
    check_agent(c, s, agent)        # reads only: a role or stack that is not this hub's stops it here
    if status == "PENDING_APPROVAL":
        set_status(c, p.registry_id, rec["recordId"], "REJECTED", reason)
    return {"status": "REJECTED", "removed": remove_agent(c, s, p, agent)}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: python -m platform_team.hosting_review.reject_agent <agent> "<reason>"')
        return 2
    agent, reason = argv
    hub = "this hub"                # every first line says which hub: its prefix and region
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        c = Clients.for_settings(s)
        out = reject(c, s, load(s, c), agent, reason)
    except CleanupFailed as e:      # the record is REJECTED by now; a second run finishes the removal
        print(f"record {agent} is REJECTED ({hub}), but not everything was removed: {e}. Run reject again to finish.")
        return 1
    except Exception as e:          # say what failed in one line, no traceback
        print(f"not rejected ({hub}): {e if isinstance(e, ValueError) else cause(e)}")
        return 1
    print(f"record {agent}: {out['status']} ({hub})")
    for line in out["removed"]:
        print(f"removed {line}")
    if not out["removed"]:
        print("nothing left to remove")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
