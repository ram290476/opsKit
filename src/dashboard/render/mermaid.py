"""Mermaid exports for READMEs and incident docs (GitHub renders ```mermaid blocks natively)."""
from __future__ import annotations

import re

from ..models import Entity, Health, TriageResult


def _sid(entity_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", entity_id)


def mermaid_workflow() -> str:
    """The triage workflow itself as a state machine: see trend -> spot anomaly -> drill -> source."""
    return "\n".join([
        "stateDiagram-v2",
        "    direction LR",
        "    [*] --> SeeTrend",
        '    SeeTrend: See the trend (cluster sparklines)',
        '    SpotAnomaly: Spot the anomaly (red / amber cards, z-score flags)',
        '    Drill: Drill down one level (click a card)',
        '    Isolate: Isolate (deepest earliest anomaly = origin)',
        '    Source: Jump to source (container / pod / node / LB)',
        "    SeeTrend --> SpotAnomaly: card turns amber/red",
        "    SeeTrend --> [*]: all green",
        "    SpotAnomaly --> Drill: click unhealthy card",
        "    Drill --> Drill: children still red",
        "    Drill --> SpotAnomaly: back / breadcrumb",
        "    Drill --> Isolate: no unhealthy children",
        "    Isolate --> Source: jump to source",
        "    Source --> [*]: mitigate + annotate",
    ])


def mermaid_incident(result: TriageResult, siblings: bool = True) -> str:
    """The red path from cluster to origin; optionally its healthy siblings for contrast."""
    nodes: dict[str, Entity] = {}
    edges: list[tuple[str, str]] = []
    by_id = result.by_id()
    for e in result.path:
        nodes[e.id] = e
        if e.parent_id:
            parent = by_id[e.parent_id]
            kids = parent.children if siblings else [e]
            for k in kids:
                nodes[k.id] = k
                edges.append((parent.id, k.id))
    if not result.path:
        nodes[result.root.id] = result.root
    lines = ["stateDiagram-v2", "    direction TB"]
    for e in nodes.values():
        tag = " (ROOT CAUSE)" if result.origin and e.id == result.origin.id else ""
        worst = max(e.metrics, key=lambda m: m.health.rank, default=None)
        hint = f" - {worst.series.name} {worst.series.latest:g}" if worst and worst.health.rank >= Health.WARN.rank else ""
        lines.append(f'    state "{e.level.singular}: {e.name}{tag}{hint}" as {_sid(e.id)}')
    lines.append(f"    [*] --> {_sid(result.root.id)}")
    lines += [f"    {_sid(a)} --> {_sid(b)}" for a, b in edges]
    lines += ["    classDef critical fill:#fde2e1,stroke:#c62828,color:#7f1d1d,font-weight:bold",
              "    classDef warn fill:#fff4d6,stroke:#b7791f,color:#5f370e",
              "    classDef ok fill:#e3f5e8,stroke:#2e7d32,color:#14532d",
              "    classDef origin fill:#c62828,stroke:#7f1d1d,color:#ffffff,font-weight:bold"]
    for state in ("critical", "warn", "ok"):
        ids = [_sid(i) for i, e in nodes.items() if e.health.value == state
               and not (result.origin and i == result.origin.id)]
        if ids:
            lines.append(f"    class {','.join(ids)} {state}")
    if result.origin:
        lines.append(f"    class {_sid(result.origin.id)} origin")
    return "\n".join(lines)
