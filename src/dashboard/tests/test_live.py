from unittest import mock

from dashboard.collectors.live import (History, LiveDashboard, MetricsApiSource, PrometheusSource, Topology,
                                       build_tree, ctr_id, node_id, pod_id)
from dashboard.models import Health, Level, MetricSeries
from dashboard.triage import triage

GI = 1024 ** 3


def fake_k8s(oom=False, metrics_api=True, ping=True):
    k = mock.Mock()
    k.ping.return_value = ping
    k.metrics_api_available.return_value = metrics_api
    k.node_status.return_value = [
        {"name": "hcd-control-plane", "ready": True, "pressure": [], "fargate": False, "zone": "",
         "allocatable": {"cpu": "4", "memory": "8Gi"}},
        {"name": "hcd-worker", "ready": True, "pressure": ["MemoryPressure"] if oom else [], "fargate": False,
         "zone": "", "allocatable": {"cpu": "4", "memory": "8Gi"}},
    ]
    k.pod_health.return_value = [
        {"namespace": "shop", "name": "api-1", "node": "hcd-worker", "phase": "Running", "ready": not oom,
         "restarts": 4 if oom else 0,
         "containers": [{"name": "api", "ready": not oom, "restarts": 4 if oom else 0,
                         "waiting": "CrashLoopBackOff" if oom else None,
                         "last_terminated": "OOMKilled" if oom else None, "limits": {"cpu": 1.0, "memory": 1.0 * GI}}]},
        {"namespace": "kube-system", "name": "coredns-x", "node": "hcd-control-plane", "phase": "Running",
         "ready": True, "restarts": 0,
         "containers": [{"name": "coredns", "ready": True, "restarts": 0, "waiting": None, "last_terminated": None,
                         "limits": {"memory": 0.17 * GI}}]},
    ]
    k.services.return_value = [{"namespace": "shop", "name": "api", "type": "NodePort", "external": []}]
    k.endpoints_not_ready.return_value = {"shop/api": 1 if oom else 0}
    k.node_usage.return_value = {"hcd-control-plane": {"cpu_cores": 0.4, "mem_bytes": 2 * GI},
                                 "hcd-worker": {"cpu_cores": 3.8 if oom else 1.0, "mem_bytes": 7.6 * GI if oom else 3 * GI}}
    k.pod_usage.return_value = {"shop/api-1": {"api": {"cpu_cores": 0.5, "mem_bytes": 0.99 * GI if oom else 0.3 * GI}},
                                "kube-system/coredns-x": {"coredns": {"cpu_cores": 0.01, "mem_bytes": 0.02 * GI}}}
    return k


def test_metrics_api_source_computes_percentages():
    k = fake_k8s()
    topo = Topology.collect(k, "kind-hcd")
    s = MetricsApiSource(k).sample(topo)
    assert s[node_id("hcd-worker")]["cpu_pct"] == 25.0
    assert s[ctr_id("shop", "api-1", "api")]["mem_pct"] == 30.0
    assert s[pod_id("shop", "api-1")]["cpu_pct"] == 50.0
    assert s["cluster-kind-hcd"]["mem_pct"] == round(100 * 5 / 16, 2)


def test_tree_has_six_levels_and_pods_under_their_node():
    k = fake_k8s()
    topo = Topology.collect(k, "kind-hcd")
    h = History()
    h.add(topo.status_sample())
    root = build_tree(topo, h, source="metrics-api")
    levels = {e.level for e in root.walk()}
    assert levels == set(Level)
    worker = next(e for e in root.walk() if e.id == node_id("hcd-worker"))
    assert [p.name for p in worker.children] == ["api-1"]


def test_live_oom_incident_origin_is_the_container():
    live = LiveDashboard("kind-hcd", lambda: fake_k8s(oom=True))
    snap = live.collect()
    assert snap.source == "metrics-api" and not snap.banner
    result = triage(snap.tree)
    assert result.root.health == Health.CRITICAL
    assert result.origin.id == ctr_id("shop", "api-1", "api")


def test_history_accumulates_and_restarts_are_windowed():
    k = fake_k8s()
    live = LiveDashboard("kind-hcd", lambda: k)
    live.collect()
    k.pod_health.return_value[0]["containers"][0]["restarts"] = 2
    k.pod_health.return_value[0]["restarts"] = 2
    snap = live.collect()
    ctr = next(e for e in snap.tree.walk() if e.id == ctr_id("shop", "api-1", "api"))
    restarts = next(s for s in ctr.series if s.name == "restarts")
    assert restarts.points == [0.0, 2.0]
    assert len(next(s for s in ctr.series if s.name == "mem_pct").points) == 2


def test_falls_back_to_demo_with_banner_when_kube_unreachable():
    snap = LiveDashboard("kind-hcd", lambda: fake_k8s(ping=False)).collect()
    assert snap.source == "demo" and "unreachable" in snap.banner


def test_falls_back_when_kubeconfig_cannot_load():
    def boom():
        raise RuntimeError("context kind-hcd not found")
    snap = LiveDashboard("kind-hcd", boom).collect()
    assert snap.source == "demo" and "kind-hcd not found" in snap.banner


def test_falls_back_when_no_metrics_backend():
    snap = LiveDashboard("kind-hcd", lambda: fake_k8s(metrics_api=False)).collect()
    assert snap.source == "demo" and "metrics.k8s.io" in snap.banner


def test_collection_error_degrades_then_reprobes():
    k = fake_k8s()
    live = LiveDashboard("kind-hcd", lambda: k)
    assert live.collect().source == "metrics-api"
    k.node_status.side_effect = RuntimeError("apiserver gone")
    assert live.collect().source == "demo"
    k.node_status.side_effect = None
    assert live.collect().source == "metrics-api"


def test_prometheus_preferred_when_ready_and_maps_series():
    prom = mock.Mock()
    prom.ready.return_value = True

    def qr(promql, name, **kw):
        if name == "container_mem_pct":
            return [MetricSeries(name, "", [40.0] * 20 + [97.0] * 10,
                                 source="prometheus:container=api,namespace=shop,pod=api-1")]
        if name == "node_cpu_pct":
            return [MetricSeries(name, "", [30.0] * 30, source="prometheus:node=hcd-worker")]
        raise RuntimeError("no such metric")
    prom.query_range.side_effect = qr
    live = LiveDashboard("kind-hcd", lambda: fake_k8s(), prom_factory=lambda: prom)
    snap = live.collect()
    assert snap.source == "prometheus"
    ctr = next(e for e in snap.tree.walk() if e.id == ctr_id("shop", "api-1", "api"))
    assert next(s for s in ctr.series if s.name == "mem_pct").points[-1] == 97.0
    assert isinstance(live.source, PrometheusSource)


def test_prometheus_down_falls_back_to_metrics_api():
    prom = mock.Mock()
    prom.ready.return_value = False
    live = LiveDashboard("kind-hcd", lambda: fake_k8s(), prom_factory=lambda: prom)
    assert live.collect().source == "metrics-api"


def test_demo_source_forced():
    snap = LiveDashboard("x", None, preferred="demo").collect()
    assert snap.source == "demo" and snap.banner
