"""Live mode: build the six-level tree from a real cluster.

Topology (which pods run on which node, readiness, restarts, OOMKills, Services, Endpoints)
always comes from the kube API. Usage numbers come from one metrics source:

* metrics-api  - metrics.k8s.io (metrics-server) via the kubernetes client. It only reports the
  current value, so `History` keeps a rolling window of samples and the sparklines fill in as
  the server keeps sampling.
* prometheus   - PROMETHEUS_URL (Prometheus, Mimir or AMP). range queries give a full window
  immediately; kube API status is still used for readiness and pressure.

`select_source()` tries Prometheus (if a URL is set) then metrics-api, and falls back to the demo
tree with a reason when neither is reachable, so the page always renders something.

Mapping to the six levels on a plain cluster (kind, EKS without AWS metrics):
  Cluster > "edge" (LoadBalancer/NodePort Services; synthetic when there are none)
  > "cluster network" (Endpoints readiness, CoreDNS errors) > Nodes > Pods > Containers.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..demo import demo_tree
from ..models import Entity, Level, MetricSeries
from .k8s import K8sCollector
from .prometheus import PrometheusCollector

log = logging.getLogger(__name__)

Sample = dict[str, dict[str, float]]          # entity id -> metric -> value


def _safe(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in value.lower())


def node_id(name: str) -> str:
    return f"node-{_safe(name)}"


def pod_id(ns: str, name: str) -> str:
    return f"pod-{_safe(ns)}-{_safe(name)}"


def ctr_id(ns: str, pod: str, name: str) -> str:
    return f"ctr-{_safe(ns)}-{_safe(pod)}-{_safe(name)}"


@dataclass
class Topology:
    """One kube API snapshot: the shape of the tree plus status-derived values."""

    cluster: str
    nodes: list[dict[str, Any]]
    pods: list[dict[str, Any]]
    services: list[dict[str, Any]] = field(default_factory=list)
    endpoints_not_ready: dict[str, int] = field(default_factory=dict)

    @classmethod
    def collect(cls, k8s: K8sCollector, cluster: str, namespaces: list[str] | None = None) -> "Topology":
        if namespaces:
            pods = [p for ns in namespaces for p in k8s.pod_health(ns)]
            services = [s for ns in namespaces for s in k8s.services(ns)]
            eps: dict[str, int] = {}
            for ns in namespaces:
                eps.update(k8s.endpoints_not_ready(ns))
        else:
            pods, services, eps = k8s.pod_health(), k8s.services(), k8s.endpoints_not_ready()
        return cls(cluster, k8s.node_status(), pods, services, eps)

    def status_sample(self) -> Sample:
        """Values that come from object status, not from a metrics backend."""
        out: Sample = defaultdict(dict)
        cid = cluster_id(self.cluster)
        out[cid]["pods_not_ready"] = float(sum(1 for p in self.pods
                                               if p["phase"] not in ("Succeeded",) and not p["ready"]))
        out[cid]["nodes_not_ready"] = float(sum(1 for n in self.nodes if not n["ready"]))
        for n in self.nodes:
            out[node_id(n["name"])]["pressure"] = float(len(n["pressure"]))
        for p in self.pods:
            out[pod_id(p["namespace"], p["name"])]["restarts"] = float(p["restarts"])
            for c in p["containers"]:
                cid_ = ctr_id(p["namespace"], p["name"], c["name"])
                out[cid_]["restarts"] = float(c["restarts"])
                out[cid_]["oom_kills"] = 1.0 if c.get("last_terminated") == "OOMKilled" else 0.0
        lb_types = ("LoadBalancer", "NodePort")
        lb_keys = {f'{s["namespace"]}/{s["name"]}' for s in self.services if s["type"] in lb_types}
        out[edge_id(self.cluster)]["unhealthy_hosts"] = float(sum(v for k, v in self.endpoints_not_ready.items()
                                                                  if k in lb_keys))
        out[network_id(self.cluster)]["endpoints_not_ready"] = float(sum(self.endpoints_not_ready.values()))
        return out


def cluster_id(cluster: str) -> str:
    return f"cluster-{_safe(cluster)}"


def edge_id(cluster: str) -> str:
    return f"lb-{_safe(cluster)}-edge"


def network_id(cluster: str) -> str:
    return f"net-{_safe(cluster)}-cluster-network"


# ----------------------------------------------------------------------------- metrics sources
class MetricsApiSource:
    """Current CPU/memory from metrics.k8s.io, as percentages of allocatable / limits."""

    name = "metrics-api"

    def __init__(self, k8s: K8sCollector) -> None:
        self.k8s = k8s

    def available(self) -> bool:
        return self.k8s.metrics_api_available()

    def sample(self, topo: Topology) -> Sample:
        out: Sample = defaultdict(dict)
        node_use = self.k8s.node_usage()
        pod_use = self.k8s.pod_usage()
        tot_cpu = tot_mem = alloc_cpu = alloc_mem = 0.0
        for n in topo.nodes:
            use = node_use.get(n["name"])
            cpu_a = _q(n["allocatable"].get("cpu"))
            mem_a = _q(n["allocatable"].get("memory"))
            if use and cpu_a and mem_a:
                out[node_id(n["name"])]["cpu_pct"] = round(100 * use["cpu_cores"] / cpu_a, 2)
                out[node_id(n["name"])]["mem_pct"] = round(100 * use["mem_bytes"] / mem_a, 2)
                tot_cpu, tot_mem = tot_cpu + use["cpu_cores"], tot_mem + use["mem_bytes"]
                alloc_cpu, alloc_mem = alloc_cpu + cpu_a, alloc_mem + mem_a
        if alloc_cpu and alloc_mem:
            out[cluster_id(topo.cluster)]["cpu_pct"] = round(100 * tot_cpu / alloc_cpu, 2)
            out[cluster_id(topo.cluster)]["mem_pct"] = round(100 * tot_mem / alloc_mem, 2)
        for p in topo.pods:
            usage = pod_use.get(f'{p["namespace"]}/{p["name"]}', {})
            cpu_used = cpu_lim = 0.0
            for c in p["containers"]:
                u = usage.get(c["name"])
                lim = c.get("limits", {})
                if not u:
                    continue
                if lim.get("memory"):
                    out[ctr_id(p["namespace"], p["name"], c["name"])]["mem_pct"] = round(
                        100 * u["mem_bytes"] / lim["memory"], 2)
                if lim.get("cpu"):
                    cpu_used, cpu_lim = cpu_used + u["cpu_cores"], cpu_lim + lim["cpu"]
            if cpu_lim:
                out[pod_id(p["namespace"], p["name"])]["cpu_pct"] = round(100 * cpu_used / cpu_lim, 2)
        return out


class PrometheusSource:
    """Range queries against Prometheus/Mimir for cAdvisor + kube-state-metrics series."""

    name = "prometheus"
    QUERIES = {
        "container_mem_pct": ('100 * max by (namespace, pod, container) (container_memory_working_set_bytes{container!="",container!="POD"})'
                              ' / on (namespace, pod, container) max by (namespace, pod, container) '
                              '(kube_pod_container_resource_limits{resource="memory"})'),
        "container_throttle_pct": ('100 * sum by (namespace, pod, container) (rate(container_cpu_cfs_throttled_periods_total{container!=""}[5m]))'
                                   ' / sum by (namespace, pod, container) (rate(container_cpu_cfs_periods_total{container!=""}[5m]))'),
        "node_cpu_pct": '100 * (1 - avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[5m])))',
        "node_mem_pct": "100 * (1 - max by (node) (node_memory_MemAvailable_bytes) / max by (node) (node_memory_MemTotal_bytes))",
        "dns_errors": 'sum(rate(coredns_dns_responses_total{rcode!="NOERROR"}[1m])) * 60',
    }

    def __init__(self, prom: PrometheusCollector, window_s: int = 1800, step_s: int = 60) -> None:
        self.prom = prom
        self.window_s = window_s
        self.step_s = step_s

    def available(self) -> bool:
        return self.prom.ready()

    def series(self, topo: Topology) -> dict[str, dict[str, list[float]]]:
        """entity id -> metric -> points. Queries that fail or return nothing are skipped."""
        out: dict[str, dict[str, list[float]]] = defaultdict(dict)
        for key, promql in self.QUERIES.items():
            try:
                result = self.prom.query_range(promql, name=key, window_s=self.window_s, step_s=self.step_s)
            except Exception as exc:
                log.warning("promql_failed", extra={"query": key, "error": repr(exc)})
                continue
            for s in result:
                labels = dict(kv.split("=", 1) for kv in s.source.removeprefix("prometheus:").split(",") if "=" in kv)
                if key.startswith("container_") and {"namespace", "pod", "container"} <= labels.keys():
                    metric = "mem_pct" if key == "container_mem_pct" else "cpu_throttle_pct"
                    out[ctr_id(labels["namespace"], labels["pod"], labels["container"])][metric] = s.points
                elif key.startswith("node_") and "node" in labels:
                    out[node_id(labels["node"])][key.removeprefix("node_")] = s.points
                elif key == "dns_errors":
                    out[network_id(topo.cluster)]["dns_errors"] = s.points
        return out


def _q(v: Any) -> float:
    from .k8s import parse_quantity
    return parse_quantity(v) if v not in (None, "") else 0.0


# ----------------------------------------------------------------------------- history + tree
class History:
    """Rolling window of samples so instantaneous sources still get sparklines."""

    def __init__(self, maxlen: int = 30) -> None:
        self.maxlen = maxlen
        self._data: dict[str, dict[str, deque[float]]] = defaultdict(dict)
        self._lock = threading.Lock()

    def add(self, sample: Sample) -> None:
        with self._lock:
            for eid, metrics in sample.items():
                for m, v in metrics.items():
                    self._data[eid].setdefault(m, deque(maxlen=self.maxlen)).append(v)

    def get(self, eid: str) -> dict[str, list[float]]:
        with self._lock:
            return {m: list(d) for m, d in self._data.get(eid, {}).items()}


_UNITS = {"cpu_pct": "%", "mem_pct": "%", "cpu_throttle_pct": "%", "pressure": "count", "restarts": "count",
          "oom_kills": "count", "pods_not_ready": "count", "nodes_not_ready": "count", "unhealthy_hosts": "count",
          "endpoints_not_ready": "count", "dns_errors": "count/min"}


def _windowed(metric: str, points: list[float]) -> list[float]:
    """Counters become 'increase since the start of the window' so thresholds mean 'in window'."""
    if metric == "restarts" and points:
        base = points[0]
        return [max(0.0, p - base) for p in points]
    return points


def build_tree(topo: Topology, history: History, ranges: dict[str, dict[str, list[float]]] | None = None,
               source: str = "") -> Entity:
    """Assemble Cluster > edge > network > nodes > pods > containers with series attached."""
    ranges = ranges or {}

    def series_for(eid: str) -> list[MetricSeries]:
        merged = history.get(eid)
        merged.update(ranges.get(eid, {}))                # full-window range data wins
        return [MetricSeries(m, _UNITS.get(m, ""), _windowed(m, pts), source=source)
                for m, pts in sorted(merged.items()) if pts]

    pods_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in topo.pods:
        pods_by_node[p["node"] or "unscheduled"].append(p)
    node_names = [n["name"] for n in topo.nodes] + (["unscheduled"] if pods_by_node.get("unscheduled") else [])
    node_meta = {n["name"]: n for n in topo.nodes}

    nodes = []
    for name in node_names:
        meta = node_meta.get(name, {})
        pods = []
        for p in sorted(pods_by_node.get(name, []), key=lambda x: (x["namespace"], x["name"])):
            ctrs = [Entity(ctr_id(p["namespace"], p["name"], c["name"]), c["name"], Level.CONTAINER,
                           series_for(ctr_id(p["namespace"], p["name"], c["name"])),
                           attrs={"ready": c["ready"], "waiting": c.get("waiting") or "-",
                                  "last_terminated": c.get("last_terminated") or "-"})
                    for c in p["containers"]]
            pods.append(Entity(pod_id(p["namespace"], p["name"]), p["name"], Level.POD,
                               series_for(pod_id(p["namespace"], p["name"])), ctrs,
                               attrs={"namespace": p["namespace"], "phase": p["phase"], "node": name}))
        nodes.append(Entity(node_id(name), name, Level.NODE, series_for(node_id(name)), pods,
                            attrs={"ready": meta.get("ready", "-"), "zone": meta.get("zone") or "-",
                                   "compute": "fargate" if meta.get("fargate") else "node",
                                   "pressure": ",".join(meta.get("pressure", [])) or "none"}))

    lb_svcs = [s for s in topo.services if s["type"] in ("LoadBalancer", "NodePort")]
    network = Entity(network_id(topo.cluster), "cluster network", Level.NETWORK,
                     series_for(network_id(topo.cluster)), nodes,
                     attrs={"services": len(topo.services),
                            "endpoints_not_ready": sum(topo.endpoints_not_ready.values())})
    edge = Entity(edge_id(topo.cluster), "edge (LoadBalancer/NodePort)" if lb_svcs else "edge (no external LB)",
                  Level.LOAD_BALANCER, series_for(edge_id(topo.cluster)), [network],
                  attrs={"services": ", ".join(f'{s["namespace"]}/{s["name"]} ({s["type"]})' for s in lb_svcs[:8]) or "none"})
    return Entity(cluster_id(topo.cluster), topo.cluster, Level.CLUSTER, series_for(cluster_id(topo.cluster)),
                  [edge], attrs={"source": source, "nodes": len(topo.nodes), "pods": len(topo.pods)})


# ----------------------------------------------------------------------------- orchestration
@dataclass
class Snapshot:
    tree: Entity
    source: str                 # "metrics-api" | "prometheus" | "demo"
    banner: str = ""            # shown on the page when not live / degraded


class LiveDashboard:
    """Pick a source once, then `collect()` on every refresh. Thread-safe enough for http.server."""

    def __init__(self, cluster: str, k8s_factory: Callable[[], K8sCollector] | None,
                 prom_factory: Callable[[], PrometheusCollector] | None = None,
                 preferred: str = "auto", namespaces: list[str] | None = None,
                 window_points: int = 30, step_s: int = 60) -> None:
        self.cluster = cluster
        self.k8s_factory = k8s_factory
        self.prom_factory = prom_factory
        self.preferred = preferred
        self.namespaces = namespaces or None
        self.history = History(window_points)
        self.step_s = step_s
        self.k8s: K8sCollector | None = None
        self.source: MetricsApiSource | PrometheusSource | None = None
        self.reason = ""

    def select_source(self) -> str:
        """Returns the chosen source name; 'demo' with self.reason set when nothing is reachable."""
        if self.preferred == "demo":
            self.reason = "demo mode requested"
            return "demo"
        try:
            self.k8s = self.k8s_factory() if self.k8s_factory else None
        except Exception as exc:                          # bad kubeconfig, missing context, no package
            self.reason = f"cannot load kubeconfig/context: {exc}"
            self.k8s = None
        if self.k8s is None or not self.k8s.ping():
            self.reason = self.reason or f"kube API unreachable ({self.cluster})"
            return "demo"
        candidates: list[MetricsApiSource | PrometheusSource] = []
        if self.prom_factory and self.preferred in ("auto", "prometheus"):
            try:
                candidates.append(PrometheusSource(self.prom_factory(), self.history.maxlen * self.step_s, self.step_s))
            except Exception as exc:
                log.warning("prometheus_client_failed", extra={"error": repr(exc)})
        if self.preferred in ("auto", "metrics-api"):
            candidates.append(MetricsApiSource(self.k8s))
        for cand in candidates:
            if cand.available():
                self.source, self.reason = cand, ""
                log.info("metrics_source_selected", extra={"source": cand.name, "cluster": self.cluster})
                return cand.name
        self.reason = "neither Prometheus nor metrics.k8s.io is reachable"
        return "demo"

    def collect(self) -> Snapshot:
        """One refresh. Any failure degrades to demo data with a banner instead of a 500."""
        if self.source is None and self.select_source() == "demo":
            return Snapshot(demo_tree(), "demo", f"DEMO DATA - {self.reason}")
        assert self.k8s is not None and self.source is not None
        try:
            topo = Topology.collect(self.k8s, self.cluster, self.namespaces)
            sample = topo.status_sample()
            ranges = None
            if isinstance(self.source, MetricsApiSource):
                for eid, metrics in self.source.sample(topo).items():
                    sample.setdefault(eid, {}).update(metrics)
            else:
                ranges = self.source.series(topo)
            self.history.add(sample)
            return Snapshot(build_tree(topo, self.history, ranges, self.source.name), self.source.name)
        except Exception as exc:
            log.exception("live_collect_failed")
            self.source = None                            # re-probe next time
            return Snapshot(demo_tree(), "demo", f"DEMO DATA - live collection failed: {exc}")
