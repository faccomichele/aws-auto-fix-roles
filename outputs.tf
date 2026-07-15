output "github_app_client_id_ssm_path" {
  description = "SSM path used to store the GitHub App client id"
  value       = local.github_app_client_id_ssm_path
}

output "github_app_installation_id_ssm_path" {
  description = "SSM path used to store the GitHub App installation id"
  value       = local.github_app_installation_id_ssm_path
}

output "github_app_private_key_ssm_path" {
  description = "SSM path used to store the GitHub App private key"
  value       = local.github_app_private_key_ssm_path
}
