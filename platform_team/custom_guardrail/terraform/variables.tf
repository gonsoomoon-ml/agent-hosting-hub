variable "prefix" {
  description = "Every resource name starts with this"
  type        = string
}

variable "code_zip" {
  description = "Path of the hub's code package (build/platform_team.zip)"
  type        = string
}

variable "topic_arn" {
  description = "The alert topic (agent_monitoring): the interceptor's errors alarm publishes here"
  type        = string
}

variable "code_names" {
  description = "Banned words: code names of projects that are not public. A request or answer that holds one is blocked"
  type        = list(string)
  default     = ["Project Falcon"]
}

variable "employee_id_pattern" {
  description = "Regular expression of an employee ID. A match is masked as {employee_id} and the call goes on"
  type        = string
  default     = "EMP-\\d{6}"
}
