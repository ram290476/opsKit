"""Kubernetes helpers (optional dependency: pip install opskit[k8s])."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


def load_clients():
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api()


def list_namespaces(core: Any, request_timeout_s: int = 30) -> list[Any]:
    """Return Kubernetes namespaces using the supplied CoreV1 API client."""
    return core.list_namespace(_request_timeout=request_timeout_s).items


def list_pods(core: Any, namespace: str | None = None, label_selector: str = "",
              request_timeout_s: int = 30) -> list[Any]:
    """Return pods in one namespace, or across all namespaces when omitted."""
    if namespace is not None:
        response = core.list_namespaced_pod(
            namespace, label_selector=label_selector, _request_timeout=request_timeout_s)
    else:
        response = core.list_pod_for_all_namespaces(
            label_selector=label_selector, _request_timeout=request_timeout_s)
    return response.items


def list_events(core: Any, namespace: str | None = None, field_selector: str = "",
                request_timeout_s: int = 30) -> list[Any]:
    """Return events in one namespace, or across all namespaces when omitted."""
    if namespace is not None:
        response = core.list_namespaced_event(
            namespace, field_selector=field_selector, _request_timeout=request_timeout_s)
    else:
        response = core.list_event_for_all_namespaces(
            field_selector=field_selector, _request_timeout=request_timeout_s)
    return response.items


def get_pod_logs(core: Any, name: str, namespace: str, container: str | None = None,
                 tail_lines: int | None = None, since_seconds: int | None = None,
                 timestamps: bool = False, previous: bool = False,
                 request_timeout_s: int = 30) -> str:
    """Read logs for a pod container; Kubernetes API errors are allowed to propagate."""
    return core.read_namespaced_pod_log(
        name=name,
        namespace=namespace,
        container=container,
        tail_lines=tail_lines,
        since_seconds=since_seconds,
        timestamps=timestamps,
        previous=previous,
        _request_timeout=request_timeout_s,
    )


def rollout_restart(apps, name: str, namespace: str) -> None:
    patch = {"spec": {"template": {"metadata": {"annotations": {
        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}}}}}
    apps.patch_namespaced_deployment(name, namespace, patch)


def wait_for_rollout(apps, name: str, namespace: str, timeout_s: int = 600, poll_s: int = 5) -> None:
    """Equivalent of `kubectl rollout status`: generation observed and all replicas updated+available."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        d = apps.read_namespaced_deployment_status(name, namespace)
        want = d.spec.replicas or 0
        s = d.status
        if ((s.observed_generation or 0) >= d.metadata.generation
                and (s.updated_replicas or 0) == want
                and (s.available_replicas or 0) == want
                and (s.replicas or 0) == want):
            return
        time.sleep(poll_s)
    raise TimeoutError(f"deployment {namespace}/{name} not ready after {timeout_s}s")


def unhealthy_pods(core, label_selector: str = "", namespace: str | None = None) -> list[tuple[str, str, str]]:
    pods = (core.list_namespaced_pod(namespace, label_selector=label_selector) if namespace
            else core.list_pod_for_all_namespaces(label_selector=label_selector))
    bad = []
    for p in pods.items:
        waiting = [c.state.waiting.reason for c in (p.status.container_statuses or [])
                   if c.state and c.state.waiting]
        if p.status.phase not in ("Running", "Succeeded") or waiting:
            bad.append((p.metadata.namespace, p.metadata.name, ",".join(waiting) or p.status.phase))
    return bad
