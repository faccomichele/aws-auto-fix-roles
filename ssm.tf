# Placeholder for the GitHub App client id.
# Set the actual value out-of-band (e.g. AWS Console or CI/CD pipeline);
# Terraform will ignore subsequent changes to `value` so it never overwrites
# real credentials with placeholders.
resource "aws_ssm_parameter" "github_app_client_id" {
  name        = local.github_app_client_id_ssm_path
  type        = "String"
  value       = "REPLACE_ME"
  description = "GitHub App client id used by the auto-roles-fix Lambda"

  lifecycle {
    ignore_changes = [value]
  }

  tags = merge(local.tags,
    {
      Name = local.github_app_client_id_ssm_path
      File = "ssm.tf"
    }
  )
}

resource "aws_ssm_parameter" "github_app_installation_id" {
  name        = local.github_app_installation_id_ssm_path
  type        = "String"
  value       = "REPLACE_ME"
  description = "GitHub App installation id used by the auto-roles-fix Lambda"

  lifecycle {
    ignore_changes = [value]
  }

  tags = merge(local.tags,
    {
      Name = local.github_app_installation_id_ssm_path
      File = "ssm.tf"
    }
  )
}

resource "aws_ssm_parameter" "github_app_private_key" {
  name        = local.github_app_private_key_ssm_path
  type        = "SecureString"
  value       = "REPLACE_ME"
  description = "GitHub App private key (PEM) used by the auto-roles-fix Lambda"

  lifecycle {
    ignore_changes = [value]
  }

  tags = merge(local.tags,
    {
      Name = local.github_app_private_key_ssm_path
      File = "ssm.tf"
    }
  )
}
