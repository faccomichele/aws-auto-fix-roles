resource "aws_cloudwatch_log_group" "auto_fix" {
  name              = "/aws/lambda/${local.project_name}-auto-fix-${local.environment}"
  retention_in_days = local.log_retention_in_days

  tags = merge(local.tags,
    {
      Name = "/aws/lambda/${local.project_name}-auto-fix-${local.environment}"
      File = "cloudwatch.tf"
    }
  )
}

resource "aws_cloudwatch_log_group" "github_issue" {
  name              = "/aws/lambda/${local.project_name}-github-issue-${local.environment}"
  retention_in_days = local.log_retention_in_days

  tags = merge(local.tags,
    {
      Name = "/aws/lambda/${local.project_name}-github-issue-${local.environment}"
      File = "cloudwatch.tf"
    }
  )
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${local.project_name}/${local.environment}"
  retention_in_days = local.log_retention_in_days

  tags = merge(local.tags,
    {
      Name = "/aws/states/${local.project_name}/${local.environment}"
      File = "cloudwatch.tf"
    }
  )
}

resource "aws_cloudwatch_metric_alarm" "sfn_execution_failures" {
  alarm_name          = "${local.project_name}-sfn-failures-${local.environment}"
  alarm_description   = "Alert when Step Functions remediation workflow fails 5+ times in 1 hour"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 5
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 3600
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.auto_fix.arn
  }

  alarm_actions = [aws_sns_topic.sfn_failures.arn]
  ok_actions    = [aws_sns_topic.sfn_failures.arn]

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-sfn-failures-${local.environment}"
      File = "cloudwatch.tf"
    }
  )
}
