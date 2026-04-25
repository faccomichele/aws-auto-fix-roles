locals {
  environment           = split("_", terraform.workspace)[0]
  aws_region            = split("_", terraform.workspace)[1]
  project_name          = var.tags["Project"] != null ? var.tags["Project"] : "unknown"
  log_retention_in_days = local.environment == "prod" ? 30 : 7
  github_token_ssm_path = "/${local.project_name}/${local.environment}/github-token"
  python_runtime        = "python3.13"

  tags = merge (var.tags, {
    Project = local.project_name
  })
}
