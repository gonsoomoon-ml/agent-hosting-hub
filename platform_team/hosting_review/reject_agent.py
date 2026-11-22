"""Reject a submission that failed the hosting review, and remove what the review made for it.

    python -m platform_team.hosting_review.reject_agent <agent> "<reason>"     # platform_team/hosting_review/reject.sh

A review that fails stops where it failed: the record stays PENDING_APPROVAL, and what the earlier steps made stays
too. Rejecting marks the record REJECTED with the reason, which the team reads on its record, and removes those
things (agent_cleanup.remove_agent). Reject only after the review has stopped: steps still running would make
things again, so a review of the record that is still running stops reject before anything changes.

A new version of an approved agent uses the same role, Runtime, target and permits as the version that runs. So when
the agent's entry permit is there (only Approve makes it, and it takes back one it made when it stops), reject marks
the record REJECTED and removes nothing. A record the team changed while its review ran is a DRAFT: reject keeps it
as it is and removes what the review made.
"""
import json
import sys

from platform_team.agent_catalog.catalog_records import records, set_status
from platform_team.company_policy.policy_engine import list_policies
from platform_team.company_policy.policy_names import entry_permit_name
from platform_team.hosting_review.agent_cleanup import CleanupFailed, cause, check_agent, check_name, remove_agent
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import Platform, load

MAX_REASON = 255        # statusReason of UpdateRegistryRecordStatus
REJECTABLE = ("PENDING_APPROVAL", "REJECTED", "DRAFT")
RUNNING_VERSION = "an approved version is running and was left as it is"
DRAFT_KEPT = "the record is a draft (the team changed it) and keeps its status"


def running_reviews(c, p: Platform, record_id: str) -> list[str]:
    """The names of the review executions still RUNNING for this record, oldest first (by startDate, then name): the
    record ID is in each execution's input (the Registry's event). No state machine, no review."""
    if not p.machine_arn:
        return []
    found = []
    for page in c.sfn.get_paginator("list_executions").paginate(stateMachineArn=p.machine_arn, statusFilter="RUNNING"):
        for e in page["executions"]:
            try:
                doc = json.loads(c.sfn.describe_execution(executionArn=e["executionArn"]).get("input") or "{}")
            except ValueError:
                doc = {}
            detail = (doc.get("detail") if isinstance(doc, dict) else None) or {}
            if isinstance(detail, dict) and detail.get("registryRecordId") == record_id:
                found.append((e["startDate"], e["name"]))
    return [name for _, name in sorted(found)]


def _approved_version_runs(c, p: Platform, agent: str) -> bool:
    """The agent's entry permit is there: a version of it was approved and still runs."""
    return bool(p.engine_id) and entry_permit_name(agent) in list_policies(c, p.engine_id)


def reject(c, s: Settings, p: Platform, agent: str, reason: str) -> dict:
    """Reject the agent's submission. Returns {"status": <the record's status>, "removed": [...]}, with "note" when
    the record or the agent was left as it is.

    An approved version runs (its entry permit is there): the record is marked REJECTED with the reason and nothing
    is removed; "note" says so. Otherwise the review's things are removed (agent_cleanup.remove_agent): a record
    pending approval is marked REJECTED first (the registry rejects only such a record); a record already REJECTED
    keeps its status and reason and is cleaned again (a run after one that stopped part way); a DRAFT keeps its
    status (a review that stopped because the team changed the record). Refused, with nothing changed: an APPROVED
    record (approved agents are stopped, not rejected), any other status, a DRAFT while an approved version runs, a
    missing record, a blank reason, a record whose review is still running (running_reviews), and an agent whose
    role or Runtime is not this hub's (agent_cleanup.check_agent). When the removal fails, the CleanupFailed carries
    the record's status as record_status."""
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
    if status not in REJECTABLE:
        raise ValueError(f"record {agent} is {status}: "
                         "reject takes a record pending approval, a rejected one or a draft")
    running = running_reviews(c, p, rec["recordId"])
    if running:                     # its steps would make again what this removes
        raise ValueError(f"a review of record {agent} is still running ({', '.join(running)}): reject after it stops")
    check_agent(c, s, agent)        # reads only: a role or Runtime that is not this hub's stops it here
    if _approved_version_runs(c, p, agent):           # the role, Runtime and permits are the running version's too
        if status == "DRAFT":
            raise ValueError(f"record {agent} is DRAFT and an approved version of it is running: "
                             "there is nothing to reject or remove")
        if status == "PENDING_APPROVAL":
            set_status(c, p.registry_id, rec["recordId"], "REJECTED", reason)
        return {"status": "REJECTED", "removed": [], "note": RUNNING_VERSION}
    if status == "PENDING_APPROVAL":
        set_status(c, p.registry_id, rec["recordId"], "REJECTED", reason)
    kept = "DRAFT" if status == "DRAFT" else "REJECTED"
    try:
        removed = remove_agent(c, s, p, agent)
    except CleanupFailed as e:
        e.record_status = kept
        raise
    return {"status": kept, "removed": removed, **({"note": DRAFT_KEPT} if kept == "DRAFT" else {})}


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
    except CleanupFailed as e:      # the record is REJECTED (or kept a DRAFT) by now; a second run finishes the removal
        print(f"record {agent} is {getattr(e, 'record_status', 'REJECTED')} ({hub}), but not everything was removed: "
              f"{e}. Run reject again to finish.")
        return 1
    except Exception as e:          # say what failed in one line, no traceback
        print(f"not rejected ({hub}): {e if isinstance(e, ValueError) else cause(e)}")
        return 1
    print(f"record {agent}: {out['status']} ({hub})")
    for line in out["removed"]:
        print(f"removed {line}")
    if out.get("note"):
        print(out["note"])
    elif not out["removed"]:
        print("nothing left to remove")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
