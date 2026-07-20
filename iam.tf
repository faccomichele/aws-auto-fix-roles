# ──────────────────────────────────────────────────────────────────────────────
# Lambda – auto-fix
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda_auto_fix" {
  name = "${local.project_name}-lambda-auto-fix-${local.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-lambda-auto-fix-${local.environment}"
      File = "iam.tf"
    }
  )
}

resource "aws_iam_role_policy" "lambda_auto_fix" {
  name = "${local.project_name}-lambda-auto-fix-${local.environment}"
  role = aws_iam_role.lambda_auto_fix.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.auto_fix.arn}:*"
      },
      {
        Sid    = "AllowGetRole"
        Effect = "Allow"
        Action = ["iam:GetRole"]
        # Scoped to roles in this account only
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*"
      },
      {
        Sid      = "AllowListInlinePolicies"
        Effect   = "Allow"
        Action   = ["iam:ListRolePolicies"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*"
      },
      {
        Sid      = "AllowReadInlinePolicies"
        Effect   = "Allow"
        Action   = ["iam:GetRolePolicy"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*"
      },
      {
        Sid      = "AllowCreateAndUpdateInlinePolicies"
        Effect   = "Allow"
        Action   = ["iam:PutRolePolicy"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*"
        Condition = {
          StringLike = {
            "iam:PolicyName" = [
              "auto-correction-*",
              "${local.project_name}-auto-fix-*",
            ]
          }
        }
      },
      {
        Sid    = "AllowSSMAutoFixParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:PutParameter",
        ]
        Resource = "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/${local.organization}/${local.project_name}/${local.environment}/auto-fix/*"
      },
    ]
  })
}

# ──────────────────────────────────────────────────────────────────────────────
# Lambda – github-issue
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda_github_issue" {
  name = "${local.project_name}-lambda-github-issue-${local.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-lambda-github-issue-${local.environment}"
      File = "iam.tf"
    }
  )
}

resource "aws_iam_role_policy" "lambda_github_issue" {
  name = "${local.project_name}-lambda-github-issue-${local.environment}"
  role = aws_iam_role.lambda_github_issue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.github_issue.arn}:*"
      },
      {
        Sid    = "AllowSSMGetGitHubAppCredentials"
        Effect = "Allow"
        Action = ["ssm:GetParameter"]
        Resource = [
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${local.github_app_client_id_ssm_path}",
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${local.github_app_installation_id_ssm_path}",
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${local.github_app_private_key_ssm_path}",
        ]
      },
    ]
  })
}

# ──────────────────────────────────────────────────────────────────────────────
# Step Functions
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "step_functions" {
  name = "${local.project_name}-step-functions-${local.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-step-functions-${local.environment}"
      File = "iam.tf"
    }
  )
}

resource "aws_iam_role_policy" "step_functions" {
  name = "${local.project_name}-step-functions-${local.environment}"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          aws_lambda_function.auto_fix.arn,
          aws_lambda_function.github_issue.arn,
        ]
      },
      {
        Sid    = "AllowCircuitBreakerStateStore"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
        ]
        Resource = aws_dynamodb_table.remediation_locks.arn
      },
      {
        Sid    = "AllowSFNCloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutLogEvents",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups",
        ]
        # DescribeLogGroups and DescribeResourcePolicies require wildcard;
        # PutLogEvents is scoped to the SFN log group.
        Resource = [
          aws_cloudwatch_log_group.sfn.arn,
          "${aws_cloudwatch_log_group.sfn.arn}:*",
          "*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
        ]
        Resource = "*"
      },
    ]
  })
}

# ──────────────────────────────────────────────────────────────────────────────
# EventBridge
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "eventbridge" {
  name = "${local.project_name}-eventbridge-${local.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-eventbridge-${local.environment}"
      File = "iam.tf"
    }
  )
}

resource "aws_iam_role_policy" "eventbridge" {
  name = "${local.project_name}-eventbridge-${local.environment}"
  role = aws_iam_role.eventbridge.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = aws_sfn_state_machine.auto_fix.arn
    }]
  })
}
