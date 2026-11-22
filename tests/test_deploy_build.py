import json, tomllib, pytest
from platform_team.hosting_review import deploy_build as d

ROLE = "arn:aws:iam::111122223333:role/hub-agent-quality_agent-role"
GW = "https://hub-tools-abc.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
ENV = {"AGENT": "quality_agent", "PREFIX": "hub", "AWS_REGION": "us-west-2", "ROLE_ARN": ROLE, "TOOL_GW_URL": GW,
       "MODEL_ID": MODEL, "BUCKET": "hub-111122223333-us-west-2", "CODE_KEY": "submissions/quality_agent/agent.zip",
       "CODE_VERSION": "v1"}
ARN = "arn:aws:bedrock-agentcore:us-west-2:111122223333:runtime/hubQualityAgent_default_agent-AbCdEf1234"

def test_agentcore_json_comes_from_the_platform_template():
    config = json.loads(d.render_config(d.TEMPLATE.read_text(), d.template_values(ENV)))
    assert config["name"] == "hubQualityAgent" and config["version"] == 2 and config["memories"] == []
    [runtime] = config["runtimes"]
    assert runtime == {
        "name": "agent", "build": "CodeZip", "entrypoint": "main.py", "codeLocation": "app/agent",
        "runtimeVersion": "PYTHON_3_13", "executionRoleArn": ROLE, "instrumentation": {"enableOtel": False},
        "envVars": [{"name": "HUB_REGION", "value": "us-west-2"}, {"name": "TOOL_GATEWAY_URL", "value": GW},
                    {"name": "MODEL_ID", "value": MODEL}, {"name": "AGENT_NAME", "value": "quality_agent"}]}

def test_a_value_fills_a_string_and_cannot_change_the_structure():
    text = d.render_config('{"a": "${X}", "b": ["x-${Y}"], "n": 2}', {"X": 'say "hi", }', "Y": "y"})
    assert json.loads(text) == {"a": 'say "hi", }', "b": ["x-y"], "n": 2}

def test_a_missing_value_is_a_clear_error():
    with pytest.raises(ValueError, match="the template needs a value for X"):
        d.render_config('{"a": "${X}"}', {})

def test_runtime_arn_is_read_from_the_deploy_output():
    out = ("deploying AgentCore-hubQualityAgent-default (usually takes a few minutes)\n"
           "deployed project 'hubQualityAgent' to target 'default'\n"
           + json.dumps({"message": "deployed", "outputs": {
               "ApplicationRuntimeAgentRuntimeIdOutput365FEF13": "hubQualityAgent_default_agent-AbCdEf1234",
               "ApplicationRuntimeAgentRoleArnOutput85617F70": ROLE,
               "ApplicationRuntimeAgentRuntimeArnOutputA6DA7CF5": ARN}}, indent=2) + "\n")
    assert d.runtime_arn(out) == ARN
    same_twice = json.dumps({"outputs": {"ARuntimeArnOutput1": ARN, "BRuntimeArnOutput2": ARN}})
    assert d.runtime_arn(same_twice) == ARN

def test_runtime_arn_absent_or_ambiguous_is_a_clear_error():
    for out in ("deploy failed\n", json.dumps({"outputs": {"ApplicationRuntimeAgentRuntimeIdOutput365FEF13": "x"}})):
        with pytest.raises(ValueError, match="no RuntimeArnOutput in the agentcore deploy output"):
            d.runtime_arn(out)
    two = json.dumps({"outputs": {"ARuntimeArnOutput1": ARN, "BRuntimeArnOutput2": ARN + "x"}})
    with pytest.raises(ValueError, match="more than one Runtime ARN in the agentcore deploy output"):
        d.runtime_arn(two)

def test_pyproject_lists_what_requirements_txt_lists():
    req = 'boto3==1.40.0  # the SDK\n\n# a comment\nrequests>=2 ; python_version >= "3.10"\nurllib3 \\\n  <3\n'
    doc = tomllib.loads(d.pyproject_from(req, "hubQualityAgent"))
    assert doc["project"]["name"] == "hubQualityAgent" and doc["project"]["requires-python"] == ">=3.13"
    assert doc["project"]["dependencies"] == ["boto3==1.40.0", 'requests>=2 ; python_version >= "3.10"', "urllib3 <3"]

def test_pyproject_refuses_pip_options():
    for line in ("--index-url https://example.com/simple", "-r more.txt", "boto3==1.40.0 --hash=sha256:abc"):
        with pytest.raises(ValueError, match="pip option.*not supported"):
            d.pyproject_from(f"requests\n{line}\n", "hubQualityAgent")
