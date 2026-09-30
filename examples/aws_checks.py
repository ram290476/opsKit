"""Account guardrail checks built on opskit.checks. Run in CI or as a scheduled job.

    python examples/aws_checks.py --region us-west-2 --fail-on high
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

from opskit import aws
from opskit.checks import Finding, check, run_checks
from opskit.log import setup_logging


@dataclass
class Ctx:
    session: boto3.Session
    region: str


@check("s3-public-access-block", severity="high")
def s3_public_access_block(ctx: Ctx) -> list[Finding]:
    s3 = aws.client("s3", ctx.region, ctx.session)
    out = []
    for b in s3.list_buckets()["Buckets"]:
        try:
            cfg = s3.get_public_access_block(Bucket=b["Name"])["PublicAccessBlockConfiguration"]
            if not all(cfg.values()):
                out.append(Finding(b["Name"], "public access block partially disabled"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
                out.append(Finding(b["Name"], "no public access block configured"))
            else:
                raise
    return out


@check("sg-open-admin-ports", severity="critical")
def sg_open_admin_ports(ctx: Ctx) -> list[Finding]:
    ec2 = aws.client("ec2", ctx.region, ctx.session)
    out = []
    for sg in aws.paginate(ec2, "describe_security_groups", "SecurityGroups"):
        for perm in sg.get("IpPermissions", []):
            lo, hi = perm.get("FromPort", 0), perm.get("ToPort", 65535)
            world = any(r.get("CidrIp") == "0.0.0.0/0" for r in perm.get("IpRanges", []))
            if world and any(lo <= p <= hi for p in (22, 3389)):
                out.append(Finding(sg["GroupId"], f"ports {lo}-{hi} open to 0.0.0.0/0"))
    return out


@check("ebs-unattached", severity="low")
def ebs_unattached(ctx: Ctx) -> list[Finding]:
    ec2 = aws.client("ec2", ctx.region, ctx.session)
    vols = aws.paginate(ec2, "describe_volumes", "Volumes",
                        Filters=[{"Name": "status", "Values": ["available"]}])
    return [Finding(v["VolumeId"], f"{v['Size']} GiB unattached") for v in vols]


@check("ebs-default-encryption", severity="medium")
def ebs_default_encryption(ctx: Ctx) -> list[Finding]:
    ec2 = aws.client("ec2", ctx.region, ctx.session)
    if not ec2.get_ebs_encryption_by_default()["EbsEncryptionByDefault"]:
        return [Finding(ctx.region, "EBS encryption by default is off")]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--fail-on", default="high")
    args = ap.parse_args()
    setup_logging()
    report = run_checks(Ctx(boto3.Session(), args.region))
    print(report.to_json())
    return report.exit_code(args.fail_on)


if __name__ == "__main__":
    sys.exit(main())
