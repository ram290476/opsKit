"""Command-line interface that delegates AWS operations to the opskit library."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opskit.aws import create_session
from opskit.inventory import (
    collect_account_inventory,
    write_inventory_excel,
    write_inventory_json,
)
from opskit.resource_insights import (
    get_basic_resource_metrics,
    get_child_resource_type_counts,
    get_resource_health,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsclient")
    commands = parser.add_subparsers(dest="command")

    inventory = commands.add_parser("inventory", help="collect and export AWS inventory")
    inventory.add_argument("--profile", help="AWS CLI profile; defaults to the boto3 credential chain")
    inventory.add_argument("--region", action="append", dest="regions",
                           help="region to scan; repeat to scan multiple regions")
    inventory.add_argument("--json", type=Path, default=Path("aws-inventory.json"),
                           help="JSON output path (default: aws-inventory.json)")
    inventory.add_argument("--excel", type=Path, help="optional Excel output path")

    inspect = commands.add_parser("inspect", help="get health, child counts, and metrics for a resource")
    inspect.add_argument("--inventory", type=Path, required=True,
                         help="inventory JSON created by the inventory command")
    inspect.add_argument("--arn", required=True, help="resource ARN from the inventory")
    inspect.add_argument("--profile", help="AWS CLI profile; defaults to the boto3 credential chain")
    inspect.add_argument("--lookback-hours", type=int, default=24)
    inspect.add_argument("--period-seconds", type=int, default=3600)
    return parser


def _run_inventory(args: argparse.Namespace) -> int:
    inventory = collect_account_inventory(profile_name=args.profile, regions=args.regions)
    json_path = write_inventory_json(inventory, args.json)
    excel_path = write_inventory_excel(inventory, args.excel) if args.excel else None
    print(json.dumps({
        "account_id": inventory["account_id"],
        "resource_count": len(inventory["resources"]),
        "errors": inventory["errors"],
        "json": str(json_path),
        "excel": str(excel_path) if excel_path else None,
    }, indent=2))
    return 0


def _run_inspect(args: argparse.Namespace) -> int:
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    resource = next((item for item in inventory.get("resources", [])
                     if item.get("arn") == args.arn), None)
    if resource is None:
        raise ValueError(f"resource ARN not found in inventory: {args.arn}")

    session = create_session(profile_name=args.profile)
    result = {
        "resource": resource,
        "health": get_resource_health(resource, session),
        "children": get_child_resource_type_counts(resource, session),
        "metrics": get_basic_resource_metrics(
            resource,
            session,
            lookback_hours=args.lookback_hours,
            period_seconds=args.period_seconds,
        ),
    }
    print(json.dumps(result, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "inventory":
            return _run_inventory(args)
        return _run_inspect(args)
    except Exception as exc:
        print(f"opsclient: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())