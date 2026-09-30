"""Tiny infrastructure validation framework: register checks, run them, report, exit non-zero on failures.

    @check("s3-public-access-block", severity="high")
    def s3_pab(ctx):
        ...
        return [Finding(resource=bucket, message="public access block disabled")]

    report = run_checks(ctx)          # -> Report; report.exit_code() for CI gates
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)
SEVERITIES = ("low", "medium", "high", "critical")


@dataclass
class Finding:
    resource: str
    message: str
    check: str = ""
    severity: str = ""          # empty -> inherit the check's severity


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    passed: list[str] = field(default_factory=list)

    def exit_code(self, fail_on: str = "high") -> int:
        threshold = SEVERITIES.index(fail_on)
        if self.errors:
            return 2                                   # a check crashed: result is untrustworthy
        return 1 if any(SEVERITIES.index(f.severity) >= threshold for f in self.findings) else 0

    def to_json(self) -> str:
        return json.dumps({"findings": [asdict(f) for f in self.findings],
                           "errors": self.errors, "passed": self.passed}, indent=2)


_REGISTRY: dict[str, tuple[str, Callable[[Any], list[Finding]]]] = {}


def check(name: str, severity: str = "medium"):
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")

    def deco(fn):
        _REGISTRY[name] = (severity, fn)
        return fn
    return deco


def registered() -> list[str]:
    return sorted(_REGISTRY)


def run_checks(ctx: Any, only: list[str] | None = None) -> Report:
    report = Report()
    for name in only or registered():
        severity, fn = _REGISTRY[name]
        try:
            found = fn(ctx) or []
        except Exception as exc:
            log.exception("check_error", extra={"check": name})
            report.errors[name] = repr(exc)
            continue
        if not found:
            report.passed.append(name)
        for f in found:
            f.check, f.severity = name, f.severity or severity
            report.findings.append(f)
    return report
