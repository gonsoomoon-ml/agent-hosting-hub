import re

import pytest

from platform_team.agent_catalog.application_form import NAME_LENGTH
from platform_team.shared_code.config import Settings

def test_names_match_the_design():
    s = Settings()
    assert (s.region, s.prefix) == ("us-west-2", "hub")
    assert (s.agent_gateway, s.tool_gateway, s.engine) == ("hub-agents", "hub-tools", "hub_pe")
    assert (s.registry, s.topic, s.machine, s.rule) == ("hub-registry", "hub-alerts", "hub-review", "hub-on-submit")
    assert s.agent_role("quality_agent") == "hub-agent-quality_agent-role"
    assert s.runtime_name("quality_agent") == "hub_quality_agent"                # one Runtime per agent
    assert s.target_name("quality_agent") == "QualityAgent"
    assert s.ssm("agents", "quality_agent", "runtime_arn") == "/hub/agents/quality_agent/runtime_arn"
    assert s.bucket("123456789012") == "hub-123456789012-us-west-2"

def test_prefix_comes_from_env(monkeypatch):
    monkeypatch.setenv("DEMO_PREFIX", "hubx")
    assert Settings.from_env().tool_gateway == "hubx-tools"

def test_the_runtime_arn_of_an_agent_is_one_exact_form():          # Entry and the cleanup use it
    s, arn = Settings(), "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-eHcqNQ7n5v"
    assert re.fullmatch(s.runtime_arn_pattern("quality_agent", "123456789012"), arn)
    assert re.fullmatch(s.runtime_id_pattern("quality_agent"), arn.rsplit("/", 1)[1])
    assert not re.fullmatch(s.runtime_arn_pattern("quality", "123456789012"), arn)

def test_the_runtime_of_an_agent_is_named_after_the_hub_and_the_agent():
    s, arn = Settings(), "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hub_quality_agent-Ab12Cd34Ef"
    assert s.runtime_name("quality_agent") == "hub_quality_agent"
    assert re.fullmatch(s.runtime_arn_pattern("quality_agent", "123456789012"), arn)
    assert not re.fullmatch(s.runtime_arn_pattern("quality", "123456789012"), arn)       # a name that only starts the same
    assert s.package_key("quality_agent", "v1") == "packages/quality_agent/v1.zip"

def test_the_longest_prefix_and_agent_name_give_a_runtime_name_agentcore_takes():
    longest = "a" + "_b" * ((NAME_LENGTH[1] - 1) // 2)                   # a valid agent name of the most characters
    assert len(longest) == NAME_LENGTH[1]
    name = Settings(prefix="abcdefghij").runtime_name(longest)          # the prefix has at most 10 characters
    assert re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", name), name      # CreateAgentRuntime's agentRuntimeName


def test_a_harness_is_named_like_a_runtime_and_the_service_model_takes_that_shape():
    import botocore.session
    from platform_team.hosting_review.preload_agents import HARNESS_NAME_MAX
    s = Settings()
    assert s.harness_name("spec_assistant") == "hub_spec_assistant" == s.runtime_name("spec_assistant")
    # the Runtime AgentCore runs the harness on, named by AgentCore (seen on 2026-11-22): its ID, its workload identity
    # and its log group are named after it
    assert s.harness_runtime_name("spec_assistant") == "harness_hub_spec_assistant"
    shape = botocore.session.get_session().get_service_model("bedrock-agentcore-control").shape_for("HarnessName")
    assert shape.metadata["pattern"] == r"[a-zA-Z][a-zA-Z0-9_]{0,39}" and HARNESS_NAME_MAX == 40
    assert re.fullmatch(shape.metadata["pattern"], s.harness_name("spec_assistant"))
    # shorter than a Runtime's 48: the longest agent name with the longest prefix does not fit, so host_harness refuses it
    assert len(Settings(prefix="abcdefghij").harness_name("a" + "_b" * 15)) == 42 > HARNESS_NAME_MAX


def test_the_prefix_harness_is_refused():
    # AgentCore names the Runtime a harness runs on harness_<harness name>. With the prefix harness, agent harness_b's
    # Runtime would be harness_harness_b, the name of agent b's harness Runtime, and the same would hold for their
    # workload identities and log groups; with the prefix hub, agent x's harness Runtime harness_hub_x would be the
    # Runtime of agent hub_x in a hub of the prefix harness.
    from platform_team.shared_code import config
    with pytest.raises(ValueError, match="prefix 'harness' is not taken: AgentCore names the Runtime of a harness"):
        Settings(prefix="harness")
    assert config.RESERVED_PREFIXES == ("harness",)
    for prefix in ("harnes", "harnessx", "xharness"):            # only the one word
        assert Settings(prefix=prefix).prefix == prefix


def test_terraform_refuses_the_prefix_harness_too():
    import pathlib
    from platform_team.shared_code import config
    text = (pathlib.Path(__file__).resolve().parents[1] / "platform_team" / "terraform" / "variables.tf").read_text()
    block = re.search(r'variable\s+"prefix"\s*{(.*?)\n}\n', text, re.S).group(1)
    reserved = re.findall(r'condition\s*=\s*!contains\(\[(.*?)\], var\.prefix\)', block)
    assert [re.findall(r'"([^"]+)"', r) for r in reserved] == [list(config.RESERVED_PREFIXES)]
