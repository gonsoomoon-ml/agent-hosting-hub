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

def test_steps_that_handle_submitted_code_cannot_grant_or_approve_by_their_own_policy():
    """Their own policy documents only. The deploy role reaches more through the CDK bootstrap roles, which with the
    default bootstrap lead to an AdministratorAccess execution role (hosting_review/README.md, the known limit)."""
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

# ------------------------------------------------------------------ fix round 1: the agent role's boundary, approve re-reads

def statements(doc):
    return re.findall(r"\n  statement {(.*?)\n  }", doc, re.S)

def test_grant_can_make_agent_roles_only_under_the_boundary():
    grant = document("grant")
    writes = [s for s in statements(grant) if "iam:CreateRole" in s or "iam:PutRolePolicy" in s]
    assert len(writes) == 1 and "iam:CreateRole" in writes[0] and "iam:PutRolePolicy" in writes[0]
    assert re.search(r'test\s*=\s*"StringEquals"', writes[0]) and re.search(r'variable\s*=\s*"iam:PermissionsBoundary"', writes[0])
    assert "aws_iam_policy.agent_boundary.arn" in writes[0]
    for forbidden in ("iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary", "iam:AttachRolePolicy",
                      "iam:UpdateAssumeRolePolicy", "iam:DeleteRolePolicy"):
        assert forbidden not in grant, forbidden
    assert re.search(r'resource\s+"aws_iam_policy"\s+"agent_boundary"\s*{[^}]*name\s*=\s*"\$\{var\.prefix\}-agent-boundary"', TEXT)

def test_the_boundary_allows_every_action_of_the_agent_role_and_no_wildcard():
    from platform_team.hosting_review.review_steps import _execution_role
    from tests.fakes import ENV
    _, perms = _execution_role(ENV)
    granted = {a for s in perms["Statement"] for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    boundary = actions(document("agent_boundary"))
    assert granted and sorted(granted - set(boundary)) == [] and [a for a in boundary if "*" in a] == []

def test_approve_can_read_the_record_again():
    assert "agent-registry:GetRegistryRecord" in document("approve")
