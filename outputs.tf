output "eventbridge_rule_arn" {
  description = "ARN of the EventBridge rule that captures CloudTrail AccessDenied events"
  value       = aws_cloudwatch_event_rule.cloudtrail_access_denied.arn
}

output "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = aws_sfn_state_machine.auto_fix.arn
}

output "auto_fix_lambda_arn" {
  description = "ARN of the auto-fix Lambda function"
  value       = aws_lambda_function.auto_fix.arn
}

output "github_issue_lambda_arn" {
  description = "ARN of the GitHub-issue Lambda function"
  value       = aws_lambda_function.github_issue.arn
}

output "github_token_ssm_path" {
  description = "SSM path used to store the GitHub fine-grained token"
  value       = var.github_token_ssm_path
}
