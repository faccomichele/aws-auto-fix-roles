# Zip the Lambda source trees at plan/apply time
data "archive_file" "auto_fix" {
  type        = "zip"
  source_dir  = "${path.module}/lambdas/auto_fix"
  output_path = "${path.module}/dist/auto_fix.zip"
}

data "archive_file" "github_issue" {
  type        = "zip"
  source_dir  = "${path.module}/lambdas/github_issue"
  output_path = "${path.module}/dist/github_issue.zip"
}

# ── Lambda: auto-fix ─────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "auto_fix" {
  name              = "/aws/lambda/${var.project_name}-auto-fix"
  retention_in_days = 14
}

resource "aws_lambda_function" "auto_fix" {
  function_name    = "${var.project_name}-auto-fix"
  filename         = data.archive_file.auto_fix.output_path
  source_code_hash = data.archive_file.auto_fix.output_base64sha256
  role             = aws_iam_role.lambda_auto_fix.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60

  environment {
    variables = {
      OIDC_PROVIDER_URL = "token.actions.githubusercontent.com"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auto_fix]
}

# ── Lambda: github-issue ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "github_issue" {
  name              = "/aws/lambda/${var.project_name}-github-issue"
  retention_in_days = 14
}

resource "aws_lambda_function" "github_issue" {
  function_name    = "${var.project_name}-github-issue"
  filename         = data.archive_file.github_issue.output_path
  source_code_hash = data.archive_file.github_issue.output_base64sha256
  role             = aws_iam_role.lambda_github_issue.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30

  environment {
    variables = {
      GITHUB_TOKEN_SSM_PATH = var.github_token_ssm_path
    }
  }

  depends_on = [aws_cloudwatch_log_group.github_issue]
}
