"""Phase 4 — messaging cores on a REAL NATS JetStream backend.

Proves the MessagingStore seam keeps queue/topic/message state in a real NATS
JetStream KV bucket, durable across a fresh store instance. Host-only (needs
nats-py + a JetStream-enabled NATS); not part of the WASM bundle. Exercises the
Pub/Sub core; SQS/SNS ride the same MessagingStore seam unchanged.

Run:  <venv-with-nats-py>/python tests/conformance/test_nats_backed_store.py
"""
import base64
import json

from core.nats_backed_store import NatsBackedMessagingStore
from core import gcp_pubsub_core as ps

P = "/v1/projects/demo"
BUCKET = "v24test_msg"
SID = "t1"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def run() -> int:
    # clean slate: drop our key from the KV bucket
    tmp = NatsBackedMessagingStore(bucket=BUCKET, store_id=SID)
    try:
        tmp._run(tmp._kv.delete(SID))
    except Exception:
        pass
    tmp.close()

    # store A: create topic + subscription, publish — persists to NATS JetStream KV
    a = NatsBackedMessagingStore(bucket=BUCKET, store_id=SID)
    ps.dispatch(a, "PUT", f"{P}/topics/t", {}, {}, b"{}")
    ps.dispatch(a, "PUT", f"{P}/subscriptions/s", {}, {},
                json.dumps({"topic": "projects/demo/topics/t"}).encode())
    pub = _j(ps.dispatch(a, "POST", f"{P}/topics/t:publish", {}, {},
                         json.dumps({"messages": [{"data": base64.b64encode(b"nats-msg").decode()}]}).encode()))
    _check("publish returns a messageId", bool(pub.get("messageIds")))
    a.close()

    # store B: FRESH instance — loads state from NATS JetStream, pulls the message
    b = NatsBackedMessagingStore(bucket=BUCKET, store_id=SID)
    _check("topic survived on NATS (fresh store)", b.get_topic("projects/demo/topics/t") is not None)
    pull = _j(ps.dispatch(b, "POST", f"{P}/subscriptions/s:pull", {}, {},
                          json.dumps({"maxMessages": 10}).encode()))
    msgs = pull.get("receivedMessages", [])
    _check("published message survives a fresh NATS-backed store",
           msgs and base64.b64decode(msgs[0]["message"]["data"]) == b"nats-msg")
    b.close()

    print("\nPHASE 4: ALL GREEN — messaging cores (Pub/Sub; SQS/SNS share the seam) run on a "
          "REAL NATS JetStream backend (state durable across a fresh store)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
