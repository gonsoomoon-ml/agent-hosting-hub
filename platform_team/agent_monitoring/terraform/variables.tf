variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "alert_email" {
  description = "Optional email address subscribed to the alert topic (empty: none)"
  type        = string
  default     = ""
}
