variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix applied to every resource name"
  type        = string
  default     = "auto-roles-fix"
}

variable "github_token_ssm_path" {
  description = "SSM Parameter Store path that holds the GitHub fine-grained token (SecureString)"
  type        = string
  default     = "/auto-roles-fix/github-token"
}
