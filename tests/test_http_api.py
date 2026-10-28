import json
from pathlib import Path

import pytest
import requests
import responses

from opskit.http_api import IDEMPOTENT_METHODS, ApiClient, ApiError, BearerAuth, HeaderAuth


BASE = "https://api.test/root"


def _client(**kwargs) -> ApiClient:
    kwargs.setdefault("sleep", lambda _delay: None)
    return ApiClient(BASE, **kwargs)


@responses.activate
def test_get_json_joins_base_url_and_sends_auth_headers():
    seen = {}

    def callback(request):
        seen["url"] = request.url
        seen["auth"] = request.headers["Authorization"]
        seen["key"] = request.headers["X-Api-Key"]
        seen["agent"] = request.headers["User-Agent"]
        return (200, {"Content-Type": "application/json"}, json.dumps({"ok": True}))

    responses.add_callback(responses.GET, f"{BASE}/v1/items", callback=callback)
    auth = BearerAuth("one")
    with _client(auth=auth, headers={"X-Api-Key": "k"}) as client:
        assert client.get_json("/v1/items") == {"ok": True}
        auth.token = "two"
        responses.add_callback(responses.GET, f"{BASE}/v1/items", callback=callback)
        assert client.get_json("v1/items") == {"ok": True}
    assert seen["url"] == f"{BASE}/v1/items"
    assert seen["auth"] == "Bearer two"
    assert seen["key"] == "k"
    assert seen["agent"].startswith("opskit/")
    assert "POST" not in IDEMPOTENT_METHODS


@responses.activate
def test_header_auth_and_basic_auth():
    def callback(request):
        assert request.headers["X-Token"] == "secret"
        return (200, {"Content-Type": "application/json"}, "{}")

    responses.add_callback(responses.GET, f"{BASE}/auth", callback=callback)
    assert _client(auth=HeaderAuth({"X-Token": "secret"})).get_json("/auth") == {}
    assert _client(auth={"X-Token": "secret"}).get_json("/auth") == {}

    def basic(request):
        assert request.headers["Authorization"].startswith("Basic ")
        return (204, {}, b"")

    responses.add_callback(responses.DELETE, f"{BASE}/auth", callback=basic)
    from requests.auth import HTTPBasicAuth

    assert _client(auth=HTTPBasicAuth("user", "pw")).delete_json("/auth") is None


@responses.activate
def test_retries_transient_status_and_connection_errors_only_for_safe_methods():
    sleeps: list[float] = []
    calls = {"get": 0, "post": 0, "put": 0}

    def get_callback(_request):
        calls["get"] += 1
        if calls["get"] < 3:
            return (503, {}, "later")
        return (200, {"Content-Type": "application/json"}, '{"ok": true}')

    def post_callback(_request):
        calls["post"] += 1
        return (503, {}, "no")

    def put_callback(_request):
        calls["put"] += 1
        if calls["put"] == 1:
            raise requests.ConnectionError("reset")
        return (200, {"Content-Type": "application/json"}, '{"saved": 1}')

    responses.add_callback(responses.GET, f"{BASE}/v", callback=get_callback)
    responses.add_callback(responses.POST, f"{BASE}/v", callback=post_callback)
    responses.add_callback(responses.PUT, f"{BASE}/v", callback=put_callback)
    client = _client(sleep=sleeps.append, attempts=4)
    assert client.get_json("/v") == {"ok": True}
    assert calls["get"] == 3
    assert sleeps
    with pytest.raises(ApiError) as post_error:
        client.post_json("/v", {"a": 1})
    assert post_error.value.status_code == 503
    assert calls["post"] == 1
    assert client.put_json("/v", {"a": 1}) == {"saved": 1}
    assert calls["put"] == 2


@responses.activate
def test_post_retries_when_opted_in_and_404_does_not():
    calls = {"n": 0}

    def callback(_request):
        calls["n"] += 1
        if calls["n"] == 1:
            return (503, {"Content-Type": "application/json"}, '{"err": "later"}')
        return (200, {"Content-Type": "application/json"}, '{"ok": true}')

    responses.add_callback(responses.POST, f"{BASE}/v", callback=callback)
    client = _client(retry_methods={"POST"})
    assert client.post_json("/v", {"a": 1}) == {"ok": True}
    assert calls["n"] == 2

    def missing(_request):
        calls["missing"] = calls.get("missing", 0) + 1
        return (404, {"Content-Type": "application/json"}, '{"err": "gone"}')

    responses.add_callback(responses.GET, f"{BASE}/missing", callback=missing)
    sleeps: list[float] = []
    with pytest.raises(ApiError) as exc:
        _client(sleep=sleeps.append).get_json("/missing")
    assert exc.value.status_code == 404
    assert exc.value.body == {"err": "gone"}
    assert calls["missing"] == 1
    assert sleeps == []


@responses.activate
def test_pagination_follows_url_cursor_and_link_header():
    responses.add(responses.GET, f"{BASE}/items", json={"items": [1], "next": f"{BASE}/items?page=2"})
    responses.add(responses.GET, f"{BASE}/items?page=2", json={"items": [2], "next": None})
    assert list(_client().paginate("/items", items_key="items")) == [1, 2]

    responses.add(responses.GET, f"{BASE}/cursor", json={"data": [{"id": 1}], "next_cursor": "abc"})
    responses.add(
        responses.GET,
        f"{BASE}/cursor?cursor=abc",
        json={"data": [{"id": 2}], "next_cursor": None},
    )
    pages = list(_client().paginate("/cursor", items_key="data", cursor_key="next_cursor"))
    assert pages == [{"id": 1}, {"id": 2}]

    responses.add(
        responses.GET,
        f"{BASE}/link",
        json={"items": [1]},
        headers={"Link": f'<{BASE}/link?page=2>; rel="next"'},
    )
    responses.add(responses.GET, f"{BASE}/link?page=2", json={"items": [2]})
    assert list(_client().paginate("/link", items_key="items", max_pages=1)) == [1]
    assert list(_client().paginate("/link", items_key="items")) == [1, 2]


@responses.activate
def test_download_and_iter_bytes_stream_chunks(tmp_path: Path):
    payload = b"abcdefghij" * 50
    calls = {"n": 0}

    def callback(_request):
        calls["n"] += 1
        if calls["n"] == 1:
            return (503, {}, "later")
        return (200, {}, payload)

    responses.add_callback(responses.GET, f"{BASE}/file", callback=callback)
    dest = tmp_path / "out" / "file.bin"
    client = _client()
    assert client.download("/file", dest, chunk_size=16) == len(payload)
    assert dest.read_bytes() == payload
    assert calls["n"] == 2
    assert not dest.with_name("file.bin.partial").exists()

    responses.add(responses.GET, f"{BASE}/file", body=payload)
    assert b"".join(client.iter_bytes("/file", chunk_size=16)) == payload


@responses.activate
def test_upload_streams_raw_put_and_multipart_post(tmp_path: Path):
    source = tmp_path / "payload.txt"
    source.write_bytes(b"hello-stream")
    captured = {}

    def raw(request):
        captured["raw"] = request.body
        captured["raw_type"] = request.headers["Content-Type"]
        if captured.get("raw_calls", 0) == 0:
            captured["raw_calls"] = 1
            return (503, {}, "later")
        return (201, {"Content-Type": "application/json"}, '{"stored": true}')

    def form(request):
        captured["form_type"] = request.headers["Content-Type"]
        captured["form"] = request.body if isinstance(request.body, bytes) else request.body.read()
        return (201, {"Content-Type": "application/json"}, '{"stored": true}')

    responses.add_callback(responses.PUT, f"{BASE}/objects/payload.txt", callback=raw)
    responses.add_callback(responses.POST, f"{BASE}/objects", callback=form)
    client = _client()
    assert client.upload("/objects/payload.txt", source, raw=True) == {"stored": True}
    assert captured["raw"] == b"hello-stream"
    assert captured["raw_type"] == "application/octet-stream"
    assert captured["raw_calls"] == 1
    assert client.upload("/objects", source, filename="payload.txt") == {"stored": True}
    assert captured["form_type"].startswith("multipart/form-data")
    assert b"hello-stream" in captured["form"]
