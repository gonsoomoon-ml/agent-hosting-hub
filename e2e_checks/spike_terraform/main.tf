# spike_terraform - can Terraform (hashicorp/aws) bring up the core of the hub's frame?
#
# The smallest set: one gateway role, one policy engine, a gateway without a protocol type (for Runtime targets) and an
# MCP gateway, both attached to the same engine in ENFORCE mode; one Lambda tool target; one Cedar policy; one Registry.
# The argument values mirror what checks/whole-process created with boto3. Every name starts with "hubtf".
#
#   terraform -chdir=e2e_checks/spike_terraform init
#   terraform -chdir=e2e_checks/spike_terraform apply -auto-approve
#   terraform -chdir=e2e_checks/spike_terraform plan -detailed-exitcode     # 0 = no changes
#   terraform -chdir=e2e_checks/spike_terraform destroy -auto-approve
#
# Check with boto3 (the agent gateway has no protocolType; both gateways have the same engine):
#   AWS_REGION=us-west-2 uv run --with 'boto3>=1.44.9' python -c "import boto3; c = boto3.client('bedrock-agentcore-control');
#   [print(n, c.get_gateway(gatewayIdentifier=i).get('protocolType'), c.get_gateway(gatewayIdentifier=i).get('policyEngineConfiguration'))
#    for n, i in (('agents', '<agent_gateway_id>'), ('tools', '<tool_gateway_id>'))]"

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.73" }
    archive = { source = "hashicorp/archive", version = "~> 2.8" }
  }
}

provider "aws" {
  region = "us-west-2"
}

locals {
  prefix = "hubtf"
  target = "Parts"
  tools = {
    get_part_spec      = "Read the specification of a part."
    get_test_result    = "Read the test result of a part and the id of the inspector."
    update_part_status = "Change the status of a part."
  }
}

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

locals {
  base = "arn:aws:bedrock-agentcore:${data.aws_region.here.region}:${data.aws_caller_identity.me.account_id}"
}

# ------------------------------------------------------------------ the tool: one Lambda with three tools

data "archive_file" "tool" {
  type        = "zip"
  output_path = "${path.module}/build/tool.zip"
  source {
    filename = "tool.py"
    content  = <<-EOT
      def handler(event, context):
          name = context.client_context.custom["bedrockAgentCoreToolName"]
          return {"tool": name.split("___", 1)[-1], "part_id": event.get("part_id", "?"), "data": "synthetic"}
    EOT
  }
}

resource "aws_iam_role" "tool" {
  name = "${local.prefix}-tool-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "tool" {
  name = "logs"
  role = aws_iam_role.tool.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" }]
  })
}

resource "aws_lambda_function" "tool" {
  function_name    = "${local.prefix}-tool"
  role             = aws_iam_role.tool.arn
  runtime          = "python3.13"
  handler          = "tool.handler"
  filename         = data.archive_file.tool.output_path
  source_code_hash = data.archive_file.tool.output_base64sha256
  timeout          = 10
}

# ------------------------------------------------------------------ the doors: one policy engine, two gateways

resource "aws_iam_role" "gateway" {
  name = "${local.prefix}-gateway-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "bedrock-agentcore.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "gateway" {
  name = "gateway"
  role = aws_iam_role.gateway.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["bedrock-agentcore:InvokeAgentRuntime"], Resource = ["${local.base}:runtime/*"] },
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [aws_lambda_function.tool.arn] },
      {
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions", "bedrock-agentcore:GetPolicyEngine"]
        Resource = ["${local.base}:policy-engine/*", "${local.base}:gateway/*"]
      },
    ]
  })
}

resource "aws_bedrockagentcore_policy_engine" "hub" {
  name        = "${local.prefix}_pe"
  description = "spike: the hub's one policy engine"
}

# The agent gateway: no protocol_type, so it can take Runtime targets (HTTP).
resource "aws_bedrockagentcore_gateway" "agents" {
  name            = "${local.prefix}-agents"
  description     = "spike: agent gateway"
  role_arn        = aws_iam_role.gateway.arn
  authorizer_type = "AWS_IAM"
  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.hub.policy_engine_arn
    mode = "ENFORCE"
  }
  depends_on = [aws_iam_role_policy.gateway]
}

resource "aws_bedrockagentcore_gateway" "tools" {
  name            = "${local.prefix}-tools"
  description     = "spike: tool gateway"
  role_arn        = aws_iam_role.gateway.arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"
  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.hub.policy_engine_arn
    mode = "ENFORCE"
  }
  depends_on = [aws_iam_role_policy.gateway]
}

resource "aws_bedrockagentcore_gateway_target" "tool" {
  name               = local.target
  gateway_identifier = aws_bedrockagentcore_gateway.tools.gateway_id
  description        = "in-house tools"
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.tool.arn
        tool_schema {
          dynamic "inline_payload" {
            for_each = local.tools
            content {
              name        = inline_payload.key
              description = inline_payload.value
              input_schema {
                type = "object"
                property {
                  name        = "part_id"
                  type        = "string"
                  description = "part id"
                  required    = true
                }
              }
            }
          }
        }
      }
    }
  }
}

# One Cedar policy that names the tool gateway: a (not created) dev role may call one tool.
resource "aws_bedrockagentcore_policy" "shared_tool_read" {
  name             = "${local.prefix}_shared_tool_read"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hub.policy_engine_id
  validation_mode  = "IGNORE_ALL_FINDINGS"
  definition {
    cedar {
      statement = join("", [
        "permit (principal == AgentCore::IamEntity::\"arn:aws:sts::${data.aws_caller_identity.me.account_id}:assumed-role/${local.prefix}-dev-role\", ",
        "action == AgentCore::Action::\"${local.target}___get_part_spec\", ",
        "resource == AgentCore::Gateway::\"${aws_bedrockagentcore_gateway.tools.gateway_arn}\");",
      ])
    }
  }
  depends_on = [aws_bedrockagentcore_gateway_target.tool]
}

# ------------------------------------------------------------------ the catalog (manual approval)

resource "aws_agentregistry_registry" "catalog" {
  name        = "${local.prefix}-registry"
  description = "spike: catalog (manual approval)"
  discovery_configuration {
    authorizer_type = "AWS_IAM"
  }
}

output "agent_gateway_id" { value = aws_bedrockagentcore_gateway.agents.gateway_id }
output "tool_gateway_id" { value = aws_bedrockagentcore_gateway.tools.gateway_id }
output "policy_engine_id" { value = aws_bedrockagentcore_policy_engine.hub.policy_engine_id }
output "registry_id" { value = aws_agentregistry_registry.catalog.registry_id }
