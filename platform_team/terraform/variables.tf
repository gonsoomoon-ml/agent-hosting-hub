# The Makefile sets region, prefix and model_id from AWS_REGION, DEMO_PREFIX and MODEL_ID (.env or the shell),
# the same values the Python side reads (platform_team.shared_code.config.Settings.from_env).

variable "region" {
  description = "AWS Region of the hub"
  type        = string
  default     = "us-west-2"
}

variable "prefix" {
  description = "Every resource name starts with this: 2 to 10 lower-case letters or digits, starting with a letter, not harness"
  type        = string
  default     = "hub"
  # The same rule as PREFIX_PATTERN in shared_code/config.py: the policy engine name and a Runtime name take no "-",
  # a gateway no "_", a bucket no upper case.
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.prefix))
    error_message = "The prefix must be 2 to 10 lower-case letters or digits, starting with a letter (for example hub)."
  }
  # RESERVED_PREFIXES in shared_code/config.py: AgentCore names the Runtime of a harness harness_<harness name>, so with
  # this prefix one agent's Runtime could have the name of another agent's harness Runtime.
  validation {
    condition     = !contains(["harness"], var.prefix)
    error_message = "The prefix harness is not taken: AgentCore names the Runtime of a harness harness_<harness name>."
  }
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
