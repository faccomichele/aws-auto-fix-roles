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
1. Retrieves GitHub App credentials from SSM Parameter Store:
    - app client id
    - app installation id
    - app private key (SecureString)
2. Exchanges a short-lived GitHub App JWT for an installation access token.
3. Opens a GitHub issue on the affected repository, labelled ``bug``, using
   the GitHub REST API.
4. Returns ``{"status": "success", "issue_url": str}`` on success.
"""

import os
import json
import time
import boto3
import logging
import urllib.error
import urllib.request
import jwt

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GITHUB_APP_CLIENT_ID_SSM_PATH: str = os.environ.get(
    "GITHUB_APP_CLIENT_ID_SSM_PATH",
    "MISSING_GITHUB_APP_CLIENT_ID_SSM_PATH!",  # e.g. "/org/project/dev/github-app-client-id"
)

GITHUB_APP_INSTALLATION_ID_SSM_PATH: str = os.environ.get(
    "GITHUB_APP_INSTALLATION_ID_SSM_PATH",
    "MISSING_GITHUB_APP_INSTALLATION_ID_SSM_PATH!",  # e.g. "/org/project/dev/github-app-installation-id"
)

GITHUB_APP_PRIVATE_KEY_SSM_PATH: str = os.environ.get(
    "GITHUB_APP_PRIVATE_KEY_SSM_PATH",
    "MISSING_GITHUB_APP_PRIVATE_KEY_SSM_PATH!",  # e.g. "/org/project/dev/github-app-private-key"
)

GITHUB_ORG: str = os.environ.get(
    "GITHUB_ORG",
    "MISSING_GITHUB_ORG!",  # e.g. "faccomichele-org"
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

    app_client_id, installation_id, private_key = _get_github_app_credentials()
    github_token = _get_github_installation_token(
        app_client_id=app_client_id,
        installation_id=installation_id,
        private_key=private_key,
    )

    issue_title = f"[Auto-Correction] IAM policy created: {policy_name}"
    issue_body = _build_issue_body(
        policy_name=policy_name,
        policy_arn=policy_arn,
        role_name=role_name,
        repo_name=repo_name,
        denied_action=denied_action,
    )

    issue_url = _create_github_issue(
        repo_name=f"{GITHUB_ORG}/{repo_name}",
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


def _get_github_app_credentials() -> tuple[str, str, str]:
    """Retrieve GitHub App client id, installation id and private key from SSM."""
    try:
        app_client_id = ssm.get_parameter(Name=GITHUB_APP_CLIENT_ID_SSM_PATH, WithDecryption=True)[
            "Parameter"
        ]["Value"]
        installation_id = ssm.get_parameter(
            Name=GITHUB_APP_INSTALLATION_ID_SSM_PATH,
            WithDecryption=True,
        )["Parameter"]["Value"]
        private_key = ssm.get_parameter(Name=GITHUB_APP_PRIVATE_KEY_SSM_PATH, WithDecryption=True)[
            "Parameter"
        ]["Value"]
        return app_client_id, installation_id, private_key
    except Exception:
        logger.exception(
            "Failed to retrieve GitHub App credentials from SSM paths '%s', '%s', '%s'",
            GITHUB_APP_CLIENT_ID_SSM_PATH,
            GITHUB_APP_INSTALLATION_ID_SSM_PATH,
            GITHUB_APP_PRIVATE_KEY_SSM_PATH,
        )
        raise


def _get_github_installation_token(
    app_client_id: str,
    installation_id: str,
    private_key: str,
) -> str:
    """Create a GitHub App JWT and exchange it for an installation access token."""
    now = int(time.time())
    app_jwt = jwt.encode(
        {
            "iat": now - 60,
            "exp": now + 540,
            "iss": app_client_id,
        },
        private_key,
        algorithm="RS256",
    )

    if isinstance(app_jwt, bytes):
        app_jwt = app_jwt.decode("utf-8")

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    req = urllib.request.Request(
        url=url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            token = data.get("token", "")
            if not token:
                raise ValueError("Missing token in GitHub installation token response")
            return token
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        logger.error(
            "GitHub App token exchange failed with HTTP %s for installation %s: %s",
            exc.code,
            installation_id,
            error_body,
        )
        raise
    except Exception:
        logger.exception("Unexpected error while creating GitHub installation token")
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
