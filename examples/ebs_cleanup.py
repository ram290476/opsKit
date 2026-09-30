"""Delete old unattached EBS volumes across accounts/regions - dry-run unless --apply.

    python examples/ebs_cleanup.py --accounts 111111111111 222222222222 --role OrgOps --apply --max-changes 20
"""
from __future__ import annotations

import argparse
import logging
import sys

from opskit import aws
from opskit.log import setup_logging
from opskit.retry import retry
from opskit.safety import ChangeBudget, is_protected

log = logging.getLogger("ebs_cleanup")


def stale_volumes(ec2, min_age_days: int):
    for v in aws.paginate(ec2, "describe_volumes", "Volumes",
                          Filters=[{"Name": "status", "Values": ["available"]}]):
        if aws.age_days(v["CreateTime"]) >= min_age_days and not is_protected(aws.tags_to_dict(v.get("Tags"))):
            yield v


@retry(attempts=5)
def delete_volume(ec2, volume_id: str) -> None:
    ec2.delete_volume(VolumeId=volume_id)


def sweep(ec2, budget: ChangeBudget, min_age_days: int) -> int:
    n = 0
    for v in stale_volumes(ec2, min_age_days):
        if budget.approve("delete_volume", v["VolumeId"]):
            delete_volume(ec2, v["VolumeId"])
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", nargs="*", default=[])
    ap.add_argument("--role", default="OrgOps")
    ap.add_argument("--regions", nargs="*")
    ap.add_argument("--min-age-days", type=int, default=30)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-changes", type=int, default=25)
    args = ap.parse_args()
    setup_logging()

    budget = ChangeBudget(apply=args.apply, max_changes=args.max_changes)
    regions = args.regions or aws.enabled_regions()
    sessions = {a: aws.assume_role_session(a, args.role) for a in args.accounts} or {"current": None}
    for acct, session in sessions.items():
        for region in regions:
            count = sweep(aws.client("ec2", region, session), budget, args.min_age_days)
            log.info("swept", extra={"account": acct, "region": region, "candidates": count})
    log.info("summary", extra=budget.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
