"""Job-level golden signals for batch jobs (optional dependency: prometheus_client)."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)


@contextmanager
def job_metrics(job: str, pushgateway: str | None = None):
    """Records duration, success/failure and last-success timestamp; pushes if a gateway is set.

    Alert on: time() - job_last_success_timestamp_seconds > expected interval.
    """
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    reg = CollectorRegistry()
    duration = Gauge("job_duration_seconds", "Job duration", registry=reg)
    success = Gauge("job_success", "1 if last run succeeded", registry=reg)
    last_ok = Gauge("job_last_success_timestamp_seconds", "Last success time", registry=reg)
    start = time.monotonic()
    try:
        yield reg
        success.set(1)
        last_ok.set_to_current_time()
    except Exception:
        success.set(0)
        raise
    finally:
        duration.set(time.monotonic() - start)
        if pushgateway:
            try:
                push_to_gateway(pushgateway, job=job, registry=reg, timeout=10)
            except Exception as exc:             # metrics must never fail the job itself
                log.warning("metrics_push_failed", extra={"error": repr(exc)})
