"""Read-only AWS resource inventory and JSON/Excel exporters."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import boto3

from .aws import DEFAULT_CONFIG, paginate

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
    aws_session = session or boto3.Session()
    account_id = aws_session.client("sts", config=DEFAULT_CONFIG).get_caller_identity()["Account"]
    resources = []
    errors = {}

    for region in sorted(set(regions)):
        try:
            tagging = aws_session.client("resourcegroupstaggingapi", region_name=region,
                                         config=DEFAULT_CONFIG)
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


def write_inventory_json(inventory: dict[str, Any], destination: str | Path) -> Path:
    """Write an inventory document as UTF-8 JSON and return its path."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_inventory_excel(inventory: dict[str, Any], destination: str | Path) -> Path:
    """Write resource and collection-error sheets; install opskit[excel] to enable this."""
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ImportError("Excel export requires openpyxl; install opskit[excel].") from exc

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Resources"
    headers = ["account_id", "region", "service", "resource_type", "resource_id",
               "arn", "tags", "iac_tool", "terraform_workspace", "terraform_project",
               "terraform_module"]
    sheet.append(headers)
    for resource in inventory.get("resources", []):
        iac = resource.get("iac", {})
        sheet.append([
            resource.get("account_id", inventory.get("account_id", "")),
            resource.get("region", ""), resource.get("service", ""),
            resource.get("resource_type", ""), resource.get("resource_id", ""),
            resource.get("arn", ""), json.dumps(resource.get("tags", {}), sort_keys=True),
            iac.get("tool", ""), iac.get("workspace", ""), iac.get("project", ""),
            iac.get("module", ""),
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    errors_sheet = workbook.create_sheet("Errors")
    errors_sheet.append(["region", "error"])
    for region, error in sorted(inventory.get("errors", {}).items()):
        errors_sheet.append([region, error])
    errors_sheet.freeze_panes = "A2"
    errors_sheet.auto_filter.ref = errors_sheet.dimensions

    workbook.save(path)
    return path