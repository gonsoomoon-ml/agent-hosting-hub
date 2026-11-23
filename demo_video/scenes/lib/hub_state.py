"""The hub's state as a take of the demo video needs to know it, printed as one JSON line (reads only):
  {"records": {<name>: {"type": "AGENT" | "MCP", "status": ...}}, "reviewing": [<agent>, ...] (the reviews running),
   "mode": guard_prompt's mode (null when off), "attached": the custom guardrail, "stopped": [<agent>, ...]}
Run with the project's Python, from any folder (lib/state.mjs does):
  uv run --quiet --project <repo> python -I demo_video/scenes/lib/hub_state.py
A read that fails prints one line (the account masked) and exits 1."""
import json
import sys

from platform_team.agent_catalog.catalog_records import records
from platform_team.agent_stop import stop_agent
from platform_team.company_policy import policy_rollout
from platform_team.custom_guardrail import guardrail_attach
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import load

POLICY = "guard_prompt"                 # the company policy the takes turn on (policy_rollout.POLICIES)


def reviewing(c, machine_arn: str, names_by_id: dict[str, str]) -> list[str]:
    """The agents whose review is running: each running execution's input names the record (the Registry's event,
    detail.registryRecordId); a record that is not in the catalog any more reads as "?"."""
    found = []
    for e in c.sfn.list_executions(stateMachineArn=machine_arn, statusFilter="RUNNING")["executions"]:
        doc = json.loads(c.sfn.describe_execution(executionArn=e["executionArn"]).get("input") or "{}")
        detail = doc.get("detail") if isinstance(doc, dict) else None
        record_id = detail.get("registryRecordId", "") if isinstance(detail, dict) else ""
        found.append(names_by_id.get(record_id, "?"))
    return sorted(found)


def state(c, s: Settings) -> dict:
    p = load(s, c)
    recs = records(c, p.registry_id)
    return {"records": {n: {"type": r.get("recordType", ""), "status": r.get("status", "")} for n, r in sorted(recs.items())},
            "reviewing": reviewing(c, p.machine_arn, {r["recordId"]: n for n, r in recs.items()}),
            "mode": policy_rollout.deployed(c, s).get(POLICY),
            "attached": guardrail_attach.status(c, s, p)["attached"],
            "stopped": [a for a in policy_rollout.hosted_agents(c, s, p) if stop_agent.stopped(c, p, a)]}


def main() -> int:
    s = Settings.from_env()
    try:
        c = Clients.for_settings(s)
        print(json.dumps(state(c, s)))
        return 0
    except Exception as e:  # noqa: BLE001 - one line for the storyboard, whatever failed
        import re
        print(re.sub(r"(?<![0-9])[0-9]{12}(?![0-9])", "<ACCOUNT>", f"the hub's state could not be read: "
                     f"{type(e).__name__}: {e}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
