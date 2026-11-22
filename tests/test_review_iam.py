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


# ------------------------------------------------------------------ the deploy step calls CreateAgentRuntime itself

def test_the_deploy_role_makes_runtimes_and_hands_them_agent_roles_and_grants_nothing():
    doc = document("deploy")
    for action in ("iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "sts:AssumeRole", "bedrock-agentcore:CreatePolicy",
                   "bedrock-agentcore:CreateGatewayTarget", "agent-registry:UpdateRegistryRecordStatus"):
        assert action not in doc
    assert '"iam:PassRole"' in doc and "iam:PassedToService" in doc and "${var.prefix}-agent-*-role" in doc
    assert sorted(actions(doc)) == sorted([
        "logs:CreateLogStream", "logs:PutLogEvents", "s3:GetObject", "s3:GetObjectVersion", "s3:GetObject",
        "s3:PutObject", "s3:GetObject",
        "bedrock-agentcore:CreateAgentRuntime", "bedrock-agentcore:UpdateAgentRuntime", "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint", "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:CreateWorkloadIdentity", "bedrock-agentcore:GetWorkloadIdentity",
        "bedrock-agentcore:ListAgentRuntimes", "iam:PassRole", "ssm:PutParameter"])
    assert "xray:" not in doc and "cdk-" not in doc


def _statement(doc, sid):
    [found] = [s for s in statements(doc) if re.search(r'sid\s*=\s*"%s"' % sid, s)]
    return found


def test_the_deploy_roles_resources_are_the_hubs_by_name_but_the_runtime_list_and_create():
    doc = document("deploy")
    runtime = _statement(doc, "TheAgentsRuntime")
    resources = re.search(r"resources\s*=\s*\[(.*?)\]", runtime, re.S).group(1)
    assert re.findall(r'"([^"]+)"', resources) == [      # the Runtimes and their workload identities, by the prefix
        "${local.agentcore}:runtime/${var.prefix}_*", "${local.agentcore}:workload-identity-directory/default",
        "${local.agentcore}:workload-identity-directory/default/workload-identity/${var.prefix}_*"]
    assert "ListAgentRuntimes" not in runtime and "CreateAgentRuntime\"" not in runtime
    # found by running: IAM checks CreateAgentRuntime against runtime/* (the new Runtime has no ID yet), so a
    # resource of runtime/<prefix>_* is denied; the create is alone in its statement, on runtime/* only
    create = _statement(doc, "CreateTheRuntime")
    assert actions(create) == ["bedrock-agentcore:CreateAgentRuntime"]
    assert re.search(r'resources\s*=\s*\["\$\{local\.agentcore\}:runtime/\*"\]', create)
    find = _statement(doc, "FindTheRuntime")                  # the only statement on "*": a list that reads names
    assert actions(find) == ["bedrock-agentcore:ListAgentRuntimes"] and re.search(r'resources\s*=\s*\["\*"\]', find)
    assert [s for s in statements(doc) if '["*"]' in s] == [find]
    pkg = _statement(doc, "ThePackage")
    assert sorted(actions(pkg)) == ["s3:GetObject", "s3:PutObject"] and "/packages/*" in pkg
    passing = _statement(doc, "PassAgentRole")
    assert actions(passing) == ["iam:PassRole"]
    assert re.search(r'test\s*=\s*"StringEquals"', passing) and re.search(r'variable\s*=\s*"iam:PassedToService"', passing)
    assert '"bedrock-agentcore.amazonaws.com"' in passing
    assert 'resources = ["arn:aws:iam::${local.account}:role/${var.prefix}-agent-*-role"]' in passing
