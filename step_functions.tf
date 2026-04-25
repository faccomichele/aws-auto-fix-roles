resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${var.project_name}"
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "auto_fix" {
  name     = "${var.project_name}-state-machine"
  role_arn = aws_iam_role.step_functions.arn

  logging_configuration {
    level                  = "ERROR"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }

  definition = jsonencode({
    Comment = "Auto-fix IAM permissions for GitHub Actions OIDC roles that hit AccessDenied"
    StartAt = "InvokeAutoFixLambda"

    States = {
      # ── Step 1: call the auto-fix Lambda ──────────────────────────────────
      InvokeAutoFixLambda = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          "FunctionName" = aws_lambda_function.auto_fix.arn
          "Payload.$"    = "$"
        }
        ResultSelector = {
          "Payload.$" = "$.Payload"
        }
        ResultPath = "$.auto_fix_result"
        Next       = "CheckAutoFixResult"
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "AutoFixFailed"
        }]
      }

      # ── Step 2: branch on whether a policy was created ────────────────────
      CheckAutoFixResult = {
        Type = "Choice"
        Choices = [{
          # Lambda returns {"policy_name": "..."} only when it acted
          Variable  = "$.auto_fix_result.Payload.policy_name"
          IsPresent = true
          Next      = "InvokeGitHubIssueLambda"
        }]
        Default = "NoChangeNeeded"
      }

      # ── Step 3: open a GitHub issue ───────────────────────────────────────
      InvokeGitHubIssueLambda = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          "FunctionName" = aws_lambda_function.github_issue.arn
          "Payload.$"    = "$.auto_fix_result.Payload"
        }
        ResultPath = "$.github_issue_result"
        End        = true
        Catch = [{
          ErrorEquals = ["States.ALL"]
          ResultPath  = "$.error"
          Next        = "GitHubIssueFailed"
        }]
      }

      # ── Terminal states ───────────────────────────────────────────────────
      NoChangeNeeded = {
        Type = "Succeed"
      }

      AutoFixFailed = {
        Type  = "Fail"
        Error = "AutoFixFailed"
        Cause = "The auto-fix Lambda raised an unhandled exception"
      }

      GitHubIssueFailed = {
        Type  = "Fail"
        Error = "GitHubIssueFailed"
        Cause = "The GitHub-issue Lambda raised an unhandled exception"
      }
    }
  })
}
