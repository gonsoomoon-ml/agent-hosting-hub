import pathlib, re
ROOT = pathlib.Path("platform_team")
FEATURES = ("company_policy", "agent_gateway", "tool_gateway", "sample_tools", "agent_catalog", "agent_monitoring", "dev_access",
            "hosting_review")
TEXT = "\n".join(p.read_text() for p in sorted(ROOT.rglob("terraform/*.tf")))

def block(kind, name):
    m = re.search(r'resource\s+"%s"\s+"%s"\s*{(.*?)\n}\n' % (kind, name), TEXT, re.S)
    assert m, f"{kind}.{name} is not declared"
    return m.group(1)

def test_every_feature_folder_has_the_same_shape():
    assert [str(p) for p in ROOT.rglob("*.tf") if p.parent.name != "terraform"] == []      # Terraform only inside terraform/
    for feature in FEATURES:
        for name in ("README.md", "terraform/main.tf", "terraform/variables.tf", "terraform/outputs.tf"):
            assert (ROOT / feature / name).is_file(), f"{feature}/{name}"

def test_the_start_point_calls_each_feature_by_its_folder_name():
    root = (ROOT / "terraform" / "main.tf").read_text()
    for feature in FEATURES:
        assert re.search(r'module\s+"%s"\s*{[^}]*source\s*=\s*"\.\./%s/terraform"' % (feature, feature), root, re.S), feature

def test_names_come_from_the_prefix_variable():
    assert re.search(r'variable\s+"prefix"\s*{[^}]*default\s*=\s*"hub"', TEXT, re.S)
    assert not re.search(r'"hub[-_]', TEXT)                     # no hard-coded names

def test_agent_gateway_has_no_protocol_type_and_keeps_what_operations_change():
    agents, tools = block("aws_bedrockagentcore_gateway", "agents"), block("aws_bedrockagentcore_gateway", "tools")
    assert "protocol_type" not in agents and re.search(r'protocol_type\s*=\s*"MCP"', tools)
    for gw in (agents, tools):
        assert "var.policy_engine_arn" in gw and re.search(r'mode\s*=\s*"ENFORCE"', gw)
    assert re.search(r"ignore_changes\s*=\s*\[\s*interceptor_configuration\s*\]", agents)

def test_outputs_are_published_for_the_python_side():
    for key in ("agent_gateway_id", "agent_gateway_arn", "agent_gateway_url", "tool_gateway_id", "tool_gateway_arn", "tool_gateway_url",
                "engine_id", "engine_arn", "registry_id", "topic_arn", "tool_lambda_arn", "dev_role_arn", "bucket", "machine_arn"):
        assert f"/platform/{key}" in TEXT

def test_the_review_gets_every_variable_its_code_reads():
    hosting = (ROOT / "hosting_review" / "terraform" / "main.tf").read_text()
    review = ROOT / "hosting_review"
    lambdas = set(re.findall(r"env\[[\"'](\w+)[\"']\]", (review / "review_steps.py").read_text() + (review / "lambda_handler.py").read_text()))
    assert lambdas and [k for k in sorted(lambdas) if not re.search(r"\b%s\s*=" % k, hosting)] == []      # Lambda environment
    from platform_team.hosting_review.deploy_build import REQUIRED_ENV
    per_run = {"AGENT", "CODE_KEY", "CODE_VERSION", "ROLE_ARN"}                     # from the state machine
    project = set(REQUIRED_ENV) - per_run - {"AWS_REGION"}                           # AWS_REGION: CodeBuild sets it
    deploy = block("aws_codebuild_project", "deploy")
    assert [k for k in sorted(project) if not re.search(r'name\s*=\s*"%s"' % k, deploy)] == []            # CodeBuild environment

def test_each_lambda_timeout_leaves_one_full_wait_after_the_margin():
    from platform_team.hosting_review import review_steps as steps
    from platform_team.hosting_review.lambda_handler import MARGIN
    hosting = (ROOT / "hosting_review" / "terraform" / "main.tf").read_text()
    body = re.search(r"\n  steps = {(.*?)\n  }", hosting, re.S).group(1)
    timeout = {k: int(v) for k, v in re.findall(r"(\w+)\s*=\s*(\d+)", body)}
    longest = {"read": 0, "grant": steps.POLICY_WAIT, "entry": max(steps.POLICY_WAIT, steps.TARGET_WAIT),
               "testcall": steps.CALL_TIMEOUT, "approve": steps.POLICY_WAIT}       # the longest single wait of each step
    assert set(timeout) == set(steps.STEPS) == set(longest)
    assert [s for s in timeout if timeout[s] > 900 or (longest[s] and timeout[s] - MARGIN < longest[s])] == []
