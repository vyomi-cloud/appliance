"""SQS "Lambda triggers" conformance (sqs.lambda-triggers) — proves an Enabled SQS event
source mapping really invokes the target function the instant SendMessage lands a message
(no separate poll step), consumes the message on success, leaves it for redelivery on a
function error, and goes quiet again once the mapping is disabled or deleted.

Run:  PYTHONPATH=. python3 tests/conformance/test_sqs_lambda_trigger_core.py
"""
import json
import types

try:
    from core import sqs_core as sqs
    from core import lambda_core as lam
    from core.messaging_store import InMemoryMessagingStore
except ImportError:  # pragma: no cover - Pyodide flat layout
    import sqs_core as sqs  # type: ignore
    import lambda_core as lam  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore

T = "AmazonSQS."
F = "/2015-03-31/functions"
ESM = "/2015-03-31/event-source-mappings"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    msg_store = InMemoryMessagingStore()
    lam_store = types.SimpleNamespace()

    def sq(action, body):
        r = sqs.dispatch(msg_store, T + action, body, lam_store=lam_store)
        if r.status != 200:
            raise AssertionError((action, r.body))
        return r.body

    def lc(method, path, body=None, q=None):
        b = json.dumps(body).encode() if body is not None else b""
        return lam.dispatch(lam_store, method, path, q or {}, {}, b)

    def lj(r):
        return json.loads(r.body) if r.body else {}

    queue_url = sq("CreateQueue", {"QueueName": "trigger-src"})["QueueUrl"]
    queue_arn = sq("GetQueueAttributes", {"QueueUrl": queue_url})["Attributes"]["QueueArn"]

    ok_fn = "trigger-ok-fn"
    _check("CreateFunction (ok handler)", lc("POST", F, {
        "FunctionName": ok_fn, "Runtime": "python3.12", "MemorySize": 256,
        "Code": {"Source": "def handler(event, context):\n    return {'n': len(event['Records'])}\n"},
    }).status == 201)

    create = lc("POST", ESM, {"FunctionName": ok_fn, "EventSourceArn": queue_arn, "EventSourceType": "SQS"})
    _check("CreateEventSourceMapping", create.status == 202 and lj(create)["State"] == "Enabled")
    uid = lj(create)["UUID"]

    sq("SendMessage", {"QueueUrl": queue_url, "MessageBody": "hello-trigger"})
    _check("message consumed by the trigger (queue drains)",
           sq("GetQueueAttributes", {"QueueUrl": queue_url})["Attributes"]["ApproximateNumberOfMessages"] == "0")
    _check("LastProcessingResult reflects the real successful invocation",
           lj(lc("GET", f"{ESM}/{uid}"))["LastProcessingResult"] == "OK")
    invocations = lj(lc("GET", f"{F}/{ok_fn}/invocations"))["Invocations"]
    _check("the function was really invoked once", len(invocations) == 1 and not invocations[0]["Error"])

    # Disabling the mapping stops delivery — the message just sits in the queue.
    _check("UpdateEventSourceMapping disables it", lj(lc("PUT", f"{ESM}/{uid}", {"Enabled": False}))["State"] == "Disabled")
    sq("SendMessage", {"QueueUrl": queue_url, "MessageBody": "should-not-fire"})
    _check("a disabled mapping does not consume the message",
           sq("GetQueueAttributes", {"QueueUrl": queue_url})["Attributes"]["ApproximateNumberOfMessages"] == "1")
    sq("PurgeQueue", {"QueueUrl": queue_url})
    _check("DeleteEventSourceMapping", lc("DELETE", f"{ESM}/{uid}").status == 200)

    # A function error leaves the message for redelivery instead of deleting it.
    err_fn = "trigger-err-fn"
    _check("CreateFunction (erroring handler)", lc("POST", F, {
        "FunctionName": err_fn, "Runtime": "python3.12", "MemorySize": 256,
        "Code": {"Source": "def handler(event, context):\n    raise RuntimeError('boom')\n"},
    }).status == 201)
    create2 = lc("POST", ESM, {"FunctionName": err_fn, "EventSourceArn": queue_arn, "EventSourceType": "SQS"})
    uid2 = lj(create2)["UUID"]
    sq("SendMessage", {"QueueUrl": queue_url, "MessageBody": "poison"})
    _check("a function error leaves the message available for redelivery",
           sq("GetQueueAttributes", {"QueueUrl": queue_url})["Attributes"]["ApproximateNumberOfMessages"] == "1")
    _check("LastProcessingResult reports the function error",
           lj(lc("GET", f"{ESM}/{uid2}"))["LastProcessingResult"].startswith("PROBLEM"))

    print("\nSQS Lambda trigger conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
