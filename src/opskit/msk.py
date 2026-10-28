"""Kafka producer and consumer aimed at Amazon MSK.

``kafka-python`` is the client. It is pure Python, so this wrapper can be
tested with fakes and does not need librdkafka or a broker. ``confluent-kafka``
is faster in production but is a native extension, which makes install and
unit tests heavier. The import is lazy: installing opskit without the extra
still works, and constructing a real client raises :class:`KafkaDependencyError`
until ``pip install 'opskit[kafka]'``.

MSK IAM auth is SASL_SSL with OAUTHBEARER. The token provider is adapted to
``kafka-python``'s abstract provider when a real client is built. Token minting
uses ``aws-msk-iam-sasl-signer-python`` (``opskit[msk]``) unless a
``token_provider`` is passed in. SASL/TLS (SCRAM or PLAIN over TLS) is the
other built-in config.

The consumer turns auto-commit off and commits the next offset only after the
handler returns. A handler error does not commit that record, so a restart
redelivers it. Topic creation is dry-run unless a :class:`~opskit.safety.ChangeBudget`
has ``apply=True``.
"""
from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .retry import is_transient, retry
from .safety import ChangeBudget
from .shutdown import install_stop_signals

log = logging.getLogger(__name__)

_INSTALL = "Kafka support requires kafka-python. Install it with: pip install 'opskit[kafka]'"
_SIGNER = (
    "MSK IAM auth requires aws-msk-iam-sasl-signer-python. "
    "Install opskit[msk] or pass token_provider= to KafkaConfig.for_msk_iam."
)
_PROTOCOLS = {"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"}
_MECHANISMS = {"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512", "OAUTHBEARER", "GSSAPI"}
_RETRYABLE_NAMES = {
    "KafkaTimeoutError",
    "KafkaConnectionError",
    "RequestTimedOutError",
    "LeaderNotAvailableError",
    "NotLeaderForPartitionError",
    "NodeNotReadyError",
    "NoBrokersAvailable",
}


class KafkaDependencyError(RuntimeError):
    """An optional Kafka or MSK IAM dependency is not installed."""


def _kafka_retryable(exc: BaseException) -> bool:
    if is_transient(exc):
        return True
    if type(exc).__name__ in _RETRYABLE_NAMES:
        return True
    return bool(getattr(exc, "retriable", False))


def _load_kafka() -> Any:
    try:
        module = importlib.import_module("kafka")
    except ImportError as exc:
        raise KafkaDependencyError(_INSTALL) from exc
    if not hasattr(module, "KafkaProducer"):
        raise KafkaDependencyError(_INSTALL)
    return module


def _token_provider_type(module: Any) -> type:
    try:
        oauth = importlib.import_module("kafka.net.sasl.oauth")
        return oauth.AbstractTokenProvider
    except ImportError:
        oauth = importlib.import_module("kafka.oauth.abstract")
        return oauth.AbstractTokenProvider


def adapt_token_provider(provider: Any, module: Any | None = None) -> Any:
    """Return a provider ``kafka-python`` accepts for SASL OAUTHBEARER."""
    module = module or _load_kafka()
    base = _token_provider_type(module)
    if isinstance(provider, base):
        return provider

    class _Adapter(base):  # type: ignore[misc, valid-type]
        def token(self) -> str:
            if callable(getattr(provider, "token", None)):
                return provider.token()
            if callable(provider):
                return provider()
            raise TypeError("token provider must be callable or implement token()")

        def extensions(self) -> dict[str, str]:
            extensions = getattr(provider, "extensions", None)
            return dict(extensions()) if callable(extensions) else {}

    return _Adapter()


class OAuthTokenProvider:
    """Callable token source that does not import ``kafka-python``."""

    def __init__(self, token_fn: Callable[[], str]):
        self._token_fn = token_fn

    def token(self) -> str:
        return self._token_fn()

    def extensions(self) -> dict[str, str]:
        return {}


def _expiry_ms(expiry: int) -> int:
    value = int(expiry)
    if value < 10**12:
        return value * 1000
    return value


def msk_iam_token(region: str, *, session: Any = None) -> tuple[str, int]:
    """Mint an MSK IAM auth token. Returns ``(token, expiry_epoch_ms)``."""
    try:
        signer = importlib.import_module("aws_msk_iam_sasl_signer")
    except ImportError as exc:
        raise KafkaDependencyError(_SIGNER) from exc
    provider = signer.MSKAuthTokenProvider
    if session is None:
        token, expiry = provider.generate_auth_token(region)
        return token, _expiry_ms(expiry)
    creds = session.get_credentials()
    if creds is None:
        raise RuntimeError("boto3 session has no credentials")
    frozen = creds.get_frozen_credentials()
    token, expiry = provider.generate_auth_token_from_credentials(
        region,
        frozen.access_key,
        frozen.secret_key,
        frozen.token,
    )
    return token, _expiry_ms(expiry)


class _MskIamTokenProvider:
    """Reuse an MSK IAM token until shortly before it expires."""

    def __init__(self, region: str, session: Any = None):
        self.region = region
        self.session = session
        self._token: str | None = None
        self._expiry_ms = 0

    def token(self) -> str:
        now_ms = int(time.time() * 1000)
        if self._token is not None and now_ms < self._expiry_ms - 60_000:
            return self._token
        token, expiry = msk_iam_token(self.region, session=self.session)
        self._token = token
        self._expiry_ms = expiry
        return token


def _encode_key(key: Any) -> bytes | None:
    if key is None:
        return None
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        return key.encode()
    raise TypeError("key must be bytes, str, or None")


def _encode_value(value: Any, *, as_json: bool) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)) and not as_json:
        return bytes(value)
    if isinstance(value, str) and not as_json:
        return value.encode()
    return json.dumps(value, default=str, separators=(",", ":")).encode()


def _decode_value(raw: Any) -> Any:
    if raw is None or isinstance(raw, (dict, list, int, float, bool)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            text = bytes(raw).decode()
        except UnicodeDecodeError:
            return bytes(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return raw


def _encode_headers(headers: Mapping[str, str | bytes] | None) -> list[tuple[str, bytes]] | None:
    if not headers:
        return None
    encoded: list[tuple[str, bytes]] = []
    for key, value in headers.items():
        encoded.append((str(key), value.encode() if isinstance(value, str) else value))
    return encoded


def _decode_key(key: Any) -> Any:
    if isinstance(key, (bytes, bytearray)):
        return bytes(key).decode(errors="replace")
    return _decode_value(key)


def _decode_headers(headers: Any) -> tuple[tuple[str, bytes], ...]:
    if not headers:
        return ()
    decoded: list[tuple[str, bytes]] = []
    for item in headers:
        if isinstance(item, tuple) and len(item) == 2:
            key, value = item
            if isinstance(value, str):
                value = value.encode()
            elif value is None:
                value = b""
            decoded.append((str(key), value))
    return tuple(decoded)


def _normalize_poll(result: Any) -> list[Any]:
    if result is None:
        return []
    if isinstance(result, Mapping):
        records: list[Any] = []
        for batch in result.values():
            records.extend(batch or [])
        return records
    if isinstance(result, (list, tuple)):
        return list(result)
    return [result]


@dataclass
class KafkaConfig:
    """Connection settings shared by producers, consumers, and the admin client."""

    bootstrap_servers: str | Sequence[str]
    security_protocol: str = "PLAINTEXT"
    sasl_mechanism: str | None = None
    sasl_username: str | None = None
    sasl_password: str | None = None
    token_provider: Any = None
    ssl_cafile: str | None = None
    ssl_check_hostname: bool = True
    client_id: str = "opskit"
    region: str | None = None
    session: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.security_protocol not in _PROTOCOLS:
            raise ValueError(f"security_protocol must be one of {sorted(_PROTOCOLS)}")
        if self.sasl_mechanism is not None and self.sasl_mechanism not in _MECHANISMS:
            raise ValueError(f"sasl_mechanism must be one of {sorted(_MECHANISMS)}")

    def client_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for a ``kafka-python`` client, before OAUTH adaptation."""
        kwargs: dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "security_protocol": self.security_protocol,
            "client_id": self.client_id,
        }
        if "SSL" in self.security_protocol:
            kwargs["ssl_check_hostname"] = self.ssl_check_hostname
            if self.ssl_cafile:
                kwargs["ssl_cafile"] = self.ssl_cafile
        if self.sasl_mechanism:
            kwargs["sasl_mechanism"] = self.sasl_mechanism
        if self.sasl_username is not None:
            kwargs["sasl_plain_username"] = self.sasl_username
            kwargs["sasl_plain_password"] = self.sasl_password or ""
        if self.token_provider is not None:
            kwargs["sasl_oauth_token_provider"] = self.token_provider
        kwargs.update(self.extra)
        return kwargs

    @classmethod
    def for_sasl_tls(
        cls,
        bootstrap_servers: str | Sequence[str],
        username: str,
        password: str,
        *,
        mechanism: str = "SCRAM-SHA-512",
        ssl_cafile: str | None = None,
        **kwargs: Any,
    ) -> KafkaConfig:
        """SASL over TLS. MSK SCRAM listeners use ``SCRAM-SHA-512`` by default."""
        return cls(
            bootstrap_servers=bootstrap_servers,
            security_protocol="SASL_SSL",
            sasl_mechanism=mechanism,
            sasl_username=username,
            sasl_password=password,
            ssl_cafile=ssl_cafile,
            **kwargs,
        )

    @classmethod
    def for_msk_iam(
        cls,
        bootstrap_servers: str | Sequence[str],
        region: str,
        *,
        session: Any = None,
        token_provider: Any = None,
        ssl_cafile: str | None = None,
        **kwargs: Any,
    ) -> KafkaConfig:
        """SASL_SSL plus OAUTHBEARER for MSK IAM authentication.

        ``session`` is a boto3 session, including one returned by
        :func:`opskit.aws.assume_role_session`. ``token_provider`` skips the
        signer package entirely.
        """
        provider = token_provider if token_provider is not None else _MskIamTokenProvider(region, session)
        return cls(
            bootstrap_servers=bootstrap_servers,
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            token_provider=provider,
            ssl_cafile=ssl_cafile,
            region=region,
            session=session,
            **kwargs,
        )

    @classmethod
    def for_msk_iam_role(
        cls,
        bootstrap_servers: str | Sequence[str],
        region: str,
        account_id: str,
        role_name: str,
        *,
        session_name: str = "opskit",
        **kwargs: Any,
    ) -> KafkaConfig:
        """Assume ``role_name`` in ``account_id`` and use those credentials for MSK IAM."""
        from .aws import assume_role_session

        session = assume_role_session(account_id, role_name, session_name=session_name)
        return cls.for_msk_iam(bootstrap_servers, region, session=session, **kwargs)


@dataclass(frozen=True)
class SendResult:
    """Broker metadata for one acknowledged produce."""

    topic: str
    partition: int | None = None
    offset: int | None = None


@dataclass(frozen=True)
class KafkaRecord:
    """One decoded consumer record."""

    topic: str
    partition: int
    offset: int
    key: Any
    value: Any
    headers: tuple[tuple[str, bytes], ...] = ()
    timestamp: int | None = None


@dataclass(frozen=True)
class ConsumeResult:
    """How many records a consumer handled, committed, or failed."""

    processed: int = 0
    committed: int = 0
    failed: int = 0


@dataclass(frozen=True)
class TopicResult:
    """Topics already present, topics created, and topics a dry-run would create."""

    existing: list[str]
    created: list[str]
    planned: list[str]


def _retry_call(fn: Callable[[], Any], *, attempts: int, base: float, cap: float, sleep: Any) -> Any:
    decorated = retry(
        attempts=attempts,
        base=base,
        cap=cap,
        when=_kafka_retryable,
        **({"sleep": sleep} if sleep is not None else {}),
    )(fn)
    return decorated()


class _RealProducer:
    def __init__(self, raw: Any):
        self.raw = raw

    def send(self, topic: str, value: bytes | None = None, key: bytes | None = None,
             headers: list[tuple[str, bytes]] | None = None, partition: int | None = None) -> Any:
        return self.raw.send(topic, value=value, key=key, headers=headers, partition=partition)

    def flush(self, timeout: float | None = None) -> Any:
        return self.raw.flush(timeout=timeout)

    def close(self, timeout: float | None = None) -> None:
        self.raw.close(timeout=timeout)


class _RealConsumer:
    def __init__(self, raw: Any):
        self.raw = raw

    def poll(self, timeout_ms: int = 0, max_records: int | None = None) -> Any:
        return self.raw.poll(timeout_ms=timeout_ms, max_records=max_records)

    def commit(self, offsets: Mapping[tuple[str, int], int] | None = None) -> None:
        if offsets is None:
            self.raw.commit()
            return
        module = _load_kafka()
        structs = importlib.import_module("kafka.structs")
        payload = {}
        for (topic, partition), offset in offsets.items():
            payload[module.TopicPartition(topic, partition)] = structs.OffsetAndMetadata(offset, "")
        self.raw.commit(payload)

    def close(self) -> None:
        self.raw.close()


class _RealAdmin:
    def __init__(self, raw: Any):
        self.raw = raw

    def list_topics(self) -> list[str]:
        return list(self.raw.list_topics())

    def create_topics(self, topics: Mapping[str, Mapping[str, Any]]) -> None:
        module = _load_kafka()
        version = tuple(int(part) for part in str(getattr(module, "__version__", "2")).split(".")[:2] if part.isdigit())
        if version >= (3, 0):
            self.raw.create_topics(dict(topics), timeout_ms=30_000)
            return
        admin_mod = importlib.import_module("kafka.admin")
        new_topics = [
            admin_mod.NewTopic(
                name=name,
                num_partitions=int(options.get("num_partitions", 1)),
                replication_factor=int(options.get("replication_factor", 1)),
            )
            for name, options in topics.items()
        ]
        self.raw.create_topics(new_topics, timeout_ms=30_000)

    def close(self) -> None:
        self.raw.close()


def _connect_producer(config: KafkaConfig) -> _RealProducer:
    module = _load_kafka()
    kwargs = config.client_kwargs()
    if "sasl_oauth_token_provider" in kwargs:
        kwargs["sasl_oauth_token_provider"] = adapt_token_provider(kwargs["sasl_oauth_token_provider"], module)
    kwargs.setdefault("acks", "all")
    kwargs.setdefault("retries", 3)
    return _RealProducer(module.KafkaProducer(**kwargs))


def _connect_consumer(config: KafkaConfig, topics: Sequence[str], group_id: str) -> _RealConsumer:
    module = _load_kafka()
    kwargs = config.client_kwargs()
    if "sasl_oauth_token_provider" in kwargs:
        kwargs["sasl_oauth_token_provider"] = adapt_token_provider(kwargs["sasl_oauth_token_provider"], module)
    kwargs["group_id"] = group_id
    kwargs["enable_auto_commit"] = False
    kwargs.setdefault("auto_offset_reset", "earliest")
    return _RealConsumer(module.KafkaConsumer(*topics, **kwargs))


def _connect_admin(config: KafkaConfig) -> _RealAdmin:
    module = _load_kafka()
    kwargs = config.client_kwargs()
    if "sasl_oauth_token_provider" in kwargs:
        kwargs["sasl_oauth_token_provider"] = adapt_token_provider(kwargs["sasl_oauth_token_provider"], module)
    return _RealAdmin(module.KafkaAdminClient(**kwargs))


class KafkaProducer:
    """Publish bytes or JSON. Pass ``producer`` to inject a fake in tests."""

    def __init__(
        self,
        config: KafkaConfig,
        *,
        producer: Any = None,
        attempts: int = 5,
        retry_base: float = 0.5,
        retry_cap: float = 30.0,
        sleep: Callable[[float], None] | None = None,
    ):
        self.config = config
        self.attempts = attempts
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self._sleep = sleep
        self._producer = producer if producer is not None else _connect_producer(config)

    def send(
        self,
        topic: str,
        value: Any,
        *,
        key: Any = None,
        headers: Mapping[str, str | bytes] | None = None,
        partition: int | None = None,
        timeout: float = 30,
        as_json: bool = False,
    ) -> SendResult:
        """Send one record and wait for the broker ack. Retries transient client errors."""
        payload = _encode_value(value, as_json=as_json)
        key_bytes = _encode_key(key)
        header_list = _encode_headers(headers)

        def _do() -> Any:
            future = self._producer.send(
                topic,
                value=payload,
                key=key_bytes,
                headers=header_list,
                partition=partition,
            )
            if hasattr(future, "get"):
                return future.get(timeout=timeout)
            return future

        meta = _retry_call(_do, attempts=self.attempts, base=self.retry_base, cap=self.retry_cap, sleep=self._sleep)
        return SendResult(
            topic=str(getattr(meta, "topic", topic)),
            partition=getattr(meta, "partition", None),
            offset=getattr(meta, "offset", None),
        )

    def send_json(
        self,
        topic: str,
        value: Any,
        *,
        key: Any = None,
        headers: Mapping[str, str | bytes] | None = None,
        partition: int | None = None,
        timeout: float = 30,
    ) -> SendResult:
        """JSON-encode ``value`` and send it. ``str`` values become JSON strings."""
        return self.send(
            topic,
            value,
            key=key,
            headers=headers,
            partition=partition,
            timeout=timeout,
            as_json=True,
        )

    def flush(self, timeout: float | None = None) -> None:
        """Block until buffered records are sent."""
        flush = getattr(self._producer, "flush", None)
        if callable(flush):
            flush(timeout=timeout)

    def close(self, timeout: float | None = None) -> None:
        """Flush and close the underlying producer."""
        self.flush(timeout)
        close = getattr(self._producer, "close", None)
        if callable(close):
            try:
                close(timeout=timeout)
            except TypeError:
                close()

    def __enter__(self) -> KafkaProducer:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False


class KafkaConsumer:
    """Poll a consumer group. Pass ``consumer`` to inject a fake in tests.

    The fake protocol is ``poll(timeout_ms, max_records)``, ``commit(offsets)``,
    and ``close()``. ``commit`` receives ``{(topic, partition): offset + 1}``.
    """

    def __init__(
        self,
        config: KafkaConfig,
        topics: str | Sequence[str],
        group_id: str,
        *,
        consumer: Any = None,
        attempts: int = 5,
        retry_base: float = 0.5,
        retry_cap: float = 30.0,
        sleep: Callable[[float], None] | None = None,
    ):
        if not group_id:
            raise ValueError("group_id is required")
        self.config = config
        self.topics = (topics,) if isinstance(topics, str) else tuple(topics)
        if not self.topics:
            raise ValueError("at least one topic is required")
        self.group_id = group_id
        self.attempts = attempts
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self._sleep = sleep
        self._consumer = consumer if consumer is not None else _connect_consumer(config, self.topics, group_id)

    def _to_record(self, raw: Any) -> KafkaRecord:
        if isinstance(raw, Mapping):
            topic = raw["topic"]
            partition = int(raw["partition"])
            offset = int(raw["offset"])
            key = raw.get("key")
            value = raw.get("value")
            headers = raw.get("headers")
            timestamp = raw.get("timestamp")
        else:
            topic = raw.topic
            partition = int(raw.partition)
            offset = int(raw.offset)
            key = getattr(raw, "key", None)
            value = getattr(raw, "value", None)
            headers = getattr(raw, "headers", None)
            timestamp = getattr(raw, "timestamp", None)
        return KafkaRecord(
            topic=str(topic),
            partition=partition,
            offset=offset,
            key=_decode_key(key),
            value=_decode_value(value),
            headers=_decode_headers(headers),
            timestamp=None if timestamp is None else int(timestamp),
        )

    def poll(self, timeout_ms: int = 1000, max_records: int = 1) -> list[KafkaRecord]:
        """Return the next decoded records. Transient poll errors are retried."""

        def _do() -> Any:
            return self._consumer.poll(timeout_ms=timeout_ms, max_records=max_records)

        raw = _retry_call(_do, attempts=self.attempts, base=self.retry_base, cap=self.retry_cap, sleep=self._sleep)
        return [self._to_record(item) for item in _normalize_poll(raw)]

    def commit(self, record: KafkaRecord | None = None) -> None:
        """Commit the next offset for ``record``, or the client's current offsets."""
        offsets = None if record is None else {(record.topic, record.partition): record.offset + 1}

        def _do() -> None:
            self._consumer.commit(offsets)

        _retry_call(_do, attempts=self.attempts, base=self.retry_base, cap=self.retry_cap, sleep=self._sleep)

    def consume(
        self,
        handler: Callable[[KafkaRecord], Any],
        *,
        poll_timeout_ms: int = 1000,
        limit: int | None = None,
        stop_on_empty: bool = False,
        stop_on_error: bool = True,
        commit: bool = True,
        stop_event: threading.Event | None = None,
        install_signals: bool = True,
    ) -> ConsumeResult:
        """Call ``handler`` until stopped. Commit only after a handler returns.

        ``stop_on_error`` leaves the failed offset uncommitted and ends the loop
        so a later commit cannot skip it. SIGINT and SIGTERM set the stop event
        when ``install_signals`` is true. An empty poll stops the loop only when
        ``stop_on_empty`` is set; a long-running consumer should leave that off
        and use ``stop_event`` or a signal.
        """
        stop_event = stop_event or threading.Event()
        restore = install_stop_signals(stop_event) if install_signals else (lambda: None)
        processed = 0
        committed = 0
        failed = 0
        log.info("kafka_consume_start", extra={"topics": ",".join(self.topics), "group_id": self.group_id})
        try:
            while not stop_event.is_set():
                if limit is not None and processed >= limit:
                    break
                records = self.poll(timeout_ms=poll_timeout_ms, max_records=1)
                if not records:
                    if stop_on_empty:
                        break
                    continue
                for record in records:
                    if stop_event.is_set():
                        break
                    try:
                        handler(record)
                    except Exception:
                        failed += 1
                        log.exception(
                            "kafka_handler_failed",
                            extra={"topic": record.topic, "offset": record.offset, "group_id": self.group_id},
                        )
                        if stop_on_error:
                            stop_event.set()
                            break
                        continue
                    processed += 1
                    if commit:
                        self.commit(record)
                        committed += 1
                    if limit is not None and processed >= limit:
                        break
        finally:
            restore()
            log.info(
                "kafka_consume_stop",
                extra={"processed": processed, "committed": committed, "failed": failed, "group_id": self.group_id},
            )
        return ConsumeResult(processed=processed, committed=committed, failed=failed)

    def close(self) -> None:
        """Close the underlying consumer."""
        close = getattr(self._consumer, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> KafkaConsumer:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False


def list_topics(config: KafkaConfig, *, admin: Any = None) -> list[str]:
    """Return sorted topic names. ``admin`` may be a fake with ``list_topics``."""
    owns = admin is None
    client = admin if admin is not None else _connect_admin(config)
    try:
        return sorted(client.list_topics())
    finally:
        if owns:
            client.close()


def ensure_topics(
    names: Iterable[str],
    *,
    config: KafkaConfig | None = None,
    admin: Any = None,
    num_partitions: int = 1,
    replication_factor: int = 2,
    budget: ChangeBudget | None = None,
) -> TopicResult:
    """Create missing topics when the budget is applying changes.

    Dry-run (the default budget) reports them in ``planned`` and does not call
    the broker. ``replication_factor`` defaults to 2; MSK clusters often want 3.
    """
    if admin is None and config is None:
        raise ValueError("config is required when admin is not provided")
    active = budget or ChangeBudget()
    owns = admin is None
    client = admin if admin is not None else _connect_admin(config)  # type: ignore[arg-type]
    try:
        existing = set(client.list_topics())
        missing = [name for name in names if name not in existing]
        created: list[str] = []
        for name in missing:
            if active.approve("kafka_create_topic", name):
                created.append(name)
        if created:
            client.create_topics(
                {
                    name: {"num_partitions": num_partitions, "replication_factor": replication_factor}
                    for name in created
                }
            )
        return TopicResult(existing=sorted(existing), created=created, planned=list(missing))
    finally:
        if owns:
            client.close()
