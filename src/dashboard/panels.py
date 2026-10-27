"""Metric catalogue per level: units, thresholds, data source, and threshold evaluation.

Each level of the triage flow is a "panel": the metrics shown on its cards and how they turn
into green / amber / red. Thresholds are defaults for an on-call SRE; override them in config.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Health, Level, MetricResult, MetricSeries, Threshold
from .trends import detect_anomaly, trend


@dataclass(frozen=True)
class MetricSpec:
    name: str
    title: str
    unit: str
    threshold: Threshold
    source: str
    sparkline: bool = True


def _m(name: str, title: str, unit: str, warn: float, crit: float, source: str,
       higher_is_worse: bool = True) -> MetricSpec:
    return MetricSpec(name, title, unit, Threshold(warn, crit, higher_is_worse), source)


PANELS: dict[Level, list[MetricSpec]] = {
    Level.CLUSTER: [
        _m("error_rate_pct", "Error rate", "%", 1, 5, "Prometheus/AMP (ingress or app RED metrics)"),
        _m("p95_latency_ms", "p95 latency", "ms", 300, 1000, "Prometheus/AMP histogram_quantile"),
        _m("pods_not_ready", "Pods not ready", "count", 1, 5, "kube API (pods)"),
        _m("nodes_not_ready", "Nodes not ready", "count", 1, 2, "kube API (nodes)"),
        _m("cpu_pct", "CPU used", "% of allocatable", 75, 90, "Metrics API / Container Insights"),
        _m("mem_pct", "Memory used", "% of allocatable", 80, 90, "Metrics API / Container Insights"),
    ],
    Level.LOAD_BALANCER: [
        _m("http_5xx", "Target 5xx", "count/min", 5, 50, "CloudWatch AWS/ApplicationELB HTTPCode_Target_5XX_Count"),
        _m("p95_latency_ms", "p95 target response", "ms", 300, 1000, "CloudWatch AWS/ApplicationELB TargetResponseTime p95"),
        _m("unhealthy_hosts", "Unhealthy targets", "count", 1, 2, "CloudWatch UnHealthyHostCount (ALB/NLB)"),
        _m("rejected_conns", "Rejected connections", "count/min", 1, 10, "CloudWatch RejectedConnectionCount"),
    ],
    Level.NETWORK: [
        _m("tcp_retransmit_pct", "TCP retransmits", "%", 1, 3, "Prometheus node_netstat / ADOT"),
        _m("dns_errors", "CoreDNS errors", "count/min", 1, 10, "Prometheus coredns_dns_responses_total{rcode!=NOERROR}"),
        _m("endpoints_not_ready", "Endpoints not ready", "count", 1, 2, "kube API (endpoints/EndpointSlices)"),
        _m("rx_drops", "RX drops", "pkts/s", 1, 10, "Container Insights pod_network_rx_dropped / node_network"),
    ],
    Level.NODE: [
        _m("cpu_pct", "CPU", "%", 75, 90, "Metrics API (kubectl top node) / Container Insights node_cpu_utilization"),
        _m("mem_pct", "Memory", "%", 80, 90, "Metrics API / Container Insights node_memory_utilization"),
        _m("pressure", "Pressure conditions", "count", 1, 1, "kube API node.status.conditions (Memory/Disk/PIDPressure)"),
        _m("evictions", "Evictions", "count", 1, 3, "kube API events reason=Evicted"),
    ],
    Level.POD: [
        _m("restarts", "Restarts (window)", "count", 1, 3, "kube API containerStatuses.restartCount"),
        _m("error_rate_pct", "Error rate", "%", 1, 5, "Prometheus/AMP app RED metrics"),
        _m("p95_latency_ms", "p95 latency", "ms", 300, 1000, "Prometheus/AMP"),
        _m("cpu_pct", "CPU of limit", "%", 80, 95, "Metrics API (kubectl top pod) / Container Insights"),
    ],
    Level.CONTAINER: [
        _m("mem_pct", "Memory of limit", "%", 85, 95, "Metrics API / Container Insights container_memory_utilization_over_container_limit"),
        _m("cpu_throttle_pct", "CPU throttled", "%", 25, 50, "Prometheus container_cpu_cfs_throttled_periods_total (cAdvisor/ADOT)"),
        _m("oom_kills", "OOMKills", "count", 1, 1, "kube API lastState.terminated.reason=OOMKilled"),
        _m("restarts", "Restarts (window)", "count", 1, 3, "kube API restartCount"),
    ],
}


def spec_for(level: Level, metric: str) -> MetricSpec | None:
    return next((s for s in PANELS[level] if s.name == metric), None)


def evaluate_threshold(level: Level, series: MetricSeries,
                       overrides: dict[str, Threshold] | None = None) -> MetricResult:
    """Turn one series into a MetricResult: health from the latest value, plus trend and anomaly.

    A z-score anomaly with no threshold breach still raises the metric to WARN so a sudden shift
    is visible before it crosses a static bound.
    """
    spec = spec_for(level, series.name)
    threshold = (overrides or {}).get(series.name) or (spec.threshold if spec else None)
    health = threshold.evaluate(series.latest) if threshold else Health.UNKNOWN
    anomaly = detect_anomaly(series, threshold)
    if anomaly and anomaly.reason == "zscore" and health.rank < Health.WARN.rank:
        health = Health.WARN
    return MetricResult(series=series, health=health, trend=trend(series.points),
                        anomaly=anomaly, threshold=threshold)
