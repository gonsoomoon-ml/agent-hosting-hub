"""The agents that are there from the start (hosting_review/preload_agents): the managed harness spec_assistant, which
the platform team hosts itself, and docs_adk, which goes through the review like any team's agent."""
import json
import pathlib

import pytest

from platform_team.company_policy import cedar_statements as cedar
from platform_team.hosting_review import preload_agents, review_steps
from platform_team.hosting_review.agent_cleanup import NotOwned
from platform_team.hosting_review.preload_agents import ask_harness, host_harness, preload
from platform_team.shared_code.config import Settings
from tests.fakes import ACCOUNT, ENV, PLATFORM, FakeClients, read_input

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC_ASSISTANT = json.loads((ROOT / "dev_team/preloaded_agents/spec_assistant/agent.json").read_text())
ROLE, HARNESS = "hub-agent-spec_assistant-role", "hub_spec_assistant"
HARNESS_ARN = f"arn:aws:bedrock-agentcore:us-west-2:{ACCOUNT}:harness/{HARNESS}-Ab12Cd34Ef"
MAKES = ("create", "submit", "delete", "put_object", "update_registry_record_status")


def _env():
    return {"HUB_REGION": "us-west-2", "PREFIX": "hub", "ACCOUNT": ACCOUNT, "MODEL_ID": Settings().model_id,
            "TOOL_GW_ARN": PLATFORM.tool_gw["arn"]}


def _record(c, name):
    return next(r for r in c.other_records if r["name"] == name)


def test_the_harness_application_names_its_hub_tools_and_its_instructions():
    assert {k: SPEC_ASSISTANT[k] for k in ("name", "team", "framework", "tools")} == {
        "name": "spec_assistant", "team": "parts", "framework": "harness",
        "tools": ["Parts___get_part_spec", "Parts___get_test_result"]}
    assert SPEC_ASSISTANT["description"].strip() and SPEC_ASSISTANT["system_prompt"].strip()


def test_a_harness_gets_a_bounded_role_its_permits_and_an_approved_record():
    c = FakeClients(record_status=None)
    out = host_harness(c, Settings(), PLATFORM, SPEC_ASSISTANT)
    assert c.roles[ROLE]["boundary"].endswith(":policy/hub-agent-boundary")
    assert c.roles[ROLE]["permissions"] == review_steps._execution_role(_env(), "spec_assistant")[1]   # as Grant makes it
    assert sorted(p["name"] for p in c.created_policies) == ["tool_spec_assistant_Parts_get_part_spec",
                                                              "tool_spec_assistant_Parts_get_test_result"]
    assert {p["statement"] for p in c.created_policies} == {
        cedar.tool_permit(ACCOUNT, ROLE, tool, PLATFORM.tool_gw["arn"]) for tool in SPEC_ASSISTANT["tools"]}
    harness = c.harnesses[HARNESS]
    # allowedTools selects a gateway's tools as @<the harness's name for the gateway>/<tool>; a plain name selects a
    # built-in tool (the AgentCore guide, "Tools"), so the application's names alone would allow no gateway tool
    assert harness["allowedTools"] == [f"@hub_tools/{t}" for t in SPEC_ASSISTANT["tools"]]
    assert harness["tools"] == [{"type": "agentcore_gateway", "name": "hub_tools", "config": {"agentCoreGateway": {
        "gatewayArn": PLATFORM.tool_gw["arn"], "outboundAuth": {"awsIam": {}}}}}]
    assert harness["executionRoleArn"] == f"arn:aws:iam::{ACCOUNT}:role/{ROLE}"
    assert harness["model"] == {"bedrockModelConfig": {"modelId": Settings().model_id}}
    assert harness["systemPrompt"] == [{"text": SPEC_ASSISTANT["system_prompt"]}]
    assert harness["memory"] == {"disabled": {}}          # no managed memory: the service would make one otherwise
    assert out == {"agent": "spec_assistant", "harness_arn": HARNESS_ARN, "record_status": "APPROVED", "kept": False}
    assert c.parameters["/hub/agents/spec_assistant/harness_arn"] == HARNESS_ARN
    record = _record(c, "spec_assistant")
    assert (record["status"], record["statusReason"]) == ("APPROVED", "preloaded by the platform team")
    assert json.loads(record["descriptors"]["custom"]["data"]) == SPEC_ASSISTANT
    # approval is asked first (the review it starts skips a harness), then given
    assert [m for s, m in c.calls if s == "reg" and m in ("submit_registry_record_for_approval",
                                                          "update_registry_record_status")] == [
        "submit_registry_record_for_approval", "update_registry_record_status"]
    assert review_steps.skip_reason(record).startswith("the application's framework is harness")


def test_grant_and_the_preload_make_an_agent_role_through_one_function(monkeypatch):
    """The harness's role is made the way Grant makes an agent role: both go through review_steps.ensure_agent_role,
    and for a new role it makes the same IAM calls for both (only the role's name and description differ)."""
    real, made = review_steps.ensure_agent_role, []

    def spy(c, env, agent, description):
        before = len(c.calls)
        arn = real(c, env, agent, description)
        made.append((agent, description, c.calls[before:]))
        return arn
    monkeypatch.setattr(review_steps, "ensure_agent_role", spy)
    harness, team = FakeClients(record_status=None), FakeClients()
    host_harness(harness, Settings(), PLATFORM, SPEC_ASSISTANT)
    review_steps.grant(review_steps.read(read_input(), team, ENV), team, ENV)
    calls = [("iam", "get_role"), ("iam", "create_role"), ("iam", "put_role_policy")]
    assert made == [("spec_assistant", "platform team: harness execution role", calls),
                    ("quality_agent", "hosting review: agent execution role", calls)]
    mine, grants = harness.roles[ROLE], team.roles["hub-agent-quality_agent-role"]
    assert (mine["trust"], mine["boundary"]) == (grants["trust"], grants["boundary"])
    assert harness.inline[ROLE] == team.inline["hub-agent-quality_agent-role"] == {"agent"}


def test_a_harness_application_without_a_description_gets_the_one_publish_gives():
    """The form does not require a description; the record then gets publish's (publish_agent.record_description)."""
    from platform_team.agent_catalog.publish_agent import record_description
    c = FakeClients(record_status=None)
    app = {k: v for k, v in SPEC_ASSISTANT.items() if k != "description"}
    assert host_harness(c, Settings(), PLATFORM, app)["record_status"] == "APPROVED"
    assert _record(c, "spec_assistant")["description"] == "spec_assistant: agent of team parts" == record_description(app)
    assert record_description(SPEC_ASSISTANT) == SPEC_ASSISTANT["description"]


@pytest.mark.parametrize("change, message", [
    ({"tools": ["Parts___get_part_spec", "Parts___delete_everything"]}, "tool not in the catalog: Parts___delete_everything"),
])
def test_a_harness_application_with_an_unknown_tool_is_refused_before_anything_is_made(change, message):
    c = FakeClients(record_status=None)
    with pytest.raises(ValueError, match=message):
        host_harness(c, Settings(), PLATFORM, {**SPEC_ASSISTANT, **change})
    assert c.calls == []


@pytest.mark.parametrize("prefix, change, message", [
    ("hub", {"framework": "strands"}, "framework must be harness"),
    ("hub", {"system_prompt": " "}, "system_prompt must be text"),
    ("hub", {"system_prompt": None}, "system_prompt must be text"),
    ("abcdefghij", {"name": "a" + "_b" * 15, "tools": []}, "harness name abcdefghij_a_b_b_b_b_b_b_b_b_b_b_b_b_b_b_b has 42 "
                                              "characters; CreateHarness takes at most 40"),
])
def test_a_harness_application_the_hub_cannot_host_is_refused_before_anything_is_made(prefix, change, message):
    c = FakeClients(record_status=None)
    with pytest.raises(ValueError, match=message):
        host_harness(c, Settings(prefix=prefix), PLATFORM, {**SPEC_ASSISTANT, **change})
    assert c.calls == []


def test_a_harness_is_not_made_under_a_role_or_beside_a_harness_the_hub_did_not_make():
    c = FakeClients(record_status=None, existing_roles={ROLE})
    c.role_boundaries[ROLE] = None                                      # a role of the name, made outside the hub
    with pytest.raises(NotOwned, match=f"role {ROLE} is not this hub's"):
        host_harness(c, Settings(), PLATFORM, SPEC_ASSISTANT)
    assert not [m for _, m in c.calls if m.startswith(MAKES) or m == "put_role_policy"]
    c = FakeClients(record_status=None)
    c.ctl.create_harness(harnessName=HARNESS, executionRoleArn=f"arn:aws:iam::{ACCOUNT}:role/someone-elses-role")
    c.calls.clear()
    with pytest.raises(NotOwned, match=f"harness {HARNESS} is not this hub's: it runs under role someone-elses-role"):
        host_harness(c, Settings(), PLATFORM, SPEC_ASSISTANT)
    assert not [m for _, m in c.calls if m.startswith(MAKES) or m == "put_role_policy"]


def _fake_publish(c, published):
    """publish_agent.publish as preload calls it: the team's path, which leaves the record PENDING_APPROVAL."""
    def publish(folder, s, variant=None, c=c):
        published.append(pathlib.Path(folder).name)
        c.other_records.append({"name": "docs_adk", "recordId": "rec-docs_adk", "recordType": "AGENT",
                                "status": "PENDING_APPROVAL"})
        return {"record_id": "rec-docs_adk", "status": "PENDING_APPROVAL", "code_key": "k", "code_version": "v1"}
    return publish


def _fake_review(outcome):
    """wait_review: the review of the record ends with `outcome`; one that succeeds leaves the record APPROVED."""
    def wait_review(c, p, record_id, after):
        if outcome == "SUCCEEDED":
            _record(c, "docs_adk")["status"] = "APPROVED"
        return {"execution": "review-1", "status": outcome, "seconds": 371}
    return wait_review


def test_preload_twice_makes_nothing_new(monkeypatch):
    c, published, lines = FakeClients(record_status=None), [], []
    monkeypatch.setattr(preload_agents, "load", lambda s, c=None: PLATFORM)
    monkeypatch.setattr(preload_agents, "publish", _fake_publish(c, published))
    monkeypatch.setattr(preload_agents, "wait_review", _fake_review("SUCCEEDED"))
    first = preload(Settings(), c, say=lines.append)
    assert first == {"spec_assistant": {"agent": "spec_assistant", "harness_arn": HARNESS_ARN, "record_status": "APPROVED",
                                        "kept": False},
                     "docs_adk": {"agent": "docs_adk", "record_status": "APPROVED",
                                  "review": {"execution": "review-1", "status": "SUCCEEDED", "seconds": 371}}}
    assert published == ["docs_adk"]
    n, said = len(c.calls), len(lines)
    second = preload(Settings(), c, say=lines.append)
    assert [m for _, m in c.calls[n:] if m.startswith(MAKES)] == []           # nothing made, asked for or changed
    assert published == ["docs_adk"] and list(c.harnesses) == [HARNESS] and len(c.created_policies) == 2
    assert second["docs_adk"] == {"agent": "docs_adk", "record_status": "APPROVED", "review": None}
    assert second["spec_assistant"] == {**first["spec_assistant"], "kept": True}
    assert all("kept" in line for line in lines[said:]), lines[said:]


OTHER_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
CHANGED_TOOLS = ["Parts___get_part_spec", "Quality___get_inspection_data"]      # one tool dropped, one added


def test_a_kept_harness_keeps_its_role_and_permits_when_the_model_or_the_tools_changed(monkeypatch):
    """A second host_harness under another MODEL_ID and with a changed tool list leaves the harness, its role's inline
    policy and its tool permits exactly as the first run made them: the role still allows only the model the harness
    runs, no permit is added or dropped. The preload's line for the agent says that the harness was kept with them."""
    c, lines = FakeClients(record_status=None), []
    monkeypatch.setattr(preload_agents, "load", lambda s, c=None: PLATFORM)
    monkeypatch.setattr(preload_agents, "publish", _fake_publish(c, []))
    monkeypatch.setattr(preload_agents, "wait_review", _fake_review("SUCCEEDED"))
    first = preload(Settings(), c, say=lines.append)["spec_assistant"]
    policy, harness = c.roles[ROLE]["permissions"], dict(c.harnesses[HARNESS])
    permits = sorted(p["name"] for p in c.created_policies)
    n, said = len(c.calls), len(lines)
    changed = {**SPEC_ASSISTANT, "tools": CHANGED_TOOLS}
    real = preload_agents.application
    monkeypatch.setattr(preload_agents, "application",
                        lambda folder: changed if folder == preload_agents.HARNESS_AGENT else real(folder))
    second = preload(Settings(model_id=OTHER_MODEL), c, say=lines.append)["spec_assistant"]
    assert [m for _, m in c.calls[n:] if m in ("create_role", "put_role_policy", "create_policy", "delete_policy",
                                                "create_harness", "update_harness")] == []
    assert c.roles[ROLE]["permissions"] == policy == review_steps._execution_role(_env(), "spec_assistant")[1]
    assert OTHER_MODEL not in json.dumps(policy) and Settings().model_id in json.dumps(policy)
    assert sorted(p["name"] for p in c.created_policies) == permits and c.deleted_policies == []
    assert c.harnesses[HARNESS] == harness and harness["model"] == {"bedrockModelConfig": {"modelId": Settings().model_id}}
    assert first["kept"] is False and second == {**first, "kept": True}
    line = lines[said]
    assert line.startswith("spec_assistant: harness hub_spec_assistant READY") and \
        "kept as it is, with its role and tool permits" in line, line
    assert "kept" not in lines[0], lines[0]                                 # the first run made the harness


def test_preload_stops_when_the_review_of_the_agent_with_code_does_not_approve_it(monkeypatch):
    c = FakeClients(record_status=None)
    monkeypatch.setattr(preload_agents, "load", lambda s, c=None: PLATFORM)
    monkeypatch.setattr(preload_agents, "publish", _fake_publish(c, []))
    monkeypatch.setattr(preload_agents, "wait_review", _fake_review("FAILED"))
    with pytest.raises(RuntimeError, match="docs_adk: review review-1 ended FAILED; the record is PENDING_APPROVAL"):
        preload(Settings(), c, say=lambda line: None)
    assert HARNESS in c.harnesses                                               # the harness came first and stays


QUESTION = "What is the spec of part P-100?"
STREAM = [
    {"messageStart": {"role": "assistant"}},
    {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Let me look that up."}}},
    {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolUse": {"toolUseId": "tool-1", "name": "Parts___get_part_spec"}}}},
    {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"part_id": "P-100"}'}}}},
    {"messageStop": {"stopReason": "tool_use"}},
    {"contentBlockStart": {"contentBlockIndex": 2, "start": {"toolResult": {"toolUseId": "tool-1", "status": "success"}}}},
    {"contentBlockDelta": {"contentBlockIndex": 2, "delta": {"toolResult": [{"text": '{"spec": "M4 x 12 mm, steel"}'}]}}},
    {"messageStop": {"stopReason": "tool_result"}},
    {"contentBlockDelta": {"contentBlockIndex": 3, "delta": {"text": " P-100 is M4 x 12 mm,"}}},
    {"contentBlockDelta": {"contentBlockIndex": 3, "delta": {"text": " steel."}}},
    {"messageStop": {"stopReason": "end_turn"}},
    {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, "metrics": {"latencyMs": 900}}},
]


def test_ask_harness_joins_the_text_of_the_stream():
    c = FakeClients()
    c.harness_stream = STREAM
    assert ask_harness(c, HARNESS_ARN, QUESTION) == "Let me look that up. P-100 is M4 x 12 mm, steel."
    call = c.harness_calls[0]
    assert (call["harnessArn"], call["messages"]) == (HARNESS_ARN, [{"role": "user", "content": [{"text": QUESTION}]}])
    assert set(call) == {"harnessArn", "runtimeSessionId", "messages"}       # no tools, model or prompt of the caller's
    ask_harness(c, HARNESS_ARN, QUESTION)
    assert c.harness_calls[0]["runtimeSessionId"] != c.harness_calls[1]["runtimeSessionId"]   # a new session each time


@pytest.mark.parametrize("event", ["runtimeClientError", "internalServerException", "validationException"])
def test_ask_harness_raises_the_error_the_stream_carries(event):
    c = FakeClients()
    c.harness_stream = [STREAM[1], {event: {"message": "the model is not available"}}]
    with pytest.raises(RuntimeError, match=f"the harness answered {event}: the model is not available"):
        ask_harness(c, HARNESS_ARN, QUESTION)
