from types import SimpleNamespace
from unittest.mock import Mock

from opskit.k8s import get_pod_logs, list_events, list_namespaces, list_pods


def test_list_namespaces_returns_items_with_timeout():
    core = Mock()
    core.list_namespace.return_value = SimpleNamespace(items=["default"])

    assert list_namespaces(core) == ["default"]
    core.list_namespace.assert_called_once_with(_request_timeout=30)


def test_list_pods_supports_namespace_and_all_namespaces():
    core = Mock()
    core.list_namespaced_pod.return_value = SimpleNamespace(items=["pod"])
    core.list_pod_for_all_namespaces.return_value = SimpleNamespace(items=["all-pod"])

    assert list_pods(core, namespace="default", label_selector="app=api") == ["pod"]
    assert list_pods(core, label_selector="app=api", request_timeout_s=12) == ["all-pod"]
    core.list_namespaced_pod.assert_called_once_with(
        "default", label_selector="app=api", _request_timeout=30)
    core.list_pod_for_all_namespaces.assert_called_once_with(
        label_selector="app=api", _request_timeout=12)


def test_list_events_supports_namespace_and_all_namespaces():
    core = Mock()
    core.list_namespaced_event.return_value = SimpleNamespace(items=["event"])
    core.list_event_for_all_namespaces.return_value = SimpleNamespace(items=["all-event"])

    assert list_events(core, namespace="default", field_selector="type=Warning") == ["event"]
    assert list_events(core, field_selector="type=Warning") == ["all-event"]
    core.list_namespaced_event.assert_called_once_with(
        "default", field_selector="type=Warning", _request_timeout=30)
    core.list_event_for_all_namespaces.assert_called_once_with(
        field_selector="type=Warning", _request_timeout=30)


def test_get_pod_logs_passes_container_and_filter_options():
    core = Mock()
    core.read_namespaced_pod_log.return_value = "container output"

    result = get_pod_logs(
        core, "api-123", "default", container="api", tail_lines=100,
        since_seconds=300, timestamps=True, previous=True, request_timeout_s=15)

    assert result == "container output"
    core.read_namespaced_pod_log.assert_called_once_with(
        name="api-123",
        namespace="default",
        container="api",
        tail_lines=100,
        since_seconds=300,
        timestamps=True,
        previous=True,
        _request_timeout=15,
    )
