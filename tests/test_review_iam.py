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
    _, perms = _execution_role(ENV, "quality_agent")
    granted ={a for s in perms["Statement"] for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
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
    assert "CreateAgentRuntimeEndpoint" not in runtime
    # found by running: IAM checks CreateAgentRuntime, and the CreateAgentRuntimeEndpoint it implies, against
    # runtime/* (perhaps because the new Runtime has no ID yet; not checked), so a resource of runtime/<prefix>_* is denied; the two creates are
    # alone in their statement, on runtime/* only
    create = _statement(doc, "CreateTheRuntime")
    assert actions(create) == ["bedrock-agentcore:CreateAgentRuntime", "bedrock-agentcore:CreateAgentRuntimeEndpoint"]
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


# ------------------------------------------------------------------ narrower roles

def _resources(statement):
    return re.findall(r'"([^"]+)"', re.search(r"resources\s*=\s*\[(.*?)\]", statement, re.S).group(1))


def test_the_deploy_role_writes_one_parameter_per_agent():
    # /<prefix>/agents/<agent>/runtime_arn, the value Entry reads; not every value under /<prefix>/agents/
    assert re.search(r'\n  agent_ssm\s*=\s*"arn:aws:ssm:\$\{local\.region\}:\$\{local\.account\}:'
                     r'parameter/\$\{var\.prefix\}/agents/\*/runtime_arn"', TEXT)
    deploy = document("deploy")
    write = _statement(deploy, "WriteTheRuntimeArn")
    assert actions(write) == ["ssm:PutParameter"] and re.search(r"resources\s*=\s*\[local\.agent_ssm\]", write)
    assert [s for s in statements(deploy) if "ssm:" in s] == [write]


def test_entry_reaches_only_runtimes_the_hub_deploys():
    runtime = _statement(document("entry"), "TheTargetsRuntime")
    assert actions(runtime) == ["bedrock-agentcore:GetAgentRuntime", "bedrock-agentcore:GetAgentRuntimeEndpoint"]
    assert _resources(runtime) == ["${local.agentcore}:runtime/${var.prefix}_*"]     # <prefix>_<agent>, Deploy's names


def test_an_agent_role_gets_tokens_for_its_own_workload_only():
    # A Runtime's workload identity is named after its ID, <Runtime name>-<10 characters> (the AWS example of a Runtime
    # execution role has .../workload-identity/<agent name>-*). An agent name has no "-", so no other agent's matches.
    from fnmatch import fnmatchcase
    from platform_team.hosting_review.review_steps import _execution_role
    from tests.fakes import ENV
    _, perms = _execution_role(ENV, "quality_agent")
    [tokens] = [s for s in perms["Statement"] if "bedrock-agentcore:GetWorkloadAccessToken" in s["Action"]]
    wid = "arn:aws:bedrock-agentcore:us-west-2:123456789012:workload-identity-directory/default"
    assert tokens["Resource"] == [wid, f"{wid}/workload-identity/hub_quality_agent-*"]
    identity = f"{wid}/workload-identity/%s-Ab12Cd34Ef"
    assert fnmatchcase(identity % "hub_quality_agent", tokens["Resource"][1])
    assert not [n for n in ("hub_quality_agent_v2", "hub_release_review", "other_quality_agent")
                if fnmatchcase(identity % n, tokens["Resource"][1])]


def test_the_inbox_refuses_requests_without_tls():
    inbox = document("inbox")
    [deny] = statements(inbox)
    assert re.search(r'effect\s*=\s*"Deny"', deny) and actions(deny) == ["s3:*"]
    assert re.search(r'principals\s*{\s*type\s*=\s*"\*"\s*identifiers\s*=\s*\["\*"\]\s*}', deny)
    assert re.search(r'condition\s*{\s*test\s*=\s*"Bool"\s*variable\s*=\s*"aws:SecureTransport"\s*values\s*=\s*\["false"\]',
                     deny)
    assert re.search(r'resources\s*=\s*\[aws_s3_bucket\.inbox\.arn,\s*"\$\{aws_s3_bucket\.inbox\.arn\}/\*"\]', deny)
    main = pathlib.Path("platform_team/hosting_review/terraform/main.tf").read_text()
    policy = re.search(r'resource\s+"aws_s3_bucket_policy"\s+"inbox"\s*{(.*?)\n}\n', main, re.S)
    assert policy and re.search(r"bucket\s*=\s*aws_s3_bucket\.inbox\.id", policy.group(1))
    assert re.search(r"policy\s*=\s*data\.aws_iam_policy_document\.inbox\.json", policy.group(1))


# ------------------------------------------------------------------ Approve reads the company policies' modes

def test_approve_reads_the_company_policy_modes_and_no_other_parameter():
    # GetParametersByPath is authorised on the path itself, as the call passes it: parameter/<prefix>/policies
    # (a denial on AWS named "...:parameter/hub/platform" for Path=/hub/platform, the dev role's read)
    from platform_team.shared_code.config import Settings
    approve = document("approve")
    read = _statement(approve, "CompanyPolicyModes")
    assert actions(read) == ["ssm:GetParametersByPath"]
    assert _resources(read) == ["arn:aws:ssm:${local.region}:${local.account}:parameter/${var.prefix}/policies"]
    assert [s for s in statements(approve) if "ssm:" in s] == [read]
    assert _resources(read)[0].replace("${var.prefix}", "hub").endswith(":parameter" + Settings().ssm("policies"))
