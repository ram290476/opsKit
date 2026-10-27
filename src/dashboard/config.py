"""Dashboard configuration: a JSON file plus DASHBOARD_* environment overrides (stdlib only).

No secrets live here. AWS credentials come from the normal boto3 chain, Kubernetes access from
in-cluster config or kubeconfig, and AMP signing from the AWS credential chain.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Threshold

PLATFORMS = ("eks", "eks-fargate", "ecs-fargate", "kind", "generic")
SOURCES = ("auto", "metrics-api", "prometheus", "demo")
DEFAULT_HOST = "0.0.0.0"                # serve on all interfaces (LAN viewing, e.g. Vision Pro Safari)
DEFAULT_PORT = 8090


@dataclass
class LoadBalancerRef:
    name: str
    arn_suffix: str                 # CloudWatch LoadBalancer dimension, e.g. app/prod-web/0123abcd
    kind: str = "ALB"               # ALB | NLB
    target_groups: list[str] = field(default_factory=list)


@dataclass
class DashboardConfig:
    cluster_name: str = ""                                       # "" -> kube context name, else "demo"
    kubeconfig: str | None = None                                # None -> $KUBECONFIG or ~/.kube/config
    kube_context: str | None = None                              # None -> kubeconfig current-context
    source: str = "auto"                                         # auto | metrics-api | prometheus | demo
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    refresh_seconds: int = 15                                    # sample + page auto-refresh interval
    region: str = "us-west-2"
    platform: str = "eks"
    namespaces: list[str] = field(default_factory=list)          # empty = all namespaces
    prometheus_url: str | None = None                            # Prometheus or AMP workspace URL
    use_container_insights: bool = True
    load_balancers: list[LoadBalancerRef] = field(default_factory=list)
    window_minutes: int = 30
    step_seconds: int = 60
    thresholds: dict[str, dict[str, Threshold]] = field(default_factory=dict)   # level -> metric -> bounds

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError(f"platform must be one of {PLATFORMS}, got {self.platform!r}")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        if not 0 <= int(self.port) <= 65535:
            raise ValueError(f"port out of range: {self.port}")
        self.port = int(self.port)
        if self.window_minutes * 60 < self.step_seconds * 6:
            raise ValueError("window must hold at least 6 steps for trends to mean anything")


def _thresholds(raw: dict[str, dict[str, Any]]) -> dict[str, dict[str, Threshold]]:
    return {level: {metric: Threshold(float(t["warn"]), float(t["critical"]),
                                      bool(t.get("higher_is_worse", True)))
                    for metric, t in metrics.items()}
            for level, metrics in raw.items()}


# config field -> environment variables, first match wins
ENV_VARS: dict[str, tuple[str, ...]] = {
    "kubeconfig": ("DASHBOARD_KUBECONFIG", "KUBECONFIG"),
    "kube_context": ("DASHBOARD_KUBE_CONTEXT", "KUBE_CONTEXT"),
    "cluster_name": ("DASHBOARD_CLUSTER", "CLUSTER_NAME"),
    "prometheus_url": ("PROMETHEUS_URL", "DASHBOARD_PROMETHEUS_URL"),
    "source": ("DASHBOARD_SOURCE",),
    "host": ("DASHBOARD_HOST",),
    "port": ("DASHBOARD_PORT",),
    "refresh_seconds": ("DASHBOARD_REFRESH_SECONDS",),
    "region": ("DASHBOARD_REGION", "AWS_REGION"),
    "platform": ("DASHBOARD_PLATFORM",),
}
_INT_FIELDS = {"port", "refresh_seconds", "window_minutes", "step_seconds"}


def load_config(path: str | Path | None = None, env: dict[str, str] | None = None,
                overrides: dict[str, Any] | None = None) -> DashboardConfig:
    """Precedence: CLI overrides > environment (ENV_VARS) > JSON file > defaults.

    `overrides` holds CLI flag values; None entries are ignored so unset flags fall through.
    """
    env = dict(os.environ) if env is None else env
    raw: dict[str, Any] = json.loads(Path(path).read_text()) if path else {}
    raw["load_balancers"] = [lb if isinstance(lb, LoadBalancerRef) else LoadBalancerRef(**lb)
                             for lb in raw.get("load_balancers", [])]
    raw["thresholds"] = _thresholds(raw.get("thresholds", {}))
    for key, names in ENV_VARS.items():
        value = next((env[n] for n in names if env.get(n)), None)
        if value is not None:
            raw[key] = value
    for key, value in (overrides or {}).items():
        if value is not None:
            raw[key] = value
    for key in _INT_FIELDS & raw.keys():
        raw[key] = int(raw[key])
    return DashboardConfig(**raw)
