import sys
from pathlib import Path

import boto3
from moto import mock_aws

from opskit import aws
from opskit.safety import ChangeBudget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))


@mock_aws
def test_paginate_returns_all_items_across_pages():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    for _ in range(12):
        ec2.create_volume(Size=1, AvailabilityZone="us-east-1a")
    vols = list(aws.paginate(ec2, "describe_volumes", "Volumes", PaginationConfig={"PageSize": 5}))
    assert len(vols) == 12


@mock_aws
def test_assume_role_session_returns_usable_session():
    s = aws.assume_role_session("123456789012", "OrgOps")
    assert s.client("sts").get_caller_identity()["Account"]


@mock_aws
def test_ebs_cleanup_respects_protection_and_dry_run():
    import ebs_cleanup
    ec2 = boto3.client("ec2", region_name="us-east-1")
    keep = ec2.create_volume(Size=1, AvailabilityZone="us-east-1a",
                             TagSpecifications=[{"ResourceType": "volume",
                                                 "Tags": [{"Key": "do-not-delete", "Value": "true"}]}])
    ec2.create_volume(Size=1, AvailabilityZone="us-east-1a")

    dry = ChangeBudget(apply=False)
    assert ebs_cleanup.sweep(ec2, dry, min_age_days=0) == 1          # protected one excluded
    assert len(ec2.describe_volumes()["Volumes"]) == 2               # dry run deleted nothing

    ebs_cleanup.sweep(ec2, ChangeBudget(apply=True), min_age_days=0)
    remaining = [v["VolumeId"] for v in ec2.describe_volumes()["Volumes"]]
    assert remaining == [keep["VolumeId"]]


@mock_aws
def test_guardrail_checks_find_open_sg_and_gate_ci():
    import aws_checks
    from opskit.checks import run_checks
    ec2 = boto3.client("ec2", region_name="us-east-1")
    sg = ec2.create_security_group(GroupName="bad", Description="bad")["GroupId"]
    ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[{
        "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="no-pab-bucket")

    report = run_checks(aws_checks.Ctx(boto3.Session(), "us-east-1"))
    by_check = {f.check for f in report.findings}
    assert "sg-open-admin-ports" in by_check
    assert "s3-public-access-block" in by_check
    assert report.exit_code("high") == 1
    assert not report.errors


def test_check_crash_returns_exit_code_2():
    from opskit.checks import Report
    r = Report(errors={"x": "boom"})
    assert r.exit_code() == 2


def test_fan_out_keeps_partial_results():
    def fn(x):
        if x == 2:
            raise RuntimeError("region down")
        return x * 10
    res = aws.fan_out([1, 2, 3], fn)
    assert res[1] == 10 and res[3] == 30 and isinstance(res[2], RuntimeError)
