# tests/test_review_iam.py  (pins the separation of the roles in text)
import pathlib, re
TEXT = pathlib.Path("platform_team/hosting_review/terraform/iam.tf").read_text()

def document(step):
    m = re.search(r'data\s+"aws_iam_policy_document"\s+"%s"\s*{(.*?)\n}\n' % step, TEXT, re.S)
    assert m, f"no policy document for {step}"
    return m.group(1)

def actions(doc):
    """Every action named in the `actions = [...]` lists of a policy document."""
    return [a for block in re.findall(r"actions\s*=\s*\[(.*?)\]", doc, re.S) for a in re.findall(r'"([^"]+)"', block)]

def test_steps_that_handle_submitted_code_cannot_grant_or_approve():
    for step in ("scan", "deploy"):
        doc = document(step)
        for forbidden in ("agent-registry:Update", "bedrock-agentcore:CreatePolicy", "bedrock-agentcore:CreateGatewayTarget", "iam:CreateRole"):
            assert forbidden not in doc, (step, forbidden)
        # no wildcard action (a log group ARN ends in :*, so the resources are not part of this check)
        assert actions(doc) and [a for a in actions(doc) if "*" in a] == [], step

def test_policy_makers_have_the_actions_found_by_running():
    for step in ("grant", "entry", "approve"):
        for action in ("bedrock-agentcore:ManageResourceScopedPolicy", "bedrock-agentcore:GetGateway",
                       "bedrock-agentcore:ListGatewayTargets", "bedrock-agentcore:InvokeGateway", "bedrock-agentcore:CreatePolicy"):
            assert action in document(step), (step, action)
    deploy = document("deploy")      # the CLI path: CloudFormation creates the Runtime through the CDK roles
    assert "sts:AssumeRole" in deploy and "cdk-hnb659fds-" in deploy
    assert "bedrock-agentcore:Create" not in deploy and "iam:PassRole" not in deploy
    assert "agent-registry:UpdateRegistryRecordStatus" in document("approve")
    assert "var.tool_gateway_arn" in document("grant") and "var.agent_gateway_arn" not in document("grant")   # grant is scoped to the tool gateway
    assert "var.agent_gateway_arn" in document("entry")
