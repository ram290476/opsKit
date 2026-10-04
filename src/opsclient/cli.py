"""Command-line client for the opskit REST API."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from requests.exceptions import RequestException

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opskit.http import build_session
from opskit.inventory import write_inventory_json

DEFAULT_PROFILE = "default"
INVENTORY_PATH = Path("aws-inventory.json")
LOOKBACK_HOURS = 24
PERIOD_SECONDS = 3600
DEFAULT_API_URL = "http://127.0.0.1:8000"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsclient")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("OPSKIT_API_URL", DEFAULT_API_URL),
        help=f"opskit API base URL (default: {DEFAULT_API_URL})",
    )
    commands = parser.add_subparsers(dest="command")

    aws = commands.add_parser("aws", aliases=["inventory"], help="collect AWS inventory and insights")
    aws.set_defaults(command="aws")
    aws.add_argument("--profile", default=DEFAULT_PROFILE)
    aws.add_argument("--region", action="append", dest="regions")
    aws.add_argument("--json", default=str(INVENTORY_PATH), dest="inventory_path")
    aws.add_argument("--lookback-hours", type=int, default=LOOKBACK_HOURS)
    aws.add_argument("--period-seconds", type=int, default=PERIOD_SECONDS)

    k8s = commands.add_parser("k8s", help="query Kubernetes through the REST API")
    k8s_commands = k8s.add_subparsers(dest="k8s_command", required=True)
    k8s_commands.add_parser("namespaces", help="list namespaces")
    for command_name, selector_name in (("pods", "label-selector"), ("events", "field-selector")):
        command = k8s_commands.add_parser(command_name)
        command.add_argument("--namespace")
        command.add_argument(f"--{selector_name}", default="")
    unhealthy = k8s_commands.add_parser("unhealthy-pods")
    unhealthy.add_argument("--namespace")
    unhealthy.add_argument("--label-selector", default="")
    logs = k8s_commands.add_parser("logs")
    logs.add_argument("name")
    logs.add_argument("--namespace", required=True)
    logs.add_argument("--container")
    logs.add_argument("--tail-lines", type=int)
    logs.add_argument("--since-seconds", type=int)
    logs.add_argument("--timestamps", action="store_true")
    logs.add_argument("--previous", action="store_true")
    rollout = k8s_commands.add_parser("rollout-status")
    rollout.add_argument("name")
    rollout.add_argument("--namespace", required=True)
    rollout.add_argument("--timeout-seconds", type=int, default=600)
    rollout.add_argument("--poll-seconds", type=int, default=5)
    restart = k8s_commands.add_parser("restart")
    restart.add_argument("name")
    restart.add_argument("--namespace", required=True)

    serve = commands.add_parser("serve", help="run the local opskit REST API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def api_request(api_url: str, method: str, path: str,
                params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None) -> Any:
    """Send one request to the REST API and return its JSON response."""
    with build_session(timeout=(3.05, 600)) as session:
        response = session.request(
            method,
            f"{api_url.rstrip('/')}{path}",
            params=params,
            json=body,
        )
    response.raise_for_status()
    return response.json()


def _aws_command(args: argparse.Namespace) -> int:
    inventory = api_request(
        args.api_url,
        "POST",
        "/aws/inventory",
        body={"profile_name": args.profile, "regions": args.regions},
    )
    json_path = write_inventory_json(inventory, args.inventory_path)
    insights = api_request(
        args.api_url,
        "POST",
        "/aws/insights",
        body={
            "profile_name": args.profile,
            "resources": inventory.get("resources", []),
            "lookback_hours": args.lookback_hours,
            "period_seconds": args.period_seconds,
        },
    )
    print(json.dumps({
        "account_id": inventory["account_id"],
        "resource_count": len(inventory.get("resources", [])),
        "errors": inventory["errors"],
        "inventory_json": str(json_path),
        "insights": insights,
    }, indent=2, default=str))
    return 0


def _k8s_command(args: argparse.Namespace) -> int:
    command = args.k8s_command
    if command == "namespaces":
        result = api_request(args.api_url, "GET", "/kubernetes/namespaces")
    elif command == "pods":
        result = api_request(
            args.api_url, "GET", "/kubernetes/pods",
            params={"namespace": args.namespace, "label_selector": args.label_selector},
        )
    elif command == "events":
        result = api_request(
            args.api_url, "GET", "/kubernetes/events",
            params={"namespace": args.namespace, "field_selector": args.field_selector},
        )
    elif command == "unhealthy-pods":
        result = api_request(
            args.api_url, "GET", "/kubernetes/pods/unhealthy",
            params={"namespace": args.namespace, "label_selector": args.label_selector},
        )
    elif command == "logs":
        namespace = quote(args.namespace, safe="")
        name = quote(args.name, safe="")
        result = api_request(
            args.api_url,
            "GET",
            f"/kubernetes/pods/{namespace}/{name}/logs",
            params={
                "container": args.container,
                "tail_lines": args.tail_lines,
                "since_seconds": args.since_seconds,
                "timestamps": args.timestamps,
                "previous": args.previous,
            },
        )
        print(result["logs"], end="")
        return 0
    elif command == "rollout-status":
        namespace = quote(args.namespace, safe="")
        name = quote(args.name, safe="")
        result = api_request(
            args.api_url,
            "GET",
            f"/kubernetes/deployments/{namespace}/{name}/rollout",
            params={"timeout_s": args.timeout_seconds, "poll_s": args.poll_seconds},
        )
    else:
        namespace = quote(args.namespace, safe="")
        name = quote(args.name, safe="")
        result = api_request(
            args.api_url, "POST",
            f"/kubernetes/deployments/{namespace}/{name}/restart",
        )

    print(json.dumps(result, indent=2, default=str))
    return 0


def _serve_command(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("API server requires uvicorn; install opskit[api].") from exc

    uvicorn.run("opskit.api:app", host=args.host, port=args.port)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(raw_args)
    if args.command is None:
        args = _parser().parse_args(["aws", *raw_args])
    try:
        if args.command == "serve":
            return _serve_command(args)
        if args.command == "k8s":
            return _k8s_command(args)
        return _aws_command(args)
    except (OSError, RequestException, RuntimeError) as exc:
        print(f"opsclient: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
