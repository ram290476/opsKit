import importlib
import sys
import threading
import time
import types

import pytest

from opskit.aws_msk import (
    KafkaConfig,
    KafkaConsumer,
    KafkaDependencyError,
    KafkaProducer,
    OAuthTokenProvider,
    adapt_token_provider,
    ensure_topics,
    list_topics,
    msk_iam_token,
)
from opskit.safety import ChangeBudget


class FakeFuture:
    def __init__(self, topic, offset):
        self.topic = topic
        self.partition = 0
        self.offset = offset

    def get(self, timeout=None):
        return self


class FakeProducer:
    def __init__(self, fail_once=False):
        self.sent = []
        self.fail_once = fail_once
        self.flushed = False
        self.closed = False

    def send(self, topic, value=None, key=None, headers=None, partition=None):
        if self.fail_once:
            self.fail_once = False
            error = type("KafkaTimeoutError", (Exception,), {})("timeout")
            raise error
        self.sent.append({"topic": topic, "value": value, "key": key, "headers": headers, "partition": partition})
        return FakeFuture(topic, len(self.sent) - 1)

    def flush(self, timeout=None):
        self.flushed = True

    def close(self, timeout=None):
        self.closed = True


class Record:
    def __init__(self, topic, partition, offset, value, key=None, headers=None):
        self.topic = topic
        self.partition = partition
        self.offset = offset
        self.value = value
        self.key = key
        self.headers = headers or []
        self.timestamp = 10


class FakeConsumer:
    def __init__(self, records):
        self.records = list(records)
        self.commits = []
        self.closed = False
        self.polls = 0

    def poll(self, timeout_ms=0, max_records=1):
        self.polls += 1
        if not self.records:
            return {}
        record = self.records.pop(0)
        return {(record.topic, record.partition): [record]}

    def commit(self, offsets=None):
        self.commits.append(offsets)

    def close(self):
        self.closed = True


class FakeAdmin:
    def __init__(self, topics):
        self.topics = set(topics)
        self.created = []
        self.closed = False

    def list_topics(self):
        return list(self.topics)

    def create_topics(self, topics):
        self.created.append(topics)
        self.topics.update(topics)

    def close(self):
        self.closed = True


def test_sasl_tls_and_msk_iam_config():
    sasl = KafkaConfig.for_sasl_tls("b-1:9096", "user", "secret", ssl_cafile="/tmp/ca.pem")
    sasl_kwargs = sasl.client_kwargs()
    assert sasl_kwargs["security_protocol"] == "SASL_SSL"
    assert sasl_kwargs["sasl_mechanism"] == "SCRAM-SHA-512"
    assert sasl_kwargs["sasl_plain_username"] == "user"
    assert sasl_kwargs["sasl_plain_password"] == "secret"
    assert sasl_kwargs["ssl_cafile"] == "/tmp/ca.pem"

    provider = OAuthTokenProvider(lambda: "tok")
    iam = KafkaConfig.for_msk_iam(["b-1.kafka.us-east-1.amazonaws.com:9098"], "us-east-1", token_provider=provider)
    iam_kwargs = iam.client_kwargs()
    assert iam_kwargs["security_protocol"] == "SASL_SSL"
    assert iam_kwargs["sasl_mechanism"] == "OAUTHBEARER"
    assert iam_kwargs["sasl_oauth_token_provider"].token() == "tok"
    assert "sasl_plain_password" not in iam_kwargs
    with pytest.raises(ValueError):
        KafkaConfig("localhost:9092", security_protocol="TELNET")


def test_msk_iam_role_uses_assume_role_and_caches_signer_tokens(monkeypatch):
    sentinel = object()

    def fake_assume(account_id, role_name, session_name="opskit", **kwargs):
        assert account_id == "123456789012"
        assert role_name == "OrgOps"
        assert session_name == "opskit"
        return sentinel

    monkeypatch.setattr("opskit.aws.assume_role_session", fake_assume)
    config = KafkaConfig.for_msk_iam_role("b-1:9098", "us-east-1", "123456789012", "OrgOps")
    assert config.session is sentinel
    assert config.token_provider.session is sentinel

    calls = {"n": 0}
    cached = KafkaConfig.for_msk_iam("b-1:9098", "us-east-1")

    class Provider:
        @staticmethod
        def generate_auth_token(region):
            calls["n"] += 1
            assert region == "us-east-1"
            return ("token-us-east-1", int(time.time() * 1000) + 900_000)

        @staticmethod
        def generate_auth_token_from_credentials(region, access_key, secret_key, token):
            return (f"{region}:{access_key}:{secret_key}:{token}", 1_700_000_000)

    module = types.ModuleType("aws_msk_iam_sasl_signer")
    module.MSKAuthTokenProvider = Provider
    monkeypatch.setitem(sys.modules, "aws_msk_iam_sasl_signer", module)
    assert cached.token_provider.token() == "token-us-east-1"
    assert cached.token_provider.token() == "token-us-east-1"
    assert calls["n"] == 1

    class Frozen:
        access_key = "AKIA"
        secret_key = "SECRET"
        token = "SESS"

    class Creds:
        def get_frozen_credentials(self):
            return Frozen()

    class Session:
        def get_credentials(self):
            return Creds()

    token, expiry = msk_iam_token("us-west-2", session=Session())
    assert token == "us-west-2:AKIA:SECRET:SESS"
    assert expiry == 1_700_000_000_000


def test_missing_kafka_dependency(monkeypatch):
    real = importlib.import_module

    def blocked(name, package=None):
        if name == "kafka" or name.startswith("kafka."):
            raise ImportError("blocked")
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", blocked)
    with pytest.raises(KafkaDependencyError):
        KafkaProducer(KafkaConfig("localhost:9092"))


def test_oauth_provider_matches_kafka_python_contract():
    pytest.importorskip("kafka")
    provider = adapt_token_provider(OAuthTokenProvider(lambda: "abc"))
    base = importlib.import_module("kafka.net.sasl.oauth").AbstractTokenProvider
    assert isinstance(provider, base)
    assert provider.token() == "abc"
    assert provider.extensions() == {}


def test_producer_json_retry_and_close():
    fake = FakeProducer(fail_once=True)
    sleeps = []
    with KafkaProducer(KafkaConfig("localhost:9092"), producer=fake, sleep=sleeps.append) as producer:
        result = producer.send_json("events", {"a": 1}, key="k", headers={"kind": "sync"})
    assert result.topic == "events"
    assert result.offset == 0
    assert fake.sent[0]["value"] == b'{"a":1}'
    assert fake.sent[0]["key"] == b"k"
    assert fake.sent[0]["headers"] == [("kind", b"sync")]
    assert sleeps
    assert fake.flushed and fake.closed

    plain = FakeProducer()
    producer = KafkaProducer(KafkaConfig("localhost:9092"), producer=plain, sleep=lambda _: None)
    producer.send("events", b"\xff", key=None)
    assert plain.sent[0]["value"] == b"\xff"

    class Permanent(FakeProducer):
        def send(self, topic, value=None, key=None, headers=None, partition=None):
            raise ValueError("bad input")

    with pytest.raises(ValueError):
        KafkaProducer(KafkaConfig("localhost:9092"), producer=Permanent(), sleep=lambda _: None).send("t", "x")


def test_consumer_commits_successes_and_stops_on_error_or_shutdown():
    records = [
        Record("events", 0, 0, b'{"n":1}', key=b"a", headers=[("h", b"v")]),
        Record("events", 0, 1, b'{"n":2}'),
        Record("events", 0, 2, b"not-json"),
    ]
    fake = FakeConsumer(records)
    consumer = KafkaConsumer(KafkaConfig("localhost:9092"), "events", "ops", consumer=fake, sleep=lambda _: None)
    seen = []
    stop = threading.Event()

    def handler(record):
        seen.append(record.value)
        if record.offset == 0:
            assert record.key == "a"
            assert record.headers == (("h", b"v"),)
            stop.set()

    stopped = consumer.consume(handler, stop_event=stop, poll_timeout_ms=0, install_signals=False)
    assert stopped.processed == 1
    assert stopped.committed == 1
    assert fake.commits == [{("events", 0): 1}]

    failing = FakeConsumer([Record("events", 1, 4, b'{"n":9}')])
    consumer = KafkaConsumer(
        KafkaConfig("localhost:9092"),
        ["events"],
        "ops",
        consumer=failing,
        sleep=lambda _: None,
    )

    def fail(_record):
        raise RuntimeError("bad record")

    failed = consumer.consume(fail, poll_timeout_ms=0, install_signals=False, limit=5)
    assert failed.processed == 0
    assert failed.failed == 1
    assert failed.committed == 0
    assert failing.commits == []

    draining = FakeConsumer([Record("events", 0, 3, b'"text"')])
    consumer = KafkaConsumer(KafkaConfig("localhost:9092"), "events", "ops", consumer=draining, sleep=lambda _: None)
    drained = consumer.consume(lambda record: seen.append(record.value), poll_timeout_ms=0, stop_on_empty=True, install_signals=False)
    assert drained.processed == 1
    assert seen[-1] == "text"
    consumer.close()
    assert draining.closed


def test_topic_helpers_honor_dry_run_and_apply():
    admin = FakeAdmin(["events"])
    assert list_topics(KafkaConfig("localhost:9092"), admin=admin) == ["events"]
    assert admin.closed is False

    dry = ensure_topics(
        ["events", "audit"],
        admin=admin,
        num_partitions=3,
        replication_factor=2,
        budget=ChangeBudget(apply=False),
    )
    assert dry.existing == ["events"]
    assert dry.planned == ["audit"]
    assert dry.created == []
    assert admin.created == []

    applied = ensure_topics(
        ["events", "audit"],
        admin=admin,
        num_partitions=3,
        replication_factor=2,
        budget=ChangeBudget(apply=True),
    )
    assert applied.created == ["audit"]
    assert admin.created == [{"audit": {"num_partitions": 3, "replication_factor": 2}}]
    assert "audit" in admin.topics
    with pytest.raises(ValueError):
        ensure_topics(["x"])
