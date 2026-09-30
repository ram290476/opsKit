"""Multi-account / multi-region AWS helpers built on boto3."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Iterable

from opsclient.aws import DEFAULT_CONFIG, assume_role_session, client, paginate

log = logging.getLogger(__name__)


def tags_to_dict(tags: Iterable[dict] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in (tags or [])}


def age_days(ts: datetime) -> float:
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400


@lru_cache(maxsize=1)
def enabled_regions(service: str = "ec2") -> tuple[str, ...]:
    ec2 = client("ec2", region="us-east-1")
    regions = ec2.describe_regions(Filters=[{"Name": "opt-in-status",
                                             "Values": ["opt-in-not-required", "opted-in"]}])
    return tuple(sorted(r["RegionName"] for r in regions["Regions"]))


def fan_out(targets: Iterable[Any], fn: Callable[[Any], Any], max_workers: int = 16) -> dict[Any, Any]:
    """Run fn(target) in parallel; collect results or exceptions per target (never lose partials)."""
    results: dict[Any, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn, t): t for t in targets}
        for fut in as_completed(futures):
            target = futures[fut]
            try:
                results[target] = fut.result()
            except Exception as exc:                       # record, don't abort the whole sweep
                log.error("fan_out_failed", extra={"target": str(target), "error": repr(exc)})
                results[target] = exc
    return results
