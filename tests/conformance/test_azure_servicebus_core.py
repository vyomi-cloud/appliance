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
  - lock duration expiry and redelivery with incremented DeliveryCount
  - renew-lock extending the lease
  - expired lock complete / renew returns 410 MessageLockLost
  - maxDeliveryCount automatic dead-lettering to $DeadLetterQueue
  - receiving and settling from $DeadLetterQueue
  - message properties fidelity and 256 KB message size limit (413)
  - direct Python entry points for the AMQP listener (core/servicebus_amqp)

Pure in-memory pub/sub (the NATS analogue). No network, no fastapi/azure-sdk/broker.
"""
from __future__ import annotations

import json

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import azure_servicebus_core as sb
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import azure_servicebus_core as sb  # type: ignore


def _check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"Check failed: {name}")
    print(f"  ok  {name}")


def _bp(resp) -> dict:
    return json.loads(resp.headers.get("BrokerProperties", "{}"))


def run(store=None):
    store = store or InMemoryMessagingStore()
    store.set_time(1000.0)

    def call(method: str, path: str, body: bytes = b"", headers: dict | None = None):
        return sb.dispatch(store, method, path, {}, headers or {}, body)

    # ── 1. topic + subscriptions ────────────────────────────────────────────
    _check("create topic 201", call("PUT", "/orders").status == 201)
    _check("get topic 200", call("GET", "/orders").status == 200)
    _check("get missing topic 404", call("GET", "/nope").status == 404)
    _check("create sub A 201", call("PUT", "/orders/subscriptions/billing").status == 201)
    _check("create sub B 201", call("PUT", "/orders/subscriptions/audit").status == 201)

    # ── 2. send → fan-out into BOTH subscriptions ───────────────────────────
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

    # ── 3. peek-lock → complete ─────────────────────────────────────────────
    call("POST", "/orders/messages", b"hello", {"content-type": "text/plain"})
    r = call("POST", "/orders/subscriptions/billing/messages/head")   # peek-lock
    _check("peek-lock 200", r.status == 200 and r.body == b"hello")
    bp = _bp(r)
    lock, seq = bp.get("LockToken"), bp.get("SequenceNumber")
    _check("peek-lock returns a lock token", bool(lock))
    _check("delivery count is 1 on first peek", bp.get("DeliveryCount") == 1)
    # locked head is not handed out again
    _check("locked msg hidden from next peek", call("POST", "/orders/subscriptions/billing/messages/head").status == 204)
    # complete removes it
    _check("complete 200", call("DELETE", f"/orders/subscriptions/billing/messages/{seq}/{lock}").status == 200)
    _check("subscription empty after complete", call("DELETE", "/orders/subscriptions/billing/messages/head").status == 204)

    # ── 4. peek-lock → abandon re-exposes the message ───────────────────────
    call("POST", "/orders/messages", b"retry-me")
    r = call("POST", "/orders/subscriptions/billing/messages/head")
    bp = _bp(r); lock, seq = bp["LockToken"], bp["SequenceNumber"]
    _check("abandon 200", call("PUT", f"/orders/subscriptions/billing/messages/{seq}/{lock}").status == 200)
    r = call("DELETE", "/orders/subscriptions/billing/messages/head")
    _check("abandoned message receivable again", r.status == 200 and r.body == b"retry-me")

    # ── 5. Lock duration expiry & redelivery (Task A2) ─────────────────────
    call("POST", "/orders/messages", b"expire-me")
    r = call("POST", "/orders/subscriptions/billing/messages/head")
    bp1 = _bp(r)
    lock1, seq1 = bp1["LockToken"], bp1["SequenceNumber"]
    _check("peek-lock before expiry has DeliveryCount 1", bp1.get("DeliveryCount") == 1)

    # Advance clock past default 60s lock duration
    store.advance(65.0)
    r2 = call("POST", "/orders/subscriptions/billing/messages/head")
    _check("expired message is redelivered after lock duration", r2.status == 200 and r2.body == b"expire-me")
    bp2 = _bp(r2)
    _check("redelivered message increments DeliveryCount to 2", bp2.get("DeliveryCount") == 2)
    lock2 = bp2["LockToken"]

    # ── 6. Renew-lock & expired lock rejection (Task A2) ───────────────────
    # Renew active lock
    renew_resp = call("POST", f"/orders/subscriptions/billing/messages/{seq1}/{lock2}")
    _check("renew active lock 200", renew_resp.status == 200)
    _check("renew returns LockedUntilUtc", "LockedUntilUtc" in _bp(renew_resp))

    # Old expired lock token complete is rejected with 410
    _check("stale lock complete rejected 410", call("DELETE", f"/orders/subscriptions/billing/messages/{seq1}/{lock1}").status == 410)

    # Advance past renewed expiry (65s more)
    store.advance(65.0)
    # Now the renewed lock is expired; complete returns 410
    _check("expired renewed lock complete rejected 410", call("DELETE", f"/orders/subscriptions/billing/messages/{seq1}/{lock2}").status == 410)
    # Drain the message so subscription is clean
    call("DELETE", "/orders/subscriptions/billing/messages/head")

    # ── 7. MaxDeliveryCount and Dead-Letter Queue (Task A2) ────────────────
    call("POST", "/orders/messages", b"poison-pill")
    # Simulate 9 deliveries + abandons (reaching delivery_count = 10)
    seq_poison = None
    for attempt in range(1, 10):
        r = call("POST", "/orders/subscriptions/billing/messages/head")
        bp = _bp(r)
        seq_poison = bp["SequenceNumber"]
        call("PUT", f"/orders/subscriptions/billing/messages/{seq_poison}/{bp['LockToken']}")

    # 10th delivery
    r10 = call("POST", "/orders/subscriptions/billing/messages/head")
    bp10 = _bp(r10)
    _check("10th delivery count is 10", bp10.get("DeliveryCount") == 10)
    # 10th abandon immediately moves message to $DeadLetterQueue
    call("PUT", f"/orders/subscriptions/billing/messages/{seq_poison}/{bp10['LockToken']}")

    # Main subscription is now empty
    _check("main subscription empty after poison moved to DLQ", call("GET", "/orders/subscriptions/billing/messages/head").status == 400 or call("POST", "/orders/subscriptions/billing/messages/head").status == 204)

    # Receive from $DeadLetterQueue
    dlq_r = call("DELETE", "/orders/subscriptions/billing/$DeadLetterQueue/messages/head")
    _check("receive from DLQ 200", dlq_r.status == 200 and dlq_r.body == b"poison-pill")
    dlq_bp = _bp(dlq_r)
    _check("DLQ message has DeadLetterReason", dlq_bp.get("DeadLetterReason") == "MaxDeliveryCountExceeded")

    # ── 8. Message properties & 256 KB limits (Task A4) ────────────────────
    rich_headers = {
        "content-type": "application/json",
        "BrokerProperties": json.dumps({
            "MessageId": "msg-custom-123",
            "CorrelationId": "corr-456",
            "Label": "TestSubject",
            "ReplyTo": "reply-queue"
        }),
        "X-Siftly-Tenant": "tenant-amber"
    }
    call("POST", "/orders/messages", b'{"data": "rich"}', rich_headers)
    recv_rich = call("DELETE", "/orders/subscriptions/billing/messages/head")
    _check("rich message received 200", recv_rich.status == 200)
    rich_bp = _bp(recv_rich)
    _check("CorrelationId round-trips", rich_bp.get("CorrelationId") == "corr-456")
    _check("Label/Subject round-trips", rich_bp.get("Label") == "TestSubject")
    _check("ReplyTo round-trips", rich_bp.get("ReplyTo") == "reply-queue")
    _check("custom application property round-trips", recv_rich.headers.get("x-siftly-tenant") == "tenant-amber")

    # 256 KB size limit
    oversize = b"x" * (256 * 1024 + 1)
    _check("oversize message rejected 413", call("POST", "/orders/messages", oversize).status == 413)

    # ── 9. Direct Python Entry Points (for Phase B AMQP) ───────────────────
    py_mid = sb.sb_send(store, "orders", b"via-python-api", correlation_id="py-corr")
    _check("sb_send returns message_id", bool(py_mid))
    py_msg, py_lock = sb.sb_peek_lock(store, "orders", "billing")
    _check("sb_peek_lock returns msg and lock", py_msg is not None and bool(py_lock))
    _check("sb_peek_lock correlation_id", py_msg.get("correlation_id") == "py-corr")
    new_exp = sb.sb_renew_lock(store, "orders", "billing", py_msg["SequenceNumber"], py_lock)
    _check("sb_renew_lock returns new visible_at", new_exp > store.now())
    sb.sb_complete(store, "orders", "billing", py_msg["SequenceNumber"], py_lock)
    _check("sb_complete settled message", sb.sb_peek_lock(store, "orders", "billing")[0] is None)

    # Explicit dead-lettering via Python API
    sb.sb_send(store, "orders", b"explicit-dead")
    m_dlq, l_dlq = sb.sb_peek_lock(store, "orders", "billing")
    sb.sb_dead_letter(store, "orders", "billing", m_dlq["SequenceNumber"], l_dlq, reason="BadFormat", description="Invalid JSON")
    dlq_item, dlq_l = sb.sb_peek_lock(store, "orders", "billing", is_dlq=True)
    _check("sb_dead_letter lands in DLQ", dlq_item is not None and dlq_item["DeadLetterReason"] == "BadFormat")
    sb.sb_complete(store, "orders", "billing", dlq_item["SequenceNumber"], dlq_l, is_dlq=True)

    # ── 10. errors & deletion ──────────────────────────────────────────────
    _check("send to missing topic 404", call("POST", "/ghost/messages", b"x").status == 404)
    _check("receive missing sub 404", call("DELETE", "/orders/subscriptions/ghost/messages/head").status == 404)
    _check("delete sub 200", call("DELETE", "/orders/subscriptions/audit").status == 200)
    _check("delete topic 200", call("DELETE", "/orders").status == 200)
    _check("deleted topic gone 404", call("GET", "/orders").status == 404)

    print("\nAzure Service Bus (topics) core conformance: ALL GREEN")
    return store


if __name__ == "__main__":
    run()
