# The Makefile sets region, prefix and model_id from AWS_REGION, DEMO_PREFIX and MODEL_ID (.env or the shell),
# the same values the Python side reads (platform_team.shared_code.config.Settings.from_env).

variable "region" {
  description = "AWS Region of the hub"
  type        = string
  default     = "us-west-2"
}

variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
  default     = "hub"
}

variable "model_id" {
  description = "Model the hosted agents call (the hosting review passes it to the agents it deploys)"
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "dev_principals" {
  description = "ARNs that may assume the dev team role. Empty means this account"
  type        = list(string)
  default     = []
}

# A variable, not a fixed path: `terraform validate` treats variables as unknown, so it runs before the first build.
variable "build_dir" {
  description = "Where `make package` writes platform_team.zip and the tool schemas, relative to this folder"
  type        = string
  default     = "../../build"
}

variable "alert_email" {
  description = "Optional email address subscribed to the alert topic"
  type        = string
  default     = ""
}
