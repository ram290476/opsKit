"""Stdlib HTTP server for the flow view (no Flask/Streamlit dependency).

    GET /            interactive HTML (re-collected per request, or cached for --refresh seconds)
    GET /state.json  evaluated tree + origin as JSON (for scripts / other UIs)
    GET /text        terminal-style summary
    GET /healthz     200 "ok"

The server is read-only and has no authentication. Binding 0.0.0.0 exposes cluster names, pod
names and metrics to the whole network segment: use it on a trusted LAN only, or put it behind
an authenticating proxy.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .collectors.live import Snapshot
from .models import Threshold, TriageResult
from .render import render_html, render_text
from .triage import triage

log = logging.getLogger(__name__)


class SnapshotCache:
    """Calls `collect` at most once per `ttl_s` seconds (0 = every request)."""

    def __init__(self, collect: Callable[[], Snapshot], ttl_s: float = 0.0,
                 thresholds: dict[str, dict[str, Threshold]] | None = None) -> None:
        self.collect = collect
        self.ttl_s = ttl_s
        self.thresholds = thresholds
        self._lock = threading.Lock()
        self._at = 0.0
        self._value: tuple[Snapshot, TriageResult] | None = None

    def get(self) -> tuple[Snapshot, TriageResult]:
        with self._lock:
            if self._value is None or time.monotonic() - self._at >= self.ttl_s:
                snap = self.collect()
                self._value = (snap, triage(snap.tree, self.thresholds))
                self._at = time.monotonic()
            return self._value


def make_handler(cache: SnapshotCache, refresh_s: int = 0) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "opskit-dashboard/0.1"

        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                return self._send(200, "ok\n", "text/plain; charset=utf-8")
            if path not in ("/", "/index.html", "/state.json", "/text"):
                return self._send(404, "not found\n", "text/plain; charset=utf-8")
            try:
                snap, result = cache.get()
            except Exception as exc:                      # never leak a traceback to the browser
                log.exception("collect_failed")
                return self._send(500, f"collection failed: {exc}\n", "text/plain; charset=utf-8")
            if path == "/text":
                return self._send(200, (f"[{snap.banner}]\n" if snap.banner else "") + render_text(result),
                                  "text/plain; charset=utf-8")
            if path == "/state.json":
                body = {"source": snap.source, "banner": snap.banner, "health": result.root.health.value,
                        "origin": result.origin.id if result.origin else None,
                        "path": [e.id for e in result.path],
                        "entities": [{"id": e.id, "name": e.name, "level": e.level.value,
                                      "health": e.health.value, "own_health": e.own_health.value,
                                      "parent": e.parent_id} for e in result.root.walk()]}
                return self._send(200, json.dumps(body, indent=2), "application/json")
            page = render_html(result, banner=snap.banner, source=snap.source, auto_refresh_s=refresh_s)
            return self._send(200, page, "text/html; charset=utf-8")

        def log_message(self, fmt: str, *args) -> None:   # route access logs through logging
            log.info("http_request", extra={"client": self.client_address[0], "request": fmt % args})

    return Handler


def make_server(cache: SnapshotCache, host: str, port: int, refresh_s: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(cache, refresh_s))


def serve(cache: SnapshotCache, host: str, port: int, refresh_s: int = 0) -> None:
    """Blocking. Ctrl-C to stop."""
    httpd = make_server(cache, host, port, refresh_s)
    if host in ("0.0.0.0", "::"):
        log.warning("serving_on_all_interfaces", extra={"host": host, "port": port,
                                                       "note": "no auth; trusted networks only"})
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
