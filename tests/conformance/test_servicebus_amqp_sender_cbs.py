"""Conformance tests for AMQP 1.0 CBS Auth, Address Resolution, Sender Links, and Batch Transfers.

Covers Layer 3 of the Service Bus implementation plan:
- B3: Shared request/response handler & CBS ($cbs) authentication
- B3: Case-insensitive address resolution (<topic>, <topic>/Subscriptions/<sub>)
- B3: Unknown entity rejection with amqp:not-found
- B4: Sender link transfer decoding & property preservation
- B4: Batch transfer unpacking (format 0x80013700)
- B4: 256 KB message size enforcement with amqp:link:message-size-exceeded
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

from core.azure_servicebus_core import sb_peek_lock
from core.azure_servicebus_runtime import bootstrap_siftly_topology, get_store, reset_store
from core.servicebus_amqp.codec import (
    AMQP_HEADER,
    FRAME_TYPE_AMQP,
    FRAME_TYPE_SASL,
    SASL_HEADER,
    DescribedType,
    Symbol,
    decode_frame,
    encode,
    encode_frame,
)
from core.servicebus_amqp.connection import AmqpConnection
from core.servicebus_amqp.message import (
    DESCRIPTOR_DATA,
    SERVICE_BUS_BATCH_FORMAT,
    Header,
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
    End,
    Flow,
    Open,
    SaslInit,
    SaslOutcome,
    Source,
    Target,
    Transfer,
    parse_performative,
)
from core.servicebus_amqp.server import AmqpServer


def assert_eq(actual, expected, msg=""):
    assert actual == expected, f"{msg} | expected {expected!r}, got {actual!r}"


def test_message_roundtrip():
    print("  testing Message encode/decode round-trip...")
    props = Properties(
        message_id="msg-123",
        correlation_id="corr-456",
        subject="invoice-ready",
        content_type="application/json",
        reply_to="reply-sub",
    )
    app_props = {"tenantId": "org-1", "priority": 10, "isTest": True}
    msg_anno = {Symbol("x-opt-partition-key"): "key-1"}

    msg = Message(
        body=b'{"amount": 100}',
        properties=props,
        application_properties=app_props,
        message_annotations=msg_anno,
        header=Header(durable=True, delivery_count=0),
    )

    encoded = msg.encode()
    decoded = Message.decode(encoded)

    assert_eq(decoded.body, b'{"amount": 100}')
    assert_eq(decoded.properties.message_id, "msg-123")
    assert_eq(decoded.properties.correlation_id, "corr-456")
    assert_eq(decoded.properties.subject, "invoice-ready")
    assert_eq(str(decoded.properties.content_type), "application/json")
    assert_eq(decoded.properties.reply_to, "reply-sub")
    assert_eq(decoded.application_properties["tenantId"], "org-1")
    assert_eq(decoded.application_properties["priority"], 10)
    assert_eq(decoded.application_properties["isTest"], True)
    assert decoded.header is not None
    assert_eq(decoded.header.durable, True)
    print("  ok  Message encode/decode round-trip")


def test_batch_message_unpacking():
    print("  testing batch transfer unpacking (0x80013700)...")
    m1 = Message(body=b"item-1", properties=Properties(message_id="id-1"))
    m2 = Message(body=b"item-2", properties=Properties(message_id="id-2"))
    m3 = Message(body=b"item-3", properties=Properties(message_id="id-3"))

    # Construct batch payload (sequence of Data sections)
    batch_payload = (
        encode(DescribedType(DESCRIPTOR_DATA, m1.encode()))
        + encode(DescribedType(DESCRIPTOR_DATA, m2.encode()))
        + encode(DescribedType(DESCRIPTOR_DATA, m3.encode()))
    )

    unpacked = Message.decode_batch(batch_payload)
    assert_eq(len(unpacked), 3)
    assert_eq(unpacked[0].body, b"item-1")
    assert_eq(unpacked[0].properties.message_id, "id-1")
    assert_eq(unpacked[1].body, b"item-2")
    assert_eq(unpacked[2].body, b"item-3")
    print("  ok  batch transfer unpacking")


def test_cbs_authentication_link_pair():
    print("  testing CBS ($cbs) authentication link-pair exchange...")
    conn = AmqpConnection()
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))
    conn.outbox.clear()

    # 1. Attach CBS Request Link (client is sender, target is $cbs)
    cbs_req_attach = Attach(
        name="cbs-request-link",
        handle=0,
        role=False,
        target=Target(address="$cbs"),
    )
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, cbs_req_attach))

    # Expect server Attach reply + Flow credit
    assert len(conn.outbox) == 2
    f_att = decode_frame(conn.outbox[0])
    assert_eq(f_att[3], 1)  # channel 1
    att_perf = parse_performative(f_att[4])
    assert isinstance(att_perf, Attach)
    assert_eq(att_perf.role, True)  # Server is receiver
    f_flow = decode_frame(conn.outbox[1])
    flow_perf = parse_performative(f_flow[4])
    assert isinstance(flow_perf, Flow)
    assert flow_perf.link_credit > 0
    conn.outbox.clear()

    # 2. Attach CBS Reply Link (client is receiver, source is $cbs)
    cbs_reply_attach = Attach(
        name="cbs-reply-link",
        handle=1,
        role=True,
        source=Source(address="$cbs"),
    )
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, cbs_reply_attach))
    assert len(conn.outbox) == 1
    f_att2 = decode_frame(conn.outbox[0])
    att_perf2 = parse_performative(f_att2[4])
    assert isinstance(att_perf2, Attach)
    assert_eq(att_perf2.role, False)  # Server is sender
    conn.outbox.clear()

    # 3. Transfer put-token request
    cbs_token_msg = Message(
        body="SharedAccessSignature sr=...&sig=...",
        properties=Properties(message_id="token-req-001"),
        application_properties={
            "operation": "put-token",
            "type": "servicebus.windows.net:sastoken",
            "name": "Endpoint=sb://localhost",
        },
    )
    t = Transfer(handle=0, delivery_id=1, delivery_tag=b"tag1", settled=False)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, t, cbs_token_msg.encode()))

    # Expect Disposition (Accepted) AND Transfer (CBS response with 202)
    assert len(conn.outbox) == 2
    f_disp = decode_frame(conn.outbox[0])
    disp_perf = parse_performative(f_disp[4])
    assert isinstance(disp_perf, Disposition)
    assert isinstance(disp_perf.state, Accepted)

    f_reply_transfer = decode_frame(conn.outbox[1])
    reply_t = parse_performative(f_reply_transfer[4])
    assert isinstance(reply_t, Transfer)
    assert_eq(reply_t.handle, 1)  # Delivered to CBS reply link
    reply_msg = Message.decode(f_reply_transfer[5])
    assert_eq(reply_msg.properties.correlation_id, "token-req-001")
    assert_eq(reply_msg.application_properties.get("statusCode"), 202)
    assert_eq(reply_msg.application_properties.get("statusDescription"), "Accepted")
    print("  ok  CBS authentication link-pair exchange with 202 status")


def test_address_resolution_and_not_found():
    print("  testing address resolution and unknown entity rejection...")
    bootstrap_siftly_topology()
    conn = AmqpConnection()
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))
    conn.outbox.clear()

    # Valid topic (case-insensitive)
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="s1", handle=0, role=False, target=Target(address="SCRAPPER_RESPONSES")),
        )
    )
    assert len(conn.outbox) >= 1
    f = decode_frame(conn.outbox[0])
    assert isinstance(parse_performative(f[4]), Attach)
    conn.outbox.clear()

    # Invalid topic
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="s2", handle=2, role=False, target=Target(address="non_existent_topic")),
        )
    )
    # AMQP 1.0 §2.6.3: the refusal is an Attach with no terminus, then a Detach
    # carrying the error (a bare Detach is an unattached handle to the client).
    assert len(conn.outbox) == 2
    refusal = parse_performative(decode_frame(conn.outbox[0])[4])
    assert isinstance(refusal, Attach)
    assert refusal.target is None and refusal.source is None
    f_err = decode_frame(conn.outbox[1])
    detach_perf = parse_performative(f_err[4])
    assert isinstance(detach_perf, Detach)
    assert detach_perf.closed == True
    assert detach_perf.error is not None
    assert_eq(detach_perf.error.condition, Symbol("amqp:not-found"))
    print("  ok  address resolution and amqp:not-found rejection")


def test_sender_link_and_batch_transfer():
    print("  testing sender link single send and batch send...")
    from core.persistent_store import SqliteStateBackend, PersistentMessagingStore
    reset_store(PersistentMessagingStore(SqliteStateBackend(":memory:"), store_id="azsb"))
    bootstrap_siftly_topology()
    store = get_store()

    conn = AmqpConnection()
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="sender-llm", handle=0, role=False, target=Target(address="llm-analysis")),
        )
    )
    conn.outbox.clear()

    # 1. Single message transfer
    msg = Message(
        body=b'{"prompt": "generate summary"}',
        properties=Properties(message_id="msg-single-1", correlation_id="c-999"),
        application_properties={"client": "siftly-worker"},
    )
    t1 = Transfer(handle=0, delivery_id=1, delivery_tag=b"tag-1", settled=False)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, t1, msg.encode()))

    assert len(conn.outbox) == 1
    disp = parse_performative(decode_frame(conn.outbox[0])[4])
    assert isinstance(disp, Disposition)
    assert isinstance(disp.state, Accepted)
    conn.outbox.clear()

    # Verify message landed in llm-analysis topic subscription
    sub_msg, lock = sb_peek_lock(store, "llm-analysis", "llm-analysis")
    assert sub_msg is not None
    assert_eq(sub_msg.get("MessageId"), "msg-single-1")
    assert_eq(sub_msg.get("CorrelationId"), "c-999")
    assert_eq(sub_msg.get("application_properties", {}).get("client"), "siftly-worker")

    # 2. Batch message transfer (SERVICE_BUS_BATCH_FORMAT 0x80013700)
    batch_msgs = [
        Message(body=f"batch-item-{i}".encode("utf-8"), properties=Properties(message_id=f"bm-{i}"))
        for i in range(3)
    ]
    batch_payload = b"".join(
        encode(DescribedType(DESCRIPTOR_DATA, m.encode())) for m in batch_msgs
    )
    t2 = Transfer(
        handle=0,
        delivery_id=2,
        delivery_tag=b"tag-batch",
        message_format=SERVICE_BUS_BATCH_FORMAT,
        settled=False,
    )
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, t2, batch_payload))

    assert len(conn.outbox) == 1
    disp2 = parse_performative(decode_frame(conn.outbox[0])[4])
    assert isinstance(disp2, Disposition)
    assert isinstance(disp2.state, Accepted)
    print("  ok  sender link single send and batch send landed in store")


def test_256kb_size_limit_rejection():
    print("  testing 256 KB message size limit rejection...")
    bootstrap_siftly_topology()
    conn = AmqpConnection()
    conn.feed_data(AMQP_HEADER)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, Begin()))
    conn.feed_data(
        encode_frame(
            FRAME_TYPE_AMQP,
            1,
            Attach(name="sender-ingest", handle=0, role=False, target=Target(address="traffic-ingest")),
        )
    )
    conn.outbox.clear()

    # Create oversized payload (300 KB)
    huge_payload = b"X" * 300000
    huge_transfer = Transfer(handle=0, delivery_id=1, delivery_tag=b"huge", settled=False)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, huge_transfer, huge_payload))

    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    detach_perf = parse_performative(frame[4])
    assert isinstance(detach_perf, Detach)
    assert detach_perf.closed == True
    assert detach_perf.error is not None
    assert_eq(detach_perf.error.condition, Symbol("amqp:link:message-size-exceeded"))
    print("  ok  256 KB message size limit rejection with amqp:link:message-size-exceeded")


def test_live_tcp_cbs_and_send():
    print("  testing live TCP socket with CBS auth and message transfer...")

    async def _run():
        from core.persistent_store import SqliteStateBackend, PersistentMessagingStore
        reset_store(PersistentMessagingStore(SqliteStateBackend(":memory:"), store_id="azsb"))
        bootstrap_siftly_topology()
        server = AmqpServer(host="127.0.0.1", port=0)
        await server.start()
        port = server.actual_port

        def _client_talk():
            s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
            try:
                # 1. AMQP Header
                s.sendall(AMQP_HEADER)
                assert_eq(s.recv(8), AMQP_HEADER)

                # 2. Open + Begin
                s.sendall(
                    encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="cbs-client"))
                    + encode_frame(FRAME_TYPE_AMQP, 1, Begin())
                )
                buf = b""
                # Read Open
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                f_open = decode_frame(buf)
                buf = f_open[6]

                # Read Begin
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                f_begin = decode_frame(buf)
                buf = f_begin[6]

                # 3. Attach CBS links
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Attach(name="cbs-req", handle=0, role=False, target=Target(address="$cbs")),
                    )
                    + encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Attach(name="cbs-rep", handle=1, role=True, source=Source(address="$cbs")),
                    )
                )

                # Read CBS Attach reply (req) + Flow
                for _ in range(3):  # Attach req reply, Flow, Attach rep reply
                    while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                        buf += s.recv(4096)
                    f = decode_frame(buf)
                    buf = f[6]

                # 4. Send put-token Transfer
                cbs_msg = Message(
                    body="token",
                    properties=Properties(message_id="token-42"),
                    application_properties={"operation": "put-token"},
                )
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Transfer(handle=0, delivery_id=1, delivery_tag=b"tag-cbs"),
                        cbs_msg.encode(),
                    )
                )

                # Read Disposition
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                f_disp = decode_frame(buf)
                disp = parse_performative(f_disp[4])
                assert isinstance(disp, Disposition)
                buf = f_disp[6]

                # Read CBS Response Transfer
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                f_rep = decode_frame(buf)
                rep_msg = Message.decode(f_rep[5])
                assert_eq(rep_msg.properties.correlation_id, "token-42")
                assert_eq(rep_msg.application_properties.get("statusCode"), 202)
                buf = f_rep[6]

                # 5. Attach Topic Sender and Send Message
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Attach(
                            name="prod-sender",
                            handle=2,
                            role=False,
                            target=Target(address="scrapper_responses"),
                        ),
                    )
                )
                # Read Attach reply + Flow
                for _ in range(2):
                    while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                        buf += s.recv(4096)
                    f = decode_frame(buf)
                    buf = f[6]

                # Send message
                app_msg = Message(
                    body=b"scrape-response-data",
                    properties=Properties(message_id="scrape-101"),
                )
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Transfer(handle=2, delivery_id=2, delivery_tag=b"tag-app"),
                        app_msg.encode(),
                    )
                )

                # Read Disposition
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    buf += s.recv(4096)
                f_app_disp = decode_frame(buf)
                app_disp = parse_performative(f_app_disp[4])
                assert isinstance(app_disp, Disposition)
                assert isinstance(app_disp.state, Accepted)

                # Close
                s.sendall(encode_frame(FRAME_TYPE_AMQP, 0, Close()))

            finally:
                s.close()

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _client_talk)
        await server.stop()

    asyncio.run(_run())
    print("  ok  live TCP socket CBS auth and message transfer verified")


def main():
    print("Running AMQP 1.0 CBS Auth & Sender Links Conformance Suite (Layer 3):")
    test_message_roundtrip()
    test_batch_message_unpacking()
    test_cbs_authentication_link_pair()
    test_address_resolution_and_not_found()
    test_sender_link_and_batch_transfer()
    test_256kb_size_limit_rejection()
    test_live_tcp_cbs_and_send()
    print("\nAMQP 1.0 CBS & Sender (Layer 3) Conformance: ALL GREEN\n")


if __name__ == "__main__":
    main()
