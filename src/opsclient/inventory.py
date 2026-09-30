"""AWS Resource Groups Tagging API inventory operations."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import boto3

from .aws import client, create_session, paginate

log = logging.getLogger(__name__)


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def _terraform_metadata(tags: dict[str, str]) -> dict[str, str]:
    normalized = {_normalized_key(key): value for key, value in tags.items()}
    managed_by = normalized.get("managedby", "")
    marker = normalized.get("terraform", "").casefold()
    iac_marker = normalized.get("iac", normalized.get("provisionedby", "")).casefold()
    is_terraform = (
        "terraform" in managed_by.casefold()
        or marker in {"true", "yes", "1", "terraform"}
        or "terraform" in iac_marker
        or any(key.startswith("terraform") or key in {"tfworkspace", "tfproject", "tfmodule"}
               for key in normalized)
    )
    if not is_terraform:
        return {}

    metadata = {"tool": "terraform"}
    if managed_by:
        metadata["managed_by"] = managed_by
    for field, aliases in {
        "workspace": ("terraformworkspace", "tfworkspace"),
        "project": ("terraformproject", "tfproject"),
        "module": ("terraformmodule", "tfmodule"),
    }.items():
        value = next((normalized[key] for key in aliases if normalized.get(key)), None)
        if value:
            metadata[field] = value
    return metadata


def collect_inventory(regions: Iterable[str], session: boto3.Session | None = None) -> dict[str, Any]:
    """Collect tagged AWS resources in regions; Terraform details are inferred from tags."""
    aws_session = session or create_session()
    account_id = client("sts", session=aws_session).get_caller_identity()["Account"]
    resources = []
    errors = {}

    for region in sorted(set(regions)):
        try:
            tagging = client("resourcegroupstaggingapi", region=region, session=aws_session)
            for item in paginate(tagging, "get_resources", "ResourceTagMappingList"):
                arn = item["ResourceARN"]
                arn_parts = arn.split(":", 5)
                service = arn_parts[2] if len(arn_parts) > 2 else ""
                resource_path = arn_parts[5] if len(arn_parts) > 5 else ""
                resource_match = re.match(r"([^/:]+)[/:](.*)", resource_path)
                tags = {tag["Key"]: tag["Value"] for tag in item.get("Tags", [])}
                resources.append({
                    "account_id": account_id,
                    "region": region,
                    "service": service,
                    "resource_type": resource_match.group(1) if resource_match else service,
                    "resource_id": resource_match.group(2) if resource_match else resource_path,
                    "arn": arn,
                    "tags": tags,
                    "iac": _terraform_metadata(tags),
                })
        except Exception as exc:
            log.exception("inventory_region_failed", extra={"region": region})
            errors[region] = repr(exc)

    resources.sort(key=lambda resource: (resource["region"], resource["arn"]))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "resources": resources,
        "errors": errors,
    }


def collect_account_inventory(profile_name: str | None = None,
                              regions: Iterable[str] | None = None) -> dict[str, Any]:
    """Collect the current AWS account using the default or named local boto3 profile.

    If regions are omitted, discover regions enabled for the account. Credentials are
    resolved by boto3 from its normal credential chain and are never stored by opskit.
    """
    session = create_session(profile_name=profile_name)
    if regions is None:
        ec2 = client("ec2", region="us-east-1", session=session)
        response = ec2.describe_regions(Filters=[{
            "Name": "opt-in-status",
            "Values": ["opt-in-not-required", "opted-in"],
        }])
        regions = (region["RegionName"] for region in response.get("Regions", []))
    return collect_inventory(regions, session)
