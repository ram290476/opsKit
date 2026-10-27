"""Seeded sample data: a realistic 30-minute incident on an EKS cluster, no cloud access needed.

Story (minute = point index, 1-minute step):
  t=9   checkout-api container in pod checkout-7d9f-x2k leaks memory past 85% of its limit
  t=12  container OOMKilled -> pod restarts, endpoint drops out of target group tg-checkout
  t=13  node ip-10-0-2-17 memory climbs, MemoryPressure condition from t=16
  t=13  ALB alb-prod-web target 5xx and p95 latency spike
  t=14  cluster-wide error rate crosses 1%
Expected root-cause origin: the checkout-api container. Everything else is a symptom.
"""
from __future__ import annotations

import random

from .models import Entity, Level, MetricSeries

WINDOW = 30
STEP_S = 60


class _Gen:
    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)

    def flat(self, base: float, jitter: float, lo: float = 0.0) -> list[float]:
        return [round(max(lo, base + self.rng.uniform(-jitter, jitter)), 2) for _ in range(WINDOW)]

    def step(self, before: float, after: float, at: int, jitter: float = 0.0) -> list[float]:
        return [round(max(0.0, (after if i >= at else before) + self.rng.uniform(-jitter, jitter)), 2)
                for i in range(WINDOW)]

    def ramp(self, base: float, peak: float, start: int, end: int, jitter: float = 0.0,
             after: float | None = None) -> list[float]:
        """Flat at base, linear climb from start to end, then hold peak (or `after`)."""
        out = []
        for i in range(WINDOW):
            if i < start:
                v = base
            elif i <= end:
                v = base + (peak - base) * (i - start) / max(1, end - start)
            else:
                v = peak if after is None else after
            out.append(round(max(0.0, v + self.rng.uniform(-jitter, jitter)), 2))
        return out

    @staticmethod
    def counter(at: list[int]) -> list[float]:
        """Cumulative count in the window, incremented at each index in `at`."""
        return [float(sum(1 for a in at if i >= a)) for i in range(WINDOW)]


def _s(name: str, unit: str, points: list[float], source: str) -> MetricSeries:
    return MetricSeries(name=name, unit=unit, points=points, step_s=STEP_S, source=source)


def _container(g: _Gen, pod: str, name: str, *, leak: bool = False) -> Entity:
    if leak:
        mem = g.ramp(58, 97, 4, 11, 1.0)
        for i in (12, 19, 25):          # usage drops after each OOMKill restart, then climbs again
            mem[i] = 40.0
        for i in range(13, WINDOW):
            if i not in (19, 25) and mem[i] != 40.0:
                mem[i] = round(min(98.0, mem[i - 1] + 9.0), 2)
        series = [
            _s("mem_pct", "%", mem, "demo"),
            _s("cpu_throttle_pct", "%", g.ramp(5, 22, 8, 14, 2.0), "demo"),
            _s("oom_kills", "count", g.counter([12, 19, 25]), "demo"),
            _s("restarts", "count", g.counter([12, 19, 25]), "demo"),
        ]
    else:
        series = [
            _s("mem_pct", "%", g.flat(42, 3), "demo"),
            _s("cpu_throttle_pct", "%", g.flat(4, 2), "demo"),
            _s("oom_kills", "count", [0.0] * WINDOW, "demo"),
            _s("restarts", "count", [0.0] * WINDOW, "demo"),
        ]
    return Entity(id=f"ctr-{pod}-{name}", name=name, level=Level.CONTAINER, series=series,
                  attrs={"image": f"123456789012.dkr.ecr.us-west-2.amazonaws.com/{name}:1.42.0"
                         if name != "aws-otel-collector" else "public.ecr.aws/aws-observability/aws-otel-collector:v0.40",
                         "last_state": "OOMKilled (exit 137)" if leak else "-"})


def _pod(g: _Gen, name: str, app: str, *, bad: bool = False, node: str = "") -> Entity:
    if bad:
        series = [
            _s("restarts", "count", g.counter([12, 19, 25]), "demo"),
            _s("error_rate_pct", "%", g.ramp(0.3, 14, 11, 13, 0.4), "demo"),
            _s("p95_latency_ms", "ms", g.ramp(120, 1400, 11, 13, 40), "demo"),
            _s("cpu_pct", "%", g.ramp(35, 62, 9, 14, 3), "demo"),
        ]
    else:
        series = [
            _s("restarts", "count", [0.0] * WINDOW, "demo"),
            _s("error_rate_pct", "%", g.flat(0.3, 0.2), "demo"),
            _s("p95_latency_ms", "ms", g.flat(130, 20), "demo"),
            _s("cpu_pct", "%", g.flat(38, 5), "demo"),
        ]
    containers = [_container(g, name, app, leak=bad), _container(g, name, "aws-otel-collector")]
    return Entity(id=f"pod-{name}", name=name, level=Level.POD, series=series, children=containers,
                  attrs={"namespace": "shop", "app": app, "node": node,
                         "status": "CrashLoopBackOff" if bad else "Running"})


def _node(g: _Gen, name: str, pods: list[Entity], *, bad: bool = False, fargate: bool = False) -> Entity:
    if bad:
        series = [
            _s("cpu_pct", "%", g.ramp(48, 71, 10, 15, 3), "demo"),
            _s("mem_pct", "%", g.ramp(66, 91, 9, 16, 1.5), "demo"),
            _s("pressure", "count", g.step(0, 1, 16), "demo"),
            _s("evictions", "count", g.counter([18, 24]), "demo"),
        ]
    else:
        series = [
            _s("cpu_pct", "%", g.flat(41, 6), "demo"),
            _s("mem_pct", "%", g.flat(55, 4), "demo"),
            _s("pressure", "count", [0.0] * WINDOW, "demo"),
            _s("evictions", "count", [0.0] * WINDOW, "demo"),
        ]
    if fargate:     # Fargate: no kubelet/node metrics; pressure + evictions are not observable
        series = [s for s in series if s.name in ("cpu_pct", "mem_pct")]
    return Entity(id=f"node-{name}", name=name, level=Level.NODE, series=series, children=pods,
                  attrs={"compute": "fargate" if fargate else "managed node group (m6i.xlarge)",
                         "az": "us-west-2b" if bad else "us-west-2a"})


def _network(g: _Gen, name: str, nodes: list[Entity], *, bad: bool = False) -> Entity:
    series = [
        _s("tcp_retransmit_pct", "%", g.ramp(0.2, 1.6, 12, 15, 0.1) if bad else g.flat(0.2, 0.1), "demo"),
        _s("dns_errors", "count/min", g.flat(0.2, 0.2), "demo"),
        _s("endpoints_not_ready", "count", g.step(0, 1, 12) if bad else [0.0] * WINDOW, "demo"),
        _s("rx_drops", "pkts/s", g.flat(0.1, 0.1), "demo"),
    ]
    return Entity(id=f"net-{name}", name=name, level=Level.NETWORK, series=series, children=nodes,
                  attrs={"kind": "target group + Service endpoints", "vpc_cni": "aws-node"})


def _lb(g: _Gen, name: str, networks: list[Entity], *, bad: bool = False, kind: str = "ALB") -> Entity:
    if bad:
        series = [
            _s("http_5xx", "count/min", g.ramp(0, 140, 12, 14, 4), "demo"),
            _s("p95_latency_ms", "ms", g.ramp(140, 1600, 12, 14, 50), "demo"),
            _s("unhealthy_hosts", "count", g.step(0, 1, 12), "demo"),
            _s("rejected_conns", "count/min", [0.0] * WINDOW, "demo"),
        ]
    else:
        series = [
            _s("http_5xx", "count/min", g.flat(0.5, 0.5), "demo"),
            _s("p95_latency_ms", "ms", g.flat(35, 6), "demo"),
            _s("unhealthy_hosts", "count", [0.0] * WINDOW, "demo"),
            _s("rejected_conns", "count/min", [0.0] * WINDOW, "demo"),
        ]
    return Entity(id=f"lb-{name}", name=name, level=Level.LOAD_BALANCER, series=series,
                  children=networks, attrs={"type": kind, "scheme": "internet-facing" if kind == "ALB" else "internal"})


def demo_tree(seed: int = 7) -> Entity:
    """Build the sample cluster tree with the incident baked in (deterministic for a given seed)."""
    g = _Gen(seed)
    bad_pod = _pod(g, "checkout-7d9f-x2k", "checkout", bad=True, node="ip-10-0-2-17")
    ok_pod = _pod(g, "checkout-7d9f-p8m", "checkout", node="ip-10-0-1-42")
    cart_pod = _pod(g, "cart-5c4b-q7w", "cart", node="ip-10-0-1-42")
    catalog_pod = _pod(g, "catalog-6f8d-z1n", "catalog", node="fargate-ip-10-0-3-88")
    grpc_pod = _pod(g, "inventory-grpc-9a2c-k4t", "inventory-grpc", node="ip-10-0-1-55")

    lb_web = _lb(g, "alb-prod-web", [
        _network(g, "tg-checkout-usw2b", [_node(g, "ip-10-0-2-17", [bad_pod], bad=True)], bad=True),
        _network(g, "tg-checkout-usw2a", [_node(g, "ip-10-0-1-42", [ok_pod, cart_pod])]),
        _network(g, "tg-catalog-fargate", [_node(g, "fargate-ip-10-0-3-88", [catalog_pod], fargate=True)]),
    ], bad=True)
    lb_grpc = _lb(g, "nlb-internal-grpc", [
        _network(g, "tg-inventory-grpc", [_node(g, "ip-10-0-1-55", [grpc_pod])]),
    ], kind="NLB")

    cluster_series = [
        _s("error_rate_pct", "%", g.ramp(0.2, 4.2, 12, 15, 0.15), "demo"),
        _s("p95_latency_ms", "ms", g.ramp(130, 640, 12, 15, 25), "demo"),
        _s("pods_not_ready", "count", g.step(0, 1, 12), "demo"),
        _s("nodes_not_ready", "count", [0.0] * WINDOW, "demo"),
        _s("cpu_pct", "%", g.ramp(44, 52, 10, 16, 2), "demo"),
        _s("mem_pct", "%", g.ramp(58, 66, 9, 16, 1), "demo"),
    ]
    return Entity(id="cluster-prod-eks-usw2", name="prod-eks-usw2", level=Level.CLUSTER,
                  series=cluster_series, children=[lb_web, lb_grpc],
                  attrs={"platform": "EKS 1.30 + Fargate profile", "region": "us-west-2"})
