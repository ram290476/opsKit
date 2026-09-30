# opskit

Reusable building blocks for operational Python (SRE / DevOps / platform engineering).
Every module follows four rules: **dry-run by default, idempotent, paginate + time out everything, structured logs + exit codes.**

| Module | What it gives you |
|---|---|
| `opskit.log` | `setup_logging()` -> JSON logs with secret redaction, quiet botocore/urllib3 |
| `opskit.retry` | `@retry` with capped exponential backoff + full jitter; `is_transient()` for AWS/Azure/GCP/HTTP errors |
| `opskit.safety` | `ChangeBudget` (dry-run + blast-radius cap), `is_protected(tags)`, `maintenance_window()` |
| `opskit.aws` | adaptive-retry clients, `assume_role_session`, `paginate`, `enabled_regions`, `fan_out` (partial-failure safe) |
| `opsclient` | separate top-level import package for boto3 clients, inventory, and resource insights; distributed with `opskit` |
| `opskit.inventory` | JSON and optional Excel inventory exporters (client functions remain available as compatibility imports) |
| `opskit.resource_insights` | compatibility imports for service health, child counts, and CloudWatch metric helpers |
| `opskit.aws_lambda` | package Python code/dependencies for Lambda and guarded runtime/code updates |
| `opskit.http` | `build_session()` - requests with retries on idempotent verbs and a mandatory timeout |
| `opskit.k8s` | client loading (in-cluster/kubeconfig), `rollout_restart`, `wait_for_rollout`, `unhealthy_pods` |
| `opskit.metrics` | `job_metrics()` - duration / success / last-success gauges for batch jobs (Pushgateway) |
| `opskit.notify` | webhook notifier (URL from env/secret store) |
| `opskit.checks` | `@check` registry + `run_checks()` -> report with CI exit codes (0 pass, 1 findings, 2 check crashed) |

Examples: `examples/ebs_cleanup.py` (multi-account cleanup with guard rails) and `examples/aws_checks.py` (guardrail checks as a CI gate).

```bash
uv venv && uv pip install -e ".[dev,k8s,metrics]"    # or: pip install -e ".[dev]"
pytest -q                                             # runs fully offline against moto
python examples/aws_checks.py --region us-west-2 --fail-on high
python examples/ebs_cleanup.py --accounts 111111111111 --role OrgOps            # dry run
python examples/ebs_cleanup.py --accounts 111111111111 --role OrgOps --apply --max-changes 20
```

Collect tagged resources and export an inventory for review. Terraform workspace, project, and module details are inferred from resource tags; AWS does not expose Terraform state through this API. Excel export requires the optional `excel` extra.

```python
from opsclient.inventory import collect_account_inventory
from opskit.inventory import write_inventory_excel, write_inventory_json

inventory = collect_account_inventory(profile_name="personal")  # uses ~/.aws/config and credentials
# Or use the default boto3 credential chain and choose regions explicitly:
inventory = collect_account_inventory(regions=["us-east-1", "us-west-2"])
write_inventory_json(inventory, "aws-inventory.json")
write_inventory_excel(inventory, "aws-inventory.xlsx")  # pip install opskit[excel]
```

Configure credentials locally with `aws configure --profile personal` or another supported boto3 credential source; opskit does not accept or store secrets. The caller needs `ec2:DescribeRegions` when regions are discovered, `sts:GetCallerIdentity`, and Resource Groups Tagging API read access (`tag:GetResources`) in each region. The inventory includes tagged resources returned by that API, not a guarantee of every untagged resource in the account.

Resource insights use service APIs for EC2 instance/volume, RDS DB instance, and Lambda health; child counts are supported for EC2 instances and RDS clusters. CloudWatch metric profiles are provided for EC2 instances, EBS volumes, RDS DB instances, and Lambda functions.

```python
from opsclient.resource_insights import (
	get_basic_resource_metrics,
	get_child_resource_type_counts,
	get_resource_health,
)

resource = inventory["resources"][0]
health = get_resource_health(resource)
children = get_child_resource_type_counts(resource)
metrics = get_basic_resource_metrics(resource, lookback_hours=24)
```

The insight helpers need the corresponding read actions: `ec2:DescribeInstanceStatus`, `ec2:DescribeInstances`, `ec2:DescribeVolumeStatus`, `rds:DescribeDBInstances`, `rds:DescribeDBClusters`, `lambda:GetFunctionConfiguration`, and `cloudwatch:GetMetricStatistics`.

Build a Lambda deployment ZIP from a handler directory and its `requirements.txt`:

```python
from opskit.aws_lambda import build_deployment_package, update_code, update_runtime
from opskit.safety import ChangeBudget

package = build_deployment_package("function", "function.zip", "function/requirements.txt")
budget = ChangeBudget(apply=True, max_changes=2)
update_runtime(lambda_client, "my-function", "python3.12", budget)
update_code(lambda_client, "my-function", package, budget)
```

The update helpers are dry-run by default. `build_deployment_package` uses the selected Python executable's `pip` to install requirements into the ZIP; build dependencies for the Lambda OS and architecture when packages contain native extensions.
