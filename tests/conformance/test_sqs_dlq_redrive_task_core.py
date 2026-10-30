"""SQS "Dead-letter queue redrive tasks" conformance (sqs.dlq.redrive-task) — proves
StartMessageMoveTask/ListMessageMoveTasks/CancelMessageMoveTask/ListDeadLetterSourceQueues
really move messages back out of a DLQ, as wired by the console's "Dead-letter queue
redrive tasks" tab and "Start DLQ redrive" action.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_sqs_dlq_redrive_task_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore

T = "AmazonSQS."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    s = InMemoryMessagingStore()
    s.set_time(0.0)

    def call(a, b):
        r = sqs.dispatch(s, T + a, b)
        if r.status != 200:
            raise AssertionError((a, r.body))
        return r.body

    dlq_url = call("CreateQueue", {"QueueName": "redrive-dlq"})["QueueUrl"]
    dlq_arn = call("GetQueueAttributes", {"QueueUrl": dlq_url})["Attributes"]["QueueArn"]
    main_url = call("CreateQueue", {"QueueName": "redrive-main", "Attributes": {
        "RedrivePolicy": '{"deadLetterTargetArn": "%s", "maxReceiveCount": 1}' % dlq_arn}})["QueueUrl"]
    main_arn = call("GetQueueAttributes", {"QueueUrl": main_url})["Attributes"]["QueueArn"]

    sources = call("ListDeadLetterSourceQueues", {"QueueUrl": dlq_url})["queueUrls"]
    _check("ListDeadLetterSourceQueues lists the queue pointing here as its DLQ", sources == [main_url])

    call("SendMessage", {"QueueUrl": main_url, "MessageBody": "poison"})
    call("ReceiveMessage", {"QueueUrl": main_url})
    s.advance(60)  # lease lapses without delete → redriven to the DLQ on next receive
    call("ReceiveMessage", {"QueueUrl": main_url})
    _check("message landed in the DLQ after maxReceiveCount",
           call("GetQueueAttributes", {"QueueUrl": dlq_url})["Attributes"]["ApproximateNumberOfMessages"] == "1")

    not_dlq = sqs.dispatch(s, T + "StartMessageMoveTask", {"SourceArn": main_arn})
    _check("StartMessageMoveTask rejects a queue that isn't a DLQ", not_dlq.status == 400)

    task = call("StartMessageMoveTask", {"SourceArn": dlq_arn})
    _check("StartMessageMoveTask returns a TaskHandle", bool(task.get("TaskHandle")))

    results = call("ListMessageMoveTasks", {"SourceArn": dlq_arn})["Results"]
    _check("ListMessageMoveTasks shows the task COMPLETED, 1 message moved",
           results and results[0]["Status"] == "COMPLETED" and results[0]["ApproximateNumberOfMessagesMoved"] == 1)

    _check("DLQ is empty after the redrive task",
           call("GetQueueAttributes", {"QueueUrl": dlq_url})["Attributes"]["ApproximateNumberOfMessages"] == "0")
    back = call("ReceiveMessage", {"QueueUrl": main_url})
    _check("the message moved back to its original source queue",
           back.get("Messages") and back["Messages"][0]["Body"] == "poison")

    cancel = sqs.dispatch(s, T + "CancelMessageMoveTask", {"TaskHandle": task["TaskHandle"]})
    _check("CancelMessageMoveTask refuses a task that already COMPLETED", cancel.status == 400)

    print("\nSQS dead-letter queue redrive task conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
