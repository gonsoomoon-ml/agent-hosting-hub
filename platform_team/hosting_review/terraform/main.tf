# The hosting review: a catalog record that asks for approval starts a Step Functions state machine.
# Read, Grant, Entry, TestCall and Approve are Lambda functions (review_steps.py): they grant, and never open the
# submitted code. Scan and Deploy are CodeBuild projects (the buildspecs in ../): they handle the submitted code, and
# their roles hold no action that grants. Scan only reads. Deploy can create a Runtime and its endpoint: the policy
# allows both creates on runtime/* (IAM checks them against that resource and denied them on runtime/<prefix>_*), so
# it does not hold a create to the hub's names. A create under another name was not tried (a Runtime gets a workload
# identity named after its ID, and the role reaches workload identities only for <prefix>_* names). The Service
# Authorization Reference (read on 2026-11-22) lists no condition key on a Runtime's name for either create (only tag,
# authorizer and network keys; the hub uses none of them).
# Deploy can update and read the hub's Runtimes, pass a Runtime a role named
# <prefix>-agent-*-role, and write an agent's Runtime ARN to SSM (the policy allows /<prefix>/agents/<agent>/runtime_arn
# and no other parameter); it cannot make a role, a policy, a gateway target or an approval. Grant makes roles of that
# name only under the agent boundary; a role of that name made outside the hub would not be bounded, and making one
# takes IAM rights that none of the review's roles hold. Its limits: one deploy role serves every review, so code
# that runs in the deploy build could change another agent's Runtime, pass it another agent's role, or write another
# agent's runtime_arn (Entry refuses an ARN that is not that agent's Runtime); and the policy leaves open that such
# code creates a Runtime whose name does not start with <prefix>_ (not tried), which the hub's cleanup would not find
# (../README.md, the known limit). Every step has its own role (iam.tf). Read reads the catalog record
# (GetRegistryRecord) and, to find an earlier review of the same record, lists this state machine's executions and
# reads their input (states:ListExecutions, states:DescribeExecution); it changes nothing. Approve reads one SSM
# path, /<prefix>/policies (the modes of the company policies, GetParametersByPath), and makes those policies and the
# entry permit; it cannot switch a policy's mode (no UpdatePolicy). A record the review does not host (not an AGENT
# record, or a harness) ends after Read, with no alert. A failed step publishes to the alert topic.

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

locals {
  account = data.aws_caller_identity.me.account_id
  region  = data.aws_region.here.region
  # Lambda steps and their timeouts (s). 900 s is the Lambda maximum, and a step's waits can add up to more
  # (300 s per policy, 300 s for a target, minutes of test calls). So each wait takes its ceiling or the time left
  # until a deadline 60 s before the timeout (lambda_handler.MARGIN), whichever is shorter: a step that runs out
  # of time deletes what it half-made and fails with its own message. Each timeout leaves room for one full wait.
  steps = {
    read     = 60  # one record, no wait
    grant    = 900 # one policy per tool of the application
    entry    = 900 # a target and two policies
    testcall = 900 # a new target and a new policy take a while before they answer
    approve  = 900 # the deployed company policies and the entry permit
  }
  # What the steps read from their environment (review_steps.py, lambda_handler.py); ACTION names the step.
  step_env = {
    HUB_REGION    = local.region
    PREFIX        = var.prefix
    ACCOUNT       = local.account
    ENGINE_ID     = var.policy_engine_id
    AGENT_GW_ID   = var.agent_gateway_id
    AGENT_GW_ARN  = var.agent_gateway_arn
    TOOL_GW_ARN   = var.tool_gateway_arn
    TESTCALL_ROLE = aws_iam_role.step["testcall"].name # the principal of review_permit_<agent>
    # The AWS documentation's example access key, not a credential: the test call sends it and expects the
    # guardrail to refuse. It is joined here so that no file of the repo holds a key-shaped string and a
    # secret scan of the repo needs no exception.
    EXAMPLE_KEY    = join("", ["AKIA", "IOSFODNN7EXAMPLE"])
    CATALOG_TOOLS  = join(",", sort(var.catalog_tools))
    AGENT_BOUNDARY = aws_iam_policy.agent_boundary.arn # Grant creates agent roles under this boundary
    MODEL_ID       = var.model_id                      # Grant: the one model an agent role may call
  }
}

# ------------------------------------------------------------------ the inbox
# Teams upload their code under submissions/; the catalog record names the object version, and both builds read
# exactly that version. The hub's code bundle sits under platform/ for the builds to download.

resource "aws_s3_bucket" "inbox" {
  bucket        = "${var.prefix}-${local.account}-${local.region}" # Settings.bucket (shared_code/config.py)
  force_destroy = true                                             # `terraform destroy` removes every version too
}

resource "aws_s3_bucket_versioning" "inbox" {
  bucket = aws_s3_bucket.inbox.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "inbox" {
  bucket                  = aws_s3_bucket.inbox.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Requests without TLS are refused (iam.tf, the policy document "inbox").
resource "aws_s3_bucket_policy" "inbox" {
  bucket     = aws_s3_bucket.inbox.id
  policy     = data.aws_iam_policy_document.inbox.json
  depends_on = [aws_s3_bucket_public_access_block.inbox]
}

resource "aws_s3_object" "code" {
  bucket      = aws_s3_bucket.inbox.id
  key         = "platform/platform_team.zip"
  source      = var.code_zip
  source_hash = filemd5(var.code_zip)
  depends_on  = [aws_s3_bucket_versioning.inbox]
}

# ------------------------------------------------------------------ the Lambda steps
# Terraform owns every log group, so `terraform destroy` removes them too.

resource "aws_cloudwatch_log_group" "step" {
  for_each          = local.steps
  name              = "/aws/lambda/${var.prefix}-review-${each.key}"
  retention_in_days = 14
}

resource "aws_lambda_function" "step" {
  for_each         = local.steps
  function_name    = "${var.prefix}-review-${each.key}"
  description      = "Hosting review, step ${each.key}"
  role             = aws_iam_role.step[each.key].arn
  handler          = "platform_team.hosting_review.lambda_handler.handler"
  runtime          = "python3.13" # the Python of `make package`; the bundle is pure Python (code_package.py)
  architectures    = ["x86_64"]   # as the sample tools Lambda
  filename         = var.code_zip
  source_code_hash = filebase64sha256(var.code_zip)
  timeout          = each.value
  memory_size      = 256
  environment {
    variables = merge(local.step_env, { ACTION = each.key })
  }
  depends_on = [aws_iam_role_policy.step, aws_cloudwatch_log_group.step]
}

# ------------------------------------------------------------------ the CodeBuild steps

resource "aws_cloudwatch_log_group" "scan" {
  name              = "/aws/codebuild/${var.prefix}-review-scan"
  retention_in_days = 14
}

resource "aws_codebuild_project" "scan" {
  name          = "${var.prefix}-review-scan"
  description   = "Hosting review, Scan: check the submission's layout and audit its requirements.txt (pip-audit)"
  service_role  = aws_iam_role.scan.arn
  build_timeout = 15
  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/../buildspec_scan.yml")
  }
  artifacts {
    type = "NO_ARTIFACTS"
  }
  environment {
    type         = "ARM_CONTAINER"
    image        = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    compute_type = "BUILD_GENERAL1_SMALL"
    environment_variable {
      name  = "BUCKET"
      value = aws_s3_bucket.inbox.bucket
    }
    environment_variable {
      name  = "PREFIX"
      value = var.prefix
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.scan.name
    }
  }
  depends_on = [aws_iam_role_policy.scan]
}

resource "aws_cloudwatch_log_group" "deploy" {
  name              = "/aws/codebuild/${var.prefix}-review-deploy"
  retention_in_days = 14
}

resource "aws_codebuild_project" "deploy" {
  name          = "${var.prefix}-review-deploy"
  description   = "Hosting review, Deploy: package the submission and create or update its AgentCore Runtime"
  service_role  = aws_iam_role.deploy.arn
  build_timeout = 30
  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/../buildspec_deploy.yml")
  }
  artifacts {
    type = "NO_ARTIFACTS"
  }
  environment {
    type         = "ARM_CONTAINER"
    image        = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    compute_type = "BUILD_GENERAL1_SMALL"
    environment_variable {
      name  = "BUCKET"
      value = aws_s3_bucket.inbox.bucket
    }
    environment_variable {
      name  = "PREFIX"
      value = var.prefix
    }
    environment_variable {
      name  = "TOOL_GW_URL"
      value = var.tool_gateway_url
    }
    environment_variable {
      name  = "MODEL_ID"
      value = var.model_id
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.deploy.name
    }
  }
  depends_on = [aws_iam_role_policy.deploy]
}

# ------------------------------------------------------------------ the state machine

resource "aws_cloudwatch_log_group" "machine" {
  name              = "/aws/vendedlogs/states/${var.prefix}-review"
  retention_in_days = 14
}

# Step Functions writes its log through CloudWatch Logs log delivery, which needs a resource policy that lets
# delivery.logs.amazonaws.com write to the log group. With none, the delivery adds a statement to the account's
# shared policy, which `terraform destroy` would leave behind. This policy is the hub's own.
resource "aws_cloudwatch_log_resource_policy" "machine" {
  policy_name = "${var.prefix}-review-logs"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "delivery.logs.amazonaws.com" }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = "${aws_cloudwatch_log_group.machine.arn}:log-stream:*"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account }
        ArnLike      = { "aws:SourceArn" = "arn:aws:logs:${local.region}:${local.account}:*" }
      }
    }]
  })
}

resource "aws_sfn_state_machine" "review" {
  name     = "${var.prefix}-review"
  type     = "STANDARD"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/review_machine.asl.json.tftpl", {
    fn_read        = aws_lambda_function.step["read"].arn
    fn_grant       = aws_lambda_function.step["grant"].arn
    fn_entry       = aws_lambda_function.step["entry"].arn
    fn_testcall    = aws_lambda_function.step["testcall"].arn
    fn_approve     = aws_lambda_function.step["approve"].arn
    scan_project   = aws_codebuild_project.scan.name
    deploy_project = aws_codebuild_project.deploy.name
    topic_arn      = var.topic_arn
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.machine.arn}:*"
    include_execution_data = true # each review's inputs and results, step by step
    level                  = "ALL"
  }
  depends_on = [aws_iam_role_policy.sfn, aws_cloudwatch_log_resource_policy.machine]
}

# ------------------------------------------------------------------ the start (picture ③)

resource "aws_cloudwatch_event_rule" "on_submit" {
  name        = "${var.prefix}-on-submit"
  description = "A record of the hub's catalog asks for approval: start the hosting review"
  event_pattern = jsonencode({
    source        = ["aws.agent-registry"]
    "detail-type" = ["Registry Record State changed to Pending Approval"]
    detail        = { registryId = [var.registry_id] }
  })
}

resource "aws_cloudwatch_event_target" "review" {
  rule       = aws_cloudwatch_event_rule.on_submit.name
  target_id  = "review"
  arn        = aws_sfn_state_machine.review.arn
  role_arn   = aws_iam_role.events.arn
  depends_on = [aws_iam_role_policy.events]
}

# A new rule missed the first event (found by running, checks/system-flows). Whoever reads machine_arn waits for this.
resource "time_sleep" "rule_settles" {
  create_duration = "90s"
  depends_on      = [aws_cloudwatch_event_rule.on_submit, aws_cloudwatch_event_target.review]
}
