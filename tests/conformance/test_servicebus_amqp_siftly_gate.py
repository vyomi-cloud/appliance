"""Phase C Siftly Acceptance Gate: Scenarios A1 through A9.

Verifies the 9 mandatory Siftly worker & traffic-ingest scenarios over AMQP 1.0:
- A1: Single send & peek-lock receive
- A2: Batch send (format 0x80013700) & receive
- A3: Complete settlement (Accepted -> removed from backlog)
- A4: Abandon settlement (Modified -> released with incremented delivery_count)
- A5: Auto-dead-lettering on 10th abandon (MaxDeliveryCountExceeded)
- A6: Explicit dead-lettering (Rejected -> moves to DLQ with reason and description)
- A7: Dead-letter queue receive from <sub_path>/$DeadLetterQueue
- A8: Auto-lock renewal loop over 3+ successive renewals
- A9: 256 KB message size limit rejection (amqp:link:message-size-exceeded)
"""

import uuid
import asyncio
import socket
import struct
import time
from typing import Any

from core.azure_servicebus_core import (
    sb_peek_lock,
    sb_send,
)
from core.azure_servicebus_runtime import bootstrap_siftly_topology, reset_store
from core.persistent_store import PersistentMessagingStore, SqliteStateBackend
from core.servicebus_amqp.codec import (
    AMQP_HEADER,
    FRAME_TYPE_AMQP,
    DescribedType,
    Symbol,
    Timestamp,
    decode_frame,
    encode_frame,
)
from core.servicebus_amqp.connection import AmqpConnection
from core.servicebus_amqp.message import (
    SERVICE_BUS_BATCH_FORMAT,
    Message,
    Properties,
)
from core.servicebus_amqp.performatives import (
    Accepted,
    Attach,
    Begin,
    Close,
    Detach,
    Disposition,
    Error,
    Flow,
    Modified,
    Open,
    Rejected,
    Source,
    Target,
    Transfer,
    parse_performative,
)
from core.servicebus_amqp.server import AmqpServer


def assert_eq(actual, expected, msg=""):
    assert actual == expected, f"{msg} | expected {expected!r}, got {actual!r}"


def setup_fresh_store() -> PersistentMessagingStore:
    store = PersistentMessagingStore(SqliteStateBackend(":memory:"), store_id="azsb")
    reset_store(store)
    bootstrap_siftly_topology(store)
    return store


def setup_connected_client(
    store: PersistentMessagingStore,
    container_id: str = "siftly-gate-client",
) -> AmqpConnection:
    conn = AmqpConnection(store=store, container_id="vyomi-servicebus-emulator")
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id=container_id)))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))
    conn.outbox.clear()
    return conn


# ── A1: Single Send & Peek-Lock Receive ───────────────────────────────────────────
def test_gate_a1_single_send_and_peek_lock_receive():
    print("  [A1] testing single send & peek-lock receive...")
    store = setup_fresh_store()
    conn = setup_connected_client(store)

    # Attach sender link to traffic-ingest
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="s-traffic", handle=0, role=False, target=Target(address="traffic-ingest")),
        )
    )
    # Attach receiver link to traffic-ingest subscription
    sub_addr = "traffic-ingest/Subscriptions/traffic-ingest"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="r-traffic", handle=1, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Send message via sender link (handle 0)
    msg_out = Message(
        body=b'{"event":"traffic_click","url":"https://linkedin.com/in/test"}',
        properties=Properties(
            message_id="a1-msg-id-100",
            correlation_id="corr-100",
            subject="traffic.click",
            content_type="application/json",
        ),
        application_properties={"tenant": "siftly-prod", "version": "1.0"},
    )
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Transfer(handle=0, delivery_id=1, delivery_tag=b"tag-a1-1"),
            msg_out.encode(),
        )
    )

    # Expect: Disposition(Accepted) on sender link
    assert len(conn.outbox) == 1
    f_disp = decode_frame(conn.outbox[0])
    p_disp = parse_performative(f_disp[4])
    assert isinstance(p_disp, Disposition)
    assert isinstance(p_disp.state, Accepted)
    conn.outbox.clear()

    # Issue Flow credit 1 on receiver link (handle 1)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=1, link_credit=1)))

    # Expect: Transfer on receiver link
    assert len(conn.outbox) == 1
    f_rx = decode_frame(conn.outbox[0])
    p_rx = parse_performative(f_rx[4])
    assert isinstance(p_rx, Transfer)
    assert_eq(p_rx.handle, 1)
    lock_token_bytes = p_rx.delivery_tag
    assert lock_token_bytes is not None

    msg_in = Message.decode(f_rx[5])
    assert_eq(msg_in.body, b'{"event":"traffic_click","url":"https://linkedin.com/in/test"}')
    assert_eq(msg_in.properties.message_id, "a1-msg-id-100")
    assert_eq(msg_in.properties.correlation_id, "corr-100")
    assert_eq(msg_in.properties.subject, "traffic.click")
    assert_eq(msg_in.application_properties.get("tenant"), "siftly-prod")

    anno = msg_in.message_annotations
    assert Symbol("x-opt-sequence-number") in anno
    assert Symbol("x-opt-enqueued-time") in anno
    assert Symbol("x-opt-locked-until") in anno
    assert Symbol("x-opt-delivery-count") in anno
    assert int(anno[Symbol("x-opt-delivery-count")]) == 1
    print("  ok  [A1] single send & peek-lock receive verified with annotations")


# ── A2: Batch Send (0x80013700) & Receive ──────────────────────────────────────────
def test_gate_a2_batch_send_and_receive():
    print("  [A2] testing batch send (format 0x80013700) & receive...")
    store = setup_fresh_store()
    conn = setup_connected_client(store)

    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="s-batch", handle=0, role=False, target=Target(address="scrapper_responses")),
        )
        + encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(
                name="r-batch",
                handle=1,
                role=True,
                source=Source(address="scrapper_responses/Subscriptions/scrapper_responses"),
            ),
        )
    )
    conn.outbox.clear()

    # Prepare batch of 3 messages
    batch_items = [
        Message(
            body=f'{{"batch_idx":{i}}}'.encode("utf-8"),
            properties=Properties(message_id=f"batch-msg-{i}"),
        )
        for i in range(3)
    ]
    batch_payload = Message.encode_batch(batch_items)

    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Transfer(
                handle=0,
                delivery_id=1,
                delivery_tag=b"tag-batch",
                message_format=SERVICE_BUS_BATCH_FORMAT,
            ),
            batch_payload,
        )
    )

    # Expect: Disposition(Accepted) for the batch transfer
    assert len(conn.outbox) == 1
    f_disp = decode_frame(conn.outbox[0])
    assert isinstance(parse_performative(f_disp[4]).state, Accepted)
    conn.outbox.clear()

    # Receive all 3 messages via credit 3
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=1, link_credit=3)))
    assert len(conn.outbox) == 3

    received_ids = []
    for ob in conn.outbox:
        f = decode_frame(ob)
        m = Message.decode(f[5])
        received_ids.append(m.properties.message_id)

    assert_eq(received_ids, ["batch-msg-0", "batch-msg-1", "batch-msg-2"])
    print("  ok  [A2] batch send (format 0x80013700) and ordered receive verified")


# ── A3: Complete Settlement ────────────────────────────────────────────────────────
def test_gate_a3_complete_settlement():
    print("  [A3] testing complete settlement (Accepted -> settled)...")
    store = setup_fresh_store()
    sb_send(store, "llm-analysis", b"analyze-job-1", message_id="llm-m1")

    conn = setup_connected_client(store)
    sub_addr = "llm-analysis/Subscriptions/llm-analysis"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="r-llm", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Receive message
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f_rx = decode_frame(conn.outbox[0])
    deliv_id = parse_performative(f_rx[4]).delivery_id
    conn.outbox.clear()

    # Settle with Accepted (Complete)
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Accepted()),
        )
    )

    # Verify message is completely removed from subscription
    sub = store.get_topic("llm-analysis")["subscriptions"]["llm-analysis"]
    assert len(sub["messages"]) == 0
    print("  ok  [A3] complete settlement removed message from backlog")


# ── A4: Abandon Settlement & Redelivery ─────────────────────────────────────────────
def test_gate_a4_abandon_settlement_and_redelivery():
    print("  [A4] testing abandon settlement (Modified -> released with delivery_count+1)...")
    store = setup_fresh_store()
    sb_send(store, "partner-scraper-responses", b"partner-item-1", message_id="p-1")

    conn = setup_connected_client(store)
    sub_addr = "partner-scraper-responses/Subscriptions/partner-scraper-responses"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="r-partner", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Receive message (1st time)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f_rx = decode_frame(conn.outbox[0])
    deliv_id1 = parse_performative(f_rx[4]).delivery_id
    conn.outbox.clear()

    # Settle with Modified(delivery_failed=True) -> Abandon
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(
                role=False,
                first=deliv_id1,
                last=deliv_id1,
                settled=True,
                state=Modified(delivery_failed=True),
            ),
        )
    )

    # Receive message again (2nd time)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f_rx2 = decode_frame(conn.outbox[0])
    msg2 = Message.decode(f_rx2[5])
    assert_eq(msg2.properties.message_id, "p-1")
    assert_eq(int(msg2.message_annotations[Symbol("x-opt-delivery-count")]), 2)
    print("  ok  [A4] abandon settlement released message and incremented delivery_count to 2")


# ── A5: Auto-Dead-Lettering on 10th Abandon ─────────────────────────────────────────
def test_gate_a5_auto_dead_lettering_on_max_delivery_count():
    print("  [A5] testing auto-dead-lettering on 10th abandon (MaxDeliveryCountExceeded)...")
    store = setup_fresh_store()
    sb_send(store, "linkedin-draft", b"poison-draft", message_id="poison-1")

    conn = setup_connected_client(store)
    sub_addr = "linkedin-draft/Subscriptions/linkedin-draft"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="r-draft", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Abandon 10 times in a loop
    for attempt in range(1, 11):
        conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
        assert len(conn.outbox) == 1, f"Expected message on attempt {attempt}"
        f_rx = decode_frame(conn.outbox[0])
        deliv_id = parse_performative(f_rx[4]).delivery_id
        conn.outbox.clear()

        # Abandon
        conn.feed_data(
            encode_frame(
                FRAME_TYPE_AMQP,
                1,
                Disposition(
                    role=False,
                    first=deliv_id,
                    last=deliv_id,
                    settled=True,
                    state=Modified(delivery_failed=True),
                ),
            )
        )

    # After 10th abandon:
    # 1. Main subscription must be EMPTY
    sub = store.get_topic("linkedin-draft")["subscriptions"]["linkedin-draft"]
    assert len(sub["messages"]) == 0, "Main queue must be empty after 10th abandon"

    # 2. DLQ must contain the poison message with reason MaxDeliveryCountExceeded
    assert len(sub["dead_letter"]) == 1
    dlq_msg = sub["dead_letter"][0]
    assert_eq(dlq_msg["MessageId"], "poison-1")
    assert_eq(dlq_msg["DeadLetterReason"], "MaxDeliveryCountExceeded")
    print("  ok  [A5] auto-dead-lettered to DLQ on 10th abandon with MaxDeliveryCountExceeded")


# ── A6: Explicit Dead-Lettering ─────────────────────────────────────────────────────
def test_gate_a6_explicit_dead_lettering():
    print("  [A6] testing explicit dead-lettering (Rejected -> DLQ with reason & desc)...")
    store = setup_fresh_store()
    sb_send(store, "traffic-ingest", b"bad-schema-payload", message_id="bad-1")

    conn = setup_connected_client(store)
    sub_addr = "traffic-ingest/Subscriptions/traffic-ingest"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="r-traffic", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Receive message
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f_rx = decode_frame(conn.outbox[0])
    deliv_id = parse_performative(f_rx[4]).delivery_id
    conn.outbox.clear()

    # Settle with Rejected(Error(..., info={DeadLetterReason, DeadLetterErrorDescription}))
    err = Error(
        condition=Symbol("com.microsoft:dead-letter"),
        description="Payload failed validation schema check",
        info={
            "DeadLetterReason": "InvalidSchemaPayload",
            "DeadLetterErrorDescription": "Field 'user_id' is missing",
        },
    )
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Rejected(err)),
        )
    )

    # Verify landed in DLQ with exact fields
    sub = store.get_topic("traffic-ingest")["subscriptions"]["traffic-ingest"]
    assert len(sub["messages"]) == 0
    assert len(sub["dead_letter"]) == 1
    dead = sub["dead_letter"][0]
    assert_eq(dead["DeadLetterReason"], "InvalidSchemaPayload")
    assert_eq(dead["DeadLetterErrorDescription"], "Field 'user_id' is missing")
    print("  ok  [A6] explicit dead-letter landed in DLQ with custom reason & description")


# ── A7: Dead-Letter Queue Receive ──────────────────────────────────────────────────
def test_gate_a7_dead_letter_queue_receive():
    print("  [A7] testing dead-letter queue receive from <sub_path>/$DeadLetterQueue...")
    store = setup_fresh_store()

    # Put a message directly into DLQ
    sb_send(store, "scrapper_responses", b"scraping-failed", message_id="failed-dlq-1")
    # Peek and dead-letter it
    m, l = sb_peek_lock(store, "scrapper_responses", "scrapper_responses")
    from core.azure_servicebus_core import sb_dead_letter
    sb_dead_letter(
        store,
        "scrapper_responses",
        "scrapper_responses",
        lock=l,
        reason="ScrapeTargetDown",
        description="Target host unreachable after 3 retries",
    )

    conn = setup_connected_client(store)
    # Attach receiver link to the DLQ address
    dlq_addr = "scrapper_responses/Subscriptions/scrapper_responses/$DeadLetterQueue"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="r-dlq", handle=0, role=True, source=Source(address=dlq_addr)),
        )
    )
    conn.outbox.clear()

    # Receive the message from DLQ
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f_rx = decode_frame(conn.outbox[0])
    p_rx = parse_performative(f_rx[4])
    assert isinstance(p_rx, Transfer)
    deliv_id = p_rx.delivery_id

    msg_dlq = Message.decode(f_rx[5])
    assert_eq(msg_dlq.body, b"scraping-failed")
    assert_eq(msg_dlq.properties.message_id, "failed-dlq-1")
    assert_eq(msg_dlq.message_annotations.get(Symbol("x-opt-dead-letter-reason")), "ScrapeTargetDown")
    assert_eq(
        msg_dlq.message_annotations.get(Symbol("x-opt-dead-letter-description")),
        "Target host unreachable after 3 retries",
    )
    conn.outbox.clear()

    # Complete the DLQ message
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Accepted()),
        )
    )

    # Verify DLQ is now empty
    sub = store.get_topic("scrapper_responses")["subscriptions"]["scrapper_responses"]
    assert len(sub["dead_letter"]) == 0
    print("  ok  [A7] dead-letter queue receive, DLQ annotations, and DLQ completion verified")


# ── A8: Auto-Lock Renewal Loop (AutoLockRenewer) ───────────────────────────────────
def test_gate_a8_auto_lock_renewer_loop():
    print("  [A8] testing auto-lock renewal loop (3+ successive renew-lock cycles)...")
    store = setup_fresh_store()
    sb_send(store, "llm-analysis", b"heavy-llm-task", message_id="llm-task-long")

    conn = setup_connected_client(store)
    sub_addr = "llm-analysis/Subscriptions/llm-analysis"
    mgmt_addr = "llm-analysis/Subscriptions/llm-analysis/$management"

    # Attach receiver link and $management link pair
    conn.feed_data(
        encode_frame(FRAME_TYPE_AMQP, 1, Attach(name="r-llm", handle=0, role=True, source=Source(address=sub_addr)))
        + encode_frame(
            FRAME_TYPE_AMQP, 1, Attach(name="mgmt-req", handle=1, role=False, target=Target(address=mgmt_addr))
        )
        + encode_frame(
            FRAME_TYPE_AMQP, 1, Attach(name="mgmt-rep", handle=2, role=True, source=Source(address=mgmt_addr))
        )
    )
    conn.outbox.clear()

    # Receive message to obtain lock token
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f_rx = decode_frame(conn.outbox[0])
    p_rx = parse_performative(f_rx[4])
    deliv_id = p_rx.delivery_id
    # Delivery tag is the lock token as a little-endian GUID (what the Azure
    # SDKs read); renew-lock sends it back as an AMQP uuid.
    lock_token = uuid.UUID(bytes_le=p_rx.delivery_tag)
    conn.outbox.clear()

    # Perform 3 successive renewal cycles, advancing the clock by 40s each time (before 60s timeout)
    prev_expiry = int(store.now() * 1000)
    for cycle in range(1, 4):
        store.advance(40.0)

        req_msg = Message(
            body={"lock-tokens": [lock_token]},
            properties=Properties(message_id=f"renew-cycle-{cycle}"),
            application_properties={"operation": "com.microsoft:renew-lock"},
        )
        conn.feed_data(
            encode_frame(
                FRAME_TYPE_AMQP,
                1,
                Transfer(handle=1, delivery_id=100 + cycle, delivery_tag=f"tag-renew-{cycle}".encode("ascii")),
                req_msg.encode(),
            )
        )

        # Expect Disposition(Accepted) + Transfer(reply)
        assert len(conn.outbox) == 2
        f_rep = decode_frame(conn.outbox[1])
        rep_msg = Message.decode(f_rep[5])
        assert_eq(rep_msg.application_properties.get("statusCode"), 200)
        assert "expirations" in rep_msg.body
        new_exp = int(rep_msg.body["expirations"][0])
        assert new_exp > prev_expiry
        prev_expiry = new_exp
        conn.outbox.clear()

    # After 3 renewals (120s total elapsed > initial 60s lock duration), complete the message!
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Accepted()),
        )
    )

    # Message must be cleanly settled
    sub = store.get_topic("llm-analysis")["subscriptions"]["llm-analysis"]
    assert len(sub["messages"]) == 0
    print("  ok  [A8] auto-lock renewal loop survived 3 renewals and completed message cleanly")


# ── A9: 256 KB Message Size Limit Rejection ────────────────────────────────────────
def test_gate_a9_message_size_limit_rejection():
    print("  [A9] testing 256 KB message size limit rejection (amqp:link:message-size-exceeded)...")
    store = setup_fresh_store()
    conn = setup_connected_client(store)

    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="s-oversize", handle=0, role=False, target=Target(address="traffic-ingest")),
        )
    )
    conn.outbox.clear()

    # Send a message with 300 KB payload (> 256 KB limit)
    oversized_body = b"X" * (300 * 1024)
    msg_oversize = Message(body=oversized_body, properties=Properties(message_id="oversize-msg"))
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Transfer(handle=0, delivery_id=1, delivery_tag=b"tag-oversize"),
            msg_oversize.encode(),
        )
    )

    # Server must reject by detaching link with amqp:link:message-size-exceeded
    assert len(conn.outbox) == 1
    f_detach = decode_frame(conn.outbox[0])
    detach_perf = parse_performative(f_detach[4])
    assert isinstance(detach_perf, Detach)
    assert detach_perf.closed is True
    assert detach_perf.error is not None
    assert_eq(detach_perf.error.condition, Symbol("amqp:link:message-size-exceeded"))
    print("  ok  [A9] oversize message rejected with amqp:link:message-size-exceeded")


def _read_frame(s: socket.socket, buf: bytes) -> tuple[Any, bytes]:
    """Read one complete AMQP frame from `s`, appending to `buf` as needed.

    Returns (decoded_frame_tuple, remaining_buf). Raises ConnectionError if
    the peer closes the connection before a full frame arrives — recv()
    returns b"" immediately on a graceful close, so without this check the
    read loop busy-spins forever instead of failing fast.
    """
    while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
        chunk = s.recv(4096)
        if not chunk:
            raise ConnectionError("Connection closed while waiting for a frame")
        buf += chunk
    frame = decode_frame(buf)
    return frame, frame[6]


# ── Live TCP Socket Integration (End-to-End Gate) ──────────────────────────────────
def test_live_tcp_siftly_end_to_end_gate():
    print("  [E2E] testing live TCP socket end-to-end (send -> receive -> complete)...")

    async def _run():
        store = setup_fresh_store()
        server = AmqpServer(host="127.0.0.1", port=0, store=store)
        await server.start()
        try:
            port = server.actual_port

            def _client_talk():
                s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
                try:
                    # 1. Handshake
                    s.sendall(AMQP_HEADER)
                    assert_eq(s.recv(8), AMQP_HEADER)

                    s.sendall(
                        encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="e2e-client"))
                        + encode_frame(FRAME_TYPE_AMQP, 1, Begin())
                    )
                    buf = b""
                    for _ in range(2):
                        _, buf = _read_frame(s, buf)

                    # 2. Attach sender to traffic-ingest
                    s.sendall(
                        encode_frame(
                            FRAME_TYPE_AMQP,
                            1,
                            Attach(name="s-e2e", handle=0, role=False, target=Target(address="traffic-ingest")),
                        )
                    )
                    # Read Attach reply + initial flow
                    for _ in range(2):
                        _, buf = _read_frame(s, buf)

                    # 3. Send message
                    out_msg = Message(
                        body=b"live-traffic-event-data",
                        properties=Properties(message_id="e2e-m1"),
                    )
                    s.sendall(
                        encode_frame(
                            FRAME_TYPE_AMQP,
                            1,
                            Transfer(handle=0, delivery_id=1, delivery_tag=b"tag-e2e-1"),
                            out_msg.encode(),
                        )
                    )
                    # Read Disposition
                    f_disp, buf = _read_frame(s, buf)
                    assert isinstance(parse_performative(f_disp[4]).state, Accepted)

                    # 4. Attach receiver to traffic-ingest subscription
                    sub_addr = "traffic-ingest/Subscriptions/traffic-ingest"
                    s.sendall(
                        encode_frame(
                            FRAME_TYPE_AMQP,
                            1,
                            Attach(name="r-e2e", handle=1, role=True, source=Source(address=sub_addr)),
                        )
                    )
                    _, buf = _read_frame(s, buf)

                    # 5. Receive message via Flow credit 1
                    s.sendall(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=1, link_credit=1)))
                    f_rx, buf = _read_frame(s, buf)
                    p_rx = parse_performative(f_rx[4])
                    deliv_id = p_rx.delivery_id

                    rx_msg = Message.decode(f_rx[5])
                    assert_eq(rx_msg.body, b"live-traffic-event-data")
                    assert_eq(rx_msg.properties.message_id, "e2e-m1")

                    # 6. Settle with Accepted (Complete)
                    s.sendall(
                        encode_frame(
                            FRAME_TYPE_AMQP,
                            1,
                            Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Accepted()),
                        )
                    )

                    # 7. Close cleanly
                    s.sendall(encode_frame(FRAME_TYPE_AMQP, 0, Close()))
                finally:
                    s.close()

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _client_talk)
        finally:
            await server.stop()

    asyncio.run(_run())
    print("  ok  [E2E] live TCP socket send, receive, and complete verified")


def main():
    print("Running Siftly Acceptance Gate A1-A9 Conformance Suite (Layer 6):")
    test_gate_a1_single_send_and_peek_lock_receive()
    test_gate_a2_batch_send_and_receive()
    test_gate_a3_complete_settlement()
    test_gate_a4_abandon_settlement_and_redelivery()
    test_gate_a5_auto_dead_lettering_on_max_delivery_count()
    test_gate_a6_explicit_dead_lettering()
    test_gate_a7_dead_letter_queue_receive()
    test_gate_a8_auto_lock_renewer_loop()
    test_gate_a9_message_size_limit_rejection()
    test_live_tcp_siftly_end_to_end_gate()
    print("\nPhase C Siftly Verification (Layer 6) Conformance: ALL GREEN\n")


if __name__ == "__main__":
    main()
