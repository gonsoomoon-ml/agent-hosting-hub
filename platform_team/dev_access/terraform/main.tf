# What the dev team may do before any review: call the shared read tool through the tool gateway, search the
# catalog, and create a record and ask for its approval. The hosting review adds the upload to its inbox.

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

resource "aws_iam_role" "dev" {
  name = "${var.prefix}-dev-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { AWS = var.dev_principals }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "dev" {
  name = "dev-team"
  role = aws_iam_role.dev.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # the gateway lets a call in; the Cedar policy below decides which tool answers
      { Effect = "Allow", Action = ["bedrock-agentcore:InvokeGateway"], Resource = [var.tool_gateway_arn] },
      # publish.sh reads where the hub's inbox and catalog are (hub_state.load); found by running
      { Effect = "Allow", Action = ["ssm:GetParametersByPath"], Resource = ["arn:aws:ssm:${data.aws_region.here.region}:${data.aws_caller_identity.me.account_id}:parameter/${var.prefix}/platform"] },
      {
        Effect = "Allow"
        Action = [
          "agent-registry:SearchDiscoverableRegistryRecords", "agent-registry:ListDiscoverableRegistryRecords",
          "agent-registry:GetRegistryRecord", "agent-registry:ListRegistryRecords",
          "agent-registry:CreateRegistryRecord", "agent-registry:UpdateRegistryRecord", "agent-registry:SubmitRegistryRecordForApproval",
        ]
        Resource = [var.registry_arn, "${var.registry_arn}/*"]
      },
    ]
  })
}

# The statement comes from the template in company_policy (one source for Python and Terraform).
locals {
  template = trimspace(file("${path.module}/../../company_policy/policy_templates/shared-tool-read.cedar"))
  statement = replace(replace(replace(replace(local.template,
    "<account>", data.aws_caller_identity.me.account_id),
    "<role_name>", aws_iam_role.dev.name),
    "<tool_id>", var.shared_tool),
  "<gateway_arn>", var.tool_gateway_arn)
}

resource "aws_bedrockagentcore_policy" "shared_tool_read" {
  name             = "shared_tool_read"
  description      = "The dev team may call the shared read tool before any review"
  policy_engine_id = var.policy_engine_id
  validation_mode  = "IGNORE_ALL_FINDINGS"
  definition {
    cedar {
      statement = local.statement
    }
  }
}
