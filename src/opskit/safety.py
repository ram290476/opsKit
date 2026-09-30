"""Guard rails for anything that mutates infrastructure."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class BlastRadiusExceeded(RuntimeError):
    pass


@dataclass
class ChangeBudget:
    """Dry-run by default and cap how many changes one run may make.

    budget = ChangeBudget(apply=args.apply, max_changes=25)
    for vol in candidates:
        if budget.approve("delete_volume", vol_id):
            ec2.delete_volume(VolumeId=vol_id)
    """
    apply: bool = False
    max_changes: int = 25
    planned: list[tuple[str, str]] = field(default_factory=list)
    executed: int = 0

    def approve(self, action: str, target: str) -> bool:
        self.planned.append((action, target))
        if not self.apply:
            log.info("plan", extra={"action": action, "target": target, "dry_run": True})
            return False
        if self.executed >= self.max_changes:
            raise BlastRadiusExceeded(f"refusing change #{self.executed + 1}; max_changes={self.max_changes}")
        self.executed += 1
        log.info("apply", extra={"action": action, "target": target, "dry_run": False})
        return True

    def summary(self) -> dict:
        return {"planned": len(self.planned), "executed": self.executed, "apply": self.apply}


PROTECTED_TAG_KEYS = ("do-not-delete", "protected", "retain")


def is_protected(tags: dict[str, str] | None) -> bool:
    tags = {k.lower(): str(v).lower() for k, v in (tags or {}).items()}
    return any(tags.get(k) in ("true", "yes", "1") for k in PROTECTED_TAG_KEYS)


@contextmanager
def maintenance_window(name: str):
    """Log start/end (and failure) of a change window so it shows up in the audit trail."""
    log.info("change_start", extra={"change": name})
    try:
        yield
    except Exception:
        log.exception("change_failed", extra={"change": name})
        raise
    else:
        log.info("change_end", extra={"change": name})
