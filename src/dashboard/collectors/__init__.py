"""Data collectors. Each takes an injected client so tests can pass a Mock and nothing
heavy (boto3, kubernetes, requests) is imported until a real client is built."""
from .cloudwatch import CloudWatchCollector
from .k8s import K8sCollector, parse_quantity
from .live import LiveDashboard, Snapshot
from .prometheus import PrometheusCollector

__all__ = ["CloudWatchCollector", "K8sCollector", "LiveDashboard", "PrometheusCollector", "Snapshot", "parse_quantity"]
