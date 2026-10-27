"""Trend and anomaly maths over a metric window (stdlib only, no numpy).

* Trend: mean of the recent half vs. the earlier half -> up / down / flat and % change.
* Anomaly: the first point that breaches the warn threshold, or, failing that, the first
  run of MIN_RUN points whose z-score against the baseline (the first third of the window)
  exceeds a limit and that moved at least MIN_REL_SHIFT from the baseline mean.
"""
from __future__ import annotations

from statistics import fmean, pstdev

from .models import Anomaly, Direction, Health, MetricSeries, Threshold, Trend

FLAT_BAND_PCT = 5.0
Z_LIMIT = 3.0
MIN_RUN = 3               # consecutive points above the z limit before a shift counts
MIN_REL_SHIFT = 0.10      # ...and at least a 10% move from the baseline mean (ignores jitter)
_ARROWS = {Direction.UP: "\u2191", Direction.DOWN: "\u2193", Direction.FLAT: "\u2192"}


def trend(points: list[float], flat_band_pct: float = FLAT_BAND_PCT) -> Trend:
    """Compare the mean of the second half of the window with the first half."""
    if len(points) < 2:
        return Trend(Direction.FLAT, 0.0, _ARROWS[Direction.FLAT])
    mid = len(points) // 2
    before, after = fmean(points[:mid]), fmean(points[mid:])
    if before == 0:
        pct = 0.0 if after == 0 else 100.0
    else:
        pct = (after - before) / abs(before) * 100.0
    direction = (Direction.FLAT if abs(pct) < flat_band_pct
                 else Direction.UP if pct > 0 else Direction.DOWN)
    return Trend(direction, round(pct, 1), _ARROWS[direction])


def zscores(points: list[float], baseline_fraction: float = 1 / 3) -> list[float]:
    """z-score of every point against the baseline segment at the start of the window."""
    n = max(2, int(len(points) * baseline_fraction))
    base = points[:n]
    if len(base) < 2:
        return [0.0] * len(points)
    mu, sigma = fmean(base), pstdev(base)
    sigma = sigma or max(abs(mu) * 0.05, 1e-9)    # flat baseline: treat 5% of mean as 1 sigma
    return [(p - mu) / sigma for p in points]


def detect_anomaly(series: MetricSeries, threshold: Threshold | None,
                   z_limit: float = Z_LIMIT, min_run: int = MIN_RUN,
                   min_rel_shift: float = MIN_REL_SHIFT) -> Anomaly | None:
    """Return the earliest anomaly in the window, or None if the series looks normal."""
    pts = series.points
    if not pts:
        return None
    if threshold is not None:
        for i, p in enumerate(pts):
            if threshold.evaluate(p).rank >= Health.WARN.rank:
                return Anomaly(series.name, "threshold", i, round(p, 3))
    zs = zscores(pts)
    n_base = max(2, int(len(pts) / 3))
    mu = fmean(pts[:n_base])
    sign = 1.0 if threshold is None or threshold.higher_is_worse else -1.0
    run_start, run = 0, 0
    for i, (p, z) in enumerate(zip(pts, zs)):
        shifted = abs(p - mu) >= max(abs(mu) * min_rel_shift, 1e-9)
        if sign * z >= z_limit and shifted:
            run_start = i if run == 0 else run_start
            run += 1
            if run >= min_run:
                return Anomaly(series.name, "zscore", run_start, round(zs[run_start], 2))
        else:
            run = 0
    return None
