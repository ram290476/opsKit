"""requests.Session with retries on idempotent methods and a mandatory timeout."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class TimeoutSession(requests.Session):
    def __init__(self, timeout: float | tuple[float, float] = (3.05, 30)):
        super().__init__()
        self._timeout = timeout

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)


def build_session(total: int = 5, backoff: float = 0.5,
                  timeout: float | tuple[float, float] = (3.05, 30),
                  user_agent: str = "opskit/1.0") -> requests.Session:
    retry = Retry(total=total, backoff_factor=backoff,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=frozenset(["GET", "HEAD", "PUT", "DELETE", "OPTIONS"]),
                  respect_retry_after_header=True)
    s = TimeoutSession(timeout)
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=32)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = user_agent
    return s
