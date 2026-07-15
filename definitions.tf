locals {
  environment           = terraform.workspace
  organization          = var.tags["Organization"] != null ? var.tags["Organization"] : "unknown"
  project_name          = var.tags["Project"] != null ? var.tags["Project"] : "unknown"
  log_retention_in_days = local.environment == "prod" ? 30 : 7
  github_token_ssm_path = "/${local.organization}/${local.project_name}/${local.environment}/github-token"
  python_runtime        = "python3.13"

  tags = var.tags # No custom tags for now, but this allows to easily add them later on.
}
