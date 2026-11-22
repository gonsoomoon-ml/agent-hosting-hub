import pathlib, re
ROOT = pathlib.Path("platform_team")
FEATURES = ("company_policy", "agent_gateway", "tool_gateway", "sample_tools", "agent_catalog", "agent_monitoring", "dev_access",
            "hosting_review", "custom_guardrail")
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
                "engine_id", "engine_arn", "registry_id", "topic_arn", "tool_lambda_arn", "dev_role_arn", "bucket", "machine_arn",
                "interceptor_arn"):
        assert f"/platform/{key}" in TEXT
    from dataclasses import fields
    from platform_team.shared_code.hub_state import Platform
    published = set(re.findall(r'"/\$\{var\.prefix\}/platform/(\w+)"', (ROOT / "terraform" / "outputs.tf").read_text()))
    plain = {f.name for f in fields(Platform)} - {"account", "agent_gw", "tool_gw"}
    assert sorted(plain - published) == []                      # every plain value the Python side reads is written

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

# ------------------------------------------------------------------ found on AWS (Task 12)

def test_the_dev_role_reads_the_hub_values_publish_needs():
    # publish.sh runs as the dev team role and first reads /<prefix>/platform/ (hub_state.load). On AWS:
    # "not authorized to perform: ssm:GetParametersByPath on resource: ...:parameter/hub/platform"
    dev = block("aws_iam_role_policy", "dev")
    reads = [line for line in dev.splitlines() if '"ssm:' in line]          # one statement per line
    assert len(reads) == 1 and re.search(r'Action\s*=\s*\["ssm:GetParametersByPath"\]', reads[0])
    assert re.search(r'Resource\s*=\s*\["arn:aws:ssm:\$\{[\w.]+\}:\$\{[\w.]+\}:parameter/\$\{var\.prefix\}/platform"\]', reads[0])

# ------------------------------------------------------------------ the gateway roles

GATEWAYS = {"agents": "agent_gateway", "tools": "tool_gateway"}      # the role's name in Terraform, its module

def gateway_block(kind, name):
    text = (ROOT / GATEWAYS[name] / "terraform" / "main.tf").read_text()
    m = re.search(r'resource\s+"%s"\s+"%s"\s*{(.*?)\n}\n' % (kind, name), text, re.S)
    assert m, f"{GATEWAYS[name]}: {kind}.{name} is not declared"
    return m.group(1)

def test_a_gateway_role_trusts_the_service_for_this_account_only():
    for name in GATEWAYS:
        trust = gateway_block("aws_iam_role", name)
        assert 'Principal = { Service = "bedrock-agentcore.amazonaws.com" }' in trust, name
        assert re.search(r'Condition\s*=\s*{\s*StringEquals\s*=\s*{\s*"aws:SourceAccount"\s*=\s*'
                         r'data\.aws_caller_identity\.me\.account_id\s*}\s*}', trust), name

def test_the_agent_gateway_invokes_one_lambda():
    # the custom guardrail's interceptor, <prefix>-guardrail (attached by API during operation), and no other function
    [line] = [l for l in gateway_block("aws_iam_role_policy", "agents").splitlines() if "lambda:InvokeFunction" in l]
    assert re.search(r'Resource\s*=\s*\["\$\{local\.lambda\}:\$\{var\.prefix\}-guardrail"\]', line)

def test_a_gateway_role_authorizes_on_the_hubs_gateways_only():
    for name in GATEWAYS:
        policy = gateway_block("aws_iam_role_policy", name)
        authorize = re.search(r'Action\s*=\s*\["bedrock-agentcore:AuthorizeAction".*?\n\s*Resource\s*=\s*\[(.*?)\]', policy, re.S)
        assert authorize and [r.strip() for r in authorize.group(1).split(",")] == [
            "var.policy_engine_arn", '"${local.agentcore}:gateway/${var.prefix}-*"'], name
    agents = gateway_block("aws_iam_role_policy", "agents")
    [guardrail] = [l for l in agents.splitlines() if "bedrock:InvokeGuardrailChecks" in l]
    assert re.search(r'Resource\s*=\s*"\*"', guardrail)               # the one action left on "*" (see the comment)

# ------------------------------------------------------------------ the custom guardrail

GUARD = ROOT / "custom_guardrail" / "terraform"

def test_the_company_guardrail_blocks_the_code_names_and_masks_the_employee_id_both_ways():
    g = block("aws_bedrock_guardrail", "company")
    assert re.search(r'name\s*=\s*"\$\{var\.prefix\}-company-guardrail"', g)
    words = re.search(r'dynamic\s+"words_config"\s*{\s*for_each\s*=\s*var\.code_names\s*content\s*{(.*?)\n      }', g, re.S)
    assert words and re.search(r"text\s*=\s*words_config\.value", words.group(1))
    regex = re.search(r"regexes_config\s*{(.*?)\n    }", g, re.S).group(1)
    assert re.search(r'name\s*=\s*"employee_id"', regex) and re.search(r"pattern\s*=\s*var\.employee_id_pattern", regex)
    for key in ("action", "input_action", "output_action"):
        assert re.search(r'\b%s\s*=\s*"ANONYMIZE"' % key, regex), key
    for key in ("input_enabled", "output_enabled"):
        assert re.search(r"\b%s\s*=\s*true" % key, regex), key
    variables = (GUARD / "variables.tf").read_text()
    assert re.search(r'variable\s+"code_names"\s*{[^}]*type\s*=\s*list\(string\)[^}]*default\s*=\s*\["Project Falcon"\]', variables)
    pattern = re.search(r'variable\s+"employee_id_pattern"\s*{(.*?)\n}', variables, re.S).group(1)
    assert re.search(r'default\s*=\s*"EMP-\\\\d\{6\}"', pattern)                              # EMP-\d{6} in HCL

def test_the_interceptor_lambda_runs_the_handler_with_the_guardrail_it_was_made_with():
    fn = block("aws_lambda_function", "guardrail")
    assert re.search(r'function_name\s*=\s*"\$\{var\.prefix\}-guardrail"', fn)      # the one the agent gateway may invoke
    handler = re.search(r'handler\s*=\s*"([\w.]+)"', fn).group(1)
    module, name = handler.rsplit(".", 1)
    import importlib
    assert callable(getattr(importlib.import_module(module), name))
    assert handler == "platform_team.custom_guardrail.interceptor_lambda.handler"
    assert re.search(r'runtime\s*=\s*"python3\.13"', fn) and re.search(r"timeout\s*=\s*8\b", fn)
    assert re.search(r"memory_size\s*=\s*256\b", fn) and re.search(r"filename\s*=\s*var\.code_zip", fn)
    assert re.search(r"GUARDRAIL_ID\s*=\s*aws_bedrock_guardrail\.company\.guardrail_id", fn)
    assert re.search(r"GUARDRAIL_VERSION\s*=\s*aws_bedrock_guardrail_version\.company\.version", fn)
    code = (ROOT / "custom_guardrail" / "interceptor_lambda.py").read_text()
    read = set(re.findall(r'environ(?:\.get\(|\[)"(\w+)"', code))
    assert read == {"GUARDRAIL_ID", "GUARDRAIL_VERSION"}                             # what the code reads, Terraform sets
    version = block("aws_bedrock_guardrail_version", "company")
    assert "guardrail_arn = aws_bedrock_guardrail.company.guardrail_arn" in version
    assert re.search(r"replace_triggered_by\s*=\s*\[aws_bedrock_guardrail\.company\]", version)   # new rules, new version

def test_the_interceptor_role_applies_this_guardrail_only_and_writes_its_own_logs():
    role = block("aws_iam_role", "guardrail")
    assert re.search(r'name\s*=\s*"\$\{var\.prefix\}-guardrail-role"', role)
    assert 'Principal = { Service = "lambda.amazonaws.com" }' in role
    policy = block("aws_iam_role_policy", "guardrail")
    statements = re.findall(r"{ Effect = \"Allow\", Action = \[(.*?)\], Resource = (.*?) },", policy)
    assert statements == [('"bedrock:ApplyGuardrail"', "[aws_bedrock_guardrail.company.guardrail_arn]"),
                          ('"logs:CreateLogStream", "logs:PutLogEvents"', '"${aws_cloudwatch_log_group.guardrail.arn}:*"')]
    logs = block("aws_cloudwatch_log_group", "guardrail")
    assert re.search(r'name\s*=\s*"/aws/lambda/\$\{var\.prefix\}-guardrail"', logs) and re.search(r"retention_in_days\s*=\s*14", logs)

def test_the_interceptor_errors_alarm_tells_the_alert_topic_within_a_minute():
    alarm = block("aws_cloudwatch_metric_alarm", "guardrail_errors")
    for pattern in (r'alarm_name\s*=\s*"\$\{var\.prefix\}-guardrail-errors"', r'namespace\s*=\s*"AWS/Lambda"',
                    r'metric_name\s*=\s*"Errors"', r"FunctionName\s*=\s*aws_lambda_function\.guardrail\.function_name",
                    r'statistic\s*=\s*"Sum"', r"period\s*=\s*60\b", r"evaluation_periods\s*=\s*1\b", r"threshold\s*=\s*1\b",
                    r'comparison_operator\s*=\s*"GreaterThanOrEqualToThreshold"', r"alarm_actions\s*=\s*\[var\.topic_arn\]"):
        assert re.search(pattern, alarm), pattern

def test_the_start_point_gives_the_custom_guardrail_the_code_and_the_alert_topic():
    root = (ROOT / "terraform" / "main.tf").read_text()
    module = re.search(r'module\s+"custom_guardrail"\s*{(.*?)\n}', root, re.S).group(1)
    assert re.search(r"code_zip\s*=\s*local\.code_zip", module) and re.search(r"topic_arn\s*=\s*module\.agent_monitoring\.topic_arn", module)
    outputs = (GUARD / "outputs.tf").read_text()
    assert set(re.findall(r'output\s+"(\w+)"', outputs)) == {"interceptor_arn", "guardrail_id", "guardrail_version"}
    assert re.search(r'"/\$\{var\.prefix\}/platform/interceptor_arn"\s+=\s+module\.custom_guardrail\.interceptor_arn\n',
                     (ROOT / "terraform" / "outputs.tf").read_text())
