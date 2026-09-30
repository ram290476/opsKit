"""Shared boto3 session, client, and pagination helpers."""
from __future__ import annotations

from typing import Iterator

import boto3
from botocore.config import Config

DEFAULT_CONFIG = Config(retries={"max_attempts": 10, "mode": "adaptive"},
                        connect_timeout=5, read_timeout=60)


def create_session(profile_name: str | None = None) -> boto3.Session:
    """Create a boto3 session from the default chain or a named local profile."""
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
