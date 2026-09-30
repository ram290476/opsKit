"""Retry with capped exponential backoff and full jitter, cloud-aware transient detection."""
from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable, Iterable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

TRANSIENT_AWS_CODES = {
    "Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException",
    "ProvisionedThroughputExceededException", "RequestTimeout", "ServiceUnavailable",
    "InternalError", "SlowDown",
}
TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


def is_transient(exc: BaseException) -> bool:
    """Best-effort classification across boto3, Azure, GCP and plain HTTP errors."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):                               # botocore ClientError
        return response.get("Error", {}).get("Code") in TRANSIENT_AWS_CODES
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)   # azure / google
    if status is None and response is not None:                   # requests HTTPError
        status = getattr(response, "status_code", None)
    try:
        return int(status) in TRANSIENT_HTTP_STATUS
    except (TypeError, ValueError):
        return False


def backoff_delays(attempts: int, base: float = 0.5, cap: float = 30.0) -> Iterable[float]:
    for i in range(attempts - 1):
        yield random.uniform(0, min(cap, base * 2 ** i))


def retry(attempts: int = 5, base: float = 0.5, cap: float = 30.0,
          when: Callable[[BaseException], bool] = is_transient,
          sleep: Callable[[float], None] = time.sleep):
    """Decorator. Retries only when `when(exc)` is True; re-raises the last error."""
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            delays = iter(backoff_delays(attempts, base, cap))
            while True:
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    delay = next(delays, None)
                    if delay is None or not when(exc):
                        raise
                    log.warning("retrying", extra={"fn": fn.__name__, "delay_s": round(delay, 2),
                                                   "error": type(exc).__name__})
                    sleep(delay)
        return wrapper
    return deco
