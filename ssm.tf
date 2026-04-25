# Placeholder for the GitHub fine-grained personal-access token.
# Set the actual token value out-of-band (e.g. AWS Console or CI/CD pipeline);
# Terraform will ignore subsequent changes to `value` so it never overwrites
# a real token with the placeholder.
resource "aws_ssm_parameter" "github_token" {
  name        = var.github_token_ssm_path
  type        = "SecureString"
  value       = "REPLACE_ME"
  description = "GitHub fine-grained token used by the auto-roles-fix Lambda to open issues"

  lifecycle {
    ignore_changes = [value]
  }
}
