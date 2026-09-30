import json
from datetime import datetime, timedelta, timezone

import boto3
from moto import mock_aws

import opsclient.inventory as inventory_client_module
from opskit.inventory import collect_inventory, write_inventory_excel, write_inventory_json
from opskit.resource_insights import (
    get_basic_resource_metrics,
    get_child_resource_type_counts,
    get_resource_health,
)


@mock_aws
def test_collect_inventory_and_write_json(tmp_path):
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2")
    ec2.create_volume(
        Size=1,
        AvailabilityZone="us-east-1a",
        TagSpecifications=[{
            "ResourceType": "volume",
            "Tags": [
                {"Key": "ManagedBy", "Value": "Terraform"},
                {"Key": "terraform:workspace", "Value": "production"},
                {"Key": "tf:project", "Value": "billing"},
            ],
        }],
    )

    inventory = collect_inventory(["us-east-1"], session)
    assert len(inventory["resources"]) == 1
    resource = inventory["resources"][0]
    assert resource["service"] == "ec2"
    assert resource["resource_type"] == "volume"
    assert resource["resource_id"].startswith("vol-")
    assert resource["iac"] == {
        "tool": "terraform",
        "managed_by": "Terraform",
        "workspace": "production",
        "project": "billing",
    }

    path = write_inventory_json(inventory, tmp_path / "reports" / "inventory.json")
    assert json.loads(path.read_text()) == inventory


def test_collect_account_inventory_uses_profile_and_enabled_regions(monkeypatch):
    class FakeEc2:
        def describe_regions(self, **kwargs):
            assert kwargs["Filters"] == [{
                "Name": "opt-in-status",
                "Values": ["opt-in-not-required", "opted-in"],
            }]
            return {"Regions": [
                {"RegionName": "us-west-2"},
                {"RegionName": "us-east-1"},
            ]}

    class FakeSession:
        def __init__(self):
            self.profile = None

        def client(self, service, **kwargs):
            assert service == "ec2"
            assert kwargs["region_name"] == "us-east-1"
            return FakeEc2()

    session = FakeSession()
    monkeypatch.setattr(
        inventory_client_module,
        "create_session",
        lambda profile_name=None: setattr(session, "profile", profile_name) or session,
    )
    collected = {}

    def fake_collect(regions, actual_session):
        collected["regions"] = list(regions)
        collected["session"] = actual_session
        return {"resources": []}

    monkeypatch.setattr(inventory_client_module, "collect_inventory", fake_collect)

    result = inventory_client_module.collect_account_inventory(profile_name="personal")

    assert result == {"resources": []}
    assert session.profile == "personal"
    assert collected == {"regions": ["us-west-2", "us-east-1"], "session": session}


@mock_aws
def test_write_inventory_excel_includes_resource_and_errors(tmp_path):
    inventory = {
        "account_id": "123456789012",
        "resources": [{
            "region": "us-east-1",
            "service": "ec2",
            "resource_type": "volume",
            "resource_id": "vol-123",
            "arn": "arn:aws:ec2:us-east-1:123456789012:volume/vol-123",
            "tags": {"ManagedBy": "Terraform"},
            "iac": {"tool": "terraform", "workspace": "production"},
        }],
        "errors": {"us-west-2": "access denied"},
    }

    path = write_inventory_excel(inventory, tmp_path / "inventory.xlsx")
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True)
    assert workbook["Resources"]["H2"].value == "terraform"
    assert workbook["Resources"]["I2"].value == "production"
    assert workbook["Errors"]["A2"].value == "us-west-2"


@mock_aws
def test_resource_insights_for_ec2_instance():
    session = boto3.Session(region_name="us-east-1")
    ec2 = session.client("ec2")
    volume_id = ec2.create_volume(Size=1, AvailabilityZone="us-east-1a")["VolumeId"]
    instance = ec2.run_instances(
        ImageId="ami-12345678", InstanceType="t2.micro", MinCount=1, MaxCount=1,
    )["Instances"][0]
    instance_id = instance["InstanceId"]
    ec2.attach_volume(VolumeId=volume_id, InstanceId=instance_id, Device="/dev/sdf")
    resource = {
        "service": "ec2",
        "resource_type": "instance",
        "resource_id": instance_id,
        "region": "us-east-1",
        "arn": f"arn:aws:ec2:us-east-1:123456789012:instance/{instance_id}",
    }

    health = get_resource_health(resource, session)
    children = get_child_resource_type_counts(resource, session)
    assert health["status"] in {"healthy", "unhealthy", "unknown"}
    assert children["supported"]
    assert children["counts"]["ec2:volume"] == 2
    assert children["counts"]["ec2:network-interface"] == 1

    cloudwatch = session.client("cloudwatch")
    cloudwatch.put_metric_data(
        Namespace="AWS/EC2",
        MetricData=[{
            "MetricName": "CPUUtilization",
            "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
            "Timestamp": datetime.now(timezone.utc) - timedelta(minutes=10),
            "Value": 37.5,
            "Unit": "Percent",
        }],
    )
    metrics = get_basic_resource_metrics(resource, session, lookback_hours=2)
    assert metrics["supported"]
    assert metrics["metrics"]["CPUUtilization"]["latest_value"] == 37.5