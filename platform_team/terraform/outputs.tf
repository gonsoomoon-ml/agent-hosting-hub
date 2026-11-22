# What Terraform made, published for the Python side (platform_team.shared_code.hub_state.load):
# one SSM parameter per value under /<prefix>/platform/.

locals {
  platform = {
    "/${var.prefix}/platform/agent_gateway_id"  = module.agent_gateway.gateway_id
    "/${var.prefix}/platform/agent_gateway_arn" = module.agent_gateway.gateway_arn
    "/${var.prefix}/platform/agent_gateway_url" = module.agent_gateway.gateway_url
    "/${var.prefix}/platform/tool_gateway_id"   = module.tool_gateway.gateway_id
    "/${var.prefix}/platform/tool_gateway_arn"  = module.tool_gateway.gateway_arn
    "/${var.prefix}/platform/tool_gateway_url"  = module.tool_gateway.gateway_url
    "/${var.prefix}/platform/engine_id"         = module.company_policy.policy_engine_id
    "/${var.prefix}/platform/engine_arn"        = module.company_policy.policy_engine_arn
    "/${var.prefix}/platform/registry_id"       = module.agent_catalog.registry_id
    "/${var.prefix}/platform/topic_arn"         = module.agent_monitoring.topic_arn
    "/${var.prefix}/platform/tool_lambda_arn"   = module.sample_tools.lambda_arn
    "/${var.prefix}/platform/dev_role_arn"      = module.dev_access.dev_role_arn
    "/${var.prefix}/platform/bucket"            = module.hosting_review.bucket
    "/${var.prefix}/platform/machine_arn"       = module.hosting_review.machine_arn
  }
}

resource "aws_ssm_parameter" "platform" {
  for_each = local.platform
  name     = each.key
  type     = "String"
  value    = each.value
}

# Names only: values hold the account ID and stay in SSM.
output "platform_parameters" {
  value = sort(keys(local.platform))
}
