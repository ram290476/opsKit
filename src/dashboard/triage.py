"""Triage pass: evaluate every card, roll health up the tree, find the root-cause origin.

Root-cause origin = the unhealthy entity whose anomaly started first (earliest onset index in
the window). Ties go to the deepest level, because a symptom usually surfaces one level up in
the same minute as its cause (an OOMKill and the pod restart it triggers). The highlighted path
is the chain of ancestors from the cluster down to that origin.
"""
from __future__ import annotations

import logging

from .models import Entity, Health, Threshold, TriageResult
from .panels import evaluate_threshold

log = logging.getLogger(__name__)


def evaluate_tree(root: Entity, overrides: dict[str, dict[str, Threshold]] | None = None) -> Entity:
    """Fill metrics, own_health, health and parent_id on every entity in place; return root."""
    overrides = overrides or {}

    def visit(entity: Entity, parent: Entity | None) -> Health:
        entity.parent_id = parent.id if parent else None
        entity.metrics = [evaluate_threshold(entity.level, s, overrides.get(entity.level.value))
                          for s in entity.series]
        entity.own_health = Health.worst([m.health for m in entity.metrics]) if entity.metrics else Health.UNKNOWN
        child_states = [visit(c, entity) for c in entity.children]
        entity.health = Health.worst([entity.own_health, *child_states])
        return entity.health

    visit(root, None)
    return root


def find_origin(root: Entity) -> Entity | None:
    """Earliest-onset unhealthy entity; ties broken by depth (deepest wins)."""
    candidates = [e for e in root.walk()
                  if e.onset_index is not None and e.own_health.rank >= Health.WARN.rank]
    if not candidates:
        return None
    return min(candidates, key=lambda e: (e.onset_index, -e.level.depth, -e.own_health.rank))


def path_to(root: Entity, target_id: str) -> list[Entity]:
    """Entities from root down to target (inclusive); empty list if target is absent."""
    if root.id == target_id:
        return [root]
    for child in root.children:
        sub = path_to(child, target_id)
        if sub:
            return [root, *sub]
    return []


def triage(root: Entity, overrides: dict[str, dict[str, Threshold]] | None = None) -> TriageResult:
    """Evaluate the tree and return origin, red path and the anomaly timeline."""
    evaluate_tree(root, overrides)
    origin = find_origin(root)
    path = path_to(root, origin.id) if origin else []
    timeline = sorted(((e.onset_index, e) for e in root.walk()
                       if e.onset_index is not None and e.own_health.rank >= Health.WARN.rank),
                      key=lambda t: (t[0], -t[1].level.depth))
    log.info("triage_done", extra={"origin": origin.id if origin else None,
                                   "cluster_health": root.health.value})
    return TriageResult(root=root, origin=origin, path=path, timeline=timeline)
