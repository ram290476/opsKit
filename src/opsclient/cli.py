"""Run inventory and resource insights for the default AWS profile."""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opskit.aws import create_session
from opskit.inventory import (
    collect_account_inventory,
    write_inventory_json,
)
from opskit.resource_insights import (
    get_basic_resource_metrics,
    get_child_resource_type_counts,
    get_resource_health,
)

DEFAULT_PROFILE = "default"
INVENTORY_PATH = Path("aws-inventory.json")
LOOKBACK_HOURS = 24
PERIOD_SECONDS = 3600


def main() -> int:
    try:
        inventory = collect_account_inventory(
            profile_name=DEFAULT_PROFILE,
            regions=None,
        )
        json_path = write_inventory_json(inventory, INVENTORY_PATH)
        session = create_session(profile_name=DEFAULT_PROFILE)
        insights = []
        for resource in inventory.get("resources", []):
            insights.append({
                "resource": resource,
                "health": get_resource_health(resource, session),
                "children": get_child_resource_type_counts(resource, session),
                "metrics": get_basic_resource_metrics(
                    resource,
                    session,
                    lookback_hours=LOOKBACK_HOURS,
                    period_seconds=PERIOD_SECONDS,
                ),
            })
        print(json.dumps({
            "account_id": inventory["account_id"],
            "resource_count": len(inventory.get("resources", [])),
            "errors": inventory["errors"],
            "inventory_json": str(json_path),
            "insights": insights,
        }, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"opsclient: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())