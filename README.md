# aws-auto-roles-fix

AWS focused automation to expand IAM roles permission automatically, for GitHub Actions assumed roles.

## Overview

`aws-auto-roles-fix` detects `AccessDenied` errors produced by GitHub Actions OIDC roles, automatically creates and attaches a remediation IAM policy, and opens a GitHub issue on the affected repository so engineers can review and permanently fix the missing permission.

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
        │     • Verifies the role uses the GitHub Actions OIDC trust policy
        │     • Creates an IAM policy (auto-correction-<role>-<timestamp>)
        │     • Attaches it to the role
        │
        └─► Lambda: github-issue
              • Retrieves a GitHub token from SSM Parameter Store
              • Opens a GitHub issue on the affected repository
```

## Architecture

| Resource | Description |
|---|---|
| **EventBridge Rule** | Captures every CloudTrail management event with `errorCode: AccessDenied` or `Client.UnauthorizedOperation` |
| **Step Functions State Machine** | Orchestrates the two Lambdas; branches on whether a policy was actually created |
| **Lambda – auto-fix** | Safety-gated remediation: only acts on roles whose trust policy allows `sts:AssumeRoleWithWebIdentity` from the GitHub Actions OIDC provider |
| **Lambda – github-issue** | Opens a GitHub issue with a summary table and action items on the affected repository |
| **SSM Parameter** | Stores the GitHub fine-grained personal-access token (SecureString) |
| **IAM Roles & Policies** | Least-privilege execution roles for Lambda, Step Functions, and EventBridge |
| **CloudWatch Log Groups** | Centralised logging for the state machine and both Lambdas |

## Prerequisites

- Terraform >= 1.3.0
- AWS provider >= 5.0
- A Terraform workspace named `<environment>_<region>` (e.g. `dev_eu-west-1`)
- A GitHub fine-grained personal-access token with `issues: write` permission on the target repositories

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

### 4. Set the GitHub token

After the first apply, store the GitHub token in SSM (the placeholder value is never overwritten by Terraform):

```bash
aws ssm put-parameter \
  --name "/<project>/<env>/github-token" \
  --value "<your-token>" \
  --type SecureString \
  --overwrite
```

### 5. Package the Lambdas

The Lambda functions must be zipped before apply:

```bash
zip -j lambdas/auto_fix.zip lambdas/auto_fix/handler.py
zip -j lambdas/github_issue.zip lambdas/github_issue/handler.py
```

## Inputs

| Variable | Type | Description |
|---|---|---|
| `tags` | `map(string)` | Map of tags to assign to all resources. Must include a `Project` key. |

## Outputs

| Output | Description |
|---|---|
| `github_token_ssm_path` | SSM path used to store the GitHub fine-grained token |

## Safety

- The auto-fix Lambda only remediates roles whose trust policy contains `sts:AssumeRoleWithWebIdentity` from `token.actions.githubusercontent.com`. All other identities are silently skipped.
- IAM policy creation is restricted to the `auto-correction-*` naming prefix.
- `AttachRolePolicy` is conditioned on the policy ARN matching the same prefix.
- The GitHub issue includes a ⚠️ reminder to review the auto-created policy and replace it with minimal permanent permissions.

## License

See [LICENSE](LICENSE).
