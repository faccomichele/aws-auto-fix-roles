resource "aws_sfn_state_machine" "auto_fix" {
  name     = "${local.project_name}-state-machine-${local.environment}"
  role_arn = aws_iam_role.step_functions.arn

  logging_configuration {
    level                  = "ALL"
    include_execution_data = true
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
  }

  definition = jsonencode({
    Comment = "Auto-fix IAM permissions for RepositoryURL-tagged IAM roles that hit AccessDenied"
    StartAt = "BuildCircuitContext"

    States = {
      BuildCircuitContext = {
        Type          = "Pass"
        QueryLanguage = "JSONata"
        Output        = "{% $merge([$states.input, {'circuit': {'RoleArn': $states.input.detail.userIdentity.sessionContext.sessionIssuer.arn, 'NowEpoch': $floor($toMillis($states.context.State.EnteredTime) / 1000), 'OpenUntilEpoch': $floor($toMillis($states.context.State.EnteredTime) / 1000) + 86400, 'FailureThreshold': 3}}]) %}"
        Next          = "GetRemediationLock"
      }

      GetRemediationLock = {
        Type     = "Task"
        Resource = "arn:aws:states:::dynamodb:getItem"
        Parameters = {
          TableName = aws_dynamodb_table.remediation_locks.name
          Key = {
            RoleArn = {
              "S.$" = "$.circuit.RoleArn"
            }
          }
          ConsistentRead = true
        }
        ResultPath = "$.lock"
        Next       = "LockHasCircuitFields"
      }

      LockHasCircuitFields = {
        Type = "Choice"
        Choices = [{
          And = [
            {
              Variable  = "$.lock.Item.FailureCount.N"
              IsPresent = true
            },
            {
              Variable  = "$.lock.Item.ExpirationTTL.N"
              IsPresent = true
            }
          ]
          Next = "NormalizeExistingCircuit"
        }]
        Default = "InvokeAutoFixLambda"
      }

      NormalizeExistingCircuit = {
        Type = "Pass"
        Parameters = {
          "FailureCount.$"  = "States.StringToJson($.lock.Item.FailureCount.N)"
          "ExpirationTTL.$" = "States.StringToJson($.lock.Item.ExpirationTTL.N)"
        }
        ResultPath = "$.circuit_state"
        Next       = "CircuitIsOpen"
      }

      CircuitIsOpen = {
        Type = "Choice"
        Choices = [{
          And = [
            {
              Variable                 = "$.circuit_state.FailureCount"
              NumericGreaterThanEquals = 3
            },
            {
              Variable           = "$.circuit_state.ExpirationTTL"
              NumericGreaterThan = 0
            },
            {
              Variable               = "$.circuit_state.ExpirationTTL"
              NumericGreaterThanPath = "$.circuit.NowEpoch"
            }
          ]
          Next = "CircuitOpen"
        }]
        Default = "InvokeAutoFixLambda"
      }

      CircuitOpen = {
        Type  = "Fail"
        Error = "CircuitOpen"
        Cause = "Circuit breaker is open for this role; remediation skipped"
      }

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
          Next        = "ClassifyAutoFixFailure"
        }]
      }

      ClassifyAutoFixFailure = {
        Type = "Choice"
        Choices = [{
          Or = [
            {
              Variable      = "$.error.Cause"
              StringMatches = "*LimitExceeded*"
            },
            {
              Variable      = "$.error.Cause"
              StringMatches = "*policy size*"
            },
            {
              Variable      = "$.error.Cause"
              StringMatches = "*PoliciesPerRole*"
            }
          ]
          Next = "IncrementFailureCount"
        }]
        Default = "AutoFixFailed"
      }

      IncrementFailureCount = {
        Type     = "Task"
        Resource = "arn:aws:states:::dynamodb:updateItem"
        Parameters = {
          TableName = aws_dynamodb_table.remediation_locks.name
          Key = {
            RoleArn = {
              "S.$" = "$.circuit.RoleArn"
            }
          }
          UpdateExpression = "ADD FailureCount :inc SET LastFailureEpoch = :now"
          ExpressionAttributeValues = {
            ":inc" = {
              N = "1"
            }
            ":now" = {
              "N.$" = "States.Format('{}', $.circuit.NowEpoch)"
            }
          }
        }
        ResultPath = "$.lock_update"
        Next       = "GetUpdatedLock"
      }

      GetUpdatedLock = {
        Type     = "Task"
        Resource = "arn:aws:states:::dynamodb:getItem"
        Parameters = {
          TableName = aws_dynamodb_table.remediation_locks.name
          Key = {
            RoleArn = {
              "S.$" = "$.circuit.RoleArn"
            }
          }
          ConsistentRead = true
        }
        ResultPath = "$.updated_lock"
        Next       = "NormalizeUpdatedLock"
      }

      NormalizeUpdatedLock = {
        Type = "Pass"
        Parameters = {
          "FailureCount.$" = "States.StringToJson($.updated_lock.Item.FailureCount.N)"
        }
        ResultPath = "$.updated_circuit"
        Next       = "FailureThresholdReached"
      }

      FailureThresholdReached = {
        Type = "Choice"
        Choices = [{
          Variable                 = "$.updated_circuit.FailureCount"
          NumericGreaterThanEquals = 3
          Next                     = "SetCircuitTTL"
        }]
        Default = "AutoFixHardLimitFailed"
      }

      SetCircuitTTL = {
        Type     = "Task"
        Resource = "arn:aws:states:::dynamodb:updateItem"
        Parameters = {
          TableName = aws_dynamodb_table.remediation_locks.name
          Key = {
            RoleArn = {
              "S.$" = "$.circuit.RoleArn"
            }
          }
          UpdateExpression = "SET ExpirationTTL = :ttl"
          ExpressionAttributeValues = {
            ":ttl" = {
              "N.$" = "States.Format('{}', $.circuit.OpenUntilEpoch)"
            }
          }
        }
        ResultPath = "$.ttl_update"
        Next       = "AutoFixHardLimitFailed"
      }

      AutoFixHardLimitFailed = {
        Type  = "Fail"
        Error = "AutoFixHardLimitFailed"
        Cause = "Auto-fix failed due to an IAM hard limit; failure count recorded"
      }

      # ── Step 2: branch on whether the auto-fix Lambda took any action ─────
      CheckAutoFixResult = {
        Type          = "Choice"
        Choices = [{
          And = [
            {
              Variable  = "$.auto_fix_result.Payload.policy_name"
              IsPresent = true
            },
            {
              Variable     = "$.auto_fix_result.Payload.actions_taken[0]"
              StringEquals = "inline_policy_created"
            }
          ]
          Next = "InvokeGitHubIssueLambda"
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

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-state-machine-${local.environment}"
      File = "step_functions.tf"
    }
  )
}
