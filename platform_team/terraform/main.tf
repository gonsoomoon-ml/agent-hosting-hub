# The hub's start point: one module per feature folder (platform_team/<feature>/terraform).
# Run from the repo root with `make deploy`: it builds build/ first (python -m platform_team.shared_code.code_package),
# then runs terraform init and apply here.

data "aws_caller_identity" "me" {}

locals {
  build          = "${path.root}/${var.build_dir}"
  code_zip       = "${local.build}/platform_team.zip"
  tool_schemas   = jsondecode(file("${local.build}/tool_schemas.json")) # TARGETS in sample_tools/tool_schema.py
  shared_read    = jsondecode(file("${local.build}/shared_read.json"))  # SHARED_READ in sample_tools/tool_schema.py
  dev_principals = length(var.dev_principals) > 0 ? var.dev_principals : ["arn:aws:iam::${data.aws_caller_identity.me.account_id}:root"]
}

module "company_policy" {
  source = "../company_policy/terraform"
  prefix = var.prefix
}

module "sample_tools" {
  source   = "../sample_tools/terraform"
  prefix   = var.prefix
  code_zip = local.code_zip
}

module "agent_gateway" {
  source            = "../agent_gateway/terraform"
  prefix            = var.prefix
  policy_engine_arn = module.company_policy.policy_engine_arn
}

module "tool_gateway" {
  source            = "../tool_gateway/terraform"
  prefix            = var.prefix
  policy_engine_arn = module.company_policy.policy_engine_arn
  tool_lambda_arn   = module.sample_tools.lambda_arn
  tool_schemas      = local.tool_schemas
}

module "agent_catalog" {
  source = "../agent_catalog/terraform"
  prefix = var.prefix
}

module "agent_monitoring" {
  source      = "../agent_monitoring/terraform"
  prefix      = var.prefix
  alert_email = var.alert_email
}

module "dev_access" {
  source           = "../dev_access/terraform"
  prefix           = var.prefix
  dev_principals   = local.dev_principals
  policy_engine_id = module.company_policy.policy_engine_id
  tool_gateway_arn = module.tool_gateway.gateway_arn
  registry_arn     = module.agent_catalog.registry_arn
  shared_tool      = one(local.shared_read) # the Cedar template names one tool
}
