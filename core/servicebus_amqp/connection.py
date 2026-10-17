"""AMQP 1.0 Connection and Session State Machine.

Handles SASL negotiation, AMQP 1.0 handshake, framing reassembly,
channel multiplexing, and heartbeat keepalive management.
"""

from __future__ import annotations

import enum
import os
import time
from typing import Any, Callable

from .codec import (
    AMQP_HEADER,
    EMPTY_FRAME,
    FRAME_TYPE_AMQP,
    FRAME_TYPE_SASL,
    SASL_HEADER,
    Symbol,
    Uint,
    Ulong,
    Ushort,
    decode_frame,
    encode_frame,
)
from .performatives import (
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


class ConnectionState(enum.Enum):
    START = "START"
    SASL_NEGOTIATING = "SASL_NEGOTIATING"
    SASL_DONE = "SASL_DONE"
    HDR_EXCHANGED = "HDR_EXCHANGED"
    OPENED = "OPENED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class Session:
    """Represents an active AMQP 1.0 session on a channel."""

    def __init__(self, channel: int, remote_channel: int):
        self.channel = channel
        self.remote_channel = remote_channel
        self.next_incoming_id = 1
        self.next_outgoing_id = 1
        self.incoming_window = 5000
        self.outgoing_window = 5000
        self.links: dict[int, Any] = {}  # handle -> link state


class AmqpConnection:
    """State machine for a single AMQP 1.0 connection."""

    def __init__(
        self,
        container_id: str = "vyomi-servicebus-emulator",
        max_frame_size: int = 65536,
        idle_time_out_ms: int = 60000,
        trace_enabled: bool | None = None,
    ):
        self.container_id = container_id
        self.server_max_frame_size = max_frame_size
        self.server_idle_timeout_ms = idle_time_out_ms
        self.state = ConnectionState.START

        # Remote peer properties
        self.remote_container_id: str | None = None
        self.remote_max_frame_size: int = 65536
        self.remote_idle_timeout_ms: int | None = None
        self.negotiated_max_frame_size: int = max_frame_size

        # Sessions: channel (int) -> Session
        self.sessions: dict[int, Session] = {}

        # Timestamps
        self.last_read_time: float = time.time()
        self.last_write_time: float = time.time()

        # Buffer for incoming incomplete bytes
        self._rx_buffer = bytearray()

        # Trace mode
        if trace_enabled is None:
            self.trace_enabled = os.environ.get("VYOMI_AMQP_TRACE", "0") in ("1", "true", "True")
        else:
            self.trace_enabled = trace_enabled

        # Queue of outgoing raw bytes to be written to socket
        self.outbox: list[bytes] = []

    def _trace(self, direction: str, detail: str) -> None:
        if self.trace_enabled:
            ts = time.strftime("%H:%M:%S", time.localtime())
            print(f"[{ts} AMQP {direction}] {detail}")

    def send_bytes(self, b: bytes) -> None:
        self.outbox.append(b)
        self.last_write_time = time.time()

    def send_frame(
        self,
        frame_type: int,
        channel: int,
        performative: Any,
        payload: bytes = b"",
    ) -> None:
        dt = performative.to_described_type() if hasattr(performative, "to_described_type") else performative
        raw = encode_frame(frame_type, channel, dt, payload)
        self._trace("OUT", f"ch={channel} type=0x{frame_type:02x} {performative!r}")
        self.send_bytes(raw)

    def send_empty_frame(self) -> None:
        self._trace("OUT", "HEARTBEAT (empty frame)")
        self.send_bytes(EMPTY_FRAME)

    def feed_data(self, data: bytes) -> None:
        """Feed incoming bytes from the TCP socket into the connection state machine."""
        self._rx_buffer.extend(data)
        self.last_read_time = time.time()
        self._process_rx_buffer()

    def _process_rx_buffer(self) -> None:
        while self._rx_buffer:
            # 1. Check for protocol headers at START or SASL_DONE
            if self.state == ConnectionState.START:
                if len(self._rx_buffer) < 8:
                    return
                header = bytes(self._rx_buffer[:8])
                if header == SASL_HEADER:
                    self._rx_buffer = self._rx_buffer[8:]
                    self._trace("IN", "SASL header received")
                    self._on_sasl_header()
                    continue
                elif header == AMQP_HEADER:
                    self._rx_buffer = self._rx_buffer[8:]
                    self._trace("IN", "AMQP 1.0 header received (skipping SASL)")
                    self._on_amqp_header()
                    continue
                else:
                    self._trace("ERR", f"Unknown protocol header: {header!r}")
                    self.send_bytes(AMQP_HEADER)
                    self.state = ConnectionState.CLOSED
                    return

            if self.state == ConnectionState.SASL_DONE:
                if len(self._rx_buffer) < 8:
                    return
                header = bytes(self._rx_buffer[:8])
                if header == AMQP_HEADER:
                    self._rx_buffer = self._rx_buffer[8:]
                    self._trace("IN", "AMQP 1.0 header received after SASL")
                    self._on_amqp_header()
                    continue
                else:
                    self._trace("ERR", f"Expected AMQP header after SASL, got: {header!r}")
                    self.state = ConnectionState.CLOSED
                    return

            # 2. Decode standard AMQP or SASL frame
            frame = decode_frame(bytes(self._rx_buffer))
            if frame is None:
                # Need more bytes
                return

            size, doff, frame_type, channel, raw_performative, payload, remaining = frame
            # Advance rx buffer
            consumed = len(self._rx_buffer) - len(remaining)
            del self._rx_buffer[:consumed]

            if raw_performative is None:
                # Empty frame (heartbeat)
                self._trace("IN", f"ch={channel} HEARTBEAT (empty frame)")
                continue

            perf = parse_performative(raw_performative)
            self._trace("IN", f"ch={channel} type=0x{frame_type:02x} {perf!r}")
            self._handle_performative(frame_type, channel, perf, payload)

    def _on_sasl_header(self) -> None:
        self.send_bytes(SASL_HEADER)
        self.state = ConnectionState.SASL_NEGOTIATING
        # Send SASL mechanisms
        mechs = SaslMechanisms([Symbol("ANONYMOUS"), Symbol("PLAIN")])
        self.send_frame(FRAME_TYPE_SASL, 0, mechs)

    def _on_amqp_header(self) -> None:
        self.send_bytes(AMQP_HEADER)
        self.state = ConnectionState.HDR_EXCHANGED

    def _handle_performative(
        self,
        frame_type: int,
        channel: int,
        perf: Any,
        payload: bytes,
    ) -> None:
        # SASL handling
        if frame_type == FRAME_TYPE_SASL:
            if isinstance(perf, SaslInit):
                self._on_sasl_init(perf)
            return

        # AMQP handling
        if isinstance(perf, Open):
            self._on_open(perf)
        elif isinstance(perf, Begin):
            self._on_begin(channel, perf)
        elif isinstance(perf, End):
            self._on_end(channel, perf)
        elif isinstance(perf, Close):
            self._on_close(perf)
        elif isinstance(perf, Attach):
            self._on_attach(channel, perf)
        elif isinstance(perf, Detach):
            self._on_detach(channel, perf)
        elif isinstance(perf, Flow):
            self._on_flow(channel, perf)

    def _on_sasl_init(self, init: SaslInit) -> None:
        # In developer emulator mode, accept any mechanism/credential
        self._trace("SASL", f"Authenticated mechanism={init.mechanism!r}")
        outcome = SaslOutcome(code=SaslOutcome.OK)
        self.send_frame(FRAME_TYPE_SASL, 0, outcome)
        self.state = ConnectionState.SASL_DONE

    def _on_open(self, remote_open: Open) -> None:
        self.remote_container_id = remote_open.container_id
        if remote_open.max_frame_size:
            self.remote_max_frame_size = int(remote_open.max_frame_size)
            self.negotiated_max_frame_size = min(
                self.server_max_frame_size, self.remote_max_frame_size
            )
        if remote_open.idle_time_out:
            self.remote_idle_timeout_ms = int(remote_open.idle_time_out)

        # Server responds with its Open frame
        local_open = Open(
            container_id=self.container_id,
            max_frame_size=self.negotiated_max_frame_size,
            channel_max=65535,
            idle_time_out=self.server_idle_timeout_ms,
            offered_capabilities=[Symbol("com.microsoft:service-bus")],
        )
        self.send_frame(FRAME_TYPE_AMQP, 0, local_open)
        self.state = ConnectionState.OPENED

    def _on_begin(self, remote_channel: int, begin: Begin) -> None:
        # Use remote_channel as the local channel for 1:1 mapping
        session = Session(channel=remote_channel, remote_channel=remote_channel)
        self.sessions[remote_channel] = session

        reply_begin = Begin(
            remote_channel=remote_channel,
            next_outgoing_id=1,
            incoming_window=5000,
            outgoing_window=5000,
            handle_max=4294967295,
        )
        self.send_frame(FRAME_TYPE_AMQP, remote_channel, reply_begin)

    def _on_end(self, remote_channel: int, end: End) -> None:
        if remote_channel in self.sessions:
            del self.sessions[remote_channel]
        reply_end = End()
        self.send_frame(FRAME_TYPE_AMQP, remote_channel, reply_end)

    def _on_close(self, close: Close) -> None:
        self.state = ConnectionState.CLOSING
        reply_close = Close()
        self.send_frame(FRAME_TYPE_AMQP, 0, reply_close)
        self.state = ConnectionState.CLOSED

    def _on_attach(self, channel: int, attach: Attach) -> None:
        # Default Layer 2 echo (Layer 3 & 4 provide full link attachment logic)
        session = self.sessions.get(channel)
        if session:
            session.links[int(attach.handle)] = attach
        reply_attach = Attach(
            name=attach.name,
            handle=attach.handle,
            role=not attach.role,  # Opposite role
            source=attach.source,
            target=attach.target,
            initial_delivery_count=0 if not attach.role else None,
        )
        self.send_frame(FRAME_TYPE_AMQP, channel, reply_attach)

    def _on_detach(self, channel: int, detach: Detach) -> None:
        session = self.sessions.get(channel)
        if session and int(detach.handle) in session.links:
            del session.links[int(detach.handle)]
        reply_detach = Detach(handle=detach.handle, closed=detach.closed)
        self.send_frame(FRAME_TYPE_AMQP, channel, reply_detach)

    def _on_flow(self, channel: int, flow: Flow) -> None:
        # In Layer 2, echo or accept flow
        pass

    def check_idle_keepalive(self, now: float | None = None) -> None:
        """Check if an idle heartbeat (empty frame) is due to be sent."""
        if self.state not in (ConnectionState.OPENED, ConnectionState.HDR_EXCHANGED):
            return

        current_time = now if now is not None else time.time()
        # If remote peer requested an idle timeout, heartbeat at half that interval
        # Otherwise heartbeat at half server idle timeout
        target_timeout_ms = self.remote_idle_timeout_ms or self.server_idle_timeout_ms
        heartbeat_interval_sec = (target_timeout_ms / 1000.0) / 2.0

        if (current_time - self.last_write_time) >= heartbeat_interval_sec:
            self.send_empty_frame()
