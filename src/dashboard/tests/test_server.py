import json
import threading
import urllib.request

from dashboard.collectors.live import Snapshot
from dashboard.demo import demo_tree
from dashboard.server import SnapshotCache, make_server


def _run(cache, refresh_s=0):
    httpd = make_server(cache, "127.0.0.1", 0, refresh_s)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode()


def test_serves_html_with_demo_banner_and_endpoints():
    calls = []

    def collect():
        calls.append(1)
        return Snapshot(demo_tree(), "demo", "DEMO DATA - kube API unreachable")
    httpd, base = _run(SnapshotCache(collect, ttl_s=0), refresh_s=15)
    try:
        code, page = _get(base + "/")
        assert code == 200 and 'id="banner"' in page and "kube API unreachable" in page
        assert 'id="node-ctr-checkout-7d9f-x2k-checkout"' in page and "location.reload" in page
        state = json.loads(_get(base + "/state.json")[1])
        assert state["origin"] == "ctr-checkout-7d9f-x2k-checkout" and state["source"] == "demo"
        assert _get(base + "/healthz") == (200, "ok\n")
        assert "ROOT CAUSE" in _get(base + "/text")[1]
        assert len(calls) == 3                     # ttl 0 -> re-collected per request (healthz excluded)
        try:
            urllib.request.urlopen(base + "/nope", timeout=5)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_cache_ttl_limits_collection():
    calls = []

    def collect():
        calls.append(1)
        return Snapshot(demo_tree(), "metrics-api")
    cache = SnapshotCache(collect, ttl_s=3600)
    cache.get()
    cache.get()
    assert len(calls) == 1


def test_live_page_has_no_banner():
    httpd, base = _run(SnapshotCache(lambda: Snapshot(demo_tree(), "metrics-api"), ttl_s=0))
    try:
        page = _get(base + "/")[1]
        assert 'id="banner"' not in page and "source: metrics-api" in page and "location.reload" not in page
    finally:
        httpd.shutdown()
        httpd.server_close()
