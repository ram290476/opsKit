# opskit

Reusable building blocks for operational Python (SRE / DevOps / platform engineering).
Every module follows four rules: **dry-run by default, idempotent, paginate + time out everything, structured logs + exit codes.**

| Module | What it gives you |
|---|---|
| `opskit.log` | `setup_logging()` -> JSON logs with secret redaction, quiet botocore/urllib3 |
| `opskit.retry` | `@retry` with capped exponential backoff + full jitter; `is_transient()` for AWS/Azure/GCP/HTTP errors |
| `opskit.safety` | `ChangeBudget` (dry-run + blast-radius cap), `is_protected(tags)`, `maintenance_window()` |
| `opskit.aws` | adaptive-retry clients, `assume_role_session`, `paginate`, `enabled_regions`, `fan_out` (partial-failure safe) |
| `opsclient` | REST API server and console client for AWS inventory/insights and Kubernetes operations |
| `opskit.inventory` | tagged AWS inventory collection, JSON and optional Excel exporters |
| `opskit.resource_insights` | service health, child counts, and CloudWatch metric helpers |
| `opskit.aws_lambda` | package Python code/dependencies for Lambda and guarded runtime/code updates |
| `opskit.http` | `build_session()` - requests with retries on idempotent verbs and a mandatory timeout |
| `opskit.streams` | constant-memory file streams: binary chunks, text lines, gzip, JSON Lines |
| `opskit.http_api` | REST client on `opskit.retry`: timeouts, auth, JSON, pagination, streaming up/down |
| `opskit.sqs` | SQS send/receive/delete, long poll, batch, FIFO, dead-letter awareness, consumer loop |
| `opskit.msk` | optional Kafka/MSK producer and consumer (`kafka-python`): IAM, SASL/TLS, JSON, commits |
| `opskit.k8s` | client loading (in-cluster/kubeconfig), namespace/pod/event listing and pod logs, `rollout_restart`, `wait_for_rollout`, `unhealthy_pods` |
| `opskit.metrics` | `job_metrics()` - duration / success / last-success gauges for batch jobs (Pushgateway) |
| `opskit.notify` | webhook notifier (URL from env/secret store) |
| `opskit.checks` | `@check` registry + `run_checks()` -> report with CI exit codes (0 pass, 1 findings, 2 check crashed) |
| `opskit.logs` | access-log parsing: named-group regex and a `str.split` fast path, top-N 5xx endpoints, ID normalization, error rates, time windows, gzip streaming, optional multiprocessing |

Examples: `examples/ebs_cleanup.py` (multi-account cleanup with guard rails) and `examples/aws_checks.py` (guardrail checks as a CI gate).

```bash
uv venv && uv pip install -e ".[dev,k8s,api,metrics]"    # or: pip install -e ".[dev]"
pytest -q                                             # runs fully offline against moto
opsclient serve                                      # local REST API on 127.0.0.1:8000
opsclient aws --profile personal
opsclient k8s namespaces
python examples/aws_checks.py --region us-west-2 --fail-on high
python examples/ebs_cleanup.py --accounts 111111111111 --role OrgOps            # dry run
python examples/ebs_cleanup.py --accounts 111111111111 --role OrgOps --apply --max-changes 20
```

Collect tagged resources and export an inventory for review. Terraform workspace, project, and module details are inferred from resource tags; AWS does not expose Terraform state through this API. Excel export requires the optional `excel` extra. Install the console command with `pip install -e .`.

```python
opsclient aws --profile personal --region us-east-1 --json aws-inventory.json
```

`opskit.api` exposes AWS inventory and resource insights at `/aws/inventory` and `/aws/insights`, and Kubernetes operations under `/kubernetes`. Start it with `opsclient serve` after installing `opskit[api]` (and `opskit[k8s]` for Kubernetes). The CLI sends requests to `OPSKIT_API_URL`, defaulting to `http://127.0.0.1:8000`; set `--api-url` to override it. For example, `opsclient k8s pods --namespace default --label-selector app=api`, `opsclient k8s events`, and `opsclient k8s logs api-123 --namespace default --container api --tail-lines 100`. The API has no built-in authentication, so keep the server bound to localhost unless it is protected by a trusted network/authentication layer.

The library APIs remain available directly from `opskit.inventory`, `opskit.resource_insights`, and `opskit.k8s` for in-process use.

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

Kubernetes helpers use the optional `k8s` extra and the current in-cluster identity or kubeconfig. Read operations return Kubernetes API objects (or log text); list helpers accept an optional namespace to query all namespaces when omitted. Calls have a 30-second default request timeout that can be overridden.

```python
from opskit.k8s import get_pod_logs, list_events, list_namespaces, list_pods, load_clients

core, apps = load_clients()
namespaces = list_namespaces(core)
pods = list_pods(core, namespace="default", label_selector="app=api")
events = list_events(core, namespace="default", field_selector="type=Warning")
logs = get_pod_logs(core, "api-123", "default", container="api", tail_lines=100)
```

The Kubernetes identity needs RBAC `list` access to namespaces, pods, and events, plus `get` access to `pods/log` for log retrieval.

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

## Access logs

`opskit.logs` ranks endpoints by server error (HTTP 5xx) in Common or Combined access logs. Malformed lines are counted and skipped. A named-group regex is the default parser; `parser="split"` is the fast path when the layout is fixed (at least 10 fields, numeric status, path at field 6, status at field 8, because the timestamp contains a space).

```python
from opskit.logs import error_rates, read_lines, top_error_endpoints

ranking, bad = top_error_endpoints(read_lines("access.log"), n=5, normalize=True)
rates = error_rates(read_lines("access.log"), n=5, min_requests=50)
```

`normalize=True` drops the query string and replaces all-digit path segments (`/api/orders/123` -> `/api/orders/{id}`), so one route is not split into a separate endpoint per id. `error_rates` divides 5xx responses by total requests and hides paths under `min_requests`, so a single failure does not rank as 100%. On the explainer's 2,000-line sample that is `/checkout` at 12.2% (12 errors in 98 requests), while raw paths put checkout first with 12 errors and normalization makes `/api/orders/{id}` first with 20. `recent` / `--minutes` keep only requests after a cutoff (333 requests in the sample's last 10 minutes). `bucket_by_time` groups the same records into fixed windows.

`read_lines` yields one line at a time. `count_files(..., workers=4)` counts each file in its own process (or splits one plain file on line boundaries) and merges the Counters. Gzip stays a single stream. The explainer's 1.5M-line benchmark on that box was about 325 MB to read the whole file versus 14 MB streaming, with split ahead of the regex and four processes over four files at about 0.21 seconds.

```bash
python -m opskit.logs access.log access.log.gz --top 5 --rates --min-requests 50 --workers 4
python -m opskit.logs access.log --minutes 10 --json
```

## HTTP client and file streams

`opskit.streams` keeps large-file work to one chunk, line, or JSON object. `opskit.http_api.ApiClient` adds timeouts, `opskit.retry` backoff, auth headers, JSON helpers, pagination, and streaming downloads and uploads. POST and PATCH are not retried unless you opt in. More examples are in [docs/http-streams.md](docs/http-streams.md).

```python
from opskit.http_api import ApiClient, BearerAuth
from opskit.streams import iter_jsonl, write_jsonl

write_jsonl("events.jsonl", ({"n": n} for n in range(1000)))
for record in iter_jsonl("events.jsonl"):
    handle(record)

with ApiClient("https://api.example.com", auth=BearerAuth(token)) as api:
    for item in api.paginate("/v1/resources", items_key="items", cursor_key="next_cursor"):
        handle(item)
    api.download("/v1/export", "export.bin")
    api.upload("/v1/export", "export.bin", raw=True)
```

## SQS

`opskit.sqs.SqsQueue` sends, long-polls, deletes, changes visibility, and runs a consumer. Clients use `opskit.aws` (including `assume_role_session`). Deletes and purges follow `ChangeBudget` and are dry-run until `apply=True`. FIFO queues take `group_id` and `dedup_id`. `dead_letter_target()` reads the redrive policy, and the consumer logs when a message is close to that queue. Details and the shutdown rules are in [docs/sqs.md](docs/sqs.md).

```python
from opskit.aws import assume_role_session
from opskit.safety import ChangeBudget
from opskit.sqs import SqsQueue

session = assume_role_session("123456789012", "OrgOps")
queue = SqsQueue.from_queue_name(
    "jobs",
    region="us-east-1",
    session=session,
    budget=ChangeBudget(apply=True, max_changes=100),
)
queue.send({"job": "cleanup"})
queue.consume(lambda message: handle(message.json()), wait_seconds=20)
```

Pass `group_id` and `dedup_id` when the queue URL ends in `.fifo`. Omit them for a standard queue.

## MSK / Kafka

`opskit.msk` is an optional producer and consumer. It uses `kafka-python` rather than `confluent-kafka` because the pure-Python client can be faked in tests without librdkafka or a broker. Install `opskit[kafka]` for the client, and `opskit[msk]` when the process should mint MSK IAM tokens (`aws-msk-iam-sasl-signer-python`). SASL/TLS and IAM configs, commit behavior, and topic helpers are in [docs/kafka.md](docs/kafka.md).

```python
from opskit.msk import KafkaConfig, KafkaConsumer, KafkaProducer, ensure_topics
from opskit.safety import ChangeBudget

config = KafkaConfig.for_sasl_tls("b-1.example.com:9096", "ops", password)
# MSK IAM: KafkaConfig.for_msk_iam(brokers, "us-east-1", session=session)

with KafkaProducer(config) as producer:
    producer.send_json("events", {"job": "cleanup"}, key="vol-123")

with KafkaConsumer(config, "events", group_id="ops") as consumer:
    consumer.consume(lambda record: handle(record.value))

ensure_topics(["events"], config=config, replication_factor=3, budget=ChangeBudget(apply=True))
```

Creating a topic is dry-run unless the budget is applying changes. The consumer commits the next offset only after the handler returns.
