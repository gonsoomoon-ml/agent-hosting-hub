"""The home page: what the hub has in AWS now. The platform's parts with the AWS service that runs each, the counts
of hosted agents, agents awaiting approval and approved tools (the catalog), the company policy's mode and the custom
guardrail, the hub's alarms and the catalog's records. Each is one panel: a read that fails is one line in its panel."""
from fastapi import APIRouter, Request

from platform_team.company_policy import policy_rollout
from platform_team.custom_guardrail import guardrail_attach
from platform_team.hub_ui.app import Hub, catalog, count, page, panel

router = APIRouter()

GATEWAY = "Amazon Bedrock AgentCore Gateway"
SERVICES = {"agent_gw": GATEWAY, "tool_gw": GATEWAY, "engine": "Policy in Amazon Bedrock AgentCore",
            "catalog": "AWS Agent Registry", "machine": "AWS Step Functions", "topic": "Amazon SNS",
            "alarms": "Amazon CloudWatch", "parameters": "AWS Systems Manager Parameter Store",
            "guardrail": f"{GATEWAY} interceptor · AWS Lambda"}
# The two concept pictures (static/), one per flow, in Korean only; the key names their texts (home.<key>.title, .alt)
PICTURES = (("flow1", "hosting-hub-flow1-concept.png"), ("flow2", "hosting-hub-flow2-concept.png"))
COMPANY_POLICY = "guard_prompt"         # the company policy rollout.sh turns on (policy_rollout.POLICIES)


def _topic(c, arn: str) -> dict:
    """A topic has no status: its state on the page is the number of confirmed subscriptions."""
    attributes = c.sns.get_topic_attributes(TopicArn=arn)["Attributes"]
    return {"name": arn.rsplit(":", 1)[-1], "status": attributes.get("SubscriptionsConfirmed", "0")}


# part -> (its ID in the platform values, the call that reads its name and status)
_PARTS = {
    "agent_gw": (lambda p: p.agent_gw.get("id"), lambda c, i: c.ctl.get_gateway(gatewayIdentifier=i)),
    "tool_gw": (lambda p: p.tool_gw.get("id"), lambda c, i: c.ctl.get_gateway(gatewayIdentifier=i)),
    "engine": (lambda p: p.engine_id, lambda c, i: c.ctl.get_policy_engine(policyEngineId=i)),
    "catalog": (lambda p: p.registry_id, lambda c, i: c.reg.get_registry(registryId=i)),
    "machine": (lambda p: p.machine_arn, lambda c, i: c.sfn.describe_state_machine(stateMachineArn=i)),
    "topic": (lambda p: p.topic_arn, _topic),
}


def _platform(hub: Hub) -> list[dict]:
    """One row per part: its name and status as AWS returns them. A part with no ID in the platform values (its
    module is not deployed) has the state None and is not read."""
    p, rows = hub.platform(), []
    for key, (ident, read) in _PARTS.items():
        found = read(hub.c, ident(p)) if ident(p) else None
        rows.append({"key": key, "name": found["name"] if found else "", "service": SERVICES[key],
                     "state": found["status"] if found else None})
    return rows


def _counts(hub: Hub) -> dict:
    records = catalog(hub)
    return {"hosted": count(records, "AGENT", "APPROVED"), "in_review": count(records, "AGENT", "PENDING_APPROVAL"),
            "tools": count(records, "MCP", "APPROVED")}


def _company(hub: Hub) -> dict:
    """The company policy's mode as rollout.sh keeps it (SSM /<prefix>/policies/, None: off) and whether the custom
    guardrail's interceptor is on the agent gateway (GetGateway)."""
    mode = policy_rollout.deployed(hub.c, hub.s).get(COMPANY_POLICY)
    attached = guardrail_attach.status(hub.c, hub.s, hub.platform())["attached"]
    return {"guard_prompt": mode, "guardrail_attached": attached}


def _alarms(hub: Hub) -> list[dict]:
    """The alarms whose name starts with <prefix>-, by name."""
    pages = hub.c.cw.get_paginator("describe_alarms").paginate(AlarmNamePrefix=f"{hub.s.prefix}-")
    return sorted(({"name": a["AlarmName"], "state": a["StateValue"]} for pg in pages for a in pg.get("MetricAlarms", [])),
                  key=lambda a: a["name"])


def _catalog(hub: Hub) -> list[dict]:
    return [{"name": r["name"], "type": r.get("recordType", ""), "status": r.get("status", "")}
            for r in sorted(catalog(hub).values(), key=lambda r: r["name"])]


def view(hub: Hub) -> dict:
    hub.platform()                      # NotDeployed: the page that says so, before any panel
    return {"platform": panel(hub, "home.platform", lambda: _platform(hub)),
            "counts": panel(hub, "home.counts", lambda: _counts(hub)),
            "company": panel(hub, "home.company", lambda: _company(hub)),
            "alarms": panel(hub, "home.alarms", lambda: _alarms(hub)),
            "catalog": panel(hub, "home.catalog", lambda: _catalog(hub))}


@router.get("/")
def home(request: Request):
    return page(request, "home.html", view=view(request.app.state.hub), services=SERVICES, pictures=PICTURES,
                parameters_path=request.app.state.hub.s.ssm("policies", COMPANY_POLICY))
