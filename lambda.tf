# ── Lambda: auto-fix ─────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "auto_fix" {
  name              = "/aws/lambda/${local.project_name}-auto-fix-${local.environment}"
  retention_in_days = local.log_retention_in_days

  tags = merge(local.tags,
    {
      Name = "/aws/lambda/${local.project_name}-auto-fix-${local.environment}"
      File = "lambda.tf"
    }
  )
}

resource "aws_lambda_function" "auto_fix" {
  function_name    = "${local.project_name}-auto-fix-${local.environment}"
  filename         = "${path.module}/lambdas/auto_fix.zip"
  source_code_hash = fileexists("${path.module}/lambdas/auto_fix.zip") ? filebase64sha256("${path.module}/lambdas/auto_fix.zip") : null
  role             = aws_iam_role.lambda_auto_fix.arn
  handler          = "handler.lambda_handler"
  runtime          = local.python_runtime
  timeout          = 60

  environment {
    variables = {
      ENVIRONMENTS      = jsonencode([local.environment])
      OIDC_PROVIDER_URL = "token.actions.githubusercontent.com"
      SSM_PATH_PREFIX   = "/${local.organization}/${local.project_name}/${local.environment}/auto-fix/"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auto_fix]

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-auto-fix-${local.environment}"
      File = "lambda.tf"
    }
  )
}

# ── Lambda: github-issue ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "github_issue" {
  name              = "/aws/lambda/${local.project_name}-github-issue-${local.environment}"
  retention_in_days = local.log_retention_in_days

  tags = merge(local.tags,
    {
      Name = "/aws/lambda/${local.project_name}-github-issue-${local.environment}"
      File = "lambda.tf"
    }
  )
}

resource "aws_lambda_function" "github_issue" {
  function_name    = "${local.project_name}-github-issue-${local.environment}"
  filename         = "${path.module}/lambdas/github_issue.zip"
  source_code_hash = fileexists("${path.module}/lambdas/github_issue.zip") ? filebase64sha256("${path.module}/lambdas/github_issue.zip") : null
  role             = aws_iam_role.lambda_github_issue.arn
  handler          = "handler.lambda_handler"
  runtime          = local.python_runtime
  timeout          = 30

  environment {
      variables = {
        GITHUB_TOKEN_SSM_PATH = local.github_token_ssm_path
        GITHUB_ORG            = local.organization
      }
    }

  depends_on = [aws_cloudwatch_log_group.github_issue]

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-github-issue-${local.environment}"
      File = "lambda.tf"
    }
  )
}
