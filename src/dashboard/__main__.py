"""CLI for the Kubernetes triage dashboard.

    python -m dashboard demo  [--html out.html] [--mermaid]       seeded incident, no cluster
    python -m dashboard live  [--context kind-hcd] [--html out.html]  one-shot from a real cluster
    python -m dashboard serve [--host 0.0.0.0] [--port 8090] [--refresh 15]  HTTP flow view

Settings come from (highest first) flags, environment (KUBECONFIG, KUBE_CONTEXT,
DASHBOARD_CLUSTER, PROMETHEUS_URL, DASHBOARD_*), the --config JSON file, then defaults.
Exit codes (demo/live) follow opskit.checks: 0 healthy, 1 warn/critical, 2 internal error.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.collectors.k8s import K8sCollector
from dashboard.collectors.live import LiveDashboard, Snapshot
from dashboard.collectors.prometheus import PrometheusCollector
from dashboard.config import SOURCES, DashboardConfig, load_config
from dashboard.demo import demo_tree
from dashboard.models import Health
from dashboard.render import mermaid_incident, mermaid_workflow, render_html, render_text
from dashboard.triage import triage

log = logging.getLogger("dashboard")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m dashboard", description="Kubernetes triage dashboard",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("command", nargs="?", choices=("demo", "live", "serve"), default="serve",
                   help="default: serve")
    p.add_argument("--config", help="JSON config file (see sample_config.json)")
    p.add_argument("--kubeconfig", help="kubeconfig path (env KUBECONFIG; default ~/.kube/config)")
    p.add_argument("--context", dest="kube_context", help="kube context (env KUBE_CONTEXT; default current-context)")
    p.add_argument("--cluster-name", help="label shown on the page (env DASHBOARD_CLUSTER; default the context name)")
    p.add_argument("--prometheus-url", help="Prometheus/Mimir base URL (env PROMETHEUS_URL)")
    p.add_argument("--source", choices=SOURCES, help="metrics source (env DASHBOARD_SOURCE; default auto)")
    p.add_argument("--namespace", action="append", dest="namespaces", help="limit to namespace (repeatable)")
    p.add_argument("--host", help="serve: bind address (env DASHBOARD_HOST; default 0.0.0.0)")
    p.add_argument("--port", type=int, help="serve: port (env DASHBOARD_PORT; default 8090)")
    p.add_argument("--refresh", type=int, dest="refresh_seconds",
                   help="serve: re-collect every N seconds in the background and auto-reload the page; "
                        "0 = re-collect on every request (default 15)")
    p.add_argument("--html", metavar="PATH", help="demo/live: write the interactive HTML here")
    p.add_argument("--mermaid", action="store_true", help="demo/live: print Mermaid diagrams")
    p.add_argument("--show-healthy", action="store_true", help="text view: expand healthy subtrees")
    p.add_argument("--seed", type=int, default=7, help="demo: random seed")
    p.add_argument("--log-level", default="WARNING")
    return p


def resolve_cluster_name(cfg: DashboardConfig) -> str:
    """Explicit name, else the context name (explicit or current-context), else 'cluster'."""
    if cfg.cluster_name:
        return cfg.cluster_name
    if cfg.kube_context:
        return cfg.kube_context
    try:
        from kubernetes import config as kconfig
        _, active = kconfig.list_kube_config_contexts(config_file=cfg.kubeconfig)
        return active["name"]
    except Exception:
        return "cluster"


def build_live(cfg: DashboardConfig) -> LiveDashboard:
    """Wire collectors from config; factories are lazy so a missing package degrades to demo."""
    prom_url = cfg.prometheus_url
    return LiveDashboard(
        cluster=resolve_cluster_name(cfg),
        k8s_factory=lambda: K8sCollector.from_kubeconfig(cfg.kubeconfig, cfg.kube_context),
        prom_factory=(lambda: PrometheusCollector(prom_url)) if prom_url else None,
        preferred=cfg.source, namespaces=cfg.namespaces,
        window_points=max(6, cfg.window_minutes * 60 // max(1, cfg.refresh_seconds or cfg.step_seconds)),
        step_s=cfg.step_seconds,
    )


def _one_shot(snap: Snapshot, cfg: DashboardConfig, args: argparse.Namespace) -> int:
    result = triage(snap.tree, cfg.thresholds)
    if snap.banner:
        print(f"[{snap.banner}]")
    print(render_text(result, show_healthy=args.show_healthy))
    if args.mermaid:
        print("\n```mermaid\n" + mermaid_workflow() + "\n```\n\n```mermaid\n" + mermaid_incident(result) + "\n```")
    if args.html:
        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(result, banner=snap.banner, source=snap.source), encoding="utf-8")
        hint = f"#{result.origin.id}" if result.origin else ""
        print(f"\nHTML written to {out.resolve()}  (append {hint} to land on the root-cause origin)" if hint
              else f"\nHTML written to {out.resolve()}")
    return 1 if result.root.health.rank >= Health.WARN.rank else 0


def _setup_logging(level: str) -> None:
    try:
        from opskit.log import setup_logging
        setup_logging(level)
    except ImportError:                       # dashboard can run without opskit installed
        logging.basicConfig(level=level.upper())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _setup_logging(args.log_level)
    try:
        cfg = load_config(args.config, overrides={
            k: getattr(args, k) for k in ("kubeconfig", "kube_context", "cluster_name", "prometheus_url",
                                          "source", "namespaces", "host", "port", "refresh_seconds")})
    except (ValueError, OSError, TypeError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "demo":
            return _one_shot(Snapshot(demo_tree(args.seed), "demo"), cfg, args)
        live = build_live(cfg) if cfg.source != "demo" else None
        if args.command == "live":
            snap = live.collect() if live else Snapshot(demo_tree(args.seed), "demo", "DEMO DATA - demo source requested")
            return _one_shot(snap, cfg, args)
        return _serve(cfg, live, args.seed)
    except Exception:
        log.exception("dashboard_failed")
        return 2


def _serve(cfg: DashboardConfig, live: LiveDashboard | None, seed: int) -> int:
    from dashboard.server import SnapshotCache, serve
    collect = live.collect if live else (lambda: Snapshot(demo_tree(seed), "demo", "DEMO DATA - demo source requested"))
    cache = SnapshotCache(collect, ttl_s=cfg.refresh_seconds, thresholds=cfg.thresholds)
    snap, _ = cache.get()                     # probe once so the console says what we are serving
    print(f"dashboard: serving {snap.source} data for '{live.cluster if live else 'demo'}' "
          f"on http://{cfg.host}:{cfg.port}/" + (f"  [{snap.banner}]" if snap.banner else ""), flush=True)
    if cfg.refresh_seconds > 0:               # keep sampling between page loads so sparklines fill in
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(cfg.refresh_seconds):
                try:
                    cache.get()
                except Exception:
                    log.exception("background_collect_failed")
        threading.Thread(target=loop, name="sampler", daemon=True).start()
    serve(cache, cfg.host, cfg.port, refresh_s=cfg.refresh_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
