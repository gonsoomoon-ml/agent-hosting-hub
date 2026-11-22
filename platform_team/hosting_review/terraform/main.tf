# The hosting review: a catalog record that asks for approval starts a Step Functions state machine.
# Read, Grant, Entry, TestCall and Approve are Lambda functions (review_steps.py): they grant, and never open the
# submitted code. Scan and Deploy are CodeBuild projects (the buildspecs in ../): they handle the submitted code and
# can grant nothing. Every step has its own role (iam.tf). A failed step publishes to the alert topic.

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

locals {
  account = data.aws_caller_identity.me.account_id
  region  = data.aws_region.here.region
  # Lambda steps and their timeouts (s). Each covers the step's own waits: ensure_policy waits up to 300 s per
  # policy, ensure_runtime_target up to 300 s, testcall retries for minutes. 900 s is the Lambda maximum.
  steps = {
    read     = 60  # one record
    grant    = 900 # one policy per tool of the application
    entry    = 900 # a target and two policies
    testcall = 900 # a new target and a new policy take a while before they answer
    approve  = 420 # one policy
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
    TESTCALL_ROLE = aws_iam_role.step["testcall"].name # the principal of entry_permit_review
    EXAMPLE_KEY   = "AKIAIOSFODNN7EXAMPLE"             # the example access key of the AWS documentation
    CATALOG_TOOLS = join(",", sort(var.catalog_tools))
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
  description   = "Hosting review, Deploy: put the submission on AgentCore Runtime with the AgentCore CLI"
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
