"""
Lambda 1 – auto-fix
====================
Triggered by the Step Functions state machine whenever EventBridge forwards a
CloudTrail ``errorCode: AccessDenied`` event.

Safety gate
-----------
The function only acts on IAM roles whose IAM metadata includes a
``RepositoryURL`` tag. The tag value is used to recover the repository org and
repository name. Any role without that tag is silently ignored and the
function returns an empty dict ``{}``.

Happy-path return value
-----------------------
``{"policy_name": str, "policy_arn": str, "repo_org": str,
    "repo_name": str, "role_name": str, "denied_action": str,
    "policy_action": str, "attachment_action": str,
    "actions_taken": list[str]}``

If nothing was changed the function returns ``{}``.
"""

import os, re
import json
import hashlib
import boto3
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SSM_PATH_PREFIX: str = os.environ.get(
    "SSM_PATH_PREFIX",
    "MISSING_SSM_PATH_PREFIX!",  # e.g. "/org/project/env/auto-fix/"
)

iam = boto3.client("iam")
ssm = boto3.client("ssm")

MAX_IAM_POLICY_NAME_LEN = 128
POLICY_TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _load_environments() -> list[str]:
    """Load the allowed environment substrings from the Lambda environment."""
    raw_value = os.environ.get("ENVIRONMENTS", '["MISSING_ENVIRONMENTS!"]')
    try:
        parsed_value = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("ENVIRONMENTS is not valid JSON; using raw string value")
        return [raw_value]

    if isinstance(parsed_value, str):
        return [parsed_value]
    if isinstance(parsed_value, list):
        return [str(item) for item in parsed_value if str(item)]

    logger.warning("ENVIRONMENTS is not a string or list; falling back to a single value")
    return [str(parsed_value)]


def _get_role_repository_url(role_name: str) -> tuple[str, str] | None:
    """Return the RepositoryURL tag as ``(org_name, repo_name)`` or ``None``.

    The tag value is expected to be a slash-delimited repository URL or slug,
    where the last path segment is the repository name and the second-to-last
    segment is the organization name.
    """
    try:
        response = iam.get_role(RoleName=role_name)
        for tag in response["Role"].get("Tags", []):
            if tag.get("Key") != "RepositoryURL":
                continue

            repository_url = str(tag.get("Value", "")).strip().strip("/")
            if not repository_url:
                logger.warning("Role '%s' has an empty RepositoryURL tag", role_name)
                return None

            parts = [segment for segment in repository_url.split("/") if segment]
            if len(parts) < 2:
                logger.warning(
                    "RepositoryURL tag '%s' on role '%s' does not contain an org and repo",
                    repository_url,
                    role_name,
                )
                return None

            return parts[-2], parts[-1]

        logger.info("Role '%s' does not have a RepositoryURL tag", role_name)
        return None
    except Exception:
        logger.exception("Failed to retrieve RepositoryURL tag for role '%s'", role_name)
        return None


def _sanitize_policy_segment(value: str) -> str:
    """Return a policy-name-safe segment."""
    return re.sub(r"[^A-Za-z0-9+=,.@_-]", "-", value)


def _clean_role_name_for_reporting(role_name: str) -> str:
    """Return a display/policy role name without the ephemeral GHARole suffix.

    Roles ending in ``-GHARole-<random>`` are normalized to remove the final
    random segment (e.g. ``my-role-GHARole-abc123`` -> ``my-role-GHARole``).
    """
    parts = role_name.split("-")
    if len(parts) >= 2 and parts[-2] == "GHARole":
        return "-".join(parts[:-1])
    return role_name


def _policy_document_canonical(policy_document: dict) -> str:
    """Return a stable string representation for policy comparisons."""
    return json.dumps(policy_document, sort_keys=True, separators=(",", ":"))


def _error_message_digest(error_message: str) -> str:
    """Return a short, stable digest for an error message."""
    return hashlib.sha256(error_message.encode("utf-8")).hexdigest()[:12]


def _build_policy_name_prefix(role_name: str, action: str, error_message: str) -> str:
    """Build a stable, max-length-safe prefix used for idempotent policy lookup.

    The final policy name appends a UTC timestamp, so this prefix reserves
    timestamp space up front to ensure the complete name remains within AWS's
    128-character policy-name limit.
    """
    digest = _error_message_digest(error_message)
    role_segment = _sanitize_policy_segment(role_name)
    action_segment = _sanitize_policy_segment(action)

    timestamp_len = len(datetime.now(tz=timezone.utc).strftime(POLICY_TIMESTAMP_FORMAT))
    max_prefix_len = MAX_IAM_POLICY_NAME_LEN - timestamp_len

    prefix_template = "auto-correction-{role}-{action}-{digest}-"
    prefix = prefix_template.format(
        role=role_segment,
        action=action_segment,
        digest=digest,
    )
    if len(prefix) <= max_prefix_len:
        return prefix

    fixed_overhead = len(prefix_template.format(role="", action="", digest=digest))
    available = max(2, max_prefix_len - fixed_overhead)

    while len(role_segment) + len(action_segment) > available:
        if len(role_segment) >= len(action_segment) and len(role_segment) > 1:
            role_segment = role_segment[:-1]
        elif len(action_segment) > 1:
            action_segment = action_segment[:-1]
        else:
            break

    return prefix_template.format(
        role=role_segment,
        action=action_segment,
        digest=digest,
    )


def _find_matching_policy(policy_name_prefix: str, policy_document: dict) -> tuple[str, str] | None:
    """Return the latest matching local policy ARN/name whose document is identical."""
    matches: list[tuple[datetime, str, str]] = []
    expected_document = _policy_document_canonical(policy_document)

    paginator = iam.get_paginator("list_policies")
    for page in paginator.paginate(Scope="Local"):
        for policy in page.get("Policies", []):
            if not policy.get("PolicyName", "").startswith(policy_name_prefix):
                continue

            try:
                policy_version = iam.get_policy_version(
                    PolicyArn=policy["Arn"],
                    VersionId=policy["DefaultVersionId"],
                )["PolicyVersion"]["Document"]
            except Exception:
                logger.exception("Failed to inspect IAM policy '%s'", policy.get("Arn", ""))
                continue

            if _policy_document_canonical(policy_version) == expected_document:
                matches.append((policy["CreateDate"], policy["PolicyName"], policy["Arn"]))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    _, policy_name, policy_arn = matches[0]
    return policy_name, policy_arn


def _is_policy_attached_to_role(role_name: str, policy_arn: str) -> bool:
    """Return ``True`` when the role already has the policy attached."""
    paginator = iam.get_paginator("list_attached_role_policies")
    for page in paginator.paginate(RoleName=role_name):
        for policy in page.get("AttachedPolicies", []):
            if policy.get("PolicyArn") == policy_arn:
                return True
    return False


def _build_iam_action(event_source: str, event_name: str) -> str:
    """Convert a CloudTrail ``eventSource`` + ``eventName`` into an IAM action string."""
    if not event_source or not event_name:
        return ""
    # e.g. "s3.amazonaws.com" -> "s3", then "s3:PutObject"
    service = event_source.split(".")[0]
    normalized_event_name = re.sub(r"\d{8}$", "", event_name)
    return f"{service}:{normalized_event_name}"


def _extract_resource_arns(resources: list, error_message: str = "") -> list:
    """Pull ARNs from the CloudTrail ``resources`` array.

    If ``resources`` is empty, tries to recover an ARN from ``errorMessage``
    before falling back to ``["*"]``. A security warning is logged when the
    wildcard fallback is used so operators can review the resulting policy.
    """
    arns = [r["ARN"] for r in resources if r.get("ARN")]
    if not arns and error_message:
        arn_matches = re.findall(r"arn:[^\s'\"<>]+", error_message)
        filtered_arns: list[str] = []
        for arn in arn_matches:
            candidate_arn = arn.rstrip(".,;:)]}")
            arn_parts = candidate_arn.split(":", 5)
            if len(arn_parts) < 6:
                continue
            if arn_parts[2] == "sts":
                continue
            filtered_arns.append(candidate_arn)
        arns = filtered_arns

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
    auto-fix is opt-in automatically.
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

    full_role_name: str = role_arn.split("/")[-1]

    ENVIRONMENTS: list[str] = _load_environments()

    if not any(environment in full_role_name for environment in ENVIRONMENTS):
        logger.info(
            "Role '%s' does not contain any allowed environment '%s' – skipping",
            full_role_name,
            ENVIRONMENTS,
        )
        return {}

    account_id: str = session_issuer.get("accountId") or role_arn.split(":")[4]

    # ── Safety gate: RepositoryURL tag must exist ────────────────────────────
    repository_info = _get_role_repository_url(full_role_name)
    if repository_info is None:
        logger.info("Role '%s' does not have a valid RepositoryURL tag – skipping", full_role_name)
        return {}

    repo_org, repo_name = repository_info
    role_name = _clean_role_name_for_reporting(full_role_name)

    # ── Auto-fix enabled check ────────────────────────────────────────────────
    if not _is_auto_fix_enabled(role_name):
        logger.info(
            "Auto-fix is disabled for role '%s' – skipping",
            role_name,
        )
        return {}

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

    error_message = str(detail.get("errorMessage", ""))

    resource_arns = _extract_resource_arns(
        detail.get("resources", []),
        error_message,
    )
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

    policy_name_prefix = _build_policy_name_prefix(role_name, action, error_message)

    existing_policy = _find_matching_policy(policy_name_prefix, policy_document)
    if existing_policy is not None:
        policy_name, policy_arn = existing_policy
        policy_action = "reused"
        logger.info("Reusing existing policy %s", policy_arn)
    else:
        timestamp = datetime.now(tz=timezone.utc).strftime(POLICY_TIMESTAMP_FORMAT)
        policy_name = f"{policy_name_prefix}{timestamp}"

        try:
            response = iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document),
                Description=(
                    f"Auto-correction for role {role_name} – "
                    f"AccessDenied on {action or 'unknown'} – created {timestamp} UTC"
                ),
            )
            policy_arn = response["Policy"]["Arn"]
            policy_action = "created"
            logger.info("Created policy: %s", policy_arn)
        except Exception:
            logger.exception("Failed to create IAM policy '%s'", policy_name)
            raise

    attachment_action = "already_attached"
    if not _is_policy_attached_to_role(full_role_name, policy_arn):
        try:
            iam.attach_role_policy(RoleName=full_role_name, PolicyArn=policy_arn)
            attachment_action = "attached"
            logger.info("Attached policy %s to role %s", policy_arn, full_role_name)
        except Exception:
            logger.exception("Failed to attach policy '%s' to role '%s'", policy_arn, full_role_name)
            raise

    if policy_action == "reused" and attachment_action == "already_attached":
        return {}

    actions_taken: list[str] = []
    if policy_action == "created":
        actions_taken.append("policy_created")
    elif policy_action == "reused":
        actions_taken.append("policy_reused")

    if attachment_action == "attached":
        actions_taken.append("policy_attached")

    return {
        "policy_name": policy_name,
        "policy_arn": policy_arn,
        "policy_action": policy_action,
        "attachment_action": attachment_action,
        "actions_taken": actions_taken,
        "repo_org": repo_org,
        "repo_name": repo_name,
        "role_name": role_name,
        "denied_action": action or "",
    }
