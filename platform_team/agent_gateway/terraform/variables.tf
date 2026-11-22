variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "policy_engine_arn" {
  description = "The hub's policy engine (company_policy), enforced on every request"
  type        = string
}
