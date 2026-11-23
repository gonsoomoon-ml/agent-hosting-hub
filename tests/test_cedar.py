import pytest

from platform_team.company_policy import cedar_statements as cedar
GW = "arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/hub-tools-abcdefghij"

def test_tool_permit():
    assert cedar.tool_permit("123456789012", "hub-agent-quality_agent-role", "Parts___get_part_spec", GW) == (
        'permit (principal == AgentCore::IamEntity::"arn:aws:sts::123456789012:assumed-role/hub-agent-quality_agent-role", '
        'action == AgentCore::Action::"Parts___get_part_spec", resource == AgentCore::Gateway::"' + GW + '");')

def test_entry_permit_for_everyone_and_for_one_role():
    assert cedar.entry_permit("QualityAgent", GW) == (
        'permit (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations", resource == AgentCore::Gateway::"' + GW + '");')
    assert 'principal == AgentCore::IamEntity::"arn:aws:sts::123456789012:assumed-role/hub-review-testcall-role"' in \
        cedar.review_permit("QualityAgent", GW, "123456789012", "hub-review-testcall-role")

def test_guard_secret_is_the_verified_statement():
    assert cedar.guard_secret("QualityAgent", GW).endswith(
        'when guardrails { BedrockGuardrails::SensitiveInformation(["AWS_ACCESS_KEY", "AWS_SECRET_KEY", "PASSWORD"], '
        '[context.input.prompt]).count() > 0 };')

GW_AGENTS = "arn:aws:bedrock-agentcore:us-west-2:123456789012:gateway/hub-agents-abcdefghij"

def test_the_prompt_guard_names_one_action_of_one_gateway():
    assert cedar.guard_prompt("QualityAgent", GW_AGENTS) == (
        'forbid (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations", '
        f'resource == AgentCore::Gateway::"{GW_AGENTS}") when guardrails {{ BedrockGuardrails::PromptAttack('
        '["PROMPT_INJECTION"], [context.input.prompt])["PROMPT_INJECTION"].confidenceScore.greaterThan(decimal("0.4")) };')

def test_the_stop_policy_lets_the_reviews_test_call_through():
    assert cedar.stop_agent("QualityAgent", GW_AGENTS, "123456789012", "hub-review-testcall-role") == (
        'forbid (principal, action == AgentCore::Action::"QualityAgent___POST:/invocations", '
        f'resource == AgentCore::Gateway::"{GW_AGENTS}") unless {{ principal == AgentCore::IamEntity::'
        '"arn:aws:sts::123456789012:assumed-role/hub-review-testcall-role" };')

def test_the_stop_policy_without_a_test_call_role_is_not_made():
    for account, role in (("123456789012", ""), ("", "hub-review-testcall-role")):
        with pytest.raises(ValueError, match="empty value"):
            cedar.stop_agent("QualityAgent", GW_AGENTS, account, role)       # an empty role would stop the test call too

# ------------------------------------------------------------------ no statement opens more than asked

def test_the_permit_for_everyone_cannot_be_asked_for_by_accident():
    with pytest.raises(TypeError):
        cedar.entry_permit("QualityAgent", GW, "123456789012")          # the old fail-open call: one of account, role
    for account, role in (("123456789012", ""), ("", "hub-review-testcall-role"), (None, "r"), ("123456789012", None)):
        with pytest.raises(ValueError, match="empty value"):
            cedar.review_permit("QualityAgent", GW, account, role)       # an empty TESTCALL_ROLE opens nothing

@pytest.mark.parametrize("value", ['Quality"Agent', "Quality\\Agent", "Quality\nAgent"])
def test_a_value_that_could_change_the_statement_is_refused(value):
    with pytest.raises(ValueError, match="may not hold"):
        cedar.entry_permit(value, GW)

def test_an_unfilled_placeholder_is_refused():
    with pytest.raises(ValueError, match="unfilled <gateway_arn>"):
        cedar._render("tool-permit.cedar", account="123456789012", role_name="r", tool_id="Parts___get_part_spec")

def test_only_the_used_helpers_are_left():
    assert [n for n in ("principal", "tool_action", "entry_action") if hasattr(cedar, n)] == []
