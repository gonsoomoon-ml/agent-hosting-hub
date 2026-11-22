variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "policy_engine_arn" {
  description = "The hub's policy engine (company_policy), enforced on every tool call"
  type        = string
}

variable "tool_lambda_arn" {
  description = "The in-house tools Lambda (sample_tools)"
  type        = string
}

variable "tool_schemas" {
  description = "MCP tool schemas by target name (build/tool_schemas.json)"
  type = map(list(object({
    name        = string
    description = string
    inputSchema = object({
      type       = string
      properties = map(object({ type = string, description = string }))
      required   = list(string)
    })
  })))
}
