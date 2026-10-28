# SQS

`opskit.sqs` sends, receives, deletes, and consumes one queue. The boto3 client comes from `opskit.aws.client`, so adaptive retries, timeouts, and `assume_role_session` apply. Throttling and other transient API errors go through `opskit.retry.retry`.

Deletes, visibility changes, and purge use `ChangeBudget`. They are dry-run until `apply=True`. Sends are not gated: a client that refuses to send is not useful, and a send is not a destructive cleanup. The consumer still only deletes after the handler returns and the budget approves the delete.

```python
from opskit.aws import assume_role_session
from opskit.safety import ChangeBudget
from opskit.sqs import SqsQueue, list_queue_urls

session = assume_role_session("123456789012", "OrgOps")
queue = SqsQueue.from_queue_name(
    "jobs",
    region="us-east-1",
    session=session,
    budget=ChangeBudget(apply=True, max_changes=100),
)

queue.send({"job": "cleanup", "volume": "vol-123"}, attributes={"kind": "ebs"})
for url in list_queue_urls(prefix="jobs", session=session, region="us-east-1"):
    print(url)

def handle(message):
    payload = message.json()
    if queue.approaching_dead_letter(message):
        log_near_dead_letter(message.message_id, message.receive_count)
    do_work(payload)

result = queue.consume(handle, wait_seconds=20)
print(result.processed, result.deleted, result.failed)
```

`send` JSON-encodes dicts and lists. `send_json` always runs `json.dumps`, including for strings. Bodies larger than 256 KiB are rejected before the API call. `send_batch` accepts strings, mappings (`body`, `group_id`, `dedup_id`, `delay_seconds`, `attributes`), or `OutgoingMessage`, in groups of 10. A partial batch failure raises `SqsBatchError` with `.failed` and `.successful`.

`receive` is a long poll. `wait_seconds` is `WaitTimeSeconds` (0 through 20) and `max_messages` is 1 through 10. System attributes and message attributes are requested so `ApproximateReceiveCount`, FIFO group id, and dedup id are present. `message.json()` decodes the body. `message.receive_count` reads `ApproximateReceiveCount`.

`delete` and `delete_batch` return without calling SQS when the budget is a dry-run. `change_visibility` and `change_visibility_batch` behave the same way. `purge` is the same and should stay rare. A message from another queue URL is rejected.

FIFO queues are detected from a `.fifo` URL. `group_id` is required. Per-message `delay_seconds` is rejected because SQS does not allow it on FIFO queues. Pass `dedup_id` unless the queue uses content-based deduplication. SQS enforces the dedup window; this client only forwards `MessageGroupId` and `MessageDeduplicationId`.

`dead_letter_target()` reads `RedrivePolicy` and returns `dead_letter_target_arn` plus `max_receive_count`. A lookup failure is logged and remembered as "no dead-letter queue" so a consumer missing `sqs:GetQueueAttributes` still runs. `approaching_dead_letter(message)` is true when `receive_count >= maxReceiveCount - margin` (`margin` defaults to 1). The consumer logs `sqs_near_dead_letter` for those messages.

`consume` calls the handler, then deletes only when `auto_delete` is true (the default) and the budget approves. A handler exception leaves the message in flight so SQS can retry it and eventually dead-letter it. `stop_on_error=True` ends the loop on the first failure. `limit` caps successful handler calls. `stop_on_empty=True` returns after a receive that finds nothing, which is the right shape for a drain and the wrong shape for a daemon that should keep long-polling. SIGINT and SIGTERM set the stop event when `install_signals` is true (the default). Pass your own `stop_event` from another thread and set `install_signals=False` there. Shutdown finishes the current `ReceiveMessage` call, which can take as long as `wait_seconds`. An exhausted `max_changes` stops the loop after the handler for that message has already run.

`ConsumeResult` reports `processed`, `deleted`, and `failed`.
