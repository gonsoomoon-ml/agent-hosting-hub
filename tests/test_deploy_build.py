import json, re, tomllib, pytest, yaml
from platform_team.hosting_review import deploy_build as d

ROLE = "arn:aws:iam::123456789012:role/hub-agent-quality_agent-role"
GW = "https://hub-tools-abcdefghij.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp"
MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
ENV = {"AGENT": "quality_agent", "PREFIX": "hub", "AWS_REGION": "us-west-2", "ROLE_ARN": ROLE, "TOOL_GW_URL": GW,
       "MODEL_ID": MODEL, "BUCKET": "hub-123456789012-us-west-2", "CODE_KEY": "submissions/quality_agent/agent.zip",
       "CODE_VERSION": "v1"}
ARN = "arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/hubQualityAgent_default_agent-AbCdEf1234"

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
    req = 'boto3==1.40.0  # the SDK\n\n# a comment\nrequests[socks]>=2\nurllib3 \\\n  <3\n'
    doc = tomllib.loads(d.pyproject_from(req, "hubQualityAgent"))
    assert doc["project"]["name"] == "hubQualityAgent" and doc["project"]["requires-python"] == ">=3.13"
    assert doc["project"]["dependencies"] == ["boto3==1.40.0", "requests[socks]>=2", "urllib3 <3"]

def test_pyproject_follows_the_scan_rule_for_requirements():
    for line in ("--index-url https://example.com/simple", "pkg @ https://example.com/pkg.whl", "./local_pkg",
                 'jinja2==2.11.2 ; platform_release == ""'):
        with pytest.raises(ValueError, match=r"^requirements\.txt: .+: " + re.escape(line) + "$"):
            d.pyproject_from(f"requests\n{line}\n", "hubQualityAgent")

def test_prepare_code_keeps_the_team_code_and_drops_its_build_settings(tmp_path):
    src, code = tmp_path / "submission", tmp_path / "project" / "app" / "agent"
    for name, text in {"main.py": "team code", "requirements.txt": "boto3\n", "helpers/util.py": "X = 1\n",
                       "pyproject.toml": "[project]\nname = 'team'\n", "uv.lock": "version = 1\n",
                       "uv.toml": "[pip]\nindex-url = 'http://127.0.0.1:9/evil-simple'\n", ".python-version": "3.8\n"}.items():
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text(text)
    code.mkdir(parents=True)
    (code / "main.py").write_text("from the CLI template")
    (code / "README.md").write_text("from the CLI template")
    dropped = d.prepare_code(src, code, "# the platform's pyproject\n")
    assert dropped == [".python-version", "pyproject.toml", "uv.lock", "uv.toml"]
    assert sorted(p.relative_to(code).as_posix() for p in code.rglob("*") if p.is_file()) == [
        "helpers/util.py", "main.py", "pyproject.toml", "requirements.txt"]
    assert (code / "main.py").read_text() == "team code"
    assert (code / "pyproject.toml").read_text() == "# the platform's pyproject\n"

def test_the_deploy_build_reads_no_uv_config_and_sends_no_telemetry():
    doc = yaml.safe_load((d.TEMPLATE.parents[1] / "buildspec_deploy.yml").read_text())
    variables = doc["env"]["variables"]
    assert variables["UV_NO_CONFIG"] == "1" and variables["AGENTCORE_TELEMETRY_DISABLED"] == "1"
    assert all(isinstance(c, str) for phase in doc["phases"].values() for c in phase.get("commands", []))
