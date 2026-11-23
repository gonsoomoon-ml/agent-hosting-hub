"""Attach the custom guardrail's interceptor to the agent gateway that exists, detach it, or say where it stands.

    platform_team/custom_guardrail/guardrail.sh attach|detach|status
    python -m platform_team.custom_guardrail.guardrail_attach detach        # make destroy, first

The interceptor is the Lambda <prefix>-guardrail; Terraform makes it and writes its ARN to SSM
/<prefix>/platform/interceptor_arn. It is attached by an API call during operation, not by Terraform (the agent
gateway's Terraform ignores its interceptor setting).

UpdateGateway replaces the whole configuration of a gateway: an optional field it is not given is reset (the service
model's documentation of UpdateGateway). So attach and detach read the gateway first and send back every setting that
UpdateGateway takes, as GetGateway gave it, with only the interceptors changed (another interceptor stays). Then they
wait until the gateway is READY and shows the change, and compare its policy engine and the names of its targets with
what was there before. A difference raises RuntimeError; the update is not undone.
"""
import sys
import time

from botocore.exceptions import ClientError

from platform_team.agent_gateway.gateway_targets import targets
from platform_team.hosting_review.agent_cleanup import cause
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import NotDeployed, Platform, load

# Every field of GetGateway's answer that UpdateGateway takes, except the interceptors (service model, botocore 1.44.9)
KEPT = ("name", "description", "roleArn", "authorizerType", "authorizerConfiguration", "protocolType",
        "protocolConfiguration", "kmsKeyArn", "customTransformConfiguration", "policyEngineConfiguration",
        "exceptionLevel", "wafConfiguration", "domainOverride")
POINTS = ("REQUEST", "RESPONSE")
UPDATE_WAIT = 300           # s, until the updated gateway is READY with the change
STEP = 3                    # s, between two looks at it
FAILED = ("UPDATE_UNSUCCESSFUL", "FAILED")


def interceptor(arn: str) -> dict:
    """What attach adds: the Lambda `arn` on every request and every answer, without the request's headers."""
    return {"interceptor": {"lambda": {"arn": arn}}, "interceptionPoints": list(POINTS),
            "inputConfiguration": {"passRequestHeaders": False}}


def _arn(config: dict) -> str:
    return ((config.get("interceptor") or {}).get("lambda") or {}).get("arn", "")


def _ours(gateway: dict, interceptor_arn: str) -> list[dict]:
    return [i for i in gateway.get("interceptorConfigurations") or [] if interceptor_arn and _arn(i) == interceptor_arn]


def _others(gateway: dict, interceptor_arn: str) -> list[dict]:
    return [i for i in gateway.get("interceptorConfigurations") or [] if _arn(i) != interceptor_arn]


def attached(gateway: dict, interceptor_arn: str) -> bool:
    """Whether the Lambda `interceptor_arn` is one of the gateway's interceptors (GetGateway's answer)."""
    return bool(_ours(gateway, interceptor_arn))


def _function(s: Settings, p: Platform) -> str:
    """The interceptor's ARN, when it is the function <prefix>-guardrail of this account and Region with no version or
    alias: the only one the agent gateway's role may invoke. With any other the gateway would refuse every request."""
    if not p.interceptor_arn:
        raise RuntimeError("no interceptor in the platform values (interceptor_arn): run `make deploy` first")
    name = f"{s.prefix}-guardrail"
    if p.interceptor_arn != f"arn:aws:lambda:{s.region}:{p.account}:function:{name}":
        raise RuntimeError(f"interceptor {p.interceptor_arn} is not the function {name} of this account and Region "
                           "(the agent gateway's role may invoke that one only): nothing was changed")
    return p.interceptor_arn


def _read(c, s: Settings, p: Platform) -> dict:
    """The agent gateway, as GetGateway gives it. One whose name is not the hub's agent gateway raises RuntimeError."""
    gid = p.agent_gw.get("id")
    if not gid:
        raise RuntimeError("no agent gateway in the platform values: run `make deploy` first")
    g = c.ctl.get_gateway(gatewayIdentifier=gid)
    if g["name"] != s.agent_gateway:
        raise RuntimeError(f"gateway {gid} is {g['name']}, not the hub's agent gateway {s.agent_gateway}: "
                           "it is left as it is")
    return g


def _settled(c, gid: str, interceptor_arn: str, want: bool, wait: int) -> dict:
    """Read the gateway until it is READY and shows the change (the interceptor attached, or not, as `want`)."""
    t0 = time.monotonic()
    while True:
        g = c.ctl.get_gateway(gatewayIdentifier=gid)
        if g["status"] in FAILED:
            raise RuntimeError(f"agent gateway {g['name']} {g['status']}: {g.get('statusReasons')}")
        if g["status"] == "READY" and attached(g, interceptor_arn) == want:
            return g
        if time.monotonic() - t0 > wait:
            raise TimeoutError(f"agent gateway {g['name']} not READY with the change within {wait}s "
                               f"(status {g['status']})")
        time.sleep(STEP)


def _update(c, p: Platform, before: dict, interceptors: list[dict], want: bool, wait: int) -> dict:
    """UpdateGateway with every kept setting of `before` and these interceptors (none: the field is left out, which
    removes them); wait until it settles; then the same policy engine and target names, or RuntimeError."""
    gid = p.agent_gw["id"]
    names = sorted(targets(c, gid))
    kept = {k: before[k] for k in KEPT if k in before}
    c.ctl.update_gateway(gatewayIdentifier=gid, **kept, **({"interceptorConfigurations": interceptors} if interceptors else {}))
    after = _settled(c, gid, p.interceptor_arn, want, wait)
    problems = []
    if after.get("policyEngineConfiguration") != before.get("policyEngineConfiguration"):
        problems.append(f"policy engine {before.get('policyEngineConfiguration')} before, "
                        f"{after.get('policyEngineConfiguration')} after")
    now = sorted(targets(c, gid))
    if now != names:
        problems.append(f"targets {names} before, {now} after")
    if problems:
        raise RuntimeError(f"the agent gateway {before['name']} changed in the update: {'; '.join(problems)} "
                           "(the update is not undone)")
    return after


def attach(c, s: Settings, p: Platform, wait: int = UPDATE_WAIT) -> dict:
    """Attach the interceptor to the agent gateway, keeping every other setting. Already attached: nothing changes.
    Returns {"attached": bool, "changed": bool}."""
    arn = _function(s, p)
    g = _read(c, s, p)
    if attached(g, arn):
        return {"attached": True, "changed": False}
    after = _update(c, p, g, _others(g, arn) + [interceptor(arn)], True, wait)
    return {"attached": attached(after, arn), "changed": True}


def detach(c, s: Settings, p: Platform, wait: int = UPDATE_WAIT) -> dict:
    """Detach the interceptor from the agent gateway, keeping every other setting (another interceptor too). Not
    attached, no agent gateway in the platform values, or the gateway gone: nothing changes.
    Returns {"attached": bool, "changed": bool}."""
    if not p.agent_gw.get("id"):
        return {"attached": False, "changed": False}
    try:
        g = _read(c, s, p)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return {"attached": False, "changed": False}
    if not attached(g, p.interceptor_arn):
        return {"attached": False, "changed": False}
    after = _update(c, p, g, _others(g, p.interceptor_arn), False, wait)
    return {"attached": attached(after, p.interceptor_arn), "changed": True}


def status(c, s: Settings, p: Platform) -> dict:
    """The agent gateway's status, whether the interceptor is attached and at which points, its policy engine
    configuration and its targets' names."""
    g = _read(c, s, p)
    ours = _ours(g, p.interceptor_arn)
    return {"gateway": g["name"], "status": g["status"], "attached": bool(ours),
            "points": sorted(ours[0].get("interceptionPoints", [])) if ours else [],
            "policy_engine": g.get("policyEngineConfiguration"), "targets": sorted(targets(c, p.agent_gw["id"]))}


# ================================================================== the command

ACTIONS = ("attach", "detach", "status")
USAGE = "usage: platform_team/custom_guardrail/guardrail.sh attach|detach|status"


def _engine(config: dict | None) -> str:
    if not config:
        return "none"
    return f"{config['arn'].rsplit('/', 1)[-1]} in {config.get('mode')}"


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ACTIONS:
        print(USAGE)
        return 2
    action = argv[0]
    hub = "this hub"                # the first line says which hub: its prefix and region
    try:
        s = Settings.from_env()
        hub = f"prefix {s.prefix}, region {s.region}"
        print(f"custom guardrail: {action} ({hub})", flush=True)
        c = Clients.for_settings(s)
        try:
            p = load(s, c)
        except NotDeployed:
            if action != "detach":
                raise
            print("nothing to detach: the hub is not deployed")         # make destroy on an empty account
            return 0
        if action == "status":
            view = status(c, s, p)
            print(f"agent gateway {view['gateway']}: {view['status']}")
            print(f"attached: {view['attached']}" + (f" ({', '.join(view['points'])})" if view["attached"] else ""))
            print(f"policy engine: {_engine(view['policy_engine'])}")
            print(f"targets: {', '.join(view['targets']) or 'none'}")
            return 0
        out = (attach if action == "attach" else detach)(c, s, p)
    except Exception as e:          # say what failed in one line, no traceback
        print(f"{action} of the custom guardrail stopped ({hub}): {cause(e)}")
        return 1
    print(f"attached: {out['attached']} ({'changed' if out['changed'] else 'nothing changed'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
