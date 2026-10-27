from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from dashboard.collectors import CloudWatchCollector, K8sCollector, PrometheusCollector, parse_quantity
from dashboard.collectors.prometheus import PromQLError


def test_parse_quantity():
    assert parse_quantity("250m") == 0.25
    assert parse_quantity("1Gi") == 2**30
    assert parse_quantity("123456Ki") == 123456 * 1024
    assert parse_quantity("2") == 2.0 and parse_quantity(3) == 3.0


def test_k8s_node_status_and_metrics_api():
    core, custom = Mock(), Mock()
    cond = lambda t, s: NS(type=t, status=s)  # noqa: E731
    core.list_node.return_value = NS(items=[NS(
        metadata=NS(name="fargate-ip-1", labels={"eks.amazonaws.com/compute-type": "fargate"}),
        status=NS(conditions=[cond("Ready", "True"), cond("MemoryPressure", "True")], allocatable={"cpu": "2"}))])
    custom.list_cluster_custom_object.return_value = {"items": [
        {"metadata": {"name": "n1"}, "usage": {"cpu": "500m", "memory": "1Gi"}}]}
    k = K8sCollector(core, custom, request_timeout_s=5)
    [n] = k.node_status()
    assert n["ready"] and n["fargate"] and n["pressure"] == ["MemoryPressure"]
    assert k.node_usage() == {"n1": {"cpu_cores": 0.5, "mem_bytes": 2**30}}
    core.list_node.assert_called_once_with(_request_timeout=5)


def test_k8s_pod_health_reads_oomkilled():
    core = Mock()
    c = NS(name="app", ready=False, restart_count=3, state=NS(waiting=NS(reason="CrashLoopBackOff")),
           last_state=NS(terminated=NS(reason="OOMKilled")))
    core.list_namespaced_pod.return_value = NS(items=[NS(
        metadata=NS(namespace="shop", name="app-1"), spec=NS(node_name="n1"),
        status=NS(phase="Running", container_statuses=[c]))])
    [p] = K8sCollector(core).pod_health("shop")
    assert p["restarts"] == 3 and not p["ready"]
    assert p["containers"][0]["last_terminated"] == "OOMKilled"


def test_cloudwatch_paginates_and_scales():
    cw = Mock()
    t = [datetime(2026, 1, 1, 0, i, tzinfo=timezone.utc) for i in range(3)]
    cw.get_metric_data.side_effect = [
        {"MetricDataResults": [{"Timestamps": t[:2], "Values": [0.1, 0.2]}], "NextToken": "x"},
        {"MetricDataResults": [{"Timestamps": t[2:], "Values": [1.5]}]},
    ]
    s = CloudWatchCollector(cw, "prod").get_series("AWS/ApplicationELB", "TargetResponseTime",
                                                   {"LoadBalancer": "app/x/1"}, "p95", name="p95_latency_ms", scale=1000)
    assert s.points == [100.0, 200.0, 1500.0] and s.name == "p95_latency_ms"
    assert cw.get_metric_data.call_args_list[1].kwargs["NextToken"] == "x"


def test_prometheus_query_range_and_error():
    session = Mock()
    session.get.return_value.json.return_value = {"status": "success", "data": {"result": [
        {"metric": {"pod": "a"}, "values": [[1, "1"], [2, "NaN"], [3, "2.5"]]}]}}
    [s] = PrometheusCollector("http://prom:9090/", session=session).query_range("up", "up", end=100)
    assert s.points == [1.0, 0.0, 2.5] and s.source == "prometheus:pod=a"
    assert session.get.call_args.args[0] == "http://prom:9090/api/v1/query_range"
    session.get.return_value.json.return_value = {"status": "error", "error": "bad query"}
    with pytest.raises(PromQLError):
        PrometheusCollector("http://prom", session=session).query("up{")
