# Every step of the hosting review has its own role, and each policy document holds what its step calls:
# read from the step's code (review_steps.py and what it imports, the buildspecs, deploy_build.py) and, where marked,
# found by running. The steps that handle submitted code (scan, deploy) can read the submission and hold no action
# that grants. Scan only reads. Deploy can create a Runtime and its endpoint: the policy allows both creates on
# runtime/* (IAM checks them against that resource and denied them on runtime/<prefix>_*), so it does not hold a
# create to the hub's names. A create under another name was not tried (a Runtime gets a workload identity named after
# its ID, and the role reaches workload identities only for <prefix>_* names), and a condition key was not looked into.
# Deploy can update and read the hub's Runtimes, pass a Runtime a role named <prefix>-agent-*-role, and write an
# agent's Runtime ARN to SSM (the policy allows /<prefix>/agents/<agent>/runtime_arn and no other parameter); it
# cannot make a role, a policy, a gateway target or an approval. Grant makes roles of that name only under the agent
# boundary (its role's iam:PermissionsBoundary condition); a role of that name made outside the hub would not be
# bounded, and making one takes IAM rights that none of the review's roles hold. Its limits: one deploy role serves
# every review, so code that runs in the deploy build could change another agent's Runtime, pass it another agent's
# role, or write another agent's runtime_arn (Entry refuses an ARN that is not that agent's Runtime); and the policy
# leaves open that such code creates a Runtime whose name does not start with <prefix>_ (not tried), which the hub's
# cleanup would not find (hosting_review/README.md, the known limit).
# The steps that grant (Lambda) never open the submitted code. Read reads the catalog record (GetRegistryRecord)
# and, to find an earlier review of the same record, lists this state machine's executions and reads their input
# (states:ListExecutions, states:DescribeExecution); it changes nothing. Approve reads one SSM path,
# /<prefix>/policies (the modes of the company policies, GetParametersByPath), and makes those policies and the
# entry permit; it cannot switch a policy's mode (no UpdatePolicy).

locals {
  agentcore  = "arn:aws:bedrock-agentcore:${local.region}:${local.account}"
  agent_ssm  = "arn:aws:ssm:${local.region}:${local.account}:parameter/${var.prefix}/agents/*/runtime_arn" # one per agent
  submission = "${aws_s3_bucket.inbox.arn}/submissions/*"
  hub_code   = "${aws_s3_bucket.inbox.arn}/${aws_s3_object.code.key}"
  step_policy = {
    read     = data.aws_iam_policy_document.read.json
    grant    = data.aws_iam_policy_document.grant.json
    entry    = data.aws_iam_policy_document.entry.json
    testcall = data.aws_iam_policy_document.testcall.json
    approve  = data.aws_iam_policy_document.approve.json
  }
}

# ------------------------------------------------------------------ who may take each role

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "codebuild_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

data "aws_iam_policy_document" "states_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

data "aws_iam_policy_document" "events_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

# ------------------------------------------------------------------ 1 Read (Lambda)

data "aws_iam_policy_document" "read" {
  statement {
    sid       = "OwnLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.step["read"].arn}:*"]
  }
  statement {
    sid       = "ReadTheApplication" # get_registry_record
    actions   = ["agent-registry:GetRegistryRecord"]
    resources = ["${var.registry_arn}/record/*"]
  }
  statement {
    sid       = "ListTheReviews" # reject_agent.running_reviews: the RUNNING executions of this state machine. An ARN built from the name (main.tf names the machine ${var.prefix}-review): the machine refers to this step's function, so a reference back would be a cycle. Not tried on AWS
    actions   = ["states:ListExecutions"]
    resources = ["arn:aws:states:${local.region}:${local.account}:stateMachine:${var.prefix}-review"]
  }
  statement {
    sid       = "ReadTheReviews" # describe_execution: the record each running review was started for (its input). Built from the name like ListTheReviews. Not tried on AWS
    actions   = ["states:DescribeExecution"]
    resources = ["arn:aws:states:${local.region}:${local.account}:execution:${var.prefix}-review:*"]
  }
}

# ------------------------------------------------------------------ 2 Scan (CodeBuild, handles submitted code)

data "aws_iam_policy_document" "scan" {
  statement {
    sid       = "OwnBuildLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.scan.arn}:*"]
  }
  statement {
    sid       = "ReadTheSubmission" # aws s3api get-object --version-id
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = [local.submission]
  }
  statement {
    sid       = "ReadTheHubCode" # aws s3 cp: submission_check.py comes from the bundle
    actions   = ["s3:GetObject"]
    resources = [local.hub_code]
  }
}

# ------------------------------------------------------------------ 3 Grant (Lambda, tool gateway only)

data "aws_iam_policy_document" "grant" {
  statement {
    sid       = "OwnLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.step["grant"].arn}:*"]
  }
  statement {
    sid       = "FindTheAgentRole" # get_role <prefix>-agent-<agent>-role
    actions   = ["iam:GetRole"]
    resources = ["arn:aws:iam::${local.account}:role/${var.prefix}-agent-*-role"]
  }
  statement {
    sid       = "AgentRoleUnderTheBoundary" # create_role, put_role_policy: only on a role whose boundary is agent_boundary
    actions   = ["iam:CreateRole", "iam:PutRolePolicy"]
    resources = ["arn:aws:iam::${local.account}:role/${var.prefix}-agent-*-role"]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.agent_boundary.arn]
    }
  }
  statement {
    sid       = "ToolPermits" # ensure_policy tool_<agent>_<Target>_<tool>: list, create, wait until ACTIVE, delete one that failed; delete the agent's permits of tools the application no longer names; from the same list, whether entry_permit_<agent> is there before the review (entryPermitBefore)
    actions   = ["bedrock-agentcore:ListPolicies", "bedrock-agentcore:CreatePolicy", "bedrock-agentcore:GetPolicy", "bedrock-agentcore:DeletePolicy"]
    resources = [var.policy_engine_arn, "${var.policy_engine_arn}/policy/*"]
  }
  statement {
    sid = "TheGatewayThePermitsName" # found by running: a policy that names a gateway needs these on that gateway
    actions = ["bedrock-agentcore:ManageResourceScopedPolicy", "bedrock-agentcore:GetGateway", "bedrock-agentcore:ListGatewayTargets",
    "bedrock-agentcore:GetGatewayTarget", "bedrock-agentcore:InvokeGateway"]
    resources = [var.tool_gateway_arn]
  }
}

# The ceiling of every agent execution role Grant creates: the actions of review_steps._execution_role, on the
# resources this project uses. Grant can create a role and write its inline policy only with this boundary set,
# and cannot change or remove a boundary, so an agent role never holds more than this, whatever its inline policy says.
data "aws_iam_policy_document" "agent_boundary" {
  statement {
    sid       = "RuntimeLogGroups"
    actions   = ["logs:DescribeLogStreams", "logs:CreateLogGroup"]
    resources = ["arn:aws:logs:${local.region}:${local.account}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }
  statement {
    sid       = "FindLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:aws:logs:${local.region}:${local.account}:log-group:*"]
  }
  statement {
    sid       = "RuntimeLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${local.region}:${local.account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"]
  }
  statement {
    sid       = "ToolGateway"
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [var.tool_gateway_arn]
  }
  statement {
    sid       = "Model" # a cross-Region inference profile and the foundation models behind it
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:*::foundation-model/*", "arn:aws:bedrock:*:${local.account}:inference-profile/*"]
  }
  statement {
    sid = "WorkloadIdentity"
    actions = ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
    "bedrock-agentcore:GetWorkloadAccessTokenForUserId"]
    resources = ["${local.agentcore}:workload-identity-directory/default",
    "${local.agentcore}:workload-identity-directory/default/workload-identity/*"]
  }
}

resource "aws_iam_policy" "agent_boundary" {
  name        = "${var.prefix}-agent-boundary"
  description = "Permissions boundary of the agent execution roles the hosting review creates"
  policy      = data.aws_iam_policy_document.agent_boundary.json
}

# ------------------------------------------------------------------ 4 Deploy (CodeBuild, handles submitted code)
# The build packages the submission and calls CreateAgentRuntime or UpdateAgentRuntime itself (deploy_build.py). It
# creates a Runtime and its endpoint under CreateTheRuntime, on runtime/*, which does not hold a create to the hub's
# names; everything else it does on a Runtime reaches only the Runtimes whose names start with <prefix>_ and their
# workload identities. It passes only roles named <prefix>-agent-*-role, to AgentCore only, and writes only the SSM
# parameters /<prefix>/agents/<agent>/runtime_arn.

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "OwnBuildLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.deploy.arn}:*"]
  }
  statement {
    sid       = "ReadTheSubmission" # get_object(VersionId=...)
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = [local.submission]
  }
  statement {
    sid       = "ReadTheHubCode" # aws s3 cp: deploy_build.py comes from the bundle
    actions   = ["s3:GetObject"]
    resources = [local.hub_code]
  }
  statement {
    sid       = "ThePackage" # put_object packages/<agent>/<code version>.zip; GetObject in case the service reads the package with the caller's rights (the agent role has no S3 action). The deploy worked with it; whether the service needs GetObject was not tried
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.inbox.arn}/packages/*"]
  }
  statement {
    sid       = "CreateTheRuntime" # found by running: IAM checks create_agent_runtime, and the endpoint create it implies, against runtime/* (perhaps because the new Runtime has no ID yet; not checked), and denies both on runtime/<prefix>_*. So this statement does not hold a create to the hub's names. A create under another name was not tried (a Runtime gets a workload identity named after its ID, which TheAgentsRuntime reaches only for <prefix>_* names); a condition key was not looked into
    actions   = ["bedrock-agentcore:CreateAgentRuntime", "bedrock-agentcore:CreateAgentRuntimeEndpoint"]
    resources = ["${local.agentcore}:runtime/*"]
  }
  statement {
    sid = "TheAgentsRuntime" # update <prefix>_<agent> and wait until READY; the endpoint and workload identity actions for what the service makes with a Runtime (CreateAgentRuntime returns workloadIdentityDetails). Create and update worked with them; whether each is needed was not tried
    actions = ["bedrock-agentcore:UpdateAgentRuntime", "bedrock-agentcore:GetAgentRuntime",
      "bedrock-agentcore:GetAgentRuntimeEndpoint",
    "bedrock-agentcore:CreateWorkloadIdentity", "bedrock-agentcore:GetWorkloadIdentity"]
    resources = ["${local.agentcore}:runtime/${var.prefix}_*", "${local.agentcore}:workload-identity-directory/default",
    "${local.agentcore}:workload-identity-directory/default/workload-identity/${var.prefix}_*"]
  }
  statement {
    sid       = "FindTheRuntime" # list_agent_runtimes, every page, to find <prefix>_<agent> by name. It reads names, IDs and status only. The Service Authorization Reference gives the action no resource type, so only "*" matches it (on "*" it worked when run; a narrower resource was not tried)
    actions   = ["bedrock-agentcore:ListAgentRuntimes"]
    resources = ["*"]
  }
  statement {
    sid       = "PassAgentRole" # roleArn of the Runtime: any role named <prefix>-agent-*-role (Grant makes them under the boundary), to AgentCore only
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account}:role/${var.prefix}-agent-*-role"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["bedrock-agentcore.amazonaws.com"]
    }
  }
  statement {
    sid       = "WriteTheRuntimeArn" # put_parameter /<prefix>/agents/<agent>/runtime_arn, read by Entry
    actions   = ["ssm:PutParameter"]
    resources = [local.agent_ssm]
  }
}

# ------------------------------------------------------------------ 5 Entry (Lambda, agent gateway)

data "aws_iam_policy_document" "entry" {
  statement {
    sid       = "OwnLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.step["entry"].arn}:*"]
  }
  statement {
    sid       = "ReadTheRuntimeArn" # get_parameter /<prefix>/agents/<agent>/runtime_arn
    actions   = ["ssm:GetParameter"]
    resources = [local.agent_ssm]
  }
  statement {
    sid       = "EntryTarget" # ensure_runtime_target (it lists and reads targets with the actions below)
    actions   = ["bedrock-agentcore:CreateGatewayTarget"]
    resources = [var.agent_gateway_arn]
  }
  statement {
    sid       = "TheTargetsRuntime" # a Runtime target names the Runtime; only the hub's, <prefix>_<agent> (Deploy's names)
    actions   = ["bedrock-agentcore:GetAgentRuntime", "bedrock-agentcore:GetAgentRuntimeEndpoint"]
    resources = ["${local.agentcore}:runtime/${var.prefix}_*"]
  }
  statement {
    sid       = "EntryPolicies" # ensure_policy: review_permit_<agent>, guard_secret_<agent>
    actions   = ["bedrock-agentcore:ListPolicies", "bedrock-agentcore:CreatePolicy", "bedrock-agentcore:GetPolicy", "bedrock-agentcore:DeletePolicy"]
    resources = [var.policy_engine_arn, "${var.policy_engine_arn}/policy/*"]
  }
  statement {
    sid = "TheGatewayThePermitsName" # found by running: a policy that names a gateway needs these on that gateway
    actions = ["bedrock-agentcore:ManageResourceScopedPolicy", "bedrock-agentcore:GetGateway", "bedrock-agentcore:ListGatewayTargets",
    "bedrock-agentcore:GetGatewayTarget", "bedrock-agentcore:InvokeGateway"]
    resources = [var.agent_gateway_arn]
  }
}

# ------------------------------------------------------------------ 6 TestCall (Lambda)
# The role's name is the principal of review_permit_<agent>: only this role may enter before approval.

data "aws_iam_policy_document" "testcall" {
  statement {
    sid       = "OwnLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.step["testcall"].arn}:*"]
  }
  statement {
    sid       = "CallTheAgent" # signed_post to <agent gateway>/<target>/invocations
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [var.agent_gateway_arn]
  }
}

# ------------------------------------------------------------------ 7 Approve (Lambda)

data "aws_iam_policy_document" "approve" {
  statement {
    sid       = "OwnLog"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.step["approve"].arn}:*"]
  }
  statement {
    sid       = "CompanyPolicyModes" # get_parameters_by_path /<prefix>/policies (policy_rollout.deployed). The resource is the path as the call passes it, as the dev role's denial for /<prefix>/platform named it; not tried for this role
    actions   = ["ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:${local.region}:${local.account}:parameter/${var.prefix}/policies"]
  }
  statement {
    sid       = "CompanyPoliciesAndEntryPermit" # ensure_policy: the deployed company policies (guard_prompt_<agent>), entry_permit_<agent>; when the approval fails after the permit, list the policies and delete the permit this review made (entryPermitBefore false)
    actions   = ["bedrock-agentcore:ListPolicies", "bedrock-agentcore:CreatePolicy", "bedrock-agentcore:GetPolicy", "bedrock-agentcore:DeletePolicy"]
    resources = [var.policy_engine_arn, "${var.policy_engine_arn}/policy/*"]
  }
  statement {
    sid = "TheGatewayThePermitsName" # found by running: a policy that names a gateway needs these on that gateway
    actions = ["bedrock-agentcore:ManageResourceScopedPolicy", "bedrock-agentcore:GetGateway", "bedrock-agentcore:ListGatewayTargets",
    "bedrock-agentcore:GetGatewayTarget", "bedrock-agentcore:InvokeGateway"]
    resources = [var.agent_gateway_arn]
  }
  statement {
    sid       = "MarkTheRecordApproved" # get_registry_record (unchanged since Read?), update_registry_record_status
    actions   = ["agent-registry:GetRegistryRecord", "agent-registry:UpdateRegistryRecordStatus"]
    resources = ["${var.registry_arn}/record/*"]
  }
}

# ------------------------------------------------------------------ the conductor and the start

data "aws_iam_policy_document" "sfn" {
  statement {
    sid       = "LambdaSteps"
    actions   = ["lambda:InvokeFunction"]
    resources = [for f in aws_lambda_function.step : f.arn]
  }
  statement {
    sid       = "BuildSteps" # startBuild.sync starts the build, waits for it, and stops it on a timeout
    actions   = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"]
    resources = [aws_codebuild_project.scan.arn, aws_codebuild_project.deploy.arn]
  }
  statement {
    sid       = "BuildSyncRule" # the service-managed rule behind codebuild:startBuild.sync
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${local.region}:${local.account}:rule/StepFunctionsGetEventForCodeBuildStartBuildRule"]
  }
  statement {
    sid       = "Notify"
    actions   = ["sns:Publish"]
    resources = [var.topic_arn]
  }
  statement {
    sid = "ExecutionLog" # log delivery to the machine's log group; these actions have no resource type
    actions = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
    "logs:ListLogDeliveries", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "events" {
  statement {
    sid       = "StartTheReview"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.review.arn]
  }
}

# The inbox's bucket policy (main.tf): every request to the inbox must come over TLS.
data "aws_iam_policy_document" "inbox" {
  statement {
    sid       = "TlsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.inbox.arn, "${aws_s3_bucket.inbox.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "dev_upload" {
  statement {
    sid       = "Submit" # the dev team uploads its code; the catalog record names the object version
    actions   = ["s3:PutObject"]
    resources = [local.submission]
  }
}

# ------------------------------------------------------------------ roles

resource "aws_iam_role" "step" {
  for_each           = local.steps
  name               = "${var.prefix}-review-${each.key}-role"
  description        = "Hosting review, step ${each.key} (Lambda)"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "step" {
  for_each = local.steps
  name     = "review-${each.key}"
  role     = aws_iam_role.step[each.key].id
  policy   = local.step_policy[each.key]
}

resource "aws_iam_role" "scan" {
  name               = "${var.prefix}-review-scan-role"
  description        = "Hosting review, step scan (CodeBuild)"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

resource "aws_iam_role_policy" "scan" {
  name   = "review-scan"
  role   = aws_iam_role.scan.id
  policy = data.aws_iam_policy_document.scan.json
}

resource "aws_iam_role" "deploy" {
  name               = "${var.prefix}-review-deploy-role"
  description        = "Hosting review, step deploy (CodeBuild)"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

resource "aws_iam_role_policy" "deploy" {
  name   = "review-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

resource "aws_iam_role" "sfn" {
  name               = "${var.prefix}-sfn-role"
  description        = "Hosting review: the state machine"
  assume_role_policy = data.aws_iam_policy_document.states_trust.json
}

resource "aws_iam_role_policy" "sfn" {
  name   = "review-machine"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_iam_role" "events" {
  name               = "${var.prefix}-events-role"
  description        = "Hosting review: the rule that starts it"
  assume_role_policy = data.aws_iam_policy_document.events_trust.json
}

resource "aws_iam_role_policy" "events" {
  name   = "review-start"
  role   = aws_iam_role.events.id
  policy = data.aws_iam_policy_document.events.json
}

# The dev team role belongs to dev_access; the hosting review adds the upload to its inbox.
resource "aws_iam_role_policy" "dev_upload" {
  name   = "hosting-inbox"
  role   = var.dev_role_name
  policy = data.aws_iam_policy_document.dev_upload.json
}
