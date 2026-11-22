from platform_team.company_policy import cedar_statements as cedar
GW = "arn:aws:bedrock-agentcore:us-west-2:111122223333:gateway/hub-tools-abc"

def test_tool_permit():
    assert cedar.tool_permit("111122223333", "hub-agent-quality_agent-role", "Parts___get_part_spec", GW) == (
        'permit (principal == AgentCore::IamEntity::"arn:aws:sts::111122223333:assumed-role/hub-agent-quality_agent-role", '
        'action == AgentCore::Action::"Parts___get_part_spec", resource == AgentCore::Gateway::"' + GW + '");')

def test_entry_permit_for_everyone_and_for_one_role():
    assert cedar.entry_permit("QualityAgent", GW) == (
        'permit (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations", resource == AgentCore::Gateway::"' + GW + '");')
    assert 'principal == AgentCore::IamEntity::"arn:aws:sts::111122223333:assumed-role/hub-review-testcall-role"' in \
        cedar.entry_permit("QualityAgent", GW, "111122223333", "hub-review-testcall-role")

def test_guard_secret_is_the_verified_statement():
    assert cedar.guard_secret("QualityAgent", GW).endswith(
        'when guardrails { BedrockGuardrails::SensitiveInformation(["AWS_ACCESS_KEY", "AWS_SECRET_KEY", "PASSWORD"], '
        '[context.input.prompt]).count() > 0 };')
