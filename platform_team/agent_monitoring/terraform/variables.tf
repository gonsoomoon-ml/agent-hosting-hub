variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "alert_email" {
  description = "Optional email address subscribed to the alert topic (empty: none)"
  type        = string
  default     = ""
}

variable "tool_gateway_arn" {
  description = "The tool gateway (tool_gateway): the alarm counts calls of one of its tools"
  type        = string
}

variable "watched_tool" {
  description = "The tool whose calls per minute the alarm counts, as <Target>___<tool>"
  type        = string
  default     = "Quality___get_inspection_data"
}

# Half the lower of the two loop rates seen on AWS (39 calls in a minute), and at least 5: see README.md.
variable "tool_calls_per_minute" {
  description = "The alarm goes off when the watched tool is called more often than this in one minute"
  type        = number
  default     = 19
}
