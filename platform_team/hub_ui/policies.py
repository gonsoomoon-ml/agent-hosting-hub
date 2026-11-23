"""The company policy page: the policies of the two gateways (each with its status and its enforcement mode, kept apart),
the company policy guard_prompt with its mode and, per agent, how often it matched and would have refused a request in
the last hour (log-only counts), the custom guardrail, and the buttons that turn guard_prompt on in log-only mode,
enforce it, turn it off, and attach or detach the guardrail. A button starts one job that calls the function its shell
command calls: policy_rollout.rollout or remove, guardrail_attach.attach or detach."""
from fastapi import APIRouter, Request

from platform_team.company_policy import policy_names, policy_rollout
from platform_team.company_policy.policy_engine import list_policies
from platform_team.custom_guardrail import guardrail_attach
from platform_team.hub_ui import jobs
from platform_team.hub_ui.app import Hub, back, page, panel
from platform_team.hub_ui.texts import lang_of, translator

router = APIRouter()

COMPANY_POLICY = "guard_prompt"         # the one policy policy_rollout.POLICIES knows
MODES = (*policy_rollout.MODE_WORDS, "off")
GUARDRAIL_ACTIONS = ("attach", "detach")
REPORT_MINUTES = policy_rollout.REPORT_MINUTES
GATEWAY = "Amazon Bedrock AgentCore Gateway"
SERVICES = {"engine": "Policy in Amazon Bedrock AgentCore", "parameters": "AWS Systems Manager Parameter Store",
            "metrics": "Amazon CloudWatch", "gateway": GATEWAY, "guardrail": "Amazon Bedrock Guardrails",
            "interceptor": f"{GATEWAY} interceptor · AWS Lambda"}
SHARED_READ = "shared_tool_read"        # the developer team's permit to call the shared read tool (dev_access/terraform)
# kind -> the gateway whose requests its policies decide on: the tool permits are the tool gateway's, every other kind
# of policy_names is the agent gateway's
GATEWAY_OF = {kind: "tool_gw" if kind == "tool" else "agent_gw" for kind in policy_names.KINDS}
GATEWAY_OF["shared_read"] = "tool_gw"


def kind_of(name: str) -> tuple[str, str]:
    """(kind, gateway) of a policy name: a kind of policy_names.KINDS, or shared_read for the shared read tool's permit,
    and gateway "agent_gw" or "tool_gw"; ("other", "") for a name of no kind."""
    if name == SHARED_READ:
        return "shared_read", GATEWAY_OF["shared_read"]
    for kind, prefix in policy_names.KINDS.items():
        if name.startswith(prefix):
            return kind, GATEWAY_OF[kind]
    return "other", ""


def _policies(hub: Hub) -> dict[str, dict]:
    """The policy engine's policies by name (ListPolicies), through the cache."""
    return hub.cache.get("policies.list", lambda: list_policies(hub.c, hub.platform().engine_id))


def _gateways(hub: Hub) -> list[dict]:
    """The policies grouped by gateway, then the ones of no kind: [{"key": "agent_gw" | "tool_gw" | "other", "name":
    the gateway's name ("" for other), "policies": [{"name", "kind", "status", "mode"}]}]. status is the policy's own
    status (ACTIVE, CREATING, ...); mode is its enforcement mode (ACTIVE or LOG_ONLY; ListPolicies may leave it out:
    the service model says it then is ACTIVE)."""
    groups = {"agent_gw": [], "tool_gw": [], "other": []}
    for name, entry in sorted(_policies(hub).items()):
        kind, gateway = kind_of(name)
        groups[gateway or "other"].append({"name": name, "kind": kind, "status": entry.get("status", ""),
                                           "mode": entry.get("enforcementMode", "ACTIVE")})
    names = {"agent_gw": hub.s.agent_gateway, "tool_gw": hub.s.tool_gateway, "other": ""}
    return [{"key": key, "name": names[key], "policies": groups[key]} for key in groups]


def _company(hub: Hub) -> dict:
    """The two company policies. guard_secret is set at approval and has no switch: `agents` is how many agents have
    its policy (None when the policy list cannot be read; the rest of the panel shows). guard_prompt: `mode` is what
    rollout keeps in SSM (None: off)."""
    mode = policy_rollout.deployed(hub.c, hub.s).get(COMPANY_POLICY)
    try:
        agents = sum(1 for name in _policies(hub) if kind_of(name)[0] == "guard_secret")
    except Exception:                   # this count only: the mode stays on the page
        agents = None
    return {"guard_secret": {"key": "guard_secret", "fixed": True, "agents": agents},
            "guard_prompt": {"key": COMPANY_POLICY, "mode": mode}}


def _guardrail(hub: Hub) -> dict:
    found = guardrail_attach.status(hub.c, hub.s, hub.platform())
    return {"attached": found["attached"], "points": found["points"], "gateway_status": found["status"]}


def view(hub: Hub) -> dict:
    """The page's reads, each a panel (a failing read is one line there): gateways (the policy tables), company (both
    company policies and their modes), report (guard_prompt's counts per agent over the last REPORT_MINUTES minutes,
    {agent: {"mode", "matches", "flips"}}) and guardrail; busy is whether a job runs (its buttons then wait)."""
    hub.platform()                      # NotDeployed: the page that says so, before any panel
    job = hub.jobs.current()
    return {"gateways": panel(hub, "policies.gateways", lambda: _gateways(hub)),
            "company": panel(hub, "policies.company", lambda: _company(hub)),
            "report": panel(hub, "policies.report", lambda: policy_rollout.report(
                hub.c, hub.s, hub.platform(), COMPANY_POLICY, REPORT_MINUTES)),
            "guardrail": panel(hub, "policies.guardrail", lambda: _guardrail(hub)),
            "busy": job is not None and job.state == jobs.RUNNING}


@router.get("/policies")
def policies_page(request: Request):
    return page(request, "policies.html", view=view(request.app.state.hub), services=SERVICES,
                company_policy=COMPANY_POLICY, report_minutes=REPORT_MINUTES,
                parameters_path=request.app.state.hub.s.ssm("policies", COMPANY_POLICY))


def _mode_job(hub: Hub, key: str, mode: str, t, say) -> dict:
    """What rollout.sh does for the mode: policy_rollout.rollout (log-only, active) or remove (off), its lines said to
    the job, then one line per agent: the mode its policy shows after the call, in the words of the page."""
    if mode == "off":
        out = policy_rollout.remove(hub.c, hub.s, hub.platform(), key, say=say)
    else:
        out = policy_rollout.rollout(hub.c, hub.s, hub.platform(), key, mode, say=say)
    for agent, read in out["read"].items():
        word = t(f"mode.{read}") + f" ({read})" if read else t("mode.off")
        say(t("job.read_back", agent=agent, mode=word))
    return out


@router.post("/policies/{key}/mode")
async def set_mode(request: Request, key: str):
    """Start the job that turns the company policy on in log-only mode, enforces it, or turns it off (form `mode`:
    log-only, active or off). A policy this hub does not have a switch for, or another mode, starts nothing."""
    hub: Hub = request.app.state.hub
    if key not in policy_rollout.POLICIES:
        return back(request, "/policies", err="policy")
    mode = (await request.form()).get("mode")
    if mode not in MODES:
        return back(request, "/policies", err="mode")
    t = translator(lang_of(request, hub.lang))
    hub.jobs.start("rollout", key, lambda say: _mode_job(hub, key, mode, t, say))       # jobs.Busy: the app answers
    return back(request, "/policies", msg="started")


def _guardrail_job(hub: Hub, action: str, say) -> dict:
    """What guardrail.sh does: guardrail_attach.attach or detach, and one line for what it returned."""
    run = guardrail_attach.attach if action == "attach" else guardrail_attach.detach
    out = run(hub.c, hub.s, hub.platform())
    say(f"guardrail {'attached' if out['attached'] else 'detached'}: {'changed' if out['changed'] else 'unchanged'}")
    return out


@router.post("/guardrail/{action}")
def guardrail(request: Request, action: str):
    """Start the job that attaches or detaches the custom guardrail on the agent gateway."""
    hub: Hub = request.app.state.hub
    if action not in GUARDRAIL_ACTIONS:
        return back(request, "/policies", err="action")
    hub.jobs.start("guardrail", action, lambda say: _guardrail_job(hub, action, say))
    return back(request, "/policies", msg="started")
