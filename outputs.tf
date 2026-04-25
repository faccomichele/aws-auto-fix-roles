output "github_token_ssm_path" {
  description = "SSM path used to store the GitHub fine-grained token"
  value       = local.github_token_ssm_path
}
