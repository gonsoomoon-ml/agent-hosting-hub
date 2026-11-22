variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "dev_principals" {
  description = "ARNs that may assume the dev team role"
  type        = list(string)
}

variable "policy_engine_id" {
  description = "The hub's policy engine (company_policy)"
  type        = string
}

variable "tool_gateway_arn" {
  description = "The tool gateway (tool_gateway)"
  type        = string
}

variable "registry_arn" {
  description = "The catalog (agent_catalog)"
  type        = string
}

variable "shared_tool" {
  description = "The read tool every developer may call, as <Target>___<tool> (SHARED_READ)"
  type        = string
}
