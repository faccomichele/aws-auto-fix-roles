# aws-auto-roles-fix

AWS focused automation to expand IAM roles permission automatically, for GitHub Actions assumed roles.

## Overview

`aws-auto-roles-fix` detects `AccessDenied` errors produced by GitHub Actions OIDC roles, automatically creates a remediation inline IAM policy on the target role, and opens a GitHub issue on the affected repository so engineers can review and permanently fix the missing permission.

### How It Works

```
CloudTrail (AccessDenied event)
        │
        ▼
EventBridge Rule
        │
        ▼
Step Functions State Machine
        │
        ├─► Lambda: auto-fix
        │     • Verifies the role has a RepositoryURL tag
        │     • Creates an inline IAM policy on the role (auto-correction-*) if missing
        │
        └─► Lambda: github-issue
                  • Retrieves GitHub App credentials from SSM Parameter Store
                  • Exchanges an App JWT for an installation access token
              • Opens a GitHub issue on the affected repository
```

## Architecture

| Resource | Description |
|---|---|
| **CloudTrail Trail** | Regional trail that records all read/write management events and writes logs to the dedicated S3 bucket |
| **S3 Bucket (CloudTrail)** | Stores CloudTrail log files; objects are automatically deleted after 365 days |
| **EventBridge Rule** | Captures every CloudTrail management event with `errorCode: AccessDenied` or `Client.UnauthorizedOperation` |
| **Step Functions State Machine** | Orchestrates the two Lambdas; branches on whether a new inline policy was actually created |
| **Lambda – auto-fix** | Safety-gated remediation: only acts on roles with a valid `RepositoryURL` tag and matching environment filter |
| **Lambda – github-issue** | Opens a GitHub issue with a summary table and action items on the affected repository |
| **SSM Parameters** | Store the GitHub App client id, installation id, and private key |
| **IAM Roles & Policies** | Least-privilege execution roles for Lambda, Step Functions, and EventBridge |
| **CloudWatch Log Groups** | Centralised logging for the state machine and both Lambdas |

## Prerequisites

- Terraform >= 1.3.0
- AWS provider >= 5.0
- A Terraform workspace named `<environment>_<region>` (e.g. `dev_eu-west-1`)
- A GitHub App installed on the target repositories with `Issues: Read and write` permission
- GitHub App credentials:
        - App client id
        - App installation id
        - App private key (PEM)

## Usage

### 1. Create a Terraform workspace

```bash
terraform workspace new dev_eu-west-1
```

### 2. Provide input variables

Create a `terraform.tfvars` file (or equivalent):

```hcl
tags = {
  Project     = "aws-auto-roles-fix"
  Environment = "dev"
  Owner       = "platform-team"
}
```

### 3. Deploy

```bash
terraform init
terraform plan
terraform apply
```

### 4. Set GitHub App credentials

After the first apply, store GitHub App credentials in SSM (placeholder values are never overwritten by Terraform):

```bash
aws ssm put-parameter \
        --name "/<organization>/<project>/<env>/github-app-client-id" \
        --value "<your-app-client-id>" \
        --type String \
        --overwrite

aws ssm put-parameter \
        --name "/<organization>/<project>/<env>/github-app-installation-id" \
        --value "<your-app-installation-id>" \
        --type String \
        --overwrite

aws ssm put-parameter \
        --name "/<organization>/<project>/<env>/github-app-private-key" \
        --value "<your-app-private-key-pem>" \
        --type SecureString \
  --overwrite
```

### 5. Package the Lambdas

The Lambda functions must be zipped before apply. The GitHub issue Lambda needs `PyJWT` with cryptography support bundled:

```bash
zip -j lambdas/auto_fix.zip lambdas/auto_fix/handler.py

rm -rf lambdas/github_issue/build
mkdir -p lambdas/github_issue/build
pip install --target lambdas/github_issue/build -r lambdas/github_issue/requirements.txt
cp lambdas/github_issue/handler.py lambdas/github_issue/build/handler.py
cd lambdas/github_issue/build && zip -r ../../github_issue.zip . && cd -
```

## Inputs

| Variable | Type | Description |
|---|---|---|
| `tags` | `map(string)` | Map of tags to assign to all resources. Must include a `Project` key. |

## Outputs

| Output | Description |
|---|---|
| `github_app_client_id_ssm_path` | SSM path used to store the GitHub App client id |
| `github_app_installation_id_ssm_path` | SSM path used to store the GitHub App installation id |
| `github_app_private_key_ssm_path` | SSM path used to store the GitHub App private key |

## Safety

- The auto-fix Lambda only remediates roles that include a `RepositoryURL` tag and match the configured environment name filter.
- Inline policy creation is restricted to policy names matching `auto-correction-*`.
- The GitHub issue includes a ⚠️ reminder to review the auto-created inline policy and replace it with minimal permanent permissions.

## License

See [LICENSE](LICENSE).
