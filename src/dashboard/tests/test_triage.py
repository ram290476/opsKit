from dashboard.demo import demo_tree
from dashboard.models import Entity, Health, Level, MetricSeries
from dashboard.triage import find_origin, path_to, triage


def s(name, points):
    return MetricSeries(name=name, unit="", points=[float(p) for p in points])


def chain(pod_restarts, ctr_oom, lb_5xx):
    ctr = Entity("ctr", "app", Level.CONTAINER, [s("oom_kills", ctr_oom)])
    pod = Entity("pod", "app-1", Level.POD, [s("restarts", pod_restarts)], [ctr])
    healthy_pod = Entity("pod-ok", "app-2", Level.POD, [s("restarts", [0] * 6)])
    node = Entity("node", "n1", Level.NODE, [s("cpu_pct", [40] * 6)], [pod, healthy_pod])
    net = Entity("net", "tg", Level.NETWORK, [s("dns_errors", [0] * 6)], [node])
    lb = Entity("lb", "alb", Level.LOAD_BALANCER, [s("http_5xx", lb_5xx)], [net])
    return Entity("cluster", "c", Level.CLUSTER, [s("error_rate_pct", [0.1] * 6)], [lb])


def test_origin_is_earliest_onset_and_path_runs_from_cluster():
    root = chain(pod_restarts=[0, 0, 0, 1, 2, 3], ctr_oom=[0, 0, 1, 1, 2, 3], lb_5xx=[0, 0, 0, 0, 60, 80])
    r = triage(root)
    assert r.origin.id == "ctr"
    assert [e.id for e in r.path] == ["cluster", "lb", "net", "node", "pod", "ctr"]
    assert [e.id for _, e in r.timeline] == ["ctr", "pod", "lb"]


def test_tie_on_onset_goes_to_deepest_level():
    root = chain(pod_restarts=[0, 0, 1, 1, 2, 3], ctr_oom=[0, 0, 1, 1, 2, 3], lb_5xx=[0, 0, 0, 0, 0, 0])
    assert triage(root).origin.id == "ctr"


def test_symptom_that_starts_first_wins_over_deeper_late_anomaly():
    root = chain(pod_restarts=[0] * 6, ctr_oom=[0, 0, 0, 0, 0, 1], lb_5xx=[0, 60, 80, 90, 90, 90])
    assert triage(root).origin.id == "lb"


def test_health_rolls_up_and_healthy_tree_has_no_origin():
    r = triage(chain([0] * 6, [0] * 6, [0] * 6))
    assert r.origin is None and r.path == [] and r.root.health == Health.OK
    r = triage(chain([0] * 6, [0, 0, 0, 0, 1, 1], [0] * 6))
    by_id = r.by_id()
    assert by_id["cluster"].own_health == Health.OK and by_id["cluster"].health == Health.CRITICAL
    assert by_id["pod-ok"].health == Health.OK and by_id["pod"].parent_id == "node"


def test_path_to_missing_id_is_empty():
    assert path_to(chain([0] * 6, [0] * 6, [0] * 6), "nope") == []


def test_demo_incident_origin_is_the_oomkilled_container():
    r = triage(demo_tree())
    assert r.origin.id == "ctr-checkout-7d9f-x2k-checkout"
    assert [e.level for e in r.path] == list(Level)
    assert r.root.health == Health.CRITICAL
    healthy = r.by_id()["lb-nlb-internal-grpc"]
    assert healthy.health == Health.OK and find_origin(healthy) is None
