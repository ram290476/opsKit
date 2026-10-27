"""CloudWatch collector: Container Insights (EKS, EKS Fargate, ECS Fargate) and ALB/NLB metrics.

Inject a boto3 CloudWatch client, e.g. `opskit.aws.client("cloudwatch", region="us-west-2")`.
IAM: cloudwatch:GetMetricData. Container Insights must be enabled (CloudWatch agent / ADOT
add-on on EKS; `containerInsights=enabled` on ECS clusters).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import MetricSeries

log = logging.getLogger(__name__)

CI_NAMESPACE = "ContainerInsights"          # EKS (EC2 + Fargate)
ECS_CI_NAMESPACE = "ECS/ContainerInsights"  # ECS (incl. Fargate)
ALB_NAMESPACE = "AWS/ApplicationELB"
NLB_NAMESPACE = "AWS/NetworkELB"

# dashboard metric name -> (CloudWatch metric, statistic)
ALB_METRICS = {
    "http_5xx": ("HTTPCode_Target_5XX_Count", "Sum"),
    "p95_latency_ms": ("TargetResponseTime", "p95"),      # seconds; converted to ms below
    "unhealthy_hosts": ("UnHealthyHostCount", "Maximum"),
    "rejected_conns": ("RejectedConnectionCount", "Sum"),
}
NLB_METRICS = {
    "unhealthy_hosts": ("UnHealthyHostCount", "Maximum"),
    "tcp_resets": ("TCP_Target_Reset_Count", "Sum"),
    "active_flows": ("ActiveFlowCount", "Average"),
}
NODE_METRICS = {"cpu_pct": "node_cpu_utilization", "mem_pct": "node_memory_utilization"}
POD_METRICS = {"cpu_pct": "pod_cpu_utilization_over_pod_limit",
               "mem_pct": "pod_memory_utilization_over_pod_limit",
               "restarts": "pod_number_of_container_restarts"}
ECS_SERVICE_METRICS = {"cpu_pct": "CpuUtilized", "mem_pct": "MemoryUtilized",
                       "running_tasks": "RunningTaskCount"}


class CloudWatchCollector:
    """Fetch evenly spaced series with GetMetricData (paginated, one query per call)."""

    def __init__(self, cloudwatch: Any, cluster_name: str, period_s: int = 60,
                 window: timedelta = timedelta(minutes=30)) -> None:
        self.cw = cloudwatch
        self.cluster = cluster_name
        self.period = period_s
        self.window = window

    def get_series(self, namespace: str, metric: str, dimensions: dict[str, str], stat: str,
                   name: str | None = None, unit: str = "", scale: float = 1.0,
                   end: datetime | None = None) -> MetricSeries:
        """One metric as a MetricSeries, oldest first; missing periods are filled with 0."""
        end = end or datetime.now(timezone.utc)
        start = end - self.window
        query = {"Id": "m0", "MetricStat": {
            "Metric": {"Namespace": namespace, "MetricName": metric,
                       "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()]},
            "Period": self.period, "Stat": stat}, "ReturnData": True}
        values: dict[datetime, float] = {}
        token = None
        while True:
            kwargs = {"MetricDataQueries": [query], "StartTime": start, "EndTime": end,
                      "ScanBy": "TimestampAscending"}
            if token:
                kwargs["NextToken"] = token
            resp = self.cw.get_metric_data(**kwargs)
            for r in resp.get("MetricDataResults", []):
                values.update(zip(r.get("Timestamps", []), r.get("Values", [])))
            token = resp.get("NextToken")
            if not token:
                break
        points = [round(values[t] * scale, 4) for t in sorted(values)]
        return MetricSeries(name=name or metric, unit=unit, points=points, step_s=self.period,
                            source=f"cloudwatch:{namespace}/{metric}")

    def alb_metrics(self, load_balancer: str, target_group: str | None = None) -> list[MetricSeries]:
        """ALB golden signals. load_balancer is the ARN suffix, e.g. 'app/prod-web/0123abcd'."""
        dims = {"LoadBalancer": load_balancer}
        if target_group:
            dims["TargetGroup"] = target_group
        units = {"http_5xx": "count/min", "p95_latency_ms": "ms", "unhealthy_hosts": "count",
                 "rejected_conns": "count/min"}
        return [self.get_series(ALB_NAMESPACE, m, dims if name != "rejected_conns" else {"LoadBalancer": load_balancer},
                                stat, name=name, unit=units[name],
                                scale=1000.0 if name == "p95_latency_ms" else 1.0)
                for name, (m, stat) in ALB_METRICS.items()]

    def nlb_metrics(self, load_balancer: str, target_group: str | None = None) -> list[MetricSeries]:
        dims = {"LoadBalancer": load_balancer, **({"TargetGroup": target_group} if target_group else {})}
        return [self.get_series(NLB_NAMESPACE, m, dims, stat, name=name)
                for name, (m, stat) in NLB_METRICS.items()]

    def node_metrics(self, node_name: str) -> list[MetricSeries]:
        """Container Insights node metrics (EC2 nodes only; Fargate has no node series)."""
        dims = {"ClusterName": self.cluster, "NodeName": node_name}
        return [self.get_series(CI_NAMESPACE, m, dims, "Average", name=name, unit="%")
                for name, m in NODE_METRICS.items()]

    def pod_metrics(self, namespace: str, pod: str) -> list[MetricSeries]:
        """Container Insights pod metrics; works for Fargate pods too (via the ADOT/CW agent)."""
        dims = {"ClusterName": self.cluster, "Namespace": namespace, "PodName": pod}
        return [self.get_series(CI_NAMESPACE, m, dims, "Average" if name != "restarts" else "Maximum",
                                name=name, unit="%" if name != "restarts" else "count")
                for name, m in POD_METRICS.items()]

    def ecs_service_metrics(self, ecs_cluster: str, service: str) -> list[MetricSeries]:
        """ECS Fargate service metrics from ECS Container Insights (no Kubernetes involved)."""
        dims = {"ClusterName": ecs_cluster, "ServiceName": service}
        return [self.get_series(ECS_CI_NAMESPACE, m, dims, "Average", name=name)
                for name, m in ECS_SERVICE_METRICS.items()]
