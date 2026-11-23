# The tool gateway: an MCP gateway in front of the in-house tools. Only tool calls a Cedar permit allows pass.
# One target per entry of var.tool_schemas (TARGETS in sample_tools/tool_schema.py); every target is the same Lambda.

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

locals {
  agentcore = "arn:aws:bedrock-agentcore:${data.aws_region.here.region}:${data.aws_caller_identity.me.account_id}"
}

resource "aws_iam_role" "tools" {
  name = "${var.prefix}-tools-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.me.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "tools" {
  name = "tool-gateway"
  role = aws_iam_role.tools.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [var.tool_lambda_arn] },
      {
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions", "bedrock-agentcore:GetPolicyEngine"]
        Resource = [var.policy_engine_arn, "${local.agentcore}:gateway/${var.prefix}-*"]
      },
    ]
  })
}

# IAM is eventually consistent, and CreateGateway checks at once that the role may use the policy engine
# (found by running: AccessDenied on bedrock-agentcore:AuthorizeAction right after the role policy was written).
resource "time_sleep" "role_settles" {
  create_duration = "20s"
  depends_on      = [aws_iam_role_policy.tools]
}

resource "aws_bedrockagentcore_gateway" "tools" {
  name            = "${var.prefix}-tools"
  description     = "Tool gateway: only permitted tool calls pass"
  role_arn        = aws_iam_role.tools.arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"
  policy_engine_configuration {
    arn  = var.policy_engine_arn
    mode = "ENFORCE"
  }
  depends_on = [time_sleep.role_settles]
}

# Agents see each tool as <Target>___<tool>.
resource "aws_bedrockagentcore_gateway_target" "tool" {
  for_each           = var.tool_schemas
  name               = each.key
  gateway_identifier = aws_bedrockagentcore_gateway.tools.gateway_id
  description        = "In-house tools: ${each.key}"
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = var.tool_lambda_arn
        tool_schema {
          dynamic "inline_payload" {
            for_each = each.value
            content {
              name        = inline_payload.value.name
              description = inline_payload.value.description
              input_schema {
                type = inline_payload.value.inputSchema.type
                dynamic "property" {
                  for_each = inline_payload.value.inputSchema.properties
                  content {
                    name        = property.key
                    type        = property.value.type
                    description = property.value.description
                    required    = contains(inline_payload.value.inputSchema.required, property.key)
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
