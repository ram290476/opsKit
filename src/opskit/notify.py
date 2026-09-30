"""Minimal Slack/Teams-style webhook notifier (webhook URL from env / secret store, never code)."""
from __future__ import annotations

import logging
import os

from .http import build_session

log = logging.getLogger(__name__)


def notify(text: str, webhook_env: str = "OPS_WEBHOOK_URL", **fields) -> bool:
    url = os.environ.get(webhook_env)
    if not url:
        log.info("notify_skipped_no_webhook", extra={"text": text})
        return False
    body = {"text": text}
    if fields:
        body["text"] += "\n" + "\n".join(f"*{k}*: {v}" for k, v in fields.items())
    resp = build_session(total=3).post(url, json=body)   # POST not auto-retried (non-idempotent)
    resp.raise_for_status()
    return True
