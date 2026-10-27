"""Terminal fallback: an indented tree that expands unhealthy branches and marks the origin."""
from __future__ import annotations

from ..models import Entity, Health, TriageResult

_ICON = {Health.OK: "[ OK ]", Health.WARN: "[WARN]", Health.CRITICAL: "[CRIT]", Health.UNKNOWN: "[ ?? ]"}
_BARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def text_sparkline(points: list[float], width: int = 16) -> str:
    """Unicode block sparkline of the last `width` points."""
    pts = points[-width:]
    if not pts:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    return "".join(_BARS[1 + int((p - lo) / span * (len(_BARS) - 2))] for p in pts)


def _metric_line(e: Entity, limit: int = 3) -> str:
    shown = sorted(e.metrics, key=lambda m: -m.health.rank)[:limit]
    return "  ".join(f"{m.series.name}={m.series.latest:g}{m.series.unit if m.series.unit in ('%', 'ms') else ''}"
                     f"{m.trend.arrow}{'!' if m.anomaly else ''}" for m in shown if m.series.latest is not None)


def render_text(result: TriageResult, show_healthy: bool = False, step_s: int = 60) -> str:
    """Healthy subtrees collapse to one line unless show_healthy=True."""
    origin_id = result.origin.id if result.origin else None
    on_path = {e.id for e in result.path}
    lines = [f"Cluster {result.root.name}: {result.root.health.value.upper()}"]
    if result.origin:
        lines.append(f"Root-cause origin: {result.origin.level.singular} "
                     f"{result.origin.name} (anomaly from t+{(result.origin.onset_index or 0) * step_s // 60}m)")
        lines.append("Path: " + " > ".join(e.name for e in result.path))
    lines.append("")

    def visit(e: Entity, depth: int) -> None:
        mark = " <== ROOT CAUSE" if e.id == origin_id else (" *" if e.id in on_path else "")
        pad = "  " * depth
        lines.append(f"{pad}{_ICON[e.health]} {e.level.value:<13} {e.name}{mark}")
        if e.metrics:
            key = max(e.metrics, key=lambda m: m.health.rank)
            lines.append(f"{pad}       {_metric_line(e)}   {key.series.name} {text_sparkline(key.series.points)}")
        for c in e.children:
            if show_healthy or c.health.rank >= Health.WARN.rank:
                visit(c, depth + 1)
        hidden = [c for c in e.children if not show_healthy and c.health.rank < Health.WARN.rank]
        if hidden:
            lines.append(f"{pad}  ({len(hidden)} healthy {hidden[0].level.value}(s) hidden)")

    visit(result.root, 0)
    if result.timeline:
        lines += ["", "Anomaly timeline (onset):"]
        lines += [f"  t+{i * step_s // 60:>2}m  {e.level.value:<13} {e.name}" for i, e in result.timeline]
    return "\n".join(lines)
