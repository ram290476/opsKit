import json

import pytest

from dashboard.config import DEFAULT_HOST, DEFAULT_PORT, load_config


def test_defaults_serve_on_all_interfaces_8090():
    cfg = load_config(env={})
    assert (cfg.host, cfg.port) == (DEFAULT_HOST, DEFAULT_PORT) == ("0.0.0.0", 8090)
    assert cfg.source == "auto" and cfg.kube_context is None


def test_precedence_cli_over_env_over_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"cluster_name": "from-json", "port": 9000, "kube_context": "json-ctx"}))
    env = {"KUBE_CONTEXT": "kind-hcd", "DASHBOARD_PORT": "9100", "PROMETHEUS_URL": "http://localhost:9090",
           "KUBECONFIG": "/tmp/kc"}
    cfg = load_config(str(p), env=env, overrides={"port": 9200, "cluster_name": None})
    assert cfg.kube_context == "kind-hcd"          # env beats JSON
    assert cfg.port == 9200                        # CLI beats env
    assert cfg.cluster_name == "from-json"         # None override is ignored
    assert cfg.prometheus_url == "http://localhost:9090" and cfg.kubeconfig == "/tmp/kc"


def test_dashboard_prefixed_env_aliases():
    cfg = load_config(env={"DASHBOARD_KUBECONFIG": "/k", "DASHBOARD_KUBE_CONTEXT": "c", "DASHBOARD_CLUSTER": "x"})
    assert (cfg.kubeconfig, cfg.kube_context, cfg.cluster_name) == ("/k", "c", "x")


def test_invalid_values_rejected():
    with pytest.raises(ValueError):
        load_config(env={"DASHBOARD_SOURCE": "nope"})
    with pytest.raises(ValueError):
        load_config(env={"DASHBOARD_PORT": "70000"})
