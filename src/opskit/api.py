"""REST API for AWS resource insights and Kubernetes operations.

Install the optional server dependencies with ``pip install opskit[api]``.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .aws import create_session
from .inventory import collect_account_inventory
from .resource_insights import (
    get_basic_resource_metrics,
    get_child_resource_type_counts,
    get_resource_health,
)

app = FastAPI(title="opskit API", version="1.0.0")


class InventoryRequest(BaseModel):
    profile_name: str | None = None
    regions: list[str] | None = None


class InsightsRequest(BaseModel):
    resources: list[dict[str, Any]]
    profile_name: str | None = None
    lookback_hours: int = Field(default=24, gt=0)
    period_seconds: int = Field(default=3600, gt=0)


def _kubernetes_clients():
    from .k8s import load_clients

    return load_clients()


def _serialize_kubernetes(items: list[Any]) -> list[Any]:
    from kubernetes.client import ApiClient

    serializer = ApiClient()
    return [serializer.sanitize_for_serialization(item) for item in items]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/aws/inventory")
def aws_inventory(request: InventoryRequest) -> dict[str, Any]:
    return collect_account_inventory(
        profile_name=request.profile_name,
        regions=request.regions,
    )


@app.post("/aws/insights")
def aws_insights(request: InsightsRequest) -> list[dict[str, Any]]:
    session = create_session(profile_name=request.profile_name)
    return [
        {
            "resource": resource,
            "health": get_resource_health(resource, session),
            "children": get_child_resource_type_counts(resource, session),
            "metrics": get_basic_resource_metrics(
                resource,
                session,
                lookback_hours=request.lookback_hours,
                period_seconds=request.period_seconds,
            ),
        }
        for resource in request.resources
    ]


@app.get("/kubernetes/namespaces")
def kubernetes_namespaces() -> list[Any]:
    from .k8s import list_namespaces

    core, _ = _kubernetes_clients()
    return _serialize_kubernetes(list_namespaces(core))


@app.get("/kubernetes/pods")
def kubernetes_pods(namespace: str | None = None, label_selector: str = "") -> list[Any]:
    from .k8s import list_pods

    core, _ = _kubernetes_clients()
    return _serialize_kubernetes(list_pods(core, namespace, label_selector))


@app.get("/kubernetes/events")
def kubernetes_events(namespace: str | None = None, field_selector: str = "") -> list[Any]:
    from .k8s import list_events

    core, _ = _kubernetes_clients()
    return _serialize_kubernetes(list_events(core, namespace, field_selector))


@app.get("/kubernetes/pods/unhealthy")
def kubernetes_unhealthy_pods(
    namespace: str | None = None, label_selector: str = ""
) -> list[dict[str, str]]:
    from .k8s import unhealthy_pods

    core, _ = _kubernetes_clients()
    return [
        {"namespace": pod_namespace, "name": name, "reason": reason}
        for pod_namespace, name, reason in unhealthy_pods(core, label_selector, namespace)
    ]


@app.get("/kubernetes/pods/{namespace}/{name}/logs")
def kubernetes_pod_logs(
    namespace: str,
    name: str,
    container: str | None = None,
    tail_lines: int | None = None,
    since_seconds: int | None = None,
    timestamps: bool = False,
    previous: bool = False,
) -> dict[str, str]:
    from .k8s import get_pod_logs

    core, _ = _kubernetes_clients()
    return {
        "logs": get_pod_logs(
            core,
            name,
            namespace,
            container,
            tail_lines,
            since_seconds,
            timestamps,
            previous,
        )
    }


@app.get("/kubernetes/deployments/{namespace}/{name}/rollout")
def kubernetes_wait_for_rollout(
    namespace: str, name: str, timeout_s: int = 600, poll_s: int = 5
) -> dict[str, bool]:
    from .k8s import wait_for_rollout

    _, apps = _kubernetes_clients()
    wait_for_rollout(apps, name, namespace, timeout_s, poll_s)
    return {"ready": True}


@app.post("/kubernetes/deployments/{namespace}/{name}/restart")
def kubernetes_rollout_restart(namespace: str, name: str) -> dict[str, str]:
    from .k8s import rollout_restart

    _, apps = _kubernetes_clients()
    rollout_restart(apps, name, namespace)
    return {"status": "restart_requested", "namespace": namespace, "name": name}
