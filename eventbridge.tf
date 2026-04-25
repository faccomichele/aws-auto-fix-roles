# Capture every CloudTrail management-event that carries errorCode: AccessDenied
# (or the equivalent Client.UnauthorizedOperation used by some services).
resource "aws_cloudwatch_event_rule" "cloudtrail_access_denied" {
  name        = "${local.project_name}-cloudtrail-access-denied-${local.environment}"
  description = "Trigger on CloudTrail events whose errorCode is AccessDenied"

  event_pattern = jsonencode({
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      errorCode = ["AccessDenied", "Client.UnauthorizedOperation"]
    }
  })

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-cloudtrail-access-denied-${local.environment}"
      File = "eventbridge.tf"
    }
  )
}

resource "aws_cloudwatch_event_target" "step_functions" {
  rule      = aws_cloudwatch_event_rule.cloudtrail_access_denied.name
  target_id = "${local.project_name}-sfn-${local.environment}"
  arn       = aws_sfn_state_machine.auto_fix.arn
  role_arn  = aws_iam_role.eventbridge.arn
}
