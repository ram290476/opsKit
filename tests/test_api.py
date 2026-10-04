from fastapi.testclient import TestClient

from opskit import api


def test_aws_inventory_endpoint_delegates_to_inventory_collection(monkeypatch):
    expected = {"account_id": "123456789012", "resources": [], "errors": {}}
    calls = []

    def collect_account_inventory(profile_name, regions):
        calls.append((profile_name, regions))
        return expected

    monkeypatch.setattr(api, "collect_account_inventory", collect_account_inventory)

    response = api.aws_inventory(api.InventoryRequest(
        profile_name="personal", regions=["us-east-1"]))

    assert response == expected
    assert calls == [("personal", ["us-east-1"])]


def test_aws_inventory_rest_route_returns_inventory(monkeypatch):
    expected = {"account_id": "123456789012", "resources": [], "errors": {}}
    monkeypatch.setattr(api, "collect_account_inventory", lambda **kwargs: expected)

    response = TestClient(api.app).post(
        "/aws/inventory",
        json={"profile_name": "personal", "regions": ["us-east-1"]},
    )

    assert response.status_code == 200
    assert response.json() == expected


def test_aws_insights_endpoint_combines_resource_insight_operations(monkeypatch):
    resource = {"arn": "arn:one"}
    session = object()
    calls = []

    monkeypatch.setattr(api, "create_session", lambda profile_name: session)
    monkeypatch.setattr(
        api, "get_resource_health",
        lambda value, actual_session:
        calls.append(("health", value, actual_session)) or {"status": "healthy"},
    )
    monkeypatch.setattr(
        api, "get_child_resource_type_counts",
        lambda value, actual_session:
        calls.append(("children", value, actual_session)) or {"supported": True},
    )
    monkeypatch.setattr(
        api, "get_basic_resource_metrics",
        lambda value, actual_session, **kwargs:
        calls.append(("metrics", value, actual_session, kwargs)) or {"supported": True},
    )

    response = api.aws_insights(api.InsightsRequest(
        resources=[resource], profile_name="personal",
        lookback_hours=12, period_seconds=300))

    assert response == [{
        "resource": resource,
        "health": {"status": "healthy"},
        "children": {"supported": True},
        "metrics": {"supported": True},
    }]
    assert [call[0] for call in calls] == ["health", "children", "metrics"]
    assert calls[-1] == (
        "metrics", resource, session,
        {"lookback_hours": 12, "period_seconds": 300},
    )


def test_kubernetes_namespace_rest_route_returns_serialized_items(monkeypatch):
    from opskit import k8s

    core = object()
    monkeypatch.setattr(api, "_kubernetes_clients", lambda: (core, None))
    monkeypatch.setattr(api, "_serialize_kubernetes", lambda items: items)
    monkeypatch.setattr(k8s, "list_namespaces", lambda actual_core: ["default"])

    response = TestClient(api.app).get("/kubernetes/namespaces")

    assert response.status_code == 200
    assert response.json() == ["default"]


def test_api_exposes_all_kubernetes_operations():
    routes = {
        (route.path, method)
        for route in api.app.routes
        for method in getattr(route, "methods", set())
    }

    assert {
        ("/kubernetes/namespaces", "GET"),
        ("/kubernetes/pods", "GET"),
        ("/kubernetes/events", "GET"),
        ("/kubernetes/pods/unhealthy", "GET"),
        ("/kubernetes/pods/{namespace}/{name}/logs", "GET"),
        ("/kubernetes/deployments/{namespace}/{name}/rollout", "GET"),
        ("/kubernetes/deployments/{namespace}/{name}/restart", "POST"),
    } <= routes
