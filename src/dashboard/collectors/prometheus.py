"""Prometheus / Amazon Managed Service for Prometheus (AMP) collector over the HTTP API.

Inject a requests-compatible session. For self-hosted Prometheus the default
`opskit.http.build_session()` is enough. For AMP the base URL is
https://aps-workspaces.<region>.amazonaws.com/workspaces/<workspace-id> and every request must be
SigV4-signed for service "aps" (e.g. requests-auth-aws-sigv4 or botocore SigV4Auth on the
session); IAM needs aps:QueryMetrics.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..models import MetricSeries

log = logging.getLogger(__name__)

# PromQL used per level. {ns}, {pod}, {node}, {svc} are filled by the caller.
QUERIES: dict[str, str] = {
    "cluster.error_rate_pct": '100 * sum(rate(http_requests_total{code=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
    "cluster.p95_latency_ms": "1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))",
    "network.tcp_retransmit_pct": "100 * rate(node_netstat_Tcp_RetransSegs[5m]) / rate(node_netstat_Tcp_OutSegs[5m])",
    "network.dns_errors": 'sum(rate(coredns_dns_responses_total{rcode!="NOERROR"}[1m])) * 60',
    "pod.error_rate_pct": '100 * sum(rate(http_requests_total{namespace="{ns}",pod="{pod}",code=~"5.."}[5m])) / sum(rate(http_requests_total{namespace="{ns}",pod="{pod}"}[5m]))',
    "pod.p95_latency_ms": '1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="{ns}",pod="{pod}"}[5m])))',
    "container.cpu_throttle_pct": '100 * rate(container_cpu_cfs_throttled_periods_total{namespace="{ns}",pod="{pod}"}[5m]) / rate(container_cpu_cfs_periods_total{namespace="{ns}",pod="{pod}"}[5m])',
    "container.mem_pct": '100 * container_memory_working_set_bytes{namespace="{ns}",pod="{pod}"} / container_spec_memory_limit_bytes{namespace="{ns}",pod="{pod}"}',
    "container.oom_kills": 'sum by (container) (kube_pod_container_status_last_terminated_reason{namespace="{ns}",pod="{pod}",reason="OOMKilled"})',
}


class PromQLError(RuntimeError):
    """Prometheus returned status != success."""


class PrometheusCollector:
    """Thin wrapper over /api/v1/query and /api/v1/query_range."""

    def __init__(self, base_url: str, session: Any | None = None, timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        if session is None:
            from opskit.http import build_session    # lazy: requests is only needed for live use
            session = build_session(timeout=timeout_s)
        self.session = session
        self.timeout = timeout_s

    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise PromQLError(body.get("error", "unknown PromQL error"))
        return body["data"]["result"]

    def ready(self) -> bool:
        """True if the endpoint answers an instant query (works for Prometheus, Mimir and AMP)."""
        try:
            self._get("/api/v1/query", {"query": "vector(1)"})
            return True
        except Exception as exc:
            log.warning("prometheus_unreachable", extra={"url": self.base_url, "error": repr(exc)})
            return False

    def query(self, promql: str) -> dict[str, float]:
        """Instant query -> {label-string: value}."""
        return {self._key(r["metric"]): float(r["value"][1])
                for r in self._get("/api/v1/query", {"query": promql})}

    def query_range(self, promql: str, name: str, unit: str = "", window_s: int = 1800,
                    step_s: int = 60, end: float | None = None) -> list[MetricSeries]:
        """Range query -> one MetricSeries per returned label set (NaN points become 0)."""
        end = end or time.time()
        result = self._get("/api/v1/query_range",
                           {"query": promql, "start": end - window_s, "end": end, "step": step_s})
        out = []
        for r in result:
            pts = []
            for _, v in r.get("values", []):
                f = float(v)
                pts.append(0.0 if f != f else round(f, 4))
            label = self._key(r["metric"])
            out.append(MetricSeries(name=name, unit=unit, points=pts, step_s=step_s,
                                    source=f"prometheus:{label}" if label else "prometheus"))
        return out

    def named(self, key: str, unit: str = "", **labels: str) -> list[MetricSeries]:
        """Run one of QUERIES (e.g. "pod.p95_latency_ms") with label placeholders filled."""
        promql = QUERIES[key]
        for k, v in labels.items():
            promql = promql.replace("{" + k + "}", v)
        return self.query_range(promql, name=key.split(".", 1)[1], unit=unit)

    @staticmethod
    def _key(metric: dict[str, str]) -> str:
        return ",".join(f"{k}={v}" for k, v in sorted(metric.items()))
