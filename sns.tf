resource "aws_sns_topic" "sfn_failures" {
  name = "${local.project_name}-sfn-failures-${local.environment}"

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-sfn-failures-${local.environment}"
      File = "step_functions.tf"
    }
  )
}

resource "aws_sns_topic_subscription" "sfn_failures_email" {
  count = var.sfn_failure_alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.sfn_failures.arn
  protocol  = "email"
  endpoint  = var.sfn_failure_alert_email
}
