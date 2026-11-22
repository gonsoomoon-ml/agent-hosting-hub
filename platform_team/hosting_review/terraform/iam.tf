# Every step of the hosting review has its own role, and each policy document holds what its step calls:
# read from the step's code (review_steps.py and what it imports, the buildspecs, deploy_build.py) and, where marked,
# found by running (checks/whole-process). The steps that handle submitted code (scan, deploy) can read the
# submission, and their own policies hold no action that grants. The deploy role, though, assumes the CDK bootstrap
# roles, and with the default bootstrap these reach the CloudFormation execution role, which is AdministratorAccess:
# in the default setup the separation is whole for scan only (hosting_review/README.md, the deploy step's known
# limit). The steps that grant (Lambda) never open the submitted code.

locals {
  agentcore  = "arn:aws:bedrock-agentcore:${local.region}:${local.account}"
  agent_ssm  = "arn:aws:ssm:${local.region}:${local.account}:parameter/${var.prefix}/agents/*" # /<prefix>/agents/<agent>/runtime_arn
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
    sid       = "ToolPermits" # ensure_policy tool_<agent>_<Target>_<tool>: list, create, wait until ACTIVE, delete one that failed
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
# The CLI path (agentcore deploy): CloudFormation creates the Runtime through the CDK bootstrap roles, so this role
# needs no bedrock-agentcore action and no iam:PassRole. Known limit: the CDK roles lead to the CDK execution role,
# which the default bootstrap makes AdministratorAccess, so code run in the deploy build is an administrator of the
# account (README.md).

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
    sid       = "CdkBootstrapRoles" # found by running (Task 0): asset publishing, deploy and lookup roles of this account and Region
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::${local.account}:role/cdk-hnb659fds-*-${local.account}-${local.region}"]
  }
  statement {
    sid       = "TransactionSearchCheck" # found by running (Task 0): the CLI only reads it; the action has no resource type
    actions   = ["xray:GetTraceSegmentDestination"]
    resources = ["*"]
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
    sid       = "TheTargetsRuntime" # as in the run that passed (checks/whole-process): a Runtime target names the Runtime
    actions   = ["bedrock-agentcore:GetAgentRuntime", "bedrock-agentcore:GetAgentRuntimeEndpoint"]
    resources = ["${local.agentcore}:runtime/${var.prefix}*"]
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
    sid       = "EntryPermit" # ensure_policy: entry_permit_<agent>
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
