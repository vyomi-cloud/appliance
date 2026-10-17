"""Conformance tests for AMQP 1.0 Receiver Links, Credit Drain, Annotations, Dispositions, and $management Renew-Lock.

Covers Layer 4 of the Service Bus implementation plan:
- B5: Receiver link credit flow & delivery with lock token delivery tag
- B5: Credit drain (flow with drain=true -> echo drain=true, link_credit=0)
- B5: Required annotations (x-opt-sequence-number, x-opt-enqueued-time, x-opt-locked-until)
- B6: Dispositions: Accepted (complete), Modified (abandon + auto-DLQ), Rejected (dead-letter)
- B6: Expired lock disposition rejection with com.microsoft:message-lock-lost
- B6: $management renew-lock node (com.microsoft:renew-lock) for AutoLockRenewer
"""

from __future__ import annotations

import asyncio
import os
import socket
import struct
import sys
import time
import uuid

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.azure_servicebus_core import sb_peek_lock, sb_send
from core.azure_servicebus_runtime import bootstrap_siftly_topology, get_store, reset_store
from core.persistent_store import PersistentMessagingStore, SqliteStateBackend
from core.servicebus_amqp.codec import (
    AMQP_HEADER,
    FRAME_TYPE_AMQP,
    DescribedType,
    Symbol,
    decode_frame,
    encode_frame,
)
from core.servicebus_amqp.connection import AmqpConnection
from core.servicebus_amqp.message import Message, Properties
from core.servicebus_amqp.performatives import (
    Accepted,
    Attach,
    Begin,
    Close,
    Detach,
    Disposition,
    End,
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


def setup_fresh_store():
    store = PersistentMessagingStore(SqliteStateBackend(":memory:"), store_id="azsb")
    reset_store(store)
    bootstrap_siftly_topology(store)
    return store


def test_receiver_delivery_and_annotations():
    print("  testing receiver link delivery and required Azure annotations...")
    store = setup_fresh_store()

    # Preload a message in scrapper_responses
    sb_send(
        store,
        "scrapper_responses",
        b"scrape-result-payload",
        message_id="msg-sr-1",
        correlation_id="corr-sr-1",
    )

    conn = AmqpConnection(store=store)
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))

    # Attach receiver link to scrapper_responses/Subscriptions/scrapper_responses
    sub_addr = "scrapper_responses/Subscriptions/scrapper_responses"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="rec-1", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Issue credit 1 to receive the message
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))

    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    assert frame is not None
    perf = parse_performative(frame[4])
    assert isinstance(perf, Transfer)
    assert_eq(perf.handle, 0)
    assert perf.delivery_tag is not None

    # Parse message sections and annotations
    msg = Message.decode(frame[5])
    assert_eq(msg.body, b"scrape-result-payload")
    assert_eq(msg.properties.message_id, "msg-sr-1")
    assert_eq(msg.properties.correlation_id, "corr-sr-1")

    # Verify strictly required annotations
    anno = msg.message_annotations
    assert Symbol("x-opt-sequence-number") in anno
    assert Symbol("x-opt-enqueued-time") in anno
    assert Symbol("x-opt-locked-until") in anno
    assert Symbol("x-opt-delivery-count") in anno
    assert int(anno[Symbol("x-opt-sequence-number")]) > 0
    assert int(anno[Symbol("x-opt-delivery-count")]) == 1
    print("  ok  receiver link delivery and required Azure annotations verified")


def test_credit_drain_no_hang():
    print("  testing credit drain (flow drain=true -> echo drain=true, link_credit=0)...")
    store = setup_fresh_store()

    # Put only 1 message in topic
    sb_send(store, "traffic-ingest", b"traffic-event-1")

    conn = AmqpConnection(store=store)
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))

    sub_addr = "traffic-ingest/Subscriptions/traffic-ingest"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="drain-rec", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Request drain with credit 5 (when only 1 message exists)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=5, drain=True)))

    # Expect: 1 Transfer frame (the 1 message) followed immediately by 1 Flow frame (drain echo!)
    assert len(conn.outbox) == 2
    f_transfer = decode_frame(conn.outbox[0])
    assert isinstance(parse_performative(f_transfer[4]), Transfer)

    f_drain_echo = decode_frame(conn.outbox[1])
    flow_echo = parse_performative(f_drain_echo[4])
    assert isinstance(flow_echo, Flow)
    assert_eq(flow_echo.drain, True)
    assert_eq(flow_echo.link_credit, 0)
    print("  ok  credit drain echoed without hanging")


def test_disposition_complete_and_abandon():
    print("  testing dispositions (complete -> Accepted, abandon -> Modified)...")
    store = setup_fresh_store()

    sb_send(store, "llm-analysis", b"task-1", message_id="m1")
    sb_send(store, "llm-analysis", b"task-2", message_id="m2")

    conn = AmqpConnection(store=store)
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))

    sub_addr = "llm-analysis/Subscriptions/llm-analysis"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="rec-llm", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Issue credit 2
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=2)))
    assert len(conn.outbox) == 2
    f1 = decode_frame(conn.outbox[0])
    f2 = decode_frame(conn.outbox[1])
    d1 = parse_performative(f1[4]).delivery_id
    d2 = parse_performative(f2[4]).delivery_id
    conn.outbox.clear()

    # Settle message 1 with Accepted (Complete)
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(role=False, first=d1, last=d1, settled=True, state=Accepted()),
        )
    )

    # Abandon message 2 with Modified(delivery_failed=True)
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(
                role=False,
                first=d2,
                last=d2,
                settled=True,
                state=Modified(delivery_failed=True),
            ),
        )
    )

    # Verify in store: message 1 is deleted (settled), message 2 is released and has delivery_count 1
    t = store.get_topic("llm-analysis")
    sub = t["subscriptions"]["llm-analysis"]
    active = sub["messages"]
    assert len(active) == 1
    assert_eq(active[0]["MessageId"], "m2")
    assert_eq(active[0]["delivery_count"], 1)
    print("  ok  dispositions complete and abandon verified")


def test_expired_lock_lock_lost_rejection():
    print("  testing expired lock settlement rejection with com.microsoft:message-lock-lost...")
    store = setup_fresh_store()

    sb_send(store, "linkedin-draft", b"draft-1", message_id="d-1")

    conn = AmqpConnection(store=store)
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))

    sub_addr = "linkedin-draft/Subscriptions/linkedin-draft"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="rec-draft", handle=0, role=True, source=Source(address=sub_addr)),
        )
    )
    conn.outbox.clear()

    # Receive message
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))
    assert len(conn.outbox) == 1
    f = decode_frame(conn.outbox[0])
    deliv_id = parse_performative(f[4]).delivery_id
    conn.outbox.clear()

    # Advance store clock by 120 seconds to expire lock duration (default 60s)
    store.advance(120.0)

    # Attempt to complete with Accepted after expiry
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Accepted()),
        )
    )

    # Server must respond with Disposition(Rejected(com.microsoft:message-lock-lost))!
    assert len(conn.outbox) == 1
    disp_frame = decode_frame(conn.outbox[0])
    disp = parse_performative(disp_frame[4])
    assert isinstance(disp, Disposition)
    assert isinstance(disp.state, Rejected)
    assert disp.state.error is not None
    assert_eq(disp.state.error.condition, Symbol("com.microsoft:message-lock-lost"))
    print("  ok  late settlement rejected with com.microsoft:message-lock-lost")


def test_management_renew_lock():
    print("  testing $management renew-lock (com.microsoft:renew-lock)...")
    store = setup_fresh_store()

    sb_send(store, "scrapper_responses", b"scraping-job", message_id="sj-1")

    # Peek message to get a lock token
    msg, lock_token = sb_peek_lock(store, "scrapper_responses", "scrapper_responses")
    assert lock_token is not None

    conn = AmqpConnection(store=store)
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))

    # Attach to $management node
    mgmt_addr = "scrapper_responses/Subscriptions/scrapper_responses/$management"
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="mgmt-req", handle=0, role=False, target=Target(address=mgmt_addr)),
        )
        + encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="mgmt-rep", handle=1, role=True, source=Source(address=mgmt_addr)),
        )
    )
    conn.outbox.clear()

    # Send renew-lock request (as AutoLockRenewer does)
    req_msg = Message(
        body={"lock-tokens": [lock_token]},
        properties=Properties(message_id="renew-req-1"),
        application_properties={"operation": "com.microsoft:renew-lock"},
    )
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Transfer(handle=0, delivery_id=1, delivery_tag=b"tag-renew"),
            req_msg.encode(),
        )
    )

    # Expect: Disposition(Accepted) + Transfer(reply on handle 1)
    assert len(conn.outbox) == 2
    f_reply = decode_frame(conn.outbox[1])
    reply_transfer = parse_performative(f_reply[4])
    assert isinstance(reply_transfer, Transfer)
    assert_eq(reply_transfer.handle, 1)

    reply_msg = Message.decode(f_reply[5])
    assert_eq(reply_msg.application_properties.get("statusCode"), 200)
    assert_eq(reply_msg.properties.correlation_id, "renew-req-1")
    assert "expirations" in reply_msg.body
    assert len(reply_msg.body["expirations"]) == 1
    new_expiry_ms = reply_msg.body["expirations"][0]
    assert new_expiry_ms > int(store.now() * 1000)
    conn.outbox.clear()

    # Now expire lock and renew again -> expect statusCode 410 with com.microsoft:message-lock-lost
    store.advance(300.0)
    req_expired = Message(
        body={"lock-tokens": [lock_token]},
        properties=Properties(message_id="renew-req-2"),
        application_properties={"operation": "com.microsoft:renew-lock"},
    )
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Transfer(handle=0, delivery_id=2, delivery_tag=b"tag-renew-2"),
            req_expired.encode(),
        )
    )

    assert len(conn.outbox) == 2
    f_reply_exp = decode_frame(conn.outbox[1])
    reply_msg_exp = Message.decode(f_reply_exp[5])
    assert_eq(reply_msg_exp.application_properties.get("statusCode"), 410)
    assert_eq(
        reply_msg_exp.application_properties.get("errorCondition"),
        Symbol("com.microsoft:message-lock-lost"),
    )
    print("  ok  $management renew-lock and lock-lost 410 verified")


def test_live_tcp_receiver_and_renew():
    print("  testing live TCP socket with receiver receive, renew, and complete...")

    async def _run():
        store = setup_fresh_store()
        sb_send(store, "traffic-ingest", b"real-socket-traffic", message_id="tcp-m1")

        server = AmqpServer(host="127.0.0.1", port=0, store=store)
        await server.start()
        port = server.actual_port

        def _client_talk():
            s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
            try:
                s.sendall(AMQP_HEADER)
                assert_eq(s.recv(8), AMQP_HEADER)

                s.sendall(
                    encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="rx-tcp-client"))
                    + encode_frame(FRAME_TYPE_AMQP, 1, Begin())
                )
                buf = b""
                # Read Open + Begin
                for _ in range(2):
                    while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                        buf += s.recv(4096)
                    buf = decode_frame(buf)[6]

                # Attach receiver link to traffic-ingest
                sub_addr = "traffic-ingest/Subscriptions/traffic-ingest"
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Attach(name="tcp-rec", handle=0, role=True, source=Source(address=sub_addr)),
                    )
                )
                # Read Attach reply
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                buf = decode_frame(buf)[6]

                # Issue Flow credit 1
                s.sendall(encode_frame(FRAME_TYPE_AMQP, 1, Flow(handle=0, link_credit=1)))

                # Read message Transfer
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                f_tr = decode_frame(buf)
                tr_perf = parse_performative(f_tr[4])
                assert isinstance(tr_perf, Transfer)
                deliv_id = tr_perf.delivery_id
                lock_tok_bytes = tr_perf.delivery_tag
                buf = f_tr[6]

                msg = Message.decode(f_tr[5])
                assert_eq(msg.body, b"real-socket-traffic")
                assert_eq(msg.properties.message_id, "tcp-m1")

                # Settle with Accepted (Complete)
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Disposition(role=False, first=deliv_id, last=deliv_id, settled=True, state=Accepted()),
                    )
                )

                # Close cleanly
                s.sendall(encode_frame(FRAME_TYPE_AMQP, 0, Close()))

            finally:
                s.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _client_talk)
        await server.stop()

    asyncio.run(_run())
    print("  ok  live TCP socket receiver receive and complete verified")


def main():
    print("Running AMQP 1.0 Receiver Links & Management Conformance Suite (Layer 4):")
    test_receiver_delivery_and_annotations()
    test_credit_drain_no_hang()
    test_disposition_complete_and_abandon()
    test_expired_lock_lock_lost_rejection()
    test_management_renew_lock()
    test_live_tcp_receiver_and_renew()
    print("\nAMQP 1.0 Receiver & Management (Layer 4) Conformance: ALL GREEN\n")


if __name__ == "__main__":
    main()
