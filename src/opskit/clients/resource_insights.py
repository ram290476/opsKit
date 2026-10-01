"""Read-only health, relationship, and CloudWatch metric service operations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from .aws import client


def _resource_key(resource: dict[str, Any]) -> tuple[str, str]:
    return resource["service"].casefold(), resource["resource_type"].casefold()


def get_resource_health(resource: dict[str, Any],
                        session: boto3.Session | None = None) -> dict[str, Any]:
    """Return a service health snapshot for supported EC2, RDS, and Lambda resources."""
    service, resource_type = _resource_key(resource)
    resource_id = resource["resource_id"]
    result = {"arn": resource.get("arn"), "status": "unsupported", "checks": {}}

    if service == "ec2" and resource_type == "instance":
        ec2 = client("ec2", region=resource["region"], session=session)
        response = ec2.describe_instance_status(InstanceIds=[resource_id], IncludeAllInstances=True)
        statuses = response.get("InstanceStatuses", [])
        if not statuses:
            return {**result, "status": "unknown"}
        status = statuses[0]
        state = status.get("InstanceState", {}).get("Name", "unknown")
        checks = {
            "instance": status.get("InstanceStatus", {}).get("Status", "unknown"),
            "system": status.get("SystemStatus", {}).get("Status", "unknown"),
        }
        values = set(checks.values())
        health = "unhealthy" if "impaired" in values else (
            "healthy" if state == "running" and values == {"ok"} else "unknown")
        return {"arn": resource.get("arn"), "status": health,
                "checks": checks, "instance_state": state, "events": status.get("Events", [])}

    if service == "ec2" and resource_type == "volume":
        ec2 = client("ec2", region=resource["region"], session=session)
        statuses = ec2.describe_volume_status(VolumeIds=[resource_id]).get("VolumeStatuses", [])
        if not statuses:
            return {**result, "status": "unknown"}
        volume_status = statuses[0]
        state = volume_status.get("VolumeStatus", {}).get("Status", "unknown")
        health = "healthy" if state == "ok" else (
            "unhealthy" if state == "impaired" else "unknown")
        return {"arn": resource.get("arn"), "status": health,
                "checks": {"volume": state}, "events": volume_status.get("Events", [])}

    if service == "rds" and resource_type in {"db", "db-instance"}:
        rds = client("rds", region=resource["region"], session=session)
        instances = rds.describe_db_instances(DBInstanceIdentifier=resource_id).get("DBInstances", [])
        if not instances:
            return {**result, "status": "unknown"}
        state = instances[0].get("DBInstanceStatus", "unknown")
        health = "healthy" if state == "available" else (
            "unhealthy" if state in {"failed", "incompatible-parameters", "incompatible-restore"}
            else "transitional")
        return {"arn": resource.get("arn"), "status": health,
                "checks": {"database": state}}

    if service == "lambda" and resource_type == "function":
        lambda_client = client("lambda", region=resource["region"], session=session)
        function_name = resource_id.split(":", 1)[0]
        configuration = lambda_client.get_function_configuration(FunctionName=function_name)
        state = configuration.get("State", "unknown")
        update = configuration.get("LastUpdateStatus", "Successful")
        health = "healthy" if state == "Active" and update == "Successful" else (
            "unhealthy" if state == "Failed" or update == "Failed" else "transitional")
        return {"arn": resource.get("arn"), "status": health,
                "checks": {"function": state, "last_update": update}}

    return result


def get_child_resource_type_counts(resource: dict[str, Any],
                                   session: boto3.Session | None = None) -> dict[str, Any]:
    """Count directly attached EC2 instance resources or RDS cluster members."""
    service, resource_type = _resource_key(resource)
    resource_id = resource["resource_id"]

    if service == "ec2" and resource_type == "instance":
        ec2 = client("ec2", region=resource["region"], session=session)
        reservations = ec2.describe_instances(InstanceIds=[resource_id]).get("Reservations", [])
        """Compatibility exports for resource insights in opskit."""
        from ..resource_insights import (
            get_basic_resource_metrics,
            get_child_resource_type_counts,
            get_resource_health,
        )