from dashboard.models import Direction, Health, Level, MetricSeries, Threshold
from dashboard.panels import evaluate_threshold
from dashboard.trends import detect_anomaly, trend, zscores


def series(points, name="error_rate_pct"):
    return MetricSeries(name=name, unit="%", points=[float(p) for p in points])


def test_threshold_evaluate_higher_and_lower_is_worse():
    t = Threshold(warn=1, critical=5)
    assert [t.evaluate(v) for v in (0.5, 1, 4.9, 5, None)] == [
        Health.OK, Health.WARN, Health.WARN, Health.CRITICAL, Health.UNKNOWN]
    healthy_hosts = Threshold(warn=2, critical=1, higher_is_worse=False)
    assert [healthy_hosts.evaluate(v) for v in (3, 2, 1, 0)] == [
        Health.OK, Health.WARN, Health.CRITICAL, Health.CRITICAL]


def test_trend_direction_and_pct():
    up = trend([10, 10, 10, 10, 20, 20, 20, 20])
    assert (up.direction, up.pct_change, up.arrow) == (Direction.UP, 100.0, "\u2191")
    assert trend([20, 20, 10, 10]).direction == Direction.DOWN
    assert trend([10, 10.2, 10.1, 9.9]).direction == Direction.FLAT
    assert trend([0, 0, 0, 3]).pct_change == 100.0          # zero baseline does not divide by zero
    assert trend([5]).direction == Direction.FLAT


def test_threshold_breach_anomaly_reports_first_breach_index():
    a = detect_anomaly(series([0.2] * 10 + [0.4, 1.5, 6, 7]), Threshold(1, 5))
    assert a is not None and a.reason == "threshold" and a.onset_index == 11


def test_zscore_anomaly_needs_a_sustained_real_shift():
    base = [100, 101, 99, 100, 102, 98, 100, 101, 99, 100]
    shifted = base + [100, 130, 131, 132, 133]
    a = detect_anomaly(series(shifted, "p95_latency_ms"), Threshold(500, 1000))
    assert a is not None and a.reason == "zscore" and a.onset_index == 11
    # a single spike is not a sustained shift
    assert detect_anomaly(series(base + [130, 100, 100, 100], "p95_latency_ms"), Threshold(500, 1000)) is None
    # jitter around a flat baseline is not flagged
    assert detect_anomaly(series(base * 3, "p95_latency_ms"), Threshold(500, 1000)) is None


def test_zscores_flat_baseline_is_safe():
    zs = zscores([5.0] * 10 + [10.0])
    assert zs[0] == 0 and zs[-1] > 3


def test_evaluate_threshold_zscore_only_raises_to_warn():
    base = [100, 101, 99, 100, 102, 98, 100, 101, 99, 100]
    r = evaluate_threshold(Level.POD, series(base + [130, 131, 132, 133], "p95_latency_ms"))
    assert r.health == Health.WARN and r.anomaly.reason == "zscore"
    r = evaluate_threshold(Level.POD, series([0, 0, 0, 1, 2, 3], "restarts"))
    assert r.health == Health.CRITICAL and r.anomaly.onset_index == 3


def test_threshold_overrides_win():
    r = evaluate_threshold(Level.POD, series([0.5] * 6),
                           overrides={"error_rate_pct": Threshold(0.1, 0.4)})
    assert r.health == Health.CRITICAL
