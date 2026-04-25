"""
Lambda 1 – auto-fix
====================
Triggered by the Step Functions state machine whenever EventBridge forwards a
CloudTrail ``errorCode: AccessDenied`` event.

Safety gate
-----------
The function only acts on IAM roles whose *trust policy* contains a statement
that allows ``sts:AssumeRoleWithWebIdentity`` from the GitHub Actions OIDC
provider (``token.actions.githubusercontent.com``).  Any other identity type is
silently ignored and the function returns an empty dict ``{}``.

Happy-path return value
-----------------------
``{"policy_name": str, "policy_arn": str, "repo_name": str,
    "role_name": str, "denied_action": str}``

If nothing was changed the function returns ``{}``.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OIDC_PROVIDER_URL: str = os.environ.get(
    "OIDC_PROVIDER_URL",
    "token.actions.githubusercontent.com",
)

iam = boto3.client("iam")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def lambda_handler(event: dict, context) -> dict:  # noqa: ANN001
    """Process a CloudTrail AccessDenied event and auto-attach a remediation policy."""
    logger.info("Received event: %s", json.dumps(event))

    detail = event.get("detail", {})
    error_code = detail.get("errorCode", "")

    if error_code not in ("AccessDenied", "Client.UnauthorizedOperation"):
        logger.info("errorCode '%s' is not AccessDenied – skipping", error_code)
        return {}

    user_identity = detail.get("userIdentity", {})

    if user_identity.get("type") != "AssumedRole":
        logger.info("userIdentity.type is not AssumedRole – skipping")
        return {}

    session_context = user_identity.get("sessionContext", {})
    session_issuer = session_context.get("sessionIssuer", {})

    if session_issuer.get("type") != "Role":
        logger.info("sessionIssuer.type is not Role – skipping")
        return {}

    role_arn: str = session_issuer.get("arn", "")
    if not role_arn:
        logger.warning("Could not find role ARN in event – skipping")
        return {}

    role_name: str = role_arn.split("/")[-1]
    account_id: str = session_issuer.get("accountId") or role_arn.split(":")[4]

    expected_provider = (
        f"arn:aws:iam::{account_id}:oidc-provider/{OIDC_PROVIDER_URL}"
    )

    # ── Safety check ─────────────────────────────────────────────────────────
    if not _is_github_actions_oidc_role(role_name, expected_provider):
        logger.info(
            "Role '%s' does not use the GitHub Actions OIDC trust policy – skipping",
            role_name,
        )
        return {}

    # ── Extract repo name from OIDC sub claim ─────────────────────────────────
    web_id_data = session_context.get("webIdFederationData", {})
    sub_claim: str = web_id_data.get("attributes", {}).get("sub", "")
    repo_name: str = _extract_repo_from_sub(sub_claim)

    # ── Build the allow statement for the denied action ───────────────────────
    action = _build_iam_action(detail.get("eventSource", ""), detail.get("eventName", ""))
    if not action:
        logger.warning(
            "Could not determine IAM action from eventSource='%s' eventName='%s' – "
            "skipping to avoid creating an overly-permissive wildcard policy",
            detail.get("eventSource", ""),
            detail.get("eventName", ""),
        )
        return {}

    resource_arns = _extract_resource_arns(detail.get("resources", []))

    # ── Create a uniquely-named IAM policy ────────────────────────────────────
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    policy_name = f"auto-correction-{role_name}-{timestamp}"

    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AutoCorrectionStatement",
                "Effect": "Allow",
                "Action": [action],
                "Resource": resource_arns,
            }
        ],
    }

    try:
        response = iam.create_policy(
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document),
            Description=(
                f"Auto-correction for role {role_name} – "
                f"AccessDenied on {action or 'unknown'} – created {timestamp} UTC"
            ),
        )
        policy_arn: str = response["Policy"]["Arn"]
        logger.info("Created policy: %s", policy_arn)
    except Exception:
        logger.exception("Failed to create IAM policy '%s'", policy_name)
        raise

    try:
        iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
        logger.info("Attached policy %s to role %s", policy_arn, role_name)
    except Exception:
        logger.exception("Failed to attach policy '%s' to role '%s'", policy_arn, role_name)
        raise

    return {
        "policy_name": policy_name,
        "policy_arn": policy_arn,
        "repo_name": repo_name,
        "role_name": role_name,
        "denied_action": action or "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _is_github_actions_oidc_role(role_name: str, expected_provider: str) -> bool:
    """Return *True* iff the role's trust policy allows sts:AssumeRoleWithWebIdentity
    from the expected GitHub Actions OIDC provider ARN."""
    try:
        response = iam.get_role(RoleName=role_name)
        trust_policy: dict = response["Role"]["AssumeRolePolicyDocument"]
    except Exception:
        logger.exception("Failed to retrieve role '%s'", role_name)
        return False

    for statement in trust_policy.get("Statement", []):
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if "sts:AssumeRoleWithWebIdentity" not in actions:
            continue

        principal = statement.get("Principal", {})
        federated = principal.get("Federated", "")
        if isinstance(federated, list):
            if expected_provider in federated:
                return True
        elif federated == expected_provider:
            return True

    return False


def _extract_repo_from_sub(sub_claim: str) -> str:
    """Extract *owner/repo* from an OIDC ``sub`` claim.

    The claim format is ``repo:owner/repo-name:ref:refs/heads/main`` (or
    ``repo:owner/repo-name:environment:prod``, etc.).
    """
    match = re.match(r"repo:([^:]+/[^:]+):", sub_claim)
    if match:
        return match.group(1)
    # Return the raw value if it cannot be parsed (safer than empty string)
    return sub_claim


def _build_iam_action(event_source: str, event_name: str) -> str:
    """Convert a CloudTrail ``eventSource`` + ``eventName`` into an IAM action string."""
    if not event_source or not event_name:
        return ""
    # e.g. "s3.amazonaws.com" -> "s3", then "s3:PutObject"
    service = event_source.split(".")[0]
    return f"{service}:{event_name}"


def _extract_resource_arns(resources: list) -> list:
    """Pull ARNs from the CloudTrail ``resources`` array.

    Falls back to ``["*"]`` when no ARNs are available – a security warning
    is logged in that case so operators can review the resulting policy.
    """
    arns = [r["ARN"] for r in resources if r.get("ARN")]
    if not arns:
        logger.warning(
            "No resource ARNs found in CloudTrail event; the remediation policy "
            "will use a wildcard resource ('*'). Please review the created policy."
        )
        return ["*"]
    return arns
