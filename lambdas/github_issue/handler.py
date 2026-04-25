"""
Lambda 2 – github-issue
========================
Called by the Step Functions state machine **only** when Lambda 1 (auto-fix)
has successfully created and attached a remediation IAM policy.

Input (from the Step Function Payload)
---------------------------------------
``{"policy_name": str, "policy_arn": str, "repo_name": str,
    "role_name": str, "denied_action": str}``

Behaviour
---------
1. Retrieves the GitHub fine-grained token from SSM Parameter Store
   (SecureString).
2. Opens a GitHub issue on the affected repository, labelled ``bug``, using
   the GitHub REST API.
3. Returns ``{"status": "success", "issue_url": str}`` on success.
"""

import json
import logging
import os
import urllib.error
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GITHUB_TOKEN_SSM_PATH: str = os.environ.get(
    "GITHUB_TOKEN_SSM_PATH",
    "/auto-roles-fix/github-token",
)

# GitHub REST API version – see https://docs.github.com/en/rest/overview/api-versions
GITHUB_API_VERSION = "2022-11-28"

ssm = boto3.client("ssm")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def lambda_handler(event: dict, context) -> dict:  # noqa: ANN001
    """Create a GitHub issue reporting the auto-correction that took place."""
    logger.info("Received event: %s", json.dumps(event))

    policy_name: str = event.get("policy_name", "")
    policy_arn: str = event.get("policy_arn", "")
    repo_name: str = event.get("repo_name", "")
    role_name: str = event.get("role_name", "")
    denied_action: str = event.get("denied_action", "")

    if not policy_name or not repo_name:
        logger.warning(
            "Missing required fields (policy_name=%r, repo_name=%r) – skipping",
            policy_name,
            repo_name,
        )
        return {"status": "skipped", "reason": "missing required fields"}

    github_token = _get_github_token()

    issue_title = f"[Auto-Correction] IAM policy created: {policy_name}"
    issue_body = _build_issue_body(
        policy_name=policy_name,
        policy_arn=policy_arn,
        role_name=role_name,
        repo_name=repo_name,
        denied_action=denied_action,
    )

    issue_url = _create_github_issue(
        repo_name=repo_name,
        title=issue_title,
        body=issue_body,
        labels=["bug"],
        token=github_token,
    )

    logger.info("Created GitHub issue: %s", issue_url)
    return {"status": "success", "issue_url": issue_url}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_github_token() -> str:
    """Retrieve the GitHub fine-grained token from SSM Parameter Store."""
    try:
        response = ssm.get_parameter(Name=GITHUB_TOKEN_SSM_PATH, WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception:
        logger.exception("Failed to retrieve GitHub token from SSM path '%s'", GITHUB_TOKEN_SSM_PATH)
        raise


def _build_issue_body(
    policy_name: str,
    policy_arn: str,
    role_name: str,
    repo_name: str,
    denied_action: str,
) -> str:
    """Render the GitHub issue body from a common template."""
    return f"""\
## Auto-Correction: IAM Permission Issue Detected

An `AccessDenied` error was detected and **automatically remediated** for a \
GitHub Actions workflow in this repository.

### Summary

| Field | Value |
|-------|-------|
| **Repository** | `{repo_name}` |
| **IAM Role** | `{role_name}` |
| **Denied Action** | `{denied_action}` |
| **Policy Created** | `{policy_name}` |
| **Policy ARN** | `{policy_arn}` |

### What Happened

A GitHub Actions workflow encountered an `AccessDenied` error while attempting \
to perform `{denied_action}`.  The automation detected this event and \
automatically created the IAM policy **`{policy_name}`** to grant the missing \
permission and attached it to the role **`{role_name}`**.

### Action Required

> ⚠️ The auto-created policy may be broader than necessary.  Please review it \
and follow the steps below.

1. Open the AWS Console and review the permissions in **`{policy_name}`**.
2. Verify that the granted permissions are appropriate and follow the \
[Principle of Least Privilege](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html#grant-least-privilege).
3. Update the Infrastructure-as-Code (IaC) to include the **minimal** required \
permissions permanently.
4. After the IaC change is deployed, **delete** the auto-created policy \
`{policy_name}` to avoid duplicate permissions.

### References

- Policy ARN: `{policy_arn}`
- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)

---
*This issue was automatically created by the \
[aws-auto-roles-fix](https://github.com/faccomichele-org/aws-auto-roles-fix) \
automation.*
"""


def _create_github_issue(
    repo_name: str,
    title: str,
    body: str,
    labels: list,
    token: str,
) -> str:
    """Open a GitHub issue via the REST API and return its HTML URL."""
    url = f"https://api.github.com/repos/{repo_name}/issues"
    payload = json.dumps({"title": title, "body": body, "labels": labels}).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    req = urllib.request.Request(url=url, data=payload, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("html_url", "")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        logger.error("GitHub API returned HTTP %s: %s", exc.code, error_body)
        raise
    except Exception:
        logger.exception("Unexpected error while calling the GitHub Issues API")
        raise
