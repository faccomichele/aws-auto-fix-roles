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

import os, re
import json
import boto3
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

OIDC_PROVIDER_URL: str = os.environ.get(
    "OIDC_PROVIDER_URL",
    "MISSING_OIDC_PROVIDER_URL!",  # e.g. "token.actions.githubusercontent.com"
)

SSM_PATH_PREFIX: str = os.environ.get(
    "SSM_PATH_PREFIX",
    "MISSING_SSM_PATH_PREFIX!",  # e.g. "/org/project/env/auto-fix/"
)

iam = boto3.client("iam")
ssm = boto3.client("ssm")


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

    # ── Fetch trust policy once ───────────────────────────────────────────────
    trust_policy = _get_role_trust_policy(role_name)
    if trust_policy is None:
        return {}

    # ── Safety check ─────────────────────────────────────────────────────────
    if not _is_github_actions_oidc_role(trust_policy, expected_provider):
        logger.info(
            "Role '%s' does not use the GitHub Actions OIDC trust policy – skipping",
            role_name,
        )
        return {}

    # ── Auto-fix enabled check ────────────────────────────────────────────────
    if not _is_auto_fix_enabled(role_name):
        logger.info(
            "Auto-fix is disabled for role '%s' – skipping",
            role_name,
        )
        return {}

    # ── Extract repo name from the role's trust policy sub condition ──────────
    repo_name: str = _extract_repo_from_trust_policy(trust_policy)

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


def _get_role_trust_policy(role_name: str) -> dict | None:
    """Return the trust policy document for *role_name*, or *None* on failure."""
    try:
        response = iam.get_role(RoleName=role_name)
        return response["Role"]["AssumeRolePolicyDocument"]
    except Exception:
        logger.exception("Failed to retrieve role '%s'", role_name)
        return None


def _is_github_actions_oidc_role(trust_policy: dict, expected_provider: str) -> bool:
    """Return *True* iff the trust policy allows sts:AssumeRoleWithWebIdentity
    from the expected GitHub Actions OIDC provider ARN."""
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


def _extract_repo_from_trust_policy(trust_policy: dict) -> str:
    """Extract the repository name from the OIDC ``sub`` condition in the trust policy.

    Looks for a condition key ``<OIDC_PROVIDER_URL>:sub`` whose value follows the
    GitHub Actions format ``repo:owner/repo-name:*``.  Returns just the bare
    repository name (e.g. ``aws-auto-fix-roles``), or an empty string when not found.
    """
    sub_key = f"{OIDC_PROVIDER_URL}:sub"
    for statement in trust_policy.get("Statement", []):
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if "sts:AssumeRoleWithWebIdentity" not in actions:
            continue

        for condition_op in statement.get("Condition", {}).values():
            sub_value = condition_op.get(sub_key, "")
            if not sub_value:
                continue
            # sub_value: "repo:owner/repo-name:*" – capture only the repo-name part
            match = re.match(r"repo:[^/]+/([^:/]+)", sub_value)
            if match:
                return match.group(1)
            logger.warning("Could not parse sub condition value '%s'", sub_value)

    logger.warning("No '%s' sub condition found in trust policy", sub_key)
    return ""


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


def _is_auto_fix_enabled(role_name: str) -> bool:
    """Return *True* iff the SSM parameter for this role permits auto-fix.

    The parameter path is ``{SSM_PATH_PREFIX}{role_name}``.
    If the parameter does not exist it is created with value ``'true'`` so that
    auto-fix is opt-out rather than opt-in.
    """
    param_name = f"{SSM_PATH_PREFIX}{role_name}"
    try:
        response = ssm.get_parameter(Name=param_name)
        value = response["Parameter"]["Value"].strip().lower()
        return value == "true"
    except ssm.exceptions.ParameterNotFound:
        logger.info(
            "SSM parameter '%s' not found – creating it with value 'true'",
            param_name,
        )
        ssm.put_parameter(
            Name=param_name,
            Value="true",
            Type="String",
            Description=(
                f"Controls whether auto-fix is enabled for IAM role '{role_name}'. "
                "Set to 'false' to disable automatic remediation for this role."
            ),
        )
        return True
    except Exception:
        logger.exception(
            "Failed to read or create SSM parameter '%s' – treating auto-fix as disabled",
            param_name,
        )
        return False
