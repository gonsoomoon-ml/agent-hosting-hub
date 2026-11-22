from platform_team.shared_code.config import Settings

def test_names_match_the_design():
    s = Settings()
    assert (s.region, s.prefix) == ("us-west-2", "hub")
    assert (s.agent_gateway, s.tool_gateway, s.engine) == ("hub-agents", "hub-tools", "hub_pe")
    assert (s.registry, s.topic, s.machine, s.rule) == ("hub-registry", "hub-alerts", "hub-review", "hub-on-submit")
    assert s.agent_role("quality_agent") == "hub-agent-quality_agent-role"
    assert s.project_name("quality_agent") == "hubQualityAgent"                 # one CLI project per agent
    assert s.runtime_name("quality_agent") == "hubQualityAgent_default_agent"   # the CLI names it <project>_<target>_<runtime>
    assert s.stack_name("quality_agent") == "AgentCore-hubQualityAgent-default"
    assert s.target_name("quality_agent") == "QualityAgent"
    assert s.ssm("agents", "quality_agent", "runtime_arn") == "/hub/agents/quality_agent/runtime_arn"
    assert s.bucket("111122223333") == "hub-111122223333-us-west-2"

def test_prefix_comes_from_env(monkeypatch):
    monkeypatch.setenv("DEMO_PREFIX", "hubx")
    assert Settings.from_env().tool_gateway == "hubx-tools"

def test_the_runtime_arn_of_an_agent_is_one_exact_form():          # final review M-2: Entry and the cleanup use it
    import re
    s, arn = Settings(), "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/hubQualityAgent_default_agent-eHcqNQ7n5v"
    assert re.fullmatch(s.runtime_arn_pattern("quality_agent", "111122223333"), arn)
    assert re.fullmatch(s.runtime_id_pattern("quality_agent"), arn.rsplit("/", 1)[1])
    assert not re.fullmatch(s.runtime_arn_pattern("quality", "111122223333"), arn)
