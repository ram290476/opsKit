"""Multi-account / multi-region AWS helpers built on boto3."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Iterable, Iterator

import boto3
from botocore.config import Config

log = logging.getLogger(__name__)
DEFAULT_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"},
                        connect_timeout=5, read_timeout=60)


def create_session(profile_name: str | None = None) -> boto3.Session:
    """Create a boto3 session from the default credential chain or a named profile."""
    return boto3.Session(profile_name=profile_name)


def client(service: str, region: str | None = None, session: boto3.Session | None = None,
           config: Config = DEFAULT_CONFIG):
    """Create a configured boto3 service client."""
    return (session or create_session()).client(service, region_name=region, config=config)


def assume_role_session(account_id: str, role_name: str, session_name: str = "opskit",
                        duration: int = 3600, base: boto3.Session | None = None,
                        partition: str = "aws") -> boto3.Session:
    """Assume an IAM role and return a session with its temporary credentials."""
    sts = client("sts", session=base)
    creds = sts.assume_role(RoleArn=f"arn:{partition}:iam::{account_id}:role/{role_name}",
                            RoleSessionName=session_name, DurationSeconds=duration)["Credentials"]
    return boto3.Session(aws_access_key_id=creds["AccessKeyId"],
                         aws_secret_access_key=creds["SecretAccessKey"],
                         aws_session_token=creds["SessionToken"])


def paginate(client_, operation: str, key: str, **kwargs) -> Iterator[dict]:
    """Yield every item under `key` across all pages."""
    for page in client_.get_paginator(operation).paginate(**kwargs):
        yield from page.get(key, [])


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
