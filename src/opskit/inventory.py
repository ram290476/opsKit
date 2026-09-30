"""Read-only AWS resource inventory and JSON/Excel exporters."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opsclient.inventory import collect_account_inventory, collect_inventory


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