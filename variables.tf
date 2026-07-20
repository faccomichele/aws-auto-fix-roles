variable "tags" {
  description = "Map of tags to assign to resources"
  type        = map(string)
}

variable "sfn_failure_alert_email" {
  description = "Optional email endpoint subscribed to the Step Functions failure SNS topic"
  type        = string
  default     = null
}
