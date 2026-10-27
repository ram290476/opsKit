"""Plain dataclasses shared by collectors, triage logic and renderers (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Level(str, Enum):
    """The six drill-down levels of the triage flow, top (blast radius) to bottom (source)."""

    CLUSTER = "cluster"
    LOAD_BALANCER = "load_balancer"
    NETWORK = "network"
    NODE = "node"
    POD = "pod"
    CONTAINER = "container"

    @property
    def depth(self) -> int:
        return LEVELS.index(self)

    @property
    def label(self) -> str:
        return {"cluster": "Cluster", "load_balancer": "Load balancers", "network": "Network",
                "node": "Nodes", "pod": "Pods", "container": "Containers"}[self.value]

    @property
    def singular(self) -> str:
        return {"cluster": "Cluster", "load_balancer": "Load balancer", "network": "Network path",
                "node": "Node", "pod": "Pod", "container": "Container"}[self.value]


LEVELS: tuple[Level, ...] = (Level.CLUSTER, Level.LOAD_BALANCER, Level.NETWORK,
                             Level.NODE, Level.POD, Level.CONTAINER)


class Health(str, Enum):
    """Traffic-light health. Ordering matters: max() of a list gives the worst state."""

    UNKNOWN = "unknown"
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ("unknown", "ok", "warn", "critical").index(self.value)

    @staticmethod
    def worst(states: list["Health"]) -> "Health":
        return max(states, key=lambda h: h.rank, default=Health.UNKNOWN)


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


@dataclass(frozen=True)
class Threshold:
    """Warn/critical bounds. higher_is_worse=False flips the comparison (e.g. healthy-host count)."""

    warn: float
    critical: float
    higher_is_worse: bool = True

    def evaluate(self, value: float | None) -> Health:
        if value is None:
            return Health.UNKNOWN
        if self.higher_is_worse:
            return (Health.CRITICAL if value >= self.critical
                    else Health.WARN if value >= self.warn else Health.OK)
        return (Health.CRITICAL if value <= self.critical
                else Health.WARN if value <= self.warn else Health.OK)


@dataclass
class MetricSeries:
    """A time series for one metric on one entity. points are evenly spaced, oldest first."""

    name: str
    unit: str
    points: list[float]
    step_s: int = 60
    source: str = ""

    @property
    def latest(self) -> float | None:
        return self.points[-1] if self.points else None


@dataclass
class Trend:
    """Window summary: direction and % change (recent half vs. earlier half)."""

    direction: Direction
    pct_change: float
    arrow: str


@dataclass
class Anomaly:
    """Why a metric was flagged and the first point index where it started (its onset)."""

    metric: str
    reason: str            # "threshold" | "zscore"
    onset_index: int
    score: float = 0.0


@dataclass
class MetricResult:
    """One evaluated metric: series plus health, trend and anomaly verdicts."""

    series: MetricSeries
    health: Health
    trend: Trend
    anomaly: Anomaly | None = None
    threshold: Threshold | None = None


@dataclass
class Entity:
    """A card in the flow graph (cluster, ALB, network path, node, pod or container)."""

    id: str
    name: str
    level: Level
    series: list[MetricSeries] = field(default_factory=list)
    children: list["Entity"] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)
    # filled in by triage.evaluate_tree
    metrics: list[MetricResult] = field(default_factory=list)
    own_health: Health = Health.UNKNOWN
    health: Health = Health.UNKNOWN          # worst of own_health and all descendants
    parent_id: str | None = None

    def walk(self):
        """Yield this entity and all descendants depth-first."""
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def onset_index(self) -> int | None:
        onsets = [m.anomaly.onset_index for m in self.metrics if m.anomaly]
        return min(onsets) if onsets else None


@dataclass
class TriageResult:
    """Output of the triage pass: the evaluated tree plus the root-cause origin and path."""

    root: Entity
    origin: Entity | None
    path: list[Entity]                       # cluster ... origin, inclusive
    timeline: list[tuple[int, Entity]]       # (onset index, entity), earliest first

    def by_id(self) -> dict[str, Entity]:
        return {e.id: e for e in self.root.walk()}
