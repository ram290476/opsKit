# MSK and Kafka

`opskit.msk` wraps a Kafka producer, consumer, and a small topic admin helper for Amazon MSK.

## Why kafka-python

The optional client is [kafka-python](https://github.com/dpkp/kafka-python), not `confluent-kafka`. kafka-python is pure Python. Tests inject a fake producer or consumer and never open a socket, and installs do not need librdkafka. `confluent-kafka` is the faster production client, but it is a C extension, which makes this repo's offline tests heavier. MSK IAM (SASL_SSL + OAUTHBEARER) and SASL/TLS (SCRAM or PLAIN over TLS) are both settings kafka-python already accepts.

The dependency is optional. Importing `opskit.msk` does not import `kafka`. Building a real client without the extra raises `KafkaDependencyError`.

```bash
pip install 'opskit[kafka]'   # kafka-python
pip install 'opskit[msk]'     # kafka-python + aws-msk-iam-sasl-signer-python
```

`opskit[msk]` is only required when the process mints MSK IAM tokens itself. Tests and apps that pass a `token_provider` do not need the signer.

## SASL/TLS and MSK IAM

```python
from opskit.aws import assume_role_session
from opskit.msk import KafkaConfig, KafkaConsumer, KafkaProducer

scram = KafkaConfig.for_sasl_tls(
    "b-1.example.com:9096",
    username="ops",
    password=password,
    mechanism="SCRAM-SHA-512",
    ssl_cafile="/etc/ssl/certs/ca-bundle.crt",
)

session = assume_role_session("123456789012", "OrgOps")
iam = KafkaConfig.for_msk_iam(
    ["b-1.kafka.us-east-1.amazonaws.com:9098"],
    "us-east-1",
    session=session,
)
# or: KafkaConfig.for_msk_iam_role(brokers, "us-east-1", "123456789012", "OrgOps")
# or: KafkaConfig.for_msk_iam(brokers, "us-east-1", token_provider=my_provider)
```

`for_msk_iam` uses SASL_SSL and OAUTHBEARER. The token provider reuses a signer token until a minute before it expires. `for_msk_iam_role` calls `assume_role_session` and feeds those credentials to the signer. A custom provider only needs `token()` returning a string. The real client adapts it to kafka-python's `AbstractTokenProvider`.

`client_kwargs()` is the dict passed to kafka-python, before that adaptation. `extra` is merged last for settings this helper does not model.

## Producer and consumer

```python
from opskit.msk import KafkaProducer, KafkaConsumer

with KafkaProducer(iam) as producer:
    producer.send_json("events", {"job": "cleanup"}, key="vol-123", headers={"kind": "ebs"})

def handle(record):
    print(record.topic, record.offset, record.value)

with KafkaConsumer(iam, "events", group_id="ops") as consumer:
    consumer.consume(handle, poll_timeout_ms=1000)
```

`send` writes bytes as-is, encodes `str` as UTF-8, and JSON-encodes other objects. `send_json` always JSON-encodes, so a string becomes a JSON string. `None` is a tombstone. Keys are UTF-8 strings or bytes. Transient client errors (`KafkaTimeoutError`, connection errors, and errors with `retriable=True`) use `opskit.retry.retry`. The produce path is at-least-once: a timeout after the broker accepted the record can send it again.

The consumer sets `enable_auto_commit=False` and `auto_offset_reset="earliest"`. It polls one record at a time and commits `offset + 1` only after the handler returns. A handler error does not commit that offset. The default `stop_on_error=True` then stops the loop so a later commit cannot skip the failed record. `stop_on_empty=True` returns after the first empty poll; leave it false for a long-running consumer. SIGINT and SIGTERM set the stop event unless `install_signals=False`. Pass `stop_event` to stop from another thread.

`ConsumeResult` reports `processed`, `committed`, and `failed`.

## Topics

Topic creation is dry-run unless the budget is applying changes. `replication_factor` defaults to 2; set 3 for a typical MSK cluster.

```python
from opskit.msk import ensure_topics, list_topics
from opskit.safety import ChangeBudget

print(list_topics(iam))
plan = ensure_topics(
    ["events", "audit"],
    config=iam,
    num_partitions=3,
    replication_factor=3,
    budget=ChangeBudget(apply=True, max_changes=5),
)
print(plan.existing, plan.created, plan.planned)
```

A dry-run lists missing names on `planned` and does not call `create_topics`.
