"""Kubernetes collector: kube API (pods, nodes, events, endpoints) + Metrics API (metrics.k8s.io).

Inject a CoreV1Api and a CustomObjectsApi (or Mocks). Build real ones with
`K8sCollector.from_kubeconfig()`, which needs the optional `kubernetes` extra (opskit[k8s]).

Fargate caveat: Fargate pods run one-per-microVM with no kubelet you can scrape; metrics-server
still reports pod usage, but node-level metrics, node conditions and evictions are not meaningful.
Use Container Insights (CloudWatch) or ADOT for Fargate.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

FARGATE_LABEL = "eks.amazonaws.com/compute-type"
PRESSURE_CONDITIONS = ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
_SUFFIXES = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
             "T": 1e12, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}


def parse_quantity(q: str | int | float) -> float:
    """Parse a Kubernetes quantity ("250m", "1.5Gi", "123456Ki", "2") to a float in base units."""
    if isinstance(q, (int, float)):
        return float(q)
    q = q.strip()
    for suffix in sorted(_SUFFIXES, key=len, reverse=True):
        if suffix and q.endswith(suffix):
            return float(q[: -len(suffix)]) * _SUFFIXES[suffix]
    return float(q)


class K8sCollector:
    """Read-only snapshots of cluster state. Every call passes a request timeout."""

    def __init__(self, core: Any, custom: Any | None = None, request_timeout_s: int = 30) -> None:
        self.core = core
        self.custom = custom
        self.timeout = request_timeout_s

    @classmethod
    def from_kubeconfig(cls, config_file: str | None = None, context: str | None = None,
                        request_timeout_s: int = 30) -> "K8sCollector":
        """Build clients for one kubeconfig context without touching global client state.

        config_file None -> $KUBECONFIG or ~/.kube/config; context None -> current-context.
        Inside a pod with no kubeconfig and no explicit context, in-cluster config is used.
        """
        import os

        from kubernetes import client, config
        if (config_file is None and context is None and os.environ.get("KUBERNETES_SERVICE_HOST")
                and not os.environ.get("KUBECONFIG")):
            config.load_incluster_config()
            api = client.ApiClient()
        else:
            if config_file:                       # "~/a:~/b" lists are merged by the client
                config_file = os.pathsep.join(os.path.expanduser(f) for f in config_file.split(os.pathsep))
            api = config.new_client_from_config(config_file=config_file, context=context)
        return cls(client.CoreV1Api(api), client.CustomObjectsApi(api), request_timeout_s)

    def ping(self) -> bool:
        """True if the kube API answers a cheap call (list one namespace)."""
        try:
            self.core.list_namespace(limit=1, _request_timeout=self.timeout)
            return True
        except Exception as exc:                      # network, auth, TLS: all mean "not reachable"
            log.warning("kube_api_unreachable", extra={"error": repr(exc)})
            return False

    def metrics_api_available(self) -> bool:
        """True if metrics.k8s.io answers (metrics-server installed and serving)."""
        if self.custom is None:
            return False
        try:
            self.custom.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes",
                                                   _request_timeout=self.timeout)
            return True
        except Exception as exc:
            log.warning("metrics_api_unavailable", extra={"error": repr(exc)})
            return False

    # --- Metrics API (kubectl top) -------------------------------------------------------
    def node_usage(self) -> dict[str, dict[str, float]]:
        """{node: {"cpu_cores": float, "mem_bytes": float}} from metrics.k8s.io/v1beta1 nodes."""
        if self.custom is None:
            return {}
        resp = self.custom.list_cluster_custom_object(
            "metrics.k8s.io", "v1beta1", "nodes", _request_timeout=self.timeout)
        return {i["metadata"]["name"]: {"cpu_cores": parse_quantity(i["usage"]["cpu"]),
                                        "mem_bytes": parse_quantity(i["usage"]["memory"])}
                for i in resp.get("items", [])}

    def pod_usage(self, namespace: str | None = None) -> dict[str, dict[str, dict[str, float]]]:
        """{"ns/pod": {container: {"cpu_cores", "mem_bytes"}}} from metrics.k8s.io pods."""
        if self.custom is None:
            return {}
        if namespace:
            resp = self.custom.list_namespaced_custom_object(
                "metrics.k8s.io", "v1beta1", namespace, "pods", _request_timeout=self.timeout)
        else:
            resp = self.custom.list_cluster_custom_object(
                "metrics.k8s.io", "v1beta1", "pods", _request_timeout=self.timeout)
        out: dict[str, dict[str, dict[str, float]]] = {}
        for item in resp.get("items", []):
            key = f'{item["metadata"]["namespace"]}/{item["metadata"]["name"]}'
            out[key] = {c["name"]: {"cpu_cores": parse_quantity(c["usage"]["cpu"]),
                                    "mem_bytes": parse_quantity(c["usage"]["memory"])}
                        for c in item.get("containers", [])}
        return out

    # --- kube API ------------------------------------------------------------------------
    def node_status(self) -> list[dict[str, Any]]:
        """Readiness, active pressure conditions, allocatable and Fargate flag for every node."""
        nodes = self.core.list_node(_request_timeout=self.timeout).items
        out = []
        for n in nodes:
            conds = {c.type: c.status for c in (n.status.conditions or [])}
            labels = n.metadata.labels or {}
            out.append({
                "name": n.metadata.name,
                "ready": conds.get("Ready") == "True",
                "pressure": [c for c in PRESSURE_CONDITIONS if conds.get(c) == "True"],
                "fargate": labels.get(FARGATE_LABEL) == "fargate",
                "zone": labels.get("topology.kubernetes.io/zone", ""),
                "allocatable": dict(n.status.allocatable or {}),
            })
        return out

    def pod_health(self, namespace: str | None = None, label_selector: str = "") -> list[dict[str, Any]]:
        """Phase, readiness, restarts, waiting reasons and last termination reason per pod."""
        resp = (self.core.list_namespaced_pod(namespace, label_selector=label_selector,
                                              _request_timeout=self.timeout) if namespace
                else self.core.list_pod_for_all_namespaces(label_selector=label_selector,
                                                           _request_timeout=self.timeout))
        out = []
        for p in resp.items:
            containers = []
            for c in p.status.container_statuses or []:
                last = getattr(getattr(c, "last_state", None), "terminated", None)
                waiting = getattr(getattr(c, "state", None), "waiting", None)
                containers.append({"name": c.name, "ready": bool(c.ready),
                                   "restarts": c.restart_count or 0,
                                   "waiting": waiting.reason if waiting else None,
                                   "last_terminated": last.reason if last else None})
            limits = {}
            for spec_c in getattr(p.spec, "containers", None) or []:
                lim = getattr(getattr(spec_c, "resources", None), "limits", None) or {}
                limits[spec_c.name] = {k: parse_quantity(v) for k, v in lim.items() if k in ("cpu", "memory")}
            for c in containers:
                c["limits"] = limits.get(c["name"], {})
            out.append({"namespace": p.metadata.namespace, "name": p.metadata.name,
                        "node": p.spec.node_name, "phase": p.status.phase,
                        "ready": bool(containers) and all(c["ready"] for c in containers),
                        "restarts": sum(c["restarts"] for c in containers),
                        "containers": containers})
        return out

    def warning_events(self, namespace: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Recent Warning events (OOMKilling, BackOff, FailedScheduling, Evicted, Unhealthy...)."""
        kwargs = {"field_selector": "type=Warning", "limit": limit, "_request_timeout": self.timeout}
        resp = (self.core.list_namespaced_event(namespace, **kwargs) if namespace
                else self.core.list_event_for_all_namespaces(**kwargs))
        return [{"namespace": e.metadata.namespace, "reason": e.reason, "message": e.message,
                 "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                 "count": e.count or 1} for e in resp.items]

    def services(self, namespace: str | None = None) -> list[dict[str, Any]]:
        """Services with their type; LoadBalancer/NodePort ones form the load-balancer level."""
        resp = (self.core.list_namespaced_service(namespace, _request_timeout=self.timeout) if namespace
                else self.core.list_service_for_all_namespaces(_request_timeout=self.timeout))
        out = []
        for svc in resp.items:
            ingress = getattr(getattr(svc.status, "load_balancer", None), "ingress", None) or []
            out.append({"namespace": svc.metadata.namespace, "name": svc.metadata.name,
                        "type": svc.spec.type,
                        "external": [i.hostname or i.ip for i in ingress if (i.hostname or i.ip)]})
        return out

    def endpoints_not_ready(self, namespace: str | None = None) -> dict[str, int]:
        """{"ns/service": not-ready address count} from Endpoints objects."""
        resp = (self.core.list_namespaced_endpoints(namespace, _request_timeout=self.timeout)
                if namespace else self.core.list_endpoints_for_all_namespaces(_request_timeout=self.timeout))
        out = {}
        for ep in resp.items:
            n = sum(len(s.not_ready_addresses or []) for s in (ep.subsets or []))
            out[f"{ep.metadata.namespace}/{ep.metadata.name}"] = n
        return out
