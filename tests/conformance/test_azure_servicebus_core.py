"""Azure Service Bus (topics) core conformance — the cross-cloud pub/sub-fan-out
peer of SNS (AWS) and Pub/Sub (GCP).

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler / unified ingress)
  - Pyodide / WASM (the Nano substrate)

Asserts the native Service Bus REST wire semantics:
  - topic + subscription create/delete
  - send → **real fan-out**: an independent copy lands in every subscription
  - receive-and-delete pops the head (204 when empty)
  - peek-lock hands out a locked head, complete removes it, abandon re-exposes it
  - a message stays isolated per subscription (deleting from A leaves B intact)

Pure in-memory pub/sub (the NATS analogue). No network, no fastapi/azure-sdk/broker.

Run on host:    python3 tests/conformance/test_azure_servicebus_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import azure_servicebus_core as sb
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import azure_servicebus_core as sb  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _bp(resp):
    return json.loads(resp.headers.get("BrokerProperties", "{}"))


def run(store=None):
    store = store or InMemoryMessagingStore()

    def call(method, path, body=b"", headers=None):
        return sb.dispatch(store, method, path, {}, headers or {}, body)

    # ── topic + subscriptions ────────────────────────────────────────────
    _check("create topic 201", call("PUT", "/orders").status == 201)
    _check("get topic 200", call("GET", "/orders").status == 200)
    _check("get missing topic 404", call("GET", "/nope").status == 404)
    _check("create sub A 201", call("PUT", "/orders/subscriptions/billing").status == 201)
    _check("create sub B 201", call("PUT", "/orders/subscriptions/audit").status == 201)

    # ── send → fan-out into BOTH subscriptions ───────────────────────────
    r = call("POST", "/orders/messages", b'{"orderId":42}',
             {"content-type": "application/json",
              "BrokerProperties": json.dumps({"MessageId": "m-1"})})
    _check("send 201", r.status == 201)

    # receive-and-delete from A
    r = call("DELETE", "/orders/subscriptions/billing/messages/head")
    _check("receive A 200", r.status == 200)
    _check("receive A body", r.body == b'{"orderId":42}')
    _check("receive A MessageId", _bp(r).get("MessageId") == "m-1")
    _check("receive A content-type", r.media_type == "application/json")

    # A is now empty …
    _check("A empty → 204", call("DELETE", "/orders/subscriptions/billing/messages/head").status == 204)
    # … but B still has its independent copy (fan-out isolation)
    r = call("DELETE", "/orders/subscriptions/audit/messages/head")
    _check("B still has the message (isolation)", r.status == 200 and r.body == b'{"orderId":42}')

    # ── peek-lock → complete ─────────────────────────────────────────────
    call("POST", "/orders/messages", b"hello", {"content-type": "text/plain"})
    r = call("POST", "/orders/subscriptions/billing/messages/head")   # peek-lock
    _check("peek-lock 200", r.status == 200 and r.body == b"hello")
    bp = _bp(r)
    lock, seq = bp.get("LockToken"), bp.get("SequenceNumber")
    _check("peek-lock returns a lock token", bool(lock))
    # locked head is not handed out again
    _check("locked msg hidden from next peek", call("POST", "/orders/subscriptions/billing/messages/head").status == 204)
    # complete removes it
    _check("complete 200", call("DELETE", f"/orders/subscriptions/billing/messages/{seq}/{lock}").status == 200)
    _check("subscription empty after complete", call("DELETE", "/orders/subscriptions/billing/messages/head").status == 204)

    # ── peek-lock → abandon re-exposes the message ───────────────────────
    call("POST", "/orders/messages", b"retry-me")
    r = call("POST", "/orders/subscriptions/billing/messages/head")
    bp = _bp(r); lock, seq = bp["LockToken"], bp["SequenceNumber"]
    _check("abandon 200", call("PUT", f"/orders/subscriptions/billing/messages/{seq}/{lock}").status == 200)
    r = call("DELETE", "/orders/subscriptions/billing/messages/head")
    _check("abandoned message receivable again", r.status == 200 and r.body == b"retry-me")

    # ── errors ───────────────────────────────────────────────────────────
    _check("send to missing topic 404", call("POST", "/ghost/messages", b"x").status == 404)
    _check("receive missing sub 404", call("DELETE", "/orders/subscriptions/ghost/messages/head").status == 404)

    # ── delete sub + topic ───────────────────────────────────────────────
    _check("delete sub 200", call("DELETE", "/orders/subscriptions/audit").status == 200)
    _check("delete topic 200", call("DELETE", "/orders").status == 200)
    _check("deleted topic gone 404", call("GET", "/orders").status == 404)

    print("\nAzure Service Bus (topics) core conformance: ALL GREEN")
    return store


if __name__ == "__main__":
    run()
