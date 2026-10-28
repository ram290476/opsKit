# AIOps / SRE mock-interview solutions

Eight short Python drills. Each one is an automation pattern you would actually run next to production: count, detect, group, gate, remediate, roll back, trace, or suppress.

| File | SRE automation pattern |
|---|---|
| `q1_log_level_counter.py` | **Log rollup.** Stream log lines, skip stack traces, count levels, and rank the services emitting the most `ERROR`s so an on-call can see who is noisy without loading the whole file. |
| `q2_error_spike_window.py` | **Spike detection.** Keep a sliding time window of error timestamps and fire once when the count crosses a threshold, then stay quiet until the rate drops. |
| `q3_alert_incident_grouping.py` | **Alert grouping.** Collapse alerts for the same service into one incident when they arrive inside a gap window, and keep the first alert, max severity, and count. |
| `q4_latency_slo_check.py` | **SLO check.** Compute per-endpoint p50/p95/p99 and the 5xx error rate, then flag a breach when latency or errors miss the objective. |
| `q5_queue_remediation_worker.py` | **Auto-remediation queue.** A bounded worker queue sheds low-severity work under backpressure, enforces a per-resource cooldown, retries runbooks with backoff, and dead-letters anything that still fails so a human gets paged. |
| `q6_deploy_auto_rollback.py` | **Deploy bake and rollback.** Watch health for a fixed window and roll back after consecutive failures. The clock and sleep are injectable so the bake can be tested without waiting. |
| `q7_trace_critical_path.py` | **Trace critical path.** Follow the child span that ends last to name the critical path, and subtract merged child time so the hottest exclusive service is obvious. |
| `q8_anomaly_detector_suppression.py` | **Anomaly suppression.** A rolling z-score detector pages only outside maintenance windows and only after a per-host cooldown, so a planned change or a flapping host does not page twice. |

Run any file directly (`python q1_log_level_counter.py`). Samples and asserts live under `if __name__ == "__main__"`.
