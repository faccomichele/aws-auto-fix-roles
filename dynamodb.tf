resource "aws_dynamodb_table" "remediation_locks" {
  name         = "${local.project_name}-remediation-locks-${local.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "RoleArn"

  attribute {
    name = "RoleArn"
    type = "S"
  }

  ttl {
    attribute_name = "ExpirationTTL"
    enabled        = true
  }

  tags = merge(local.tags,
    {
      Name = "${local.project_name}-remediation-locks-${local.environment}"
      File = "dynamodb.tf"
    }
  )
}