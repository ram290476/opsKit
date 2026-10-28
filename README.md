# opskit

Reusable building blocks for operational Python (SRE, DevOps, and platform engineering).

Library code lives in `src/opskit`. The design rules in `opskit/__init__.py` are: dry-run by default with an explicit apply, safe to re-run, paginate and time out remote calls, and emit structured logs with meaningful exit codes. Mutating AWS helpers honor `ChangeBudget` and do nothing until `apply=True`.

## Contents

- [Install](#install)
- [Tests](#tests)
- [Layout](#layout)
- [Module index](#module-index)
- [Logging, retry, and safety](#logging-retry-and-safety)
- [AWS helpers](#aws-helpers)
- [HTTP and file streams](#http-and-file-streams)
- [Access logs](#access-logs)
- [SQS](#sqs)
- [MSK and Kafka](#msk-and-kafka)
- [Inventory, insights, Lambda, and checks](#inventory-insights-lambda-and-checks)
- [Kubernetes and the opsclient CLI](#kubernetes-and-the-opsclient-cli)
- [Data-structure samples and wrappers](#data-structure-samples-and-wrappers)

## Install

Requires Python 3.10+. `boto3` and `requests` are always installed. Everything else is an extra.

```bash
pip install -e ".[dev]"
pip install -e ".[dev,k8s,api,metrics,excel,kafka]"
pip install -e ".[msk]"    # kafka-python plus the MSK IAM signer
```

| Extra | Packages | Used by |
|---|---|---|
| `k8s` | `kubernetes` | `opskit.k8s` |
| `api` | `fastapi`, `uvicorn` | `opskit.api`, `opsclient serve` |
| `metrics` | `prometheus_client` | `opskit.metrics` |
| `excel` | `openpyxl` | `opskit.inventory.write_inventory_excel` |
| `kafka` | `kafka-python` | `opskit.aws_msk` producer and consumer |
| `msk` | `kafka-python`, `aws-msk-iam-sasl-signer-python` | MSK IAM token minting inside `opskit.aws_msk` |
| `dev` | pytest, moto, responses, httpx, fastapi, openpyxl, ruff, mypy | the `tests/` suite |

`opskit[msk]` is only needed when the process mints MSK IAM tokens. Pass a `token_provider` and `opskit[kafka]` is enough.

## Tests

`pytest` is configured with `pythonpath = src` and `testpaths = tests`. The suite does not call AWS or the network: moto covers AWS, and `responses` covers HTTP.

```bash
pip install -e ".[dev]"
pytest -q
```

Wrapper tests sit outside that path:

```bash
python src/data-structures/tests/test_wrappers.py
```

Dashboard tests live under `src/dashboard/tests` and are documented in [src/dashboard/README.md](src/dashboard/README.md).

## Layout

```text
opsKit/
├── pyproject.toml
├── README.md
├── docs/
│   ├── http-streams.md    # longer HTTP and stream notes
│   ├── sqs.md             # longer SQS notes (imports below are the current names)
│   └── kafka.md           # longer MSK notes (same caveat)
├── examples/
│   ├── aws_checks.py      # CI guardrail checks
│   └── ebs_cleanup.py     # multi-account cleanup with ChangeBudget
├── tests/                 # pytest target
├── src/opsclient/         # `opsclient` console script
├── src/opskit/            # library modules
├── src/dashboard/         # Kubernetes triage dashboard
└── src/data-structures/   # interview samples plus wrappers.py
```

## Module index

| Module | Purpose |
|---|---|
| `opskit.log` | JSON logs with secret redaction |
| `opskit.retry` | Capped exponential backoff with full jitter |
| `opskit.safety` | Dry-run budget, protected tags, change-window logs |
| `opskit.aws` | boto3 sessions, assume-role, pagination, fan-out |
| `opskit.http` | `requests` session with a mandatory timeout |
| `opskit.http_api` | REST client: auth, JSON, pagination, streamed bodies |
| `opskit.streams` | Constant-memory binary, text, gzip, and JSON Lines I/O |
| `opskit.logs` | Rank access-log endpoints by HTTP 5xx |
| `opskit.aws_sqs` | SQS send, long-poll, delete, FIFO, and a consumer |
| `opskit.aws_msk` | Optional Kafka producer and consumer for Amazon MSK |
| `opskit.shutdown` | SIGINT/SIGTERM handler that sets a stop event |
| `opskit.inventory` | Tagged-resource inventory, JSON and optional Excel |
| `opskit.resource_insights` | Health, child counts, and CloudWatch metrics |
| `opskit.aws_lambda` | Zip a Python function and guard runtime or code updates |
| `opskit.k8s` | Read pods, events, and logs; restart and wait for rollouts |
| `opskit.metrics` | Job duration and last-success gauges |
| `opskit.notify` | Webhook post; URL comes from the environment |
| `opskit.checks` | Check registry and a CI exit code |
| `opskit.api` | Local REST API for inventory, insights, and Kubernetes |
| `opskit.clients` | Grouped AWS, inventory, and insight helpers for that API |
| `opsclient` | CLI for the local API |
| `data-structures/wrappers.py` | `FakeClock`, `TTLCache`, and `TopK` shared by the samples |

`docs/sqs.md` and `docs/kafka.md` still show the earlier import names `opskit.sqs` and `opskit.msk`. The modules on main are `opskit.aws_sqs` and `opskit.aws_msk`. Use the imports in this README.

## Logging, retry, and safety

**`opskit.log`.** One-line purpose: JSON logs on stderr, with secret-like fields redacted. No extra. No CLI. Call it once from an entry point; libraries only use `logging.getLogger`.

```python
from opskit.log import setup_logging

setup_logging(level="INFO", json_output=True)
```

**`opskit.retry`.** One-line purpose: retry only transient AWS, HTTP, and connection errors, with capped exponential backoff and full jitter. No extra. No CLI.

```python
from opskit.retry import retry

@retry(attempts=5)
def load():
    return fetch()
```

`is_transient` treats throttling, HTTP 408/429/500/502/503/504, and built-in `ConnectionError` / `TimeoutError` as retryable. Pass `sleep=` in tests so the decorator does not wait.

**`opskit.safety`.** One-line purpose: cap and dry-run infrastructure changes. No extra. No CLI. `approve` returns false until `apply=True`, then raises `BlastRadiusExceeded` past `max_changes`.

```python
from opskit.safety import ChangeBudget, is_protected, maintenance_window

budget = ChangeBudget(apply=False, max_changes=25)
if not is_protected(tags) and budget.approve("delete_volume", volume_id):
    ec2.delete_volume(VolumeId=volume_id)
```

`maintenance_window(name)` logs the start, failure, and end of a change.

## AWS helpers

**`opskit.aws`.** One-line purpose: boto3 sessions with adaptive retries, short connect timeouts, assume-role, and pagination. No extra beyond `boto3`. No CLI.

```python
from opskit.aws import assume_role_session, client, paginate

session = assume_role_session("123456789012", "OrgOps")
ec2 = client("ec2", region="us-east-1", session=session)
for volume in paginate(ec2, "describe_volumes", "Volumes"):
    print(volume["VolumeId"])
```

Also: `create_session`, `enabled_regions`, `fan_out` (one failure does not drop the other results), `tags_to_dict`, and `age_days`.

## HTTP and file streams

Longer notes: [docs/http-streams.md](docs/http-streams.md).

**`opskit.streams`.** One-line purpose: read and write large files one chunk, line, or JSON object at a time, including gzip. No extra. No CLI. A path is closed by the helper. A file object you opened stays open.

```python
from opskit.streams import iter_jsonl, iter_lines, write_jsonl

write_jsonl("events.jsonl", ({"n": n} for n in range(1000)))
for record in iter_jsonl("events.jsonl"):
    handle(record)
for line in iter_lines("app.log"):
    if "ERROR" in line:
        print(line)
```

Context managers: `open_binary`, `open_text`, `open_gzip`, and `open_jsonl`. A bad JSON line raises `JsonlError` with `line_number` set.

**`opskit.http`.** One-line purpose: a `requests` session that always sets a timeout and retries idempotent verbs (not POST) on 429 and 5xx via urllib3. No extra. No CLI.

```python
from opskit.http import build_session

with build_session() as session:
    response = session.get("https://example.com/health")
```

**`opskit.http_api`.** One-line purpose: a REST client whose backoff goes through `opskit.retry`, not urllib3. No extra. No CLI. GET, HEAD, OPTIONS, PUT, and DELETE retry. POST and PATCH do not, unless listed in `retry_methods`. Downloads land in a `.partial` file and are renamed after the body succeeds.

```python
from opskit.http_api import ApiClient, BearerAuth

auth = BearerAuth(token)
with ApiClient("https://api.example.com", auth=auth) as api:
    created = api.post_json("/v1/jobs", {"name": "cleanup"})
    for item in api.paginate("/v1/resources", items_key="items", cursor_key="next_cursor"):
        handle(item)
    api.download("/v1/export", "export.bin")
    api.upload("/v1/bundle", "bundle.tar.gz", raw=True)
```

`BearerAuth.token` is read on each call. `HeaderAuth` or a dict adds fixed headers. Status 400 and above raise `ApiError`.

## Access logs

**`opskit.logs`.** One-line purpose: rank Common or Combined access-log endpoints by HTTP 5xx, skipping malformed lines. No extra. CLI: `python -m opskit.logs`.

```python
from opskit.logs import error_rates, read_lines, top_error_endpoints

ranking, bad = top_error_endpoints(read_lines("access.log"), n=5, normalize=True)
rates = error_rates(read_lines("access.log"), n=5, min_requests=50)
```

`normalize=True` drops the query string and replaces all-digit segments (`/api/orders/123` becomes `/api/orders/{id}`). `parser="split"` is the fast path for a fixed field layout. `read_lines` streams plain text and gzip. `count_files(..., workers=4)` counts files in a process pool and merges the counters. Gzip stays one stream.

```bash
python -m opskit.logs access.log access.log.gz --top 5 --rates --min-requests 50 --workers 4
python -m opskit.logs access.log --minutes 10 --bucket-seconds 60 --json
python -m opskit.logs access.log --parser split --no-normalize
```

`--minutes` and `--bucket-seconds` need the regex parser. `--normalize` is on by default.

## SQS

**`opskit.aws_sqs`.** One-line purpose: send, long-poll, delete, and consume one queue, including FIFO group and dedup ids and dead-letter awareness. No extra beyond `boto3`. No CLI. Longer notes: [docs/sqs.md](docs/sqs.md).

Deletes, visibility changes, and purge use `ChangeBudget` and stay dry-run until `apply=True`. Sends are not gated. The consumer deletes a message only after the handler returns and the budget approves. A handler exception leaves the message for SQS retry and, past `maxReceiveCount`, the dead-letter queue.

```python
from opskit.aws import assume_role_session
from opskit.aws_sqs import SqsQueue
from opskit.safety import ChangeBudget

session = assume_role_session("123456789012", "OrgOps")
queue = SqsQueue.from_queue_name(
    "jobs",
    region="us-east-1",
    session=session,
    budget=ChangeBudget(apply=True, max_changes=100),
)
queue.send({"job": "cleanup"})
result = queue.consume(lambda message: handle(message.json()), wait_seconds=20)
```

FIFO queue URLs end in `.fifo` and require `group_id`. Pass `dedup_id` unless the queue uses content-based deduplication. `list_queue_urls` follows the SQS paginator. `dead_letter_target()` reads the redrive policy. `approaching_dead_letter` is true when `ApproximateReceiveCount` is within one receive of `maxReceiveCount` by default.

`opskit.shutdown.install_stop_signals` is what the consumer uses. SIGINT and SIGTERM set a `threading.Event`. There is no CLI. Handlers can only be installed on the main thread.

## MSK and Kafka

**`opskit.aws_msk`.** One-line purpose: Kafka producer, consumer, and topic helpers for Amazon MSK, using kafka-python because it is pure Python and tests can fake it without a broker or librdkafka. Extras: `opskit[kafka]`, and `opskit[msk]` when minting IAM tokens. No CLI. Longer notes: [docs/kafka.md](docs/kafka.md).

Importing the module does not import `kafka`. Constructing a real client without the extra raises `KafkaDependencyError`.

```python
from opskit.aws_msk import KafkaConfig, KafkaConsumer, KafkaProducer, ensure_topics
from opskit.safety import ChangeBudget

config = KafkaConfig.for_sasl_tls("b-1.example.com:9096", "ops", password)
# MSK IAM: KafkaConfig.for_msk_iam(brokers, "us-east-1", session=session)
# or KafkaConfig.for_msk_iam_role(brokers, "us-east-1", "123456789012", "OrgOps")

with KafkaProducer(config) as producer:
    producer.send_json("events", {"job": "cleanup"}, key="vol-123")

with KafkaConsumer(config, "events", group_id="ops") as consumer:
    consumer.consume(lambda record: handle(record.value))

ensure_topics(
    ["events"],
    config=config,
    replication_factor=3,
    budget=ChangeBudget(apply=True),
)
```

The consumer turns auto-commit off and commits the next offset only after the handler returns. A handler error does not commit that record. Topic creation is dry-run unless the budget applies. `replication_factor` defaults to 2.

## Inventory, insights, Lambda, and checks

**`opskit.inventory`.** One-line purpose: collect tagged resources through the Resource Groups Tagging API and write JSON, or Excel with the `excel` extra. No CLI of its own; `opsclient aws` calls it through the API. Terraform workspace, project, and module names are inferred from tags. Untagged resources are not guaranteed to appear.

```python
from opskit.inventory import collect_account_inventory, write_inventory_json

inventory = collect_account_inventory(profile_name="personal", regions=["us-east-1"])
write_inventory_json(inventory, "aws-inventory.json")
```

The caller needs `ec2:DescribeRegions` when regions are discovered, `sts:GetCallerIdentity`, and `tag:GetResources` in each region.

**`opskit.resource_insights`.** One-line purpose: service health, child counts, and CloudWatch metrics for inventory rows. No extra. No CLI.

```python
from opskit.resource_insights import (
    get_basic_resource_metrics,
    get_child_resource_type_counts,
    get_resource_health,
)

resource = inventory["resources"][0]
health = get_resource_health(resource)
children = get_child_resource_type_counts(resource)
metrics = get_basic_resource_metrics(resource, lookback_hours=24)
```

Reads used: `ec2:DescribeInstanceStatus`, `ec2:DescribeInstances`, `ec2:DescribeVolumeStatus`, `rds:DescribeDBInstances`, `rds:DescribeDBClusters`, `lambda:GetFunctionConfiguration`, and `cloudwatch:GetMetricStatistics`. Health covers EC2 instances and volumes, RDS instances, and Lambda. Child counts cover EC2 instances and RDS clusters.

**`opskit.aws_lambda`.** One-line purpose: build a deployment zip and update runtime or code only when the budget applies. No extra. No CLI. Native extensions must be built for the Lambda OS and architecture.

```python
from opskit.aws_lambda import build_deployment_package, update_code, update_runtime
from opskit.safety import ChangeBudget

package = build_deployment_package("function", "function.zip", "function/requirements.txt")
budget = ChangeBudget(apply=True, max_changes=2)
update_runtime(lambda_client, "my-function", "python3.12", budget)
update_code(lambda_client, "my-function", package, budget)
```

**`opskit.checks`.** One-line purpose: register checks and turn a report into a CI exit code. No extra. No CLI. `0` means clean, `1` means findings at or above `fail_on`, `2` means a check crashed. `examples/aws_checks.py` is the sample gate.

```bash
python examples/aws_checks.py --region us-west-2 --fail-on high
python examples/ebs_cleanup.py --accounts 111111111111 --role OrgOps
python examples/ebs_cleanup.py --accounts 111111111111 --role OrgOps --apply --max-changes 20
```

**`opskit.metrics`.** One-line purpose: record job duration, success, and last-success time, and push them when a Pushgateway is set. Extra: `opskit[metrics]`. No CLI. A push failure is logged and does not fail the job.

```python
from opskit.metrics import job_metrics

with job_metrics("ebs-cleanup", pushgateway="http://pushgateway:9091"):
    run()
```

**`opskit.notify`.** One-line purpose: POST a text payload to the webhook URL in `OPS_WEBHOOK_URL` (or another env var). No extra. No CLI. Returns false when the variable is unset. POST is not retried by `build_session`.

```python
from opskit.notify import notify

notify("cleanup finished", deleted=3)
```

## Kubernetes and the opsclient CLI

**`opskit.k8s`.** One-line purpose: load an in-cluster or kubeconfig client and list or mutate workloads. Extra: `opskit[k8s]`. No CLI of its own. List calls default to a 30-second timeout. The identity needs `list` on namespaces, pods, and events, and `get` on `pods/log`.

```python
from opskit.k8s import get_pod_logs, list_events, list_namespaces, list_pods, load_clients

core, apps = load_clients()
namespaces = list_namespaces(core)
pods = list_pods(core, namespace="default", label_selector="app=api")
events = list_events(core, namespace="default", field_selector="type=Warning")
logs = get_pod_logs(core, "api-123", "default", container="api", tail_lines=100)
```

`rollout_restart` and `wait_for_rollout` update a deployment annotation and poll until the rollout finishes. `unhealthy_pods` returns `(namespace, name, reason)`.

**`opskit.api`.** One-line purpose: a FastAPI app for inventory, insights, and the Kubernetes helpers. Extra: `opskit[api]`, plus `opskit[k8s]` for the Kubernetes routes. No authentication. Bind it to localhost unless something else authenticates it.

Routes: `GET /health`, `POST /aws/inventory`, `POST /aws/insights`, and `/kubernetes` for namespaces, pods, events, unhealthy pods, logs, rollout status, and restart.

**`opskit.clients`.** One-line purpose: the AWS, inventory, and resource-insight helpers grouped for those routes. `clients.aws` re-exports `assume_role_session`, `client`, `create_session`, and `paginate`. No CLI.

**`opsclient`.** Console script `opsclient`, implemented in `src/opsclient/cli.py`. It talks to `OPSKIT_API_URL`, default `http://127.0.0.1:8000`.

```bash
opsclient serve --host 127.0.0.1 --port 8000
opsclient aws --profile personal --region us-east-1 --json aws-inventory.json
opsclient k8s namespaces
opsclient k8s pods --namespace default --label-selector app=api
opsclient k8s events --namespace default --field-selector type=Warning
opsclient k8s unhealthy-pods --namespace default
opsclient k8s logs api-123 --namespace default --container api --tail-lines 100
opsclient k8s rollout-status api --namespace default
opsclient k8s restart api --namespace default
```

`aws` is also available as `inventory`. Credentials come from boto3 (`aws configure --profile personal` or another supported source). opskit does not store secrets.

The Kubernetes triage UI is a separate package, [src/dashboard/README.md](src/dashboard/README.md):

```bash
python -m dashboard demo
python -m dashboard live --context kind-hcd
python -m dashboard serve --port 8090
```

## Data-structure samples and wrappers

`src/data-structures/` holds 37 interview samples (heaps, caches, intervals, graphs, logs) plus eight short AIOps drills. The file list, SRE notes, and how to run each sample are in [src/data-structures/README.md](src/data-structures/README.md) and [src/data-structures/aiops-mock-interview/README.md](src/data-structures/aiops-mock-interview/README.md). The samples are not an installable extra and have no opskit CLI.

**`wrappers.py`.** One-line purpose: standard-library helpers for the patterns those samples repeat. `FakeClock` injects time. `TTLCache` / `ttl_cache` expire entries and can bound size like an LRU. `TopK` / `top_k` keep the k largest items in O(k) memory. No extra. No CLI beyond the demo.

```bash
python src/data-structures/wrappers.py
python src/data-structures/tests/test_wrappers.py
```

```python
from wrappers import FakeClock, TTLCache, top_k

clock = FakeClock()
cache = TTLCache(ttl=60, clock=clock)
cache.get_or_compute("req-1", lambda: "vol-1")
clock.advance(61)

top = top_k([("a", 3), ("b", 9), ("c", 1)], 2, key=lambda item: item[1])
```

Run that import from `src/data-structures`, or put that directory on `PYTHONPATH`. The 37 sample files are left unchanged; the wrappers are the reusable form.
