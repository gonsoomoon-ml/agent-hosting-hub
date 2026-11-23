"""Attaching the custom guardrail's interceptor to the agent gateway that exists, and detaching it. UpdateGateway
replaces the whole configuration (the service model: an optional field that is left out is reset), so every setting
the gateway has goes back unchanged. The client is a real boto3 client in a botocore Stubber: every call is checked
against the service model, and a call that is not expected fails the test."""
import datetime
from dataclasses import replace

import boto3
import pytest
from botocore.stub import Stubber

from platform_team.custom_guardrail import guardrail_attach
from platform_team.custom_guardrail.guardrail_attach import attach, attached, detach, status
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings
from platform_team.shared_code.hub_state import NotDeployed
from tests.fakes import ACCOUNT, PLATFORM

S, NOW = Settings(), datetime.datetime(2026, 11, 22)
GW, ARN = PLATFORM.agent_gw["id"], PLATFORM.interceptor_arn
OTHER = f"arn:aws:lambda:us-west-2:{ACCOUNT}:function:hub-audit"          # another team's interceptor on the same gateway
INTERCEPTOR = {"interceptor": {"lambda": {"arn": ARN}}, "interceptionPoints": ["REQUEST", "RESPONSE"],
               "inputConfiguration": {"passRequestHeaders": False}}
ANOTHER = {"interceptor": {"lambda": {"arn": OTHER}}, "interceptionPoints": ["REQUEST"],
           "inputConfiguration": {"passRequestHeaders": True}}
ENGINE = {"arn": PLATFORM.engine_arn, "mode": "ENFORCE"}
SETTINGS = {"name": "hub-agents", "description": "Agent gateway: company policy on every request to a hosted agent",
            "roleArn": f"arn:aws:iam::{ACCOUNT}:role/hub-agents-role", "authorizerType": "AWS_IAM",
            "policyEngineConfiguration": ENGINE, "exceptionLevel": "DEBUG"}
MORE = {"kmsKeyArn": f"arn:aws:kms:us-west-2:{ACCOUNT}:key/abcdefghij", "wafConfiguration": {"failureMode": "FAIL_CLOSE"}}


def gateway(status="READY", settings=SETTINGS, interceptors=None, **changes):
    """GetGateway's answer: the gateway's settings, its interceptors and `changes` (a value None leaves the key out).
    The read-only fields (ARN, URL, times, workload identity) are there too: UpdateGateway takes none of them."""
    g = {"gatewayArn": PLATFORM.agent_gw["arn"], "gatewayId": GW, "gatewayUrl": PLATFORM.agent_gw["url"],
         "createdAt": NOW, "updatedAt": NOW, "status": status, **settings,
         "workloadIdentityDetails": {"workloadIdentityArn": f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:"
                                                            "workload-identity-directory/default/workload-identity/hub-agents"},
         **({"interceptorConfigurations": interceptors} if interceptors else {})}
    g.update(changes)
    return {k: v for k, v in g.items() if v is not None}


def listed(*names):
    return {"items": [{"targetId": f"{n}-abcdefghij", "name": n, "status": "READY", "createdAt": NOW, "updatedAt": NOW}
                      for n in names]}


@pytest.fixture
def ctl(monkeypatch, tmp_path):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    c = Clients(boto3.Session(region_name="us-west-2", aws_access_key_id="test-access-key", aws_secret_access_key="example"))
    st = Stubber(c.ctl)
    st.activate()
    yield c, st
    st.assert_no_pending_responses()
    st.deactivate()


def _update(st, before, after_reads, targets_before=("QualityAgent",), targets_after=("QualityAgent",), sent=None):
    """GetGateway (before), its targets, UpdateGateway with `sent`, GetGateway until it settles, its targets again."""
    st.add_response("get_gateway", before, {"gatewayIdentifier": GW})
    st.add_response("list_gateway_targets", listed(*targets_before), {"gatewayIdentifier": GW, "maxResults": 100})
    st.add_response("update_gateway", {**after_reads[-1], "status": "UPDATING"}, {"gatewayIdentifier": GW, **sent})
    for read in after_reads:
        st.add_response("get_gateway", read, {"gatewayIdentifier": GW})
    st.add_response("list_gateway_targets", listed(*targets_after), {"gatewayIdentifier": GW, "maxResults": 100})


def test_attach_sends_every_setting_the_gateway_already_has(ctl):
    """get_gateway returns name, description, roleArn, authorizerType, policyEngineConfiguration and exceptionLevel;
    update_gateway is called with all of them unchanged plus interceptorConfigurations =
    [{"interceptor": {"lambda": {"arn": ARN}}, "interceptionPoints": ["REQUEST", "RESPONSE"], "inputConfiguration": {"passRequestHeaders": False}}]."""
    c, st = ctl
    after = gateway(interceptors=[INTERCEPTOR])
    # the first read after the update may still show the old gateway: it waits until READY shows the interceptor
    _update(st, gateway(), [gateway(), gateway("UPDATING", interceptors=[INTERCEPTOR]), after],
            sent={**SETTINGS, "interceptorConfigurations": [INTERCEPTOR]})
    assert attach(c, S, PLATFORM) == {"attached": True, "changed": True}


def test_attach_also_sends_back_settings_the_hub_does_not_use_and_another_interceptor(ctl):
    """A key, a WAF setting and another interceptor are reset by an UpdateGateway that leaves them out: they go back too."""
    c, st = ctl
    settings = {**SETTINGS, **MORE}
    _update(st, gateway(settings=settings, interceptors=[ANOTHER]),
            [gateway(settings=settings, interceptors=[ANOTHER, INTERCEPTOR])],
            sent={**settings, "interceptorConfigurations": [ANOTHER, INTERCEPTOR]})
    assert attach(c, S, PLATFORM) == {"attached": True, "changed": True}


def test_attach_twice_changes_nothing(ctl):
    c, st = ctl
    st.add_response("get_gateway", gateway(interceptors=[INTERCEPTOR]), {"gatewayIdentifier": GW})    # no update_gateway
    assert attach(c, S, PLATFORM) == {"attached": True, "changed": False}


def test_attach_fails_loudly_when_the_policy_engine_is_gone_after_the_update(ctl):
    c, st = ctl
    _update(st, gateway(), [gateway(interceptors=[INTERCEPTOR], policyEngineConfiguration=None)],
            sent={**SETTINGS, "interceptorConfigurations": [INTERCEPTOR]})
    with pytest.raises(RuntimeError, match="policy engine"):
        attach(c, S, PLATFORM)


def test_attach_fails_loudly_when_the_policy_engine_mode_changed_after_the_update(ctl):
    c, st = ctl
    _update(st, gateway(), [gateway(interceptors=[INTERCEPTOR], policyEngineConfiguration={**ENGINE, "mode": "LOG_ONLY"})],
            sent={**SETTINGS, "interceptorConfigurations": [INTERCEPTOR]})
    with pytest.raises(RuntimeError, match="policy engine"):
        attach(c, S, PLATFORM)


def test_attach_fails_loudly_when_a_target_is_gone_after_the_update(ctl):
    c, st = ctl
    _update(st, gateway(), [gateway(interceptors=[INTERCEPTOR])], targets_before=("QualityAgent", "ReleaseReview"),
            targets_after=("QualityAgent",), sent={**SETTINGS, "interceptorConfigurations": [INTERCEPTOR]})
    with pytest.raises(RuntimeError, match="targets .*ReleaseReview"):
        attach(c, S, PLATFORM)


def test_attach_fails_loudly_when_the_update_is_unsuccessful(ctl):
    c, st = ctl
    st.add_response("get_gateway", gateway(), {"gatewayIdentifier": GW})
    st.add_response("list_gateway_targets", listed(), {"gatewayIdentifier": GW, "maxResults": 100})
    st.add_response("update_gateway", gateway("UPDATING"), {"gatewayIdentifier": GW, **SETTINGS,
                                                            "interceptorConfigurations": [INTERCEPTOR]})
    st.add_response("get_gateway", gateway("UPDATE_UNSUCCESSFUL", statusReasons=["the Lambda was not found"]),
                    {"gatewayIdentifier": GW})
    with pytest.raises(RuntimeError, match="UPDATE_UNSUCCESSFUL.*the Lambda was not found"):
        attach(c, S, PLATFORM)


def test_attach_gives_up_when_the_update_does_not_settle_in_time(ctl, monkeypatch):
    c, st = ctl
    clock = iter(range(0, 1000, 100))
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    st.add_response("get_gateway", gateway(), {"gatewayIdentifier": GW})
    st.add_response("list_gateway_targets", listed(), {"gatewayIdentifier": GW, "maxResults": 100})
    st.add_response("update_gateway", gateway("UPDATING"), {"gatewayIdentifier": GW, **SETTINGS,
                                                            "interceptorConfigurations": [INTERCEPTOR]})
    for _ in range(3):
        st.add_response("get_gateway", gateway("UPDATING"), {"gatewayIdentifier": GW})
    with pytest.raises(TimeoutError, match="hub-agents"):
        attach(c, S, PLATFORM, wait=250)


def test_attach_refuses_a_gateway_that_is_not_the_hubs_agent_gateway(ctl):
    c, st = ctl
    st.add_response("get_gateway", gateway(name="other-agents"), {"gatewayIdentifier": GW})       # and nothing else
    with pytest.raises(RuntimeError, match="other-agents, not the hub's agent gateway hub-agents"):
        attach(c, S, PLATFORM)


@pytest.mark.parametrize("interceptor", [ARN + ":live", ARN + ":3", OTHER, ARN.replace("hub-guardrail", "hub-guardrails")])
def test_attach_refuses_any_function_but_the_hubs_interceptor_before_any_call(ctl, interceptor):
    """The agent gateway's role may invoke <prefix>-guardrail only (no version, no alias): with any other ARN the
    gateway would refuse every request."""
    c, _ = ctl
    with pytest.raises(RuntimeError, match="not the function hub-guardrail"):
        attach(c, S, replace(PLATFORM, interceptor_arn=interceptor))


def test_attach_without_the_interceptor_in_the_platform_values_says_deploy_first(ctl):
    c, _ = ctl
    with pytest.raises(RuntimeError, match="make deploy"):
        attach(c, S, replace(PLATFORM, interceptor_arn=""))


def test_detach_keeps_every_other_setting(ctl):
    c, st = ctl
    _update(st, gateway(interceptors=[INTERCEPTOR]), [gateway(interceptors=[INTERCEPTOR]), gateway()], sent=SETTINGS)
    assert detach(c, S, PLATFORM) == {"attached": False, "changed": True}


def test_detach_keeps_another_interceptor(ctl):
    c, st = ctl
    settings = {**SETTINGS, **MORE}
    _update(st, gateway(settings=settings, interceptors=[ANOTHER, INTERCEPTOR]),
            [gateway(settings=settings, interceptors=[ANOTHER])],
            sent={**settings, "interceptorConfigurations": [ANOTHER]})
    assert detach(c, S, PLATFORM) == {"attached": False, "changed": True}


def test_detach_fails_loudly_when_a_target_is_gone_after_the_update(ctl):
    c, st = ctl
    _update(st, gateway(interceptors=[INTERCEPTOR]), [gateway()], targets_after=(), sent=SETTINGS)
    with pytest.raises(RuntimeError, match="targets"):
        detach(c, S, PLATFORM)


def test_detach_of_a_gateway_without_it_changes_nothing(ctl):
    c, st = ctl
    st.add_response("get_gateway", gateway(interceptors=[ANOTHER]), {"gatewayIdentifier": GW})
    assert detach(c, S, PLATFORM) == {"attached": False, "changed": False}


def test_detach_when_the_gateway_is_gone_does_nothing(ctl):
    c, st = ctl
    st.add_client_error("get_gateway", "ResourceNotFoundException", http_status_code=404,
                        expected_params={"gatewayIdentifier": GW})
    assert detach(c, S, PLATFORM) == {"attached": False, "changed": False}


def test_attached_reads_the_interceptor_by_its_arn():
    assert attached(gateway(interceptors=[INTERCEPTOR]), ARN)
    assert attached(gateway(interceptors=[ANOTHER, INTERCEPTOR]), ARN)
    assert not attached(gateway(interceptors=[ANOTHER]), ARN)
    assert not attached(gateway(), ARN)
    assert not attached(gateway(interceptors=[INTERCEPTOR]), "")
    assert not attached(gateway(interceptors=[{"interceptor": {}, "interceptionPoints": ["REQUEST"]}]), ARN)


def test_status_reads_the_interceptor_the_policy_engine_and_the_targets(ctl):
    c, st = ctl
    st.add_response("get_gateway", gateway(interceptors=[INTERCEPTOR]), {"gatewayIdentifier": GW})
    st.add_response("list_gateway_targets", listed("ReleaseReview", "QualityAgent"), {"gatewayIdentifier": GW, "maxResults": 100})
    assert status(c, S, PLATFORM) == {"gateway": "hub-agents", "status": "READY", "attached": True,
                                      "points": ["REQUEST", "RESPONSE"], "policy_engine": ENGINE,
                                      "targets": ["QualityAgent", "ReleaseReview"]}


# ------------------------------------------------------------------ the command (guardrail.sh)

class _Clients:
    account = ACCOUNT


@pytest.fixture
def command(monkeypatch):
    """main() with the AWS side replaced: Clients, the platform values and status (a test replaces attach or detach)."""
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("DEMO_PREFIX", "hub")
    monkeypatch.setattr(guardrail_attach.Clients, "for_settings", lambda s: _Clients())
    monkeypatch.setattr(guardrail_attach, "load", lambda s, c: PLATFORM)
    view = {"gateway": "hub-agents", "status": "READY", "attached": True, "points": ["REQUEST", "RESPONSE"],
            "policy_engine": ENGINE, "targets": []}
    monkeypatch.setattr(guardrail_attach, "status", lambda c, s, p: view)
    return monkeypatch


def test_the_command_says_which_hub_and_what_it_found(command, capsys):
    assert guardrail_attach.main(["status"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "custom guardrail: status (prefix hub, region us-west-2)",
        "agent gateway hub-agents: READY",
        "attached: True (REQUEST, RESPONSE)",
        "policy engine: engine-1 in ENFORCE",
        "targets: none"]


@pytest.mark.parametrize("action, result, line", [
    ("attach", {"attached": True, "changed": True}, "attached: True (changed)"),
    ("attach", {"attached": True, "changed": False}, "attached: True (nothing changed)"),
    ("detach", {"attached": False, "changed": True}, "attached: False (changed)"),
])
def test_attach_and_detach_say_where_the_interceptor_stands(command, capsys, action, result, line):
    command.setattr(guardrail_attach, action, lambda c, s, p: result)
    assert guardrail_attach.main([action]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"custom guardrail: {action} (prefix hub, region us-west-2)" and out[1] == line


def test_detach_on_a_hub_that_is_not_deployed_does_nothing_and_succeeds(command, capsys):
    """make destroy runs it first: an empty account is not a failure."""
    def not_deployed(s, c):
        raise NotDeployed("nothing under /hub/platform/: run `make deploy` first")
    command.setattr(guardrail_attach, "load", not_deployed)
    assert guardrail_attach.main(["detach"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "nothing to detach: the hub is not deployed"
    assert guardrail_attach.main(["attach"]) == 1                                  # attach needs a hub


def test_a_failure_is_one_line_with_the_account_masked(command, capsys):
    def broken(c, s, p):
        raise RuntimeError(f"the agent gateway hub-agents lost its policy engine: arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:x")
    command.setattr(guardrail_attach, "attach", broken)
    assert guardrail_attach.main(["attach"]) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert last.startswith("attach of the custom guardrail stopped (prefix hub, region us-west-2): ")
    assert ACCOUNT not in last and "<ACCOUNT>" in last


@pytest.mark.parametrize("argv", [[], ["on"], ["attach", "now"]])
def test_an_unknown_action_prints_the_usage(argv, capsys):
    assert guardrail_attach.main(argv) == 2
    assert "guardrail.sh attach|detach|status" in capsys.readouterr().out
