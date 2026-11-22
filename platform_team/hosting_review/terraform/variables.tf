variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "code_zip" {
  description = "Path of the hub's code package (build/platform_team.zip): the Lambda steps run it, the builds download it"
  type        = string
}

variable "model_id" {
  description = "Model the deployed agents call (the deploy build writes it into the Runtime's environment); the start point passes var.model_id"
  type        = string
}

variable "catalog_tools" {
  description = "Tool IDs an application may name, as <Target>___<tool> (every tool in build/tool_schemas.json)"
  type        = list(string)
}

variable "agent_gateway_id" {
  description = "The agent gateway (agent_gateway): Entry adds the agent's target, TestCall calls it"
  type        = string
}

variable "agent_gateway_arn" {
  description = "The agent gateway (agent_gateway)"
  type        = string
}

variable "tool_gateway_arn" {
  description = "The tool gateway (tool_gateway): Grant permits the application's tools here"
  type        = string
}

variable "tool_gateway_url" {
  description = "The tool gateway's URL (tool_gateway): the deploy build gives it to the agent"
  type        = string
}

variable "policy_engine_id" {
  description = "The hub's policy engine (company_policy): every permit the review makes goes here"
  type        = string
}

variable "policy_engine_arn" {
  description = "The hub's policy engine (company_policy)"
  type        = string
}

variable "registry_id" {
  description = "The catalog (agent_catalog): its approval requests start the review"
  type        = string
}

variable "registry_arn" {
  description = "The catalog (agent_catalog)"
  type        = string
}

variable "topic_arn" {
  description = "The alert topic (agent_monitoring): a failed review is published here"
  type        = string
}

variable "dev_role_name" {
  description = "The dev team role (dev_access): it may upload to the inbox's submissions/"
  type        = string
}
