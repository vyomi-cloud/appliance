"""Conformance tests for AMQP 1.0 Codec, Framing, Connection, and TCP Server.

Covers Layer 2 of the Service Bus implementation plan:
- B1/B2: AMQP 1.0 primitive & compound type codec
- B2: Protocol headers & SASL negotiation (ANONYMOUS, PLAIN)
- B2: Connection Open/Begin/Attach/Detach/End/Close state machine
- B2: Idle keepalive heartbeats (empty frame)
- B2: Asyncio TCP transport server (live network socket testing)
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

from core.servicebus_amqp import codec
from core.servicebus_amqp.codec import (
    AMQP_HEADER,
    EMPTY_FRAME,
    FRAME_TYPE_AMQP,
    FRAME_TYPE_SASL,
    SASL_HEADER,
    DescribedType,
    Symbol,
    Timestamp,
    Ubyte,
    Uint,
    Ulong,
    Ushort,
    decode,
    decode_frame,
    encode,
    encode_frame,
)
from core.servicebus_amqp.connection import AmqpConnection, ConnectionState
from core.servicebus_amqp.performatives import (
    Attach,
    Begin,
    Close,
    Detach,
    End,
    Error,
    Flow,
    Open,
    SaslInit,
    SaslMechanisms,
    SaslOutcome,
    parse_performative,
)
from core.servicebus_amqp.server import AmqpServer


def assert_eq(actual, expected, msg=""):
    assert actual == expected, f"{msg} | expected {expected!r}, got {actual!r}"


def test_codec_primitives():
    print("  testing codec primitive types...")
    # Null
    b = encode(None)
    assert_eq(b, b"\x40")
    val, offset = decode(b)
    assert_eq(val, None)
    assert_eq(offset, 1)

    # Booleans
    b_true = encode(True)
    assert_eq(b_true, b"\x41")
    val, _ = decode(b_true)
    assert_eq(val, True)

    b_false = encode(False)
    assert_eq(b_false, b"\x42")
    val, _ = decode(b_false)
    assert_eq(val, False)

    # 1-octet Boolean
    val, _ = decode(b"\x56\x01")
    assert_eq(val, True)
    val, _ = decode(b"\x56\x00")
    assert_eq(val, False)

    # Integers (small and full)
    val, _ = decode(encode(0))
    assert_eq(val, 0)

    val, _ = decode(encode(42))
    assert_eq(val, 42)

    val, _ = decode(encode(-42))
    assert_eq(val, -42)

    val, _ = decode(encode(100000))
    assert_eq(val, 100000)

    val, _ = decode(encode(10000000000))
    assert_eq(val, 10000000000)

    # Explicit integer types
    val, _ = decode(encode(Ubyte(255)))
    assert_eq(val, 255)

    val, _ = decode(encode(Ushort(65535)))
    assert_eq(val, 65535)

    val, _ = decode(encode(Uint(4294967295)))
    assert_eq(val, 4294967295)

    val, _ = decode(encode(Ulong(18446744073709551615)))
    assert_eq(val, 18446744073709551615)

    # Strings & Symbols
    val, _ = decode(encode("hello world"))
    assert_eq(val, "hello world")

    sym = Symbol("amqp:link:message-size-exceeded")
    enc_sym = encode(sym)
    val, _ = decode(enc_sym)
    assert_eq(val, sym)
    assert isinstance(val, Symbol)

    # Binaries
    raw = b"\x01\x02\x03\x04\x05"
    val, _ = decode(encode(raw))
    assert_eq(val, raw)

    # UUID
    test_uuid = uuid.uuid4()
    val, _ = decode(encode(test_uuid))
    assert_eq(val, test_uuid)

    # Timestamp
    ts = Timestamp(1729180000000)
    val, _ = decode(encode(ts))
    assert_eq(val, ts)

    print("  ok  codec primitives")


def test_codec_compounds():
    print("  testing codec compound types (list, map, array, described)...")
    # Empty list
    val, _ = decode(encode([]))
    assert_eq(val, [])

    # List
    lst = [1, "two", Symbol("three"), True, None]
    val, _ = decode(encode(lst))
    assert_eq(val, lst)

    # Map
    mapping = {Symbol("host"): "localhost", "port": 5672, Symbol("tls"): False}
    val, _ = decode(encode(mapping))
    assert_eq(val, mapping)

    # Described Type
    dt = DescribedType(Ulong(16), ["my-container", "localhost", 65536])
    b = encode(dt)
    val, _ = decode(b)
    assert isinstance(val, DescribedType)
    assert_eq(val.descriptor, 16)
    assert_eq(val.value, ["my-container", "localhost", 65536])

    print("  ok  codec compounds")


def test_framing():
    print("  testing frame encoding, decoding and partial buffers...")
    # Empty heartbeat frame
    frame = decode_frame(EMPTY_FRAME)
    assert frame is not None
    size, doff, frame_type, channel, perf, payload, rem = frame
    assert_eq(size, 8)
    assert_eq(doff, 2)
    assert_eq(frame_type, FRAME_TYPE_AMQP)
    assert_eq(channel, 0)
    assert_eq(perf, None)
    assert_eq(payload, b"")
    assert_eq(rem, b"")

    # Regular AMQP frame
    open_perf = Open(container_id="test-box", max_frame_size=65536)
    raw = encode_frame(FRAME_TYPE_AMQP, channel=0, performative=open_perf)
    assert len(raw) >= 8

    # Partial decode (simulating network chunking)
    assert decode_frame(raw[:5]) is None
    assert decode_frame(raw[:15]) is None

    # Full decode
    frame = decode_frame(raw)
    assert frame is not None
    size, doff, frame_type, channel, perf, payload, rem = frame
    assert_eq(frame_type, FRAME_TYPE_AMQP)
    assert_eq(channel, 0)
    parsed = parse_performative(perf)
    assert isinstance(parsed, Open)
    assert_eq(parsed.container_id, "test-box")
    assert_eq(parsed.max_frame_size, 65536)

    print("  ok  framing & partial buffers")


def test_performatives_roundtrip():
    print("  testing performative models round-trip...")
    # Open
    op = Open(container_id="c1", hostname="sb.local", idle_time_out=30000)
    dt = op.to_described_type()
    op2 = Open.from_described_type(dt)
    assert_eq(op2.container_id, "c1")
    assert_eq(op2.hostname, "sb.local")
    assert_eq(op2.idle_time_out, 30000)

    # Begin
    bg = Begin(remote_channel=3, next_outgoing_id=10, incoming_window=2048)
    bg2 = Begin.from_described_type(bg.to_described_type())
    assert_eq(bg2.remote_channel, 3)
    assert_eq(bg2.next_outgoing_id, 10)
    assert_eq(bg2.incoming_window, 2048)

    # Attach
    att = Attach(name="link1", handle=0, role=False, initial_delivery_count=0)
    att2 = Attach.from_described_type(att.to_described_type())
    assert_eq(att2.name, "link1")
    assert_eq(att2.handle, 0)
    assert_eq(att2.role, False)

    # Flow
    fl = Flow(handle=0, link_credit=100, drain=True)
    fl2 = Flow.from_described_type(fl.to_described_type())
    assert_eq(fl2.handle, 0)
    assert_eq(fl2.link_credit, 100)
    assert_eq(fl2.drain, True)

    # End & Close with Error
    err = Error(condition=Symbol("amqp:connection:forced"), description="maintenance")
    cl = Close(error=err)
    cl2 = Close.from_described_type(cl.to_described_type())
    assert cl2.error is not None
    assert_eq(cl2.error.condition, Symbol("amqp:connection:forced"))
    assert_eq(cl2.error.description, "maintenance")

    # SASL performatives
    mechs = SaslMechanisms(["ANONYMOUS", "PLAIN"])
    mechs2 = SaslMechanisms.from_described_type(mechs.to_described_type())
    assert_eq(mechs2.mechanisms, [Symbol("ANONYMOUS"), Symbol("PLAIN")])

    init = SaslInit(mechanism="PLAIN", initial_response=b"\x00user\x00pass")
    init2 = SaslInit.from_described_type(init.to_described_type())
    assert_eq(init2.mechanism, Symbol("PLAIN"))
    assert_eq(init2.initial_response, b"\x00user\x00pass")

    outcome = SaslOutcome(code=0)
    outcome2 = SaslOutcome.from_described_type(outcome.to_described_type())
    assert_eq(outcome2.code, 0)

    print("  ok  performative models round-trip")


def test_connection_state_machine():
    print("  testing connection state machine in-memory...")
    conn = AmqpConnection(container_id="vyomi-mock-server", max_frame_size=65536)
    assert_eq(conn.state, ConnectionState.START)

    # 1. Feed SASL Header
    conn.feed_data(SASL_HEADER)
    assert_eq(conn.state, ConnectionState.SASL_NEGOTIATING)
    assert len(conn.outbox) >= 2
    assert_eq(conn.outbox[0], SASL_HEADER)
    # Check SaslMechanisms frame
    frame = decode_frame(conn.outbox[1])
    assert frame is not None
    perf = parse_performative(frame[4])
    assert isinstance(perf, SaslMechanisms)
    assert Symbol("ANONYMOUS") in perf.mechanisms
    assert Symbol("PLAIN") in perf.mechanisms
    conn.outbox.clear()

    # 2. Feed SaslInit
    sasl_init = SaslInit(mechanism="ANONYMOUS")
    conn.feed_data(encode_frame(FRAME_TYPE_SASL, 0, sasl_init))
    assert_eq(conn.state, ConnectionState.SASL_DONE)
    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    perf = parse_performative(frame[4])
    assert isinstance(perf, SaslOutcome)
    assert_eq(perf.code, SaslOutcome.OK)
    conn.outbox.clear()

    # 3. Feed AMQP 1.0 Header
    conn.feed_data(AMQP_HEADER)
    assert_eq(conn.state, ConnectionState.HDR_EXCHANGED)
    assert len(conn.outbox) == 1
    assert_eq(conn.outbox[0], AMQP_HEADER)
    conn.outbox.clear()

    # 4. Feed Open
    client_open = Open(container_id="client-42", max_frame_size=32768, idle_time_out=60000)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, client_open))
    assert_eq(conn.state, ConnectionState.OPENED)
    assert_eq(conn.remote_container_id, "client-42")
    assert_eq(conn.negotiated_max_frame_size, 32768)
    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    perf = parse_performative(frame[4])
    assert isinstance(perf, Open)
    assert_eq(perf.container_id, "vyomi-mock-server")
    conn.outbox.clear()

    # 5. Feed Begin (Channel 1)
    client_begin = Begin(next_outgoing_id=1, incoming_window=5000, outgoing_window=5000)
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, client_begin))
    assert 1 in conn.sessions
    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    assert_eq(frame[3], 1)  # channel 1
    perf = parse_performative(frame[4])
    assert isinstance(perf, Begin)
    assert_eq(perf.remote_channel, 1)
    conn.outbox.clear()

    # 6. Idle Heartbeat keepalive
    # Advance time to trigger keepalive
    conn.check_idle_keepalive(now=time.time() + 35.0)
    assert len(conn.outbox) == 1
    assert_eq(conn.outbox[0], EMPTY_FRAME)
    conn.outbox.clear()

    # 7. Feed End (Channel 1)
    client_end = End()
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 1, client_end))
    assert 1 not in conn.sessions
    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    assert_eq(frame[3], 1)
    perf = parse_performative(frame[4])
    assert isinstance(perf, End)
    conn.outbox.clear()

    # 8. Feed Close
    client_close = Close()
    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, client_close))
    assert_eq(conn.state, ConnectionState.CLOSED)
    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    perf = parse_performative(frame[4])
    assert isinstance(perf, Close)
    conn.outbox.clear()

    print("  ok  connection state machine in-memory")


def test_skip_sasl_direct_connect():
    print("  testing direct AMQP header (skipping SASL)...")
    conn = AmqpConnection()
    conn.feed_data(AMQP_HEADER)
    assert_eq(conn.state, ConnectionState.HDR_EXCHANGED)
    assert_eq(conn.outbox[0], AMQP_HEADER)
    conn.outbox.clear()

    conn.feed_data(encode_frame(FRAME_TYPE_AMQP, 0, Open(container_id="c1")))
    assert_eq(conn.state, ConnectionState.OPENED)
    assert len(conn.outbox) == 1
    frame = decode_frame(conn.outbox[0])
    assert isinstance(parse_performative(frame[4]), Open)
    print("  ok  direct AMQP connect without SASL")


def test_live_tcp_server():
    print("  testing live TCP server with raw socket handshake...")

    async def _run():
        server = AmqpServer(host="127.0.0.1", port=0)
        await server.start()
        port = server.actual_port
        assert port > 0

        # Run synchronous socket operations in thread
        def _client_talk():
            s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
            try:
                # 1. Send SASL header
                s.sendall(SASL_HEADER)
                resp = s.recv(8)
                assert_eq(resp, SASL_HEADER)

                # Receive SaslMechanisms frame
                buf = b""
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading SASL mechanisms"
                    buf += chunk
                frame = decode_frame(buf)
                assert frame is not None
                perf = parse_performative(frame[4])
                assert isinstance(perf, SaslMechanisms)
                buf = frame[6]  # remaining

                # 2. Send SaslInit PLAIN
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_SASL,
                        0,
                        SaslInit("PLAIN", initial_response=b"\x00root\x00key"),
                    )
                )

                # Receive SaslOutcome
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading SASL outcome"
                    buf += chunk
                frame = decode_frame(buf)
                assert frame is not None
                perf = parse_performative(frame[4])
                assert isinstance(perf, SaslOutcome)
                assert_eq(perf.code, 0)
                buf = frame[6]

                # 3. Send AMQP 1.0 Header
                s.sendall(AMQP_HEADER)
                while len(buf) < 8:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading AMQP header"
                    buf += chunk
                assert_eq(buf[:8], AMQP_HEADER)
                buf = buf[8:]

                # 4. Send Open + Begin pipelined!
                req = encode_frame(
                    FRAME_TYPE_AMQP, 0, Open(container_id="test-runner", idle_time_out=60000)
                ) + encode_frame(
                    FRAME_TYPE_AMQP,
                    1,
                    Begin(next_outgoing_id=1, incoming_window=5000, outgoing_window=5000),
                )
                s.sendall(req)

                # Receive Open
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading Open"
                    buf += chunk
                frame = decode_frame(buf)
                assert frame is not None
                assert isinstance(parse_performative(frame[4]), Open)
                buf = frame[6]

                # Receive Begin
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading Begin"
                    buf += chunk
                frame = decode_frame(buf)
                assert frame is not None
                assert_eq(frame[3], 1)  # channel 1
                assert isinstance(parse_performative(frame[4]), Begin)
                buf = frame[6]

                # 5. Send Attach
                s.sendall(
                    encode_frame(
                        FRAME_TYPE_AMQP,
                        1,
                        Attach(name="test-sender", handle=0, role=False),
                    )
                )
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading Attach"
                    buf += chunk
                frame = decode_frame(buf)
                assert frame is not None
                att = parse_performative(frame[4])
                assert isinstance(att, Attach)
                assert_eq(att.name, "test-sender")
                assert_eq(att.role, True)  # server responded with opposite role
                buf = frame[6]

                # 6. Send End + Close
                s.sendall(
                    encode_frame(FRAME_TYPE_AMQP, 1, End())
                    + encode_frame(FRAME_TYPE_AMQP, 0, Close())
                )

                # Receive frames until End
                perf = None
                while not isinstance(perf, End):
                    while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                        chunk = s.recv(4096)
                        assert chunk, "Unexpected EOF reading End"
                        buf += chunk
                    frame = decode_frame(buf)
                    assert frame is not None
                    perf = parse_performative(frame[4])
                    buf = frame[6]

                # Receive Close
                while len(buf) < 8 or len(buf) < struct.unpack_from(">I", buf, 0)[0]:
                    chunk = s.recv(4096)
                    assert chunk, "Unexpected EOF reading Close"
                    buf += chunk
                frame = decode_frame(buf)
                assert frame is not None
                assert isinstance(parse_performative(frame[4]), Close)

            finally:
                s.close()

        loop = asyncio.get_running_loop()
        # Test 5 concurrent clients connecting and negotiating simultaneously
        await asyncio.gather(
            loop.run_in_executor(None, _client_talk),
            loop.run_in_executor(None, _client_talk),
            loop.run_in_executor(None, _client_talk),
            loop.run_in_executor(None, _client_talk),
            loop.run_in_executor(None, _client_talk),
        )

        await server.stop()

    asyncio.run(_run())
    print("  ok  live TCP server with concurrent clients, pipelining, and full handshake")


def test_tracing_output():
    print("  testing AMQP frame tracing (VYOMI_AMQP_TRACE)...")
    import io

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        conn = AmqpConnection(trace_enabled=True)
        conn.feed_data(SASL_HEADER)
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    assert "AMQP IN" in output
    assert "SASL header received" in output
    assert "AMQP OUT" in output
    print("  ok  frame tracing logs IN and OUT events cleanly")


def main():
    print("Running AMQP 1.0 Transport & Codec Conformance Suite (Layer 2):")
    test_codec_primitives()
    test_codec_compounds()
    test_framing()
    test_performatives_roundtrip()
    test_connection_state_machine()
    test_skip_sasl_direct_connect()
    test_tracing_output()
    test_live_tcp_server()
    print("\nAMQP 1.0 Transport (Layer 2) Conformance: ALL GREEN\n")


if __name__ == "__main__":
    main()
