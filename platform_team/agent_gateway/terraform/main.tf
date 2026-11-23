# The agent gateway: every request to a hosted agent passes the company policy here.
# Hosted agents are Runtime targets. The hosting review adds them by API (gateway_targets.py), not Terraform.

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

locals {
  agentcore = "arn:aws:bedrock-agentcore:${data.aws_region.here.region}:${data.aws_caller_identity.me.account_id}"
  lambda    = "arn:aws:lambda:${data.aws_region.here.region}:${data.aws_caller_identity.me.account_id}:function"
}

resource "aws_iam_role" "agents" {
  name = "${var.prefix}-agents-role"
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

resource "aws_iam_role_policy" "agents" {
  name = "agent-gateway"
  role = aws_iam_role.agents.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # the hosted agents: the review names their Runtimes <prefix>_<agent>, so this reaches no Runtime of a hub whose
      # prefix starts with this one (hub2_...); a harness has no target here. Not run on AWS yet
      { Effect = "Allow", Action = ["bedrock-agentcore:InvokeAgentRuntime"], Resource = ["${local.agentcore}:runtime/${var.prefix}_*"] },
      # the interceptor Lambda of the custom guardrail, attached after the gateway exists (by API, during operation)
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = ["${local.lambda}:${var.prefix}-guardrail"] },
      {
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions", "bedrock-agentcore:GetPolicyEngine"]
        Resource = [var.policy_engine_arn, "${local.agentcore}:gateway/${var.prefix}-*"]
      },
      # company policies that use guardrails (BedrockGuardrails::...). Not narrowed: the AWS documents give this
      # action's resource differently (AgentCore's "Guardrails in policies" a guardrail ARN; Bedrock's "Set up
      # permissions" for InvokeGuardrailChecks says it has none and uses "*", and the Service Authorization Reference
      # lists no resource type for it).
      { Effect = "Allow", Action = ["bedrock:InvokeGuardrailChecks"], Resource = "*" },
    ]
  })
}

# IAM is eventually consistent, and CreateGateway checks at once that the role may use the policy engine
# (found by running: AccessDenied on bedrock-agentcore:AuthorizeAction right after the role policy was written).
resource "time_sleep" "role_settles" {
  create_duration = "20s"
  depends_on      = [aws_iam_role_policy.agents]
}

# No protocol type: a gateway without one takes Runtime targets (HTTP); an MCP gateway does not.
resource "aws_bedrockagentcore_gateway" "agents" {
  name            = "${var.prefix}-agents"
  description     = "Agent gateway: company policy on every request to a hosted agent"
  role_arn        = aws_iam_role.agents.arn
  authorizer_type = "AWS_IAM"
  policy_engine_configuration {
    arn  = var.policy_engine_arn
    mode = "ENFORCE"
  }
  lifecycle {
    # The custom guardrail's interceptor is attached by an API call (UpdateGateway) during operation.
    ignore_changes = [interceptor_configuration]
  }
  depends_on = [time_sleep.role_settles]
}
