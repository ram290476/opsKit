"""SQS send, receive, delete, and a consumer loop.

Clients come from :func:`opskit.aws.client`, so timeouts, adaptive retries, and
:func:`opskit.aws.assume_role_session` apply. Transient SQS errors go through
:func:`opskit.retry.retry`. Deletes, visibility changes, and purge honor
:class:`opskit.safety.ChangeBudget` and are dry-run unless ``apply`` is set.

The consumer deletes a message only after the handler returns and the budget
approves the delete. A handler exception leaves the message in flight so SQS
can retry it and, once ``maxReceiveCount`` is reached, move it to the
dead-letter queue. Shutdown waits for the current receive call, then stops.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .aws import client as aws_client
from .aws import paginate
from .retry import retry
from .safety import BlastRadiusExceeded, ChangeBudget
from .shutdown import install_stop_signals

log = logging.getLogger(__name__)

_MAX_BODY_BYTES = 256 * 1024
_BATCH = 10


class SqsBatchError(RuntimeError):
    """One or more entries in an SQS batch call were rejected."""

    def __init__(self, action: str, failed: list[dict[str, Any]], successful: list[str]):
        super().__init__(f"{len(failed)} SQS {action} entries failed")
        self.action = action
        self.failed = failed
        self.successful = successful


@dataclass(frozen=True)
class SqsMessage:
    """One received SQS message."""

    message_id: str
    receipt_handle: str
    body: str
    attributes: dict[str, str]
    message_attributes: dict[str, Any]
    queue_url: str

    def json(self) -> Any:
        """Decode the body as JSON."""
        return json.loads(self.body)

    @property
    def receive_count(self) -> int:
        """``ApproximateReceiveCount``, or 1 when the attribute is missing."""
        try:
            return int(self.attributes.get("ApproximateReceiveCount", "1"))
        except (TypeError, ValueError):
            return 1


@dataclass
class OutgoingMessage:
    """One message to send. ``body`` may be a string or any JSON value."""

    body: Any
    group_id: str | None = None
    dedup_id: str | None = None
    delay_seconds: int = 0
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class BatchResult:
    """Ids that succeeded, entries that failed, and ids skipped by a dry-run budget."""

    successful: list[str]
    failed: list[dict[str, Any]]
    skipped: list[str]


@dataclass(frozen=True)
class ConsumeResult:
    """How many messages a consumer handled, deleted, or failed."""

    processed: int = 0
    deleted: int = 0
    failed: int = 0


@dataclass
class _Prepared:
    body: str
    group_id: str | None
    dedup_id: str | None
    delay_seconds: int
    attributes: dict[str, Any] | None


def list_queue_urls(
    prefix: str | None = None,
    *,
    region: str | None = None,
    session: Any = None,
    client: Any = None,
) -> Iterator[str]:
    """Yield queue URLs, following the SQS paginator."""
    sqs = client or aws_client("sqs", region=region, session=session)
    kwargs: dict[str, Any] = {}
    if prefix:
        kwargs["QueueNamePrefix"] = prefix
    yield from paginate(sqs, "list_queues", "QueueUrls", **kwargs)


def _body_text(body: Any) -> str:
    if isinstance(body, str):
        text = body
    elif isinstance(body, bytes):
        text = body.decode()
    else:
        text = json.dumps(body, default=str, separators=(",", ":"))
    if len(text.encode("utf-8")) > _MAX_BODY_BYTES:
        raise ValueError("SQS message body exceeds 256 KiB")
    return text


def _encode_attributes(attributes: Mapping[str, Any] | None) -> dict[str, dict[str, Any]] | None:
    if not attributes:
        return None
    encoded: dict[str, dict[str, Any]] = {}
    for key, value in attributes.items():
        if isinstance(value, bytes):
            encoded[str(key)] = {"DataType": "Binary", "BinaryValue": value}
        else:
            encoded[str(key)] = {"DataType": "String", "StringValue": str(value)}
    return encoded


def _decode_attributes(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if not isinstance(value, Mapping):
            decoded[str(key)] = value
        elif "StringValue" in value:
            decoded[str(key)] = value["StringValue"]
        elif "BinaryValue" in value:
            decoded[str(key)] = value["BinaryValue"]
        else:
            decoded[str(key)] = dict(value)
    return decoded


def _message_from_raw(raw: Mapping[str, Any], queue_url: str) -> SqsMessage:
    attributes = {str(key): str(value) for key, value in (raw.get("Attributes") or {}).items()}
    return SqsMessage(
        message_id=str(raw["MessageId"]),
        receipt_handle=str(raw["ReceiptHandle"]),
        body=str(raw.get("Body", "")),
        attributes=attributes,
        message_attributes=_decode_attributes(raw.get("MessageAttributes")),
        queue_url=queue_url,
    )


def _chunks(items: Iterable[Any], size: int) -> Iterator[list[Any]]:
    chunk: list[Any] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


class SqsQueue:
    """One SQS queue. Pass a budget with ``apply=True`` to delete or purge."""

    def __init__(
        self,
        queue_url: str,
        *,
        client: Any = None,
        region: str | None = None,
        session: Any = None,
        budget: ChangeBudget | None = None,
        attempts: int = 5,
        retry_base: float = 0.5,
        retry_cap: float = 30.0,
        sleep: Callable[[float], None] | None = None,
        fifo: bool | None = None,
    ):
        self.queue_url = queue_url
        self.client = client or aws_client("sqs", region=region, session=session)
        self.budget = budget or ChangeBudget()
        self.attempts = attempts
        self.retry_base = retry_base
        self.retry_cap = retry_cap
        self._sleep = sleep
        self.fifo = queue_url.rstrip("/").endswith(".fifo") if fifo is None else fifo
        self._dlq_loaded = False
        self._dlq: dict[str, Any] | None = None

    @classmethod
    def from_queue_name(
        cls,
        queue_name: str,
        *,
        region: str | None = None,
        session: Any = None,
        client: Any = None,
        **kwargs: Any,
    ) -> SqsQueue:
        """Resolve ``queue_name`` with ``GetQueueUrl`` and return a queue helper."""
        sqs = client or aws_client("sqs", region=region, session=session)
        url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        return cls(url, client=sqs, **kwargs)

    def _call(self, fn: Callable[..., Any], **kwargs: Any) -> Any:
        sleep = self._sleep

        def _do() -> Any:
            return fn(**kwargs)

        decorated = retry(
            attempts=self.attempts,
            base=self.retry_base,
            cap=self.retry_cap,
            **({"sleep": sleep} if sleep is not None else {}),
        )(_do)
        return decorated()

    def _budget(self, budget: ChangeBudget | None) -> ChangeBudget:
        return self.budget if budget is None else budget

    def _prepare(
        self,
        body: Any,
        *,
        group_id: str | None,
        dedup_id: str | None,
        delay_seconds: int,
        attributes: Mapping[str, Any] | None,
    ) -> _Prepared:
        text = _body_text(body)
        if self.fifo and not group_id:
            raise ValueError("FIFO queues require group_id")
        if self.fifo and delay_seconds:
            raise ValueError("FIFO queues do not accept per-message delay_seconds")
        return _Prepared(
            body=text,
            group_id=group_id,
            dedup_id=dedup_id,
            delay_seconds=delay_seconds,
            attributes=dict(attributes) if attributes else None,
        )

    def _send_kwargs(self, prepared: _Prepared) -> dict[str, Any]:
        params: dict[str, Any] = {"QueueUrl": self.queue_url, "MessageBody": prepared.body}
        if prepared.delay_seconds:
            params["DelaySeconds"] = prepared.delay_seconds
        if prepared.group_id:
            params["MessageGroupId"] = prepared.group_id
        if prepared.dedup_id:
            params["MessageDeduplicationId"] = prepared.dedup_id
        encoded = _encode_attributes(prepared.attributes)
        if encoded:
            params["MessageAttributes"] = encoded
        return params

    def send(
        self,
        body: Any,
        *,
        group_id: str | None = None,
        dedup_id: str | None = None,
        delay_seconds: int = 0,
        attributes: Mapping[str, Any] | None = None,
    ) -> str:
        """Send one message. Dict and list bodies are JSON-encoded. Returns the message id."""
        prepared = self._prepare(
            body,
            group_id=group_id,
            dedup_id=dedup_id,
            delay_seconds=delay_seconds,
            attributes=attributes,
        )
        response = self._call(self.client.send_message, **self._send_kwargs(prepared))
        return str(response["MessageId"])

    def send_json(self, payload: Any, **kwargs: Any) -> str:
        """JSON-encode ``payload`` and send it. Strings are encoded as JSON strings."""
        return self.send(json.dumps(payload, default=str), **kwargs)

    def send_batch(self, messages: Iterable[Any]) -> list[str]:
        """Send messages in batches of 10. Each item is a string, mapping, or :class:`OutgoingMessage`."""
        ids: list[str] = []
        for chunk in _chunks(messages, _BATCH):
            entries = []
            for index, item in enumerate(chunk):
                prepared = self._coerce(item)
                entry: dict[str, Any] = {"Id": str(index), "MessageBody": prepared.body}
                if prepared.delay_seconds:
                    entry["DelaySeconds"] = prepared.delay_seconds
                if prepared.group_id:
                    entry["MessageGroupId"] = prepared.group_id
                if prepared.dedup_id:
                    entry["MessageDeduplicationId"] = prepared.dedup_id
                encoded = _encode_attributes(prepared.attributes)
                if encoded:
                    entry["MessageAttributes"] = encoded
                entries.append(entry)
            response = self._call(self.client.send_message_batch, QueueUrl=self.queue_url, Entries=entries)
            failed = list(response.get("Failed") or [])
            successful = [str(item["MessageId"]) for item in response.get("Successful") or []]
            ids.extend(successful)
            if failed:
                raise SqsBatchError("send", failed, ids)
        return ids

    def _coerce(self, item: Any) -> _Prepared:
        if isinstance(item, OutgoingMessage):
            return self._prepare(
                item.body,
                group_id=item.group_id,
                dedup_id=item.dedup_id,
                delay_seconds=item.delay_seconds,
                attributes=item.attributes,
            )
        if isinstance(item, str):
            return self._prepare(item, group_id=None, dedup_id=None, delay_seconds=0, attributes=None)
        if isinstance(item, Mapping):
            body = item.get("body", item.get("Body"))
            return self._prepare(
                body,
                group_id=item.get("group_id", item.get("MessageGroupId")),
                dedup_id=item.get("dedup_id", item.get("MessageDeduplicationId")),
                delay_seconds=int(item.get("delay_seconds", item.get("DelaySeconds", 0)) or 0),
                attributes=item.get("attributes"),
            )
        raise TypeError("message must be a string, mapping, or OutgoingMessage")

    def receive(
        self,
        *,
        max_messages: int = 1,
        wait_seconds: int = 20,
        visibility_timeout: int | None = None,
    ) -> list[SqsMessage]:
        """Long-poll the queue. ``wait_seconds`` is SQS ``WaitTimeSeconds`` (0-20)."""
        if not 0 <= wait_seconds <= 20:
            raise ValueError("wait_seconds must be between 0 and 20")
        if not 1 <= max_messages <= 10:
            raise ValueError("max_messages must be between 1 and 10")
        if visibility_timeout is not None and not 0 <= visibility_timeout <= 43200:
            raise ValueError("visibility_timeout must be between 0 and 43200")
        params: dict[str, Any] = {
            "QueueUrl": self.queue_url,
            "MaxNumberOfMessages": max_messages,
            "WaitTimeSeconds": wait_seconds,
            "MessageAttributeNames": ["All"],
            "MessageSystemAttributeNames": ["All"],
        }
        if visibility_timeout is not None:
            params["VisibilityTimeout"] = visibility_timeout
        response = self._call(self.client.receive_message, **params)
        return [_message_from_raw(raw, self.queue_url) for raw in response.get("Messages") or []]

    def _handle_of(self, message: SqsMessage | str) -> str:
        if isinstance(message, SqsMessage):
            if message.queue_url and message.queue_url != self.queue_url:
                raise ValueError("message belongs to a different queue")
            return message.receipt_handle
        return message

    def _target_of(self, message: SqsMessage | str) -> str:
        if isinstance(message, SqsMessage):
            return message.message_id
        return message[:80]

    def delete(self, message: SqsMessage | str, *, budget: ChangeBudget | None = None) -> bool:
        """Delete one message. Returns False when the budget is still a dry-run."""
        handle = self._handle_of(message)
        active = self._budget(budget)
        if not active.approve("sqs_delete", self._target_of(message)):
            return False
        self._call(self.client.delete_message, QueueUrl=self.queue_url, ReceiptHandle=handle)
        return True

    def delete_batch(
        self,
        messages: Sequence[SqsMessage | str],
        *,
        budget: ChangeBudget | None = None,
    ) -> BatchResult:
        """Delete up to the whole sequence, 10 at a time. Dry-run entries are skipped."""
        active = self._budget(budget)
        approved: list[tuple[str, str]] = []
        skipped: list[str] = []
        for message in messages:
            target = self._target_of(message)
            if active.approve("sqs_delete", target):
                approved.append((target, self._handle_of(message)))
            else:
                skipped.append(target)
        successful: list[str] = []
        failed: list[dict[str, Any]] = []
        for chunk in _chunks(approved, _BATCH):
            entries = [{"Id": str(index), "ReceiptHandle": handle} for index, (_target, handle) in enumerate(chunk)]
            response = self._call(self.client.delete_message_batch, QueueUrl=self.queue_url, Entries=entries)
            by_id = {str(index): target for index, (target, _handle) in enumerate(chunk)}
            for item in response.get("Successful") or []:
                successful.append(by_id.get(str(item.get("Id")), str(item.get("Id"))))
            failed.extend(response.get("Failed") or [])
        if failed:
            raise SqsBatchError("delete", failed, successful)
        return BatchResult(successful=successful, failed=failed, skipped=skipped)

    def change_visibility(
        self,
        message: SqsMessage | str,
        timeout: int,
        *,
        budget: ChangeBudget | None = None,
    ) -> bool:
        """Change one message's visibility timeout. Dry-run returns False."""
        if not 0 <= timeout <= 43200:
            raise ValueError("timeout must be between 0 and 43200")
        handle = self._handle_of(message)
        active = self._budget(budget)
        if not active.approve("sqs_change_visibility", self._target_of(message)):
            return False
        self._call(
            self.client.change_message_visibility,
            QueueUrl=self.queue_url,
            ReceiptHandle=handle,
            VisibilityTimeout=timeout,
        )
        return True

    def change_visibility_batch(
        self,
        messages: Sequence[SqsMessage | str],
        timeout: int,
        *,
        budget: ChangeBudget | None = None,
    ) -> BatchResult:
        """Change visibility for many messages. Dry-run entries are skipped."""
        if not 0 <= timeout <= 43200:
            raise ValueError("timeout must be between 0 and 43200")
        active = self._budget(budget)
        approved: list[tuple[str, str]] = []
        skipped: list[str] = []
        for message in messages:
            target = self._target_of(message)
            if active.approve("sqs_change_visibility", target):
                approved.append((target, self._handle_of(message)))
            else:
                skipped.append(target)
        successful: list[str] = []
        failed: list[dict[str, Any]] = []
        for chunk in _chunks(approved, _BATCH):
            entries = [
                {"Id": str(index), "ReceiptHandle": handle, "VisibilityTimeout": timeout}
                for index, (_target, handle) in enumerate(chunk)
            ]
            response = self._call(
                self.client.change_message_visibility_batch,
                QueueUrl=self.queue_url,
                Entries=entries,
            )
            by_id = {str(index): target for index, (target, _handle) in enumerate(chunk)}
            for item in response.get("Successful") or []:
                successful.append(by_id.get(str(item.get("Id")), str(item.get("Id"))))
            failed.extend(response.get("Failed") or [])
        if failed:
            raise SqsBatchError("change_visibility", failed, successful)
        return BatchResult(successful=successful, failed=failed, skipped=skipped)

    def purge(self, *, budget: ChangeBudget | None = None) -> bool:
        """Purge the queue. Refuses unless the budget is applying changes."""
        active = self._budget(budget)
        if not active.approve("sqs_purge", self.queue_url):
            return False
        self._call(self.client.purge_queue, QueueUrl=self.queue_url)
        return True

    def dead_letter_target(self, *, refresh: bool = False) -> dict[str, Any] | None:
        """Return ``dead_letter_target_arn`` and ``max_receive_count``, or None.

        A lookup failure is logged and cached as "no dead-letter queue" so a
        consumer missing ``GetQueueAttributes`` still runs. Pass ``refresh``
        after the redrive policy changes.
        """
        if self._dlq_loaded and not refresh:
            return self._dlq
        self._dlq_loaded = True
        try:
            response = self._call(
                self.client.get_queue_attributes,
                QueueUrl=self.queue_url,
                AttributeNames=["RedrivePolicy"],
            )
        except (ClientError, BotoCoreError) as exc:
            log.warning(
                "sqs_redrive_lookup_failed",
                extra={"queue_url": self.queue_url, "error": type(exc).__name__},
            )
            self._dlq = None
            return None
        raw = (response.get("Attributes") or {}).get("RedrivePolicy")
        if not raw:
            self._dlq = None
            return None
        try:
            policy = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("sqs_redrive_unreadable", extra={"queue_url": self.queue_url})
            self._dlq = None
            return None
        max_receive = policy.get("maxReceiveCount")
        try:
            max_receive_count = int(max_receive) if max_receive is not None else None
        except (TypeError, ValueError):
            max_receive_count = None
        self._dlq = {
            "dead_letter_target_arn": policy.get("deadLetterTargetArn"),
            "max_receive_count": max_receive_count,
        }
        return self._dlq

    def approaching_dead_letter(self, message: SqsMessage, *, margin: int = 1) -> bool:
        """True when the message is within ``margin`` receives of the dead-letter queue."""
        target = self.dead_letter_target()
        if not target or not target.get("max_receive_count"):
            return False
        threshold = int(target["max_receive_count"]) - margin
        return message.receive_count >= max(1, threshold)

    def consume(
        self,
        handler: Callable[[SqsMessage], Any],
        *,
        batch_size: int = 10,
        wait_seconds: int = 20,
        visibility_timeout: int | None = None,
        limit: int | None = None,
        auto_delete: bool = True,
        stop_on_empty: bool = False,
        stop_on_error: bool = False,
        stop_event: threading.Event | None = None,
        install_signals: bool = True,
        budget: ChangeBudget | None = None,
    ) -> ConsumeResult:
        """Call ``handler`` for each message until stopped.

        Successful handlers delete the message when ``auto_delete`` is set and
        the budget approves it. Failures are left for SQS retry and the
        dead-letter policy. SIGINT and SIGTERM set the stop event when
        ``install_signals`` is true. An exhausted change budget stops the loop.
        """
        active = self._budget(budget)
        stop_event = stop_event or threading.Event()
        restore = install_stop_signals(stop_event) if install_signals else (lambda: None)
        processed = 0
        deleted = 0
        failed = 0
        log.info("sqs_consume_start", extra={"queue_url": self.queue_url, "apply": active.apply})
        try:
            while not stop_event.is_set():
                if limit is not None and processed >= limit:
                    break
                messages = self.receive(
                    max_messages=batch_size,
                    wait_seconds=wait_seconds,
                    visibility_timeout=visibility_timeout,
                )
                if not messages:
                    if stop_on_empty:
                        break
                    continue
                for message in messages:
                    if stop_event.is_set():
                        break
                    if limit is not None and processed >= limit:
                        break
                    if self.approaching_dead_letter(message):
                        log.warning(
                            "sqs_near_dead_letter",
                            extra={
                                "message_id": message.message_id,
                                "receive_count": message.receive_count,
                                "queue_url": self.queue_url,
                            },
                        )
                    try:
                        handler(message)
                    except Exception:
                        failed += 1
                        log.exception(
                            "sqs_handler_failed",
                            extra={"message_id": message.message_id, "queue_url": self.queue_url},
                        )
                        if stop_on_error:
                            stop_event.set()
                            break
                        continue
                    processed += 1
                    if not auto_delete:
                        continue
                    try:
                        if self.delete(message, budget=active):
                            deleted += 1
                    except BlastRadiusExceeded:
                        log.error("sqs_budget_exhausted", extra={"queue_url": self.queue_url})
                        stop_event.set()
                        break
        finally:
            restore()
            log.info(
                "sqs_consume_stop",
                extra={
                    "queue_url": self.queue_url,
                    "processed": processed,
                    "deleted": deleted,
                    "failed": failed,
                },
            )
        return ConsumeResult(processed=processed, deleted=deleted, failed=failed)
