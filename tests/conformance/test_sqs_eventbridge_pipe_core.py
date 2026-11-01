"""SQS "EventBridge Pipes" conformance (sqs.eventbridge-pipes) — proves a RUNNING pipe
sourced from an SQS queue really forwards each message to its Target (another SQS queue,
or a Lambda function) the instant it's sent, consumes it from the source, and stops
forwarding once stopped/deleted or while pointed at a target that doesn't exist.

Run:  PYTHONPATH=. python3 tests/conformance/test_sqs_eventbridge_pipe_core.py
"""
import json
import types

try:
    from core import sqs_core as sqs
    from core import eventbridge_core as eb
    from core import lambda_core as lam
    from core.messaging_store import InMemoryMessagingStore
except ImportError:  # pragma: no cover - Pyodide flat layout
    import sqs_core as sqs  # type: ignore
    import eventbridge_core as eb  # type: ignore
    import lambda_core as lam  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore

T = "AmazonSQS."
F = "/2015-03-31/functions"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    store = InMemoryMessagingStore()
    lam_store = types.SimpleNamespace()

    def sq(action, body):
        r = sqs.dispatch(store, T + action, body, lam_store=lam_store)
        if r.status != 200:
            raise AssertionError((action, r.body))
        return r.body

    def pj(r):
        return json.loads(r.body) if r.body else {}

    src_url = sq("CreateQueue", {"QueueName": "pipe-src"})["QueueUrl"]
    src_arn = sq("GetQueueAttributes", {"QueueUrl": src_url})["Attributes"]["QueueArn"]
    dst_url = sq("CreateQueue", {"QueueName": "pipe-dst"})["QueueUrl"]
    dst_arn = sq("GetQueueAttributes", {"QueueUrl": dst_url})["Attributes"]["QueueArn"]

    create = eb.dispatch_pipes(store, "POST", "/v1/pipes/my-pipe",
                                body=json.dumps({"Source": src_arn, "Target": dst_arn}).encode())
    _check("CreatePipe", create.status == 200 and pj(create)["CurrentState"] == "RUNNING")

    sq("SendMessage", {"QueueUrl": src_url, "MessageBody": "piped-message"})
    _check("the source message was consumed by the pipe",
           sq("GetQueueAttributes", {"QueueUrl": src_url})["Attributes"]["ApproximateNumberOfMessages"] == "0")
    recv = sq("ReceiveMessage", {"QueueUrl": dst_url})
    _check("the target queue really received it", recv.get("Messages") and recv["Messages"][0]["Body"] == "piped-message")

    _check("StopPipe", pj(eb.dispatch_pipes(store, "POST", "/v1/pipes/my-pipe/stop"))["CurrentState"] == "STOPPED")
    sq("SendMessage", {"QueueUrl": src_url, "MessageBody": "should-stay-put"})
    _check("a stopped pipe does not forward",
           sq("GetQueueAttributes", {"QueueUrl": src_url})["Attributes"]["ApproximateNumberOfMessages"] == "1")
    sq("PurgeQueue", {"QueueUrl": src_url})
    _check("StartPipe resumes it", pj(eb.dispatch_pipes(store, "POST", "/v1/pipes/my-pipe/start"))["CurrentState"] == "RUNNING")

    # A pipe can target a Lambda function too (reuses the same cross-core `deliver`
    # Rules/Targets and Scheduler already use).
    fn = "pipe-target-fn"
    lam.dispatch(lam_store, "POST", F, {}, {}, json.dumps({
        "FunctionName": fn, "Runtime": "python3.12", "MemorySize": 256,
        "Code": {"Source": "def handler(event, context):\n    return {'got': event}\n"},
    }).encode())
    fn_arn = json.loads(lam.dispatch(lam_store, "GET", f"{F}/{fn}", {}, {}, b"").body)["Configuration"]["FunctionArn"]
    eb.dispatch_pipes(store, "PUT", "/v1/pipes/my-pipe", body=json.dumps({"Target": fn_arn}).encode())
    sq("SendMessage", {"QueueUrl": src_url, "MessageBody": "to-lambda"})
    _check("message consumed when the pipe targets a Lambda function",
           sq("GetQueueAttributes", {"QueueUrl": src_url})["Attributes"]["ApproximateNumberOfMessages"] == "0")
    invocations = json.loads(lam.dispatch(lam_store, "GET", f"{F}/{fn}/invocations", {}, {}, b"").body)["Invocations"]
    _check("the Lambda target was really invoked", len(invocations) == 1 and not invocations[0]["Error"])

    _check("DeletePipe", eb.dispatch_pipes(store, "DELETE", "/v1/pipes/my-pipe").status == 200)
    sq("SendMessage", {"QueueUrl": src_url, "MessageBody": "no-pipe-left"})
    _check("no pipe left to forward once deleted",
           sq("GetQueueAttributes", {"QueueUrl": src_url})["Attributes"]["ApproximateNumberOfMessages"] == "1")

    print("\nSQS EventBridge Pipes conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
