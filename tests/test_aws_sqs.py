import json
import signal
import threading

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from opskit.aws import assume_role_session
from opskit.safety import BlastRadiusExceeded, ChangeBudget
from opskit.shutdown import install_stop_signals
from opskit.aws_sqs import OutgoingMessage, SqsBatchError, SqsMessage, SqsQueue, list_queue_urls


def _queue(name="jobs", **attributes):
    client = boto3.client("sqs", region_name="us-east-1")
    url = client.create_queue(QueueName=name, Attributes=attributes)["QueueUrl"]
    return client, SqsQueue(url, client=client, budget=ChangeBudget(apply=True, max_changes=100))


def _client_error(code="Throttling"):
    return ClientError({"Error": {"Code": code, "Message": "slow"}}, "SendMessage")


def test_stop_signals_set_the_event_and_restore_the_previous_handler():
    stop = threading.Event()
    previous = signal.getsignal(signal.SIGTERM)
    restore = install_stop_signals(stop)
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        handler(signal.SIGTERM, None)
        assert stop.is_set()
    finally:
        restore()
    assert signal.getsignal(signal.SIGTERM) is previous


def test_send_retries_throttling_and_encodes_fifo_fields():
    class Flaky:
        def __init__(self):
            self.calls = 0
            self.kwargs = None

        def send_message(self, **kwargs):
            self.calls += 1
            self.kwargs = kwargs
            if self.calls == 1:
                raise _client_error()
            return {"MessageId": "m1"}

    standard = SqsQueue("https://sqs.us-east-1.amazonaws.com/1/jobs", client=Flaky(), sleep=lambda _delay: None)
    assert standard.send({"job": "sync"}, attributes={"kind": "sync"}) == "m1"
    assert standard.client.calls == 2
    assert json.loads(standard.client.kwargs["MessageBody"]) == {"job": "sync"}
    assert standard.client.kwargs["MessageAttributes"]["kind"]["StringValue"] == "sync"

    fifo_client = Flaky()
    fifo = SqsQueue("https://sqs.us-east-1.amazonaws.com/1/jobs.fifo", client=fifo_client, sleep=lambda _: None)
    with pytest.raises(ValueError):
        fifo.send("x")
    with pytest.raises(ValueError):
        fifo.send("x", group_id="g", delay_seconds=5)
    assert fifo.send("x", group_id="orders", dedup_id="d1") == "m1"
    assert fifo_client.kwargs["MessageGroupId"] == "orders"
    assert fifo_client.kwargs["MessageDeduplicationId"] == "d1"


def test_batch_failure_and_dry_run_skip_api_calls():
    class Fake:
        def __init__(self):
            self.deleted = False
            self.purged = False

        def send_message_batch(self, **kwargs):
            return {
                "Successful": [],
                "Failed": [{"Id": "0", "Code": "InvalidMessageContents", "SenderFault": True, "Message": "bad"}],
            }

        def delete_message(self, **kwargs):
            self.deleted = True

        def purge_queue(self, **kwargs):
            self.purged = True

    queue = SqsQueue("https://sqs.us-east-1.amazonaws.com/1/jobs", client=Fake(), sleep=lambda _: None)
    with pytest.raises(SqsBatchError) as exc:
        queue.send_batch(["hello"])
    assert exc.value.failed[0]["Code"] == "InvalidMessageContents"
    assert queue.delete("handle") is False
    assert queue.purge() is False
    assert queue.client.deleted is False
    assert queue.client.purged is False
    assert queue.purge(budget=ChangeBudget(apply=True)) is True
    assert queue.client.purged is True


def test_change_budget_stops_a_second_delete():
    class Fake:
        def __init__(self):
            self.deletes = 0

        def delete_message(self, **kwargs):
            self.deletes += 1

    queue = SqsQueue(
        "https://sqs.us-east-1.amazonaws.com/1/jobs",
        client=Fake(),
        budget=ChangeBudget(apply=True, max_changes=1),
        sleep=lambda _: None,
    )
    assert queue.delete("one") is True
    with pytest.raises(BlastRadiusExceeded):
        queue.delete("two")
    assert queue.client.deletes == 1


@mock_aws
def test_send_receive_delete_and_batch_round_trip():
    _client, queue = _queue()
    assert queue.send({"n": 1})
    first = queue.receive(wait_seconds=0, max_messages=1)[0]
    assert first.json() == {"n": 1}
    assert first.receive_count == 1
    assert queue.delete(first)

    ids = queue.send_batch([{"body": str(i)} for i in range(15)])
    assert len(ids) == 15
    got = []
    while True:
        batch = queue.receive(wait_seconds=0, max_messages=10)
        if not batch:
            break
        got.extend(batch)
        result = queue.delete_batch(batch)
        assert not result.failed
    assert len(got) == 15
    assert {message.body for message in got} == {str(i) for i in range(15)}


@mock_aws
def test_visibility_change_makes_a_message_available_again():
    _client, queue = _queue()
    queue.send("visible", attributes={"job": "sync"})
    message = queue.receive(wait_seconds=0, visibility_timeout=60)[0]
    assert message.message_attributes["job"] == "sync"
    assert queue.receive(wait_seconds=0) == []
    assert queue.change_visibility(message, 0)
    again = queue.receive(wait_seconds=0)[0]
    assert again.body == "visible"
    assert queue.change_visibility_batch([again], 0).successful


@mock_aws
def test_fifo_requires_group_and_preserves_dedup_attributes():
    _client, queue = _queue("orders.fifo", FifoQueue="true")
    with pytest.raises(ValueError):
        queue.send("x")
    message_id = queue.send("x", group_id="g", dedup_id="d1")
    message = queue.receive(wait_seconds=0)[0]
    assert message.message_id == message_id
    assert message.attributes["MessageGroupId"] == "g"
    assert message.attributes["MessageDeduplicationId"] == "d1"
    queue.delete(message)
    queue.send_batch([OutgoingMessage("y", group_id="g", dedup_id="d2")])
    bodies = {item.body for item in queue.receive(wait_seconds=0, max_messages=10)}
    assert bodies == {"y"}


@mock_aws
def test_dead_letter_target_and_consumer_lifecycle():
    client = boto3.client("sqs", region_name="us-east-1")
    dlq_url = client.create_queue(QueueName="jobs-dlq")["QueueUrl"]
    dlq_arn = client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    source = client.create_queue(
        QueueName="jobs",
        Attributes={"RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 5})},
    )["QueueUrl"]
    queue = SqsQueue(source, client=client, budget=ChangeBudget(apply=True, max_changes=10))
    target = queue.dead_letter_target()
    assert target["dead_letter_target_arn"] == dlq_arn
    assert target["max_receive_count"] == 5
    near = SqsMessage("id", "handle", "body", {"ApproximateReceiveCount": "4"}, {}, source)
    early = SqsMessage("id2", "handle", "body", {"ApproximateReceiveCount": "1"}, {}, source)
    assert queue.approaching_dead_letter(near)
    assert not queue.approaching_dead_letter(early)

    queue.send("keep")
    queue.send("drop")
    seen = []

    def handler(message):
        seen.append(message.body)
        if message.body == "drop":
            raise RuntimeError("nope")

    failed = queue.consume(handler, wait_seconds=0, stop_on_empty=True, install_signals=False, limit=5)
    assert failed.failed == 1
    assert "drop" in seen
    hidden = client.get_queue_attributes(
        QueueUrl=source,
        AttributeNames=["ApproximateNumberOfMessagesNotVisible", "ApproximateNumberOfMessages"],
    )["Attributes"]
    assert int(hidden["ApproximateNumberOfMessagesNotVisible"]) >= 1

    fresh = SqsQueue(source, client=client)
    fresh.send("dry")
    dry = fresh.consume(
        lambda message: seen.append("dry-run"),
        wait_seconds=0,
        limit=1,
        install_signals=False,
        visibility_timeout=30,
    )
    assert dry.processed == 1
    assert dry.deleted == 0

    applied = SqsQueue(source, client=client, budget=ChangeBudget(apply=True, max_changes=10))
    applied.send("done")
    stop = threading.Event()

    def stop_after(message):
        seen.append(message.body)
        stop.set()

    stopped = applied.consume(
        stop_after,
        wait_seconds=0,
        stop_event=stop,
        install_signals=False,
        visibility_timeout=0,
        limit=10,
    )
    assert stopped.processed == 1
    assert stopped.deleted == 1
    assert stop.is_set()


@mock_aws
def test_list_and_assume_role_session():
    client = boto3.client("sqs", region_name="us-east-1")
    client.create_queue(QueueName="alpha")
    client.create_queue(QueueName="beta")
    client.create_queue(QueueName="other")
    urls = list(list_queue_urls(prefix="a", client=client))
    assert len(urls) == 1
    assert urls[0].endswith("/alpha")
    assert len(list(list_queue_urls(client=client))) == 3

    session = assume_role_session("123456789012", "OrgOps")
    role_client = session.client("sqs", region_name="us-east-1")
    role_client.create_queue(QueueName="from-role")
    queue = SqsQueue.from_queue_name("from-role", session=session, region="us-east-1")
    queue.send("hello")
    assert queue.receive(wait_seconds=0)[0].body == "hello"


def test_rejects_oversized_bodies_and_foreign_messages():
    queue = SqsQueue("https://sqs.us-east-1.amazonaws.com/1/jobs", client=object(), sleep=lambda _: None)
    with pytest.raises(ValueError):
        queue.send("x" * (256 * 1024 + 1))
    with pytest.raises(ValueError):
        queue.receive(wait_seconds=21)
    foreign = SqsMessage("id", "handle", "body", {}, {}, "https://sqs.us-east-1.amazonaws.com/1/other")
    with pytest.raises(ValueError):
        queue.delete(foreign, budget=ChangeBudget(apply=True))
