"""AMQP 1.0 Connection and Session State Machine.

Handles SASL negotiation, AMQP 1.0 handshake, framing reassembly,
channel multiplexing, CBS authentication ($cbs), address resolution,
sender links (batch 0x80013700), receiver links (credit flow, credit drain),
mandatory delivery annotations, dispositions (complete, abandon, DLQ),
and $management renew-lock node (AutoLockRenewer).
"""

from __future__ import annotations

import enum
import os
import time
import uuid
from typing import Any, Callable, Sequence

from core.azure_servicebus_core import (
    ServiceBusError,
    sb_abandon,
    sb_complete,
    sb_dead_letter,
    sb_peek_lock,
    sb_renew_lock,
    sb_send,
)
from core.azure_servicebus_runtime import get_store

from .codec import (
    AMQP_HEADER,
    EMPTY_FRAME,
    FRAME_TYPE_AMQP,
    FRAME_TYPE_SASL,
    SASL_HEADER,
    Long,
    Symbol,
    Timestamp,
    Uint,
    Ulong,
    Ushort,
    decode_frame,
    encode_frame,
)
from .message import (
    SERVICE_BUS_BATCH_FORMAT,
    Header,
    Message,
    Properties,
)
from .performatives import (
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
    Released,
    SaslInit,
    SaslMechanisms,
    SaslOutcome,
    Source,
    Target,
    Transfer,
    parse_performative,
)

MAX_MESSAGE_SIZE = 262144  # 256 KB


class ConnectionState(enum.Enum):
    START = "START"
    SASL_NEGOTIATING = "SASL_NEGOTIATING"
    SASL_DONE = "SASL_DONE"
    HDR_EXCHANGED = "HDR_EXCHANGED"
    OPENED = "OPENED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class Link:
    """Represents a Sender or Receiver Link on an AMQP session."""

    def __init__(
        self,
        handle: int,
        name: str,
        role: bool,  # False = remote sender / local receiver, True = remote receiver / local sender
        address: str,
        source: Source | None = None,
        target: Target | None = None,
        topic_name: str | None = None,
        sub_name: str | None = None,
        is_dlq: bool = False,
    ):
        self.handle = handle
        self.name = name
        self.role = role
        self.address = address
        self.source = source
        self.target = target
        self.topic_name = topic_name
        self.sub_name = sub_name
        self.is_dlq = is_dlq
        self.delivery_count = 0
        self.link_credit = 0
        self.drain = False
        self.rx_transfer_buffers: dict[int, bytearray] = {}  # delivery_id -> bytes
        self.deliveries: dict[int, dict[str, Any]] = {}  # delivery_id -> dict


class Session:
    """Represents an active AMQP 1.0 session on a channel."""

    def __init__(self, channel: int, remote_channel: int):
        self.channel = channel
        self.remote_channel = remote_channel
        self.next_incoming_id = 1
        self.next_outgoing_id = 1
        self.incoming_window = 5000
        self.outgoing_window = 5000
        self.links: dict[int, Link] = {}  # remote handle -> Link
        self.cbs_reply_handle: int | None = None
        self.cbs_request_handle: int | None = None
        self.mgmt_reply_handle: int | None = None
        self.mgmt_request_handle: int | None = None
        self.mgmt_topic: str | None = None
        self.mgmt_sub: str | None = None


class AmqpConnection:
    """State machine for a single AMQP 1.0 connection."""

    def __init__(
        self,
        container_id: str = "vyomi-servicebus-emulator",
        max_frame_size: int = 65536,
        idle_time_out_ms: int = 60000,
        trace_enabled: bool | None = None,
        store: Any = None,
    ):
        self.container_id = container_id
        self.server_max_frame_size = max_frame_size
        self.server_idle_timeout_ms = idle_time_out_ms
        self.state = ConnectionState.START
        self.store = store

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
        elif isinstance(perf, Transfer):
            self._on_transfer(channel, perf, payload)
        elif isinstance(perf, Disposition):
            self._on_disposition(channel, perf)

    def _on_sasl_init(self, init: SaslInit) -> None:
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

    def _get_store(self) -> Any:
        if self.store is not None:
            return self.store
        return get_store()

    # --- Address Resolution ---

    def resolve_address(
        self_or_cls, addr: str, store: Any = None
    ) -> tuple[str, str | None, bool] | None:
        """Resolve an AMQP target/source address against the Service Bus store.

        Returns:
            (topic_name, sub_name, is_dlq) or None if not found.
        """
        if not addr:
            return None
        clean_addr = addr.strip().strip("/")
        if store is not None:
            pass
        elif isinstance(self_or_cls, AmqpConnection):
            store = self_or_cls._get_store()
        else:
            store = get_store()

        is_dlq = False
        if clean_addr.lower().endswith("/$deadletterqueue"):
            is_dlq = True
            clean_addr = clean_addr[: -len("/$deadletterqueue")].strip("/")

        # Check for <topic>/Subscriptions/<sub>
        if "/subscriptions/" in clean_addr.lower():
            idx = clean_addr.lower().find("/subscriptions/")
            t_part = clean_addr[:idx].strip("/")
            s_part = clean_addr[idx + len("/subscriptions/") :].strip("/")

            matched_topic = None
            for t in store.topics:
                if t.lower() == t_part.lower():
                    matched_topic = t
                    break
            if not matched_topic:
                return None

            matched_sub = None
            subs = store.topics[matched_topic].get("subscriptions", {})
            for s in subs:
                if s.lower() == s_part.lower():
                    matched_sub = s
                    break
            if not matched_sub:
                return None

            return (matched_topic, matched_sub, is_dlq)

        # Plain topic
        matched_topic = None
        for t in store.topics:
            if t.lower() == clean_addr.lower():
                matched_topic = t
                break

        if matched_topic:
            return (matched_topic, None, is_dlq)
        return None

    def _on_attach(self, channel: int, attach: Attach) -> None:
        session = self.sessions.get(channel)
        if not session:
            return

        handle = int(attach.handle)
        is_sender = not attach.role  # False = client is sender, True = client is receiver
        address = ""

        if is_sender:
            address = attach.target.address if attach.target and attach.target.address else ""
        else:
            address = attach.source.address if attach.source and attach.source.address else ""

        # 1. Claims-Based Security ($cbs) node
        if address == "$cbs":
            link = Link(handle=handle, name=attach.name, role=attach.role, address="$cbs")
            session.links[handle] = link
            if is_sender:
                session.cbs_request_handle = handle
            else:
                session.cbs_reply_handle = handle

            reply_attach = Attach(
                name=attach.name,
                handle=attach.handle,
                role=not attach.role,
                source=attach.source,
                target=attach.target,
                initial_delivery_count=0 if not attach.role else None,
            )
            self.send_frame(FRAME_TYPE_AMQP, channel, reply_attach)

            if is_sender:
                flow = Flow(handle=attach.handle, link_credit=1000, next_incoming_id=1, next_outgoing_id=1)
                self.send_frame(FRAME_TYPE_AMQP, channel, flow)
            return

        # 2. Management ($management) node
        if "$management" in address:
            link = Link(handle=handle, name=attach.name, role=attach.role, address=address)
            # Parse topic and sub from address e.g. <topic>/Subscriptions/<sub>/$management
            base_addr = address.replace("/$management", "").strip("/")
            resolution = self.resolve_address(base_addr)
            if resolution:
                link.topic_name, link.sub_name, link.is_dlq = resolution
                session.mgmt_topic = link.topic_name
                session.mgmt_sub = link.sub_name

            session.links[handle] = link
            if is_sender:
                session.mgmt_request_handle = handle
            else:
                session.mgmt_reply_handle = handle

            reply_attach = Attach(
                name=attach.name,
                handle=attach.handle,
                role=not attach.role,
                source=attach.source,
                target=attach.target,
                initial_delivery_count=0 if not attach.role else None,
            )
            self.send_frame(FRAME_TYPE_AMQP, channel, reply_attach)
            if is_sender:
                flow = Flow(handle=attach.handle, link_credit=1000, next_incoming_id=1, next_outgoing_id=1)
                self.send_frame(FRAME_TYPE_AMQP, channel, flow)
            return

        # 3. Entity Address Resolution
        topic_name = None
        sub_name = None
        is_dlq = False
        if address:
            resolution = self.resolve_address(address)
            if resolution is None:
                self._trace("ERR", f"Entity not found: {address!r}")
                err = Error(Symbol("amqp:not-found"), f"The messaging entity '{address}' could not be found.")
                reply_detach = Detach(handle=attach.handle, closed=True, error=err)
                self.send_frame(FRAME_TYPE_AMQP, channel, reply_detach)
                return
            topic_name, sub_name, is_dlq = resolution

        # Record link
        link = Link(
            handle=handle,
            name=attach.name,
            role=attach.role,
            address=address,
            source=attach.source,
            target=attach.target,
            topic_name=topic_name,
            sub_name=sub_name,
            is_dlq=is_dlq,
        )
        session.links[handle] = link

        reply_attach = Attach(
            name=attach.name,
            handle=attach.handle,
            role=not attach.role,
            source=attach.source,
            target=attach.target,
            initial_delivery_count=0 if not attach.role else None,
        )
        self.send_frame(FRAME_TYPE_AMQP, channel, reply_attach)

        if is_sender:
            flow = Flow(handle=attach.handle, link_credit=1000, next_incoming_id=1, next_outgoing_id=1)
            self.send_frame(FRAME_TYPE_AMQP, channel, flow)

    def _on_detach(self, channel: int, detach: Detach) -> None:
        session = self.sessions.get(channel)
        if session and int(detach.handle) in session.links:
            del session.links[int(detach.handle)]
        reply_detach = Detach(handle=detach.handle, closed=detach.closed)
        self.send_frame(FRAME_TYPE_AMQP, channel, reply_detach)

    def _on_flow(self, channel: int, flow: Flow) -> None:
        session = self.sessions.get(channel)
        if not session or flow.handle is None:
            return
        link = session.links.get(int(flow.handle))
        if link:
            link.link_credit = int(flow.link_credit) if flow.link_credit is not None else 0
            link.drain = bool(flow.drain)
            # If client is receiver (role=True), process message delivery immediately!
            if link.role:
                self._process_receiver_delivery(channel, link, is_drain=link.drain)

    def _process_receiver_delivery(self, channel: int, link: Link, is_drain: bool = False) -> None:
        session = self.sessions.get(channel)
        if not session or not link.topic_name:
            if is_drain:
                reply_flow = Flow(
                    handle=link.handle,
                    link_credit=0,
                    drain=True,
                    next_incoming_id=session.next_incoming_id if session else 1,
                    incoming_window=5000,
                    next_outgoing_id=session.next_outgoing_id if session else 1,
                    outgoing_window=5000,
                )
                self.send_frame(FRAME_TYPE_AMQP, channel, reply_flow)
            return

        store = self._get_store()
        sub_name = link.sub_name or link.topic_name

        while link.link_credit > 0:
            msg, lock_token = sb_peek_lock(store, link.topic_name, sub_name, is_dlq=link.is_dlq)
            if not msg or not lock_token:
                break

            link.link_credit -= 1
            deliv_id = session.next_outgoing_id
            session.next_outgoing_id += 1

            link.deliveries[deliv_id] = {
                "lock_token": lock_token,
                "seq": msg.get("SequenceNumber"),
                "topic": link.topic_name,
                "sub": sub_name,
                "is_dlq": link.is_dlq,
            }

            # Required Azure Service Bus annotations
            now_ms = int(store.now() * 1000)
            vis_ms = int(msg.get("visible_at", store.now() + 60.0) * 1000)
            annotations = {
                Symbol("x-opt-sequence-number"): Long(int(msg.get("SequenceNumber", 1))),
                Symbol("x-opt-enqueued-time"): Timestamp(now_ms),
                Symbol("x-opt-locked-until"): Timestamp(vis_ms),
                Symbol("x-opt-delivery-count"): Uint(int(msg.get("delivery_count", 1))),
            }
            if msg.get("DeadLetterReason"):
                annotations[Symbol("x-opt-dead-letter-reason")] = str(msg["DeadLetterReason"])
            if msg.get("DeadLetterErrorDescription"):
                annotations[Symbol("x-opt-dead-letter-description")] = str(msg["DeadLetterErrorDescription"])

            props = Properties(
                message_id=msg.get("MessageId"),
                correlation_id=msg.get("CorrelationId") or msg.get("correlation_id"),
                subject=msg.get("Subject") or msg.get("subject"),
                reply_to=msg.get("ReplyTo") or msg.get("reply_to"),
                content_type=msg.get("ContentType") or msg.get("content_type"),
            )

            body_val = msg.get("body", b"")
            body_bytes = body_val if isinstance(body_val, (bytes, bytearray)) else str(body_val).encode("utf-8")

            out_msg = Message(
                body=body_bytes,
                properties=props,
                application_properties=msg.get("application_properties", {}),
                message_annotations=annotations,
            )

            deliv_tag = lock_token.encode("ascii")
            transfer = Transfer(
                handle=link.handle,
                delivery_id=deliv_id,
                delivery_tag=deliv_tag,
                settled=False,
            )
            self.send_frame(FRAME_TYPE_AMQP, channel, transfer, out_msg.encode())

        if is_drain:
            link.link_credit = 0
            reply_flow = Flow(
                handle=link.handle,
                link_credit=0,
                drain=True,
                next_incoming_id=session.next_incoming_id,
                incoming_window=5000,
                next_outgoing_id=session.next_outgoing_id,
                outgoing_window=5000,
            )
            self.send_frame(FRAME_TYPE_AMQP, channel, reply_flow)

    def _on_transfer(self, channel: int, transfer: Transfer, payload: bytes) -> None:
        session = self.sessions.get(channel)
        if not session:
            return
        link = session.links.get(int(transfer.handle))
        if not link:
            return

        delivery_id = int(transfer.delivery_id) if transfer.delivery_id is not None else 0

        # Multi-frame reassembly
        if transfer.more:
            if delivery_id not in link.rx_transfer_buffers:
                link.rx_transfer_buffers[delivery_id] = bytearray()
            link.rx_transfer_buffers[delivery_id].extend(payload)
            return

        if delivery_id in link.rx_transfer_buffers:
            full_payload = bytes(link.rx_transfer_buffers.pop(delivery_id)) + payload
        else:
            full_payload = payload

        # Check max message size (256 KB)
        if len(full_payload) > MAX_MESSAGE_SIZE:
            err = Error(
                Symbol("amqp:link:message-size-exceeded"),
                f"The received message (size: {len(full_payload)} bytes) exceeds the 256 KB limit.",
            )
            detach = Detach(handle=transfer.handle, closed=True, error=err)
            self.send_frame(FRAME_TYPE_AMQP, channel, detach)
            return

        # 1. Claims-Based Security ($cbs) Handler
        if link.address == "$cbs":
            msg = Message.decode(full_payload)
            corr_id = msg.properties.message_id if msg.properties else None

            disp = Disposition(role=True, first=delivery_id, last=delivery_id, settled=True, state=Accepted())
            self.send_frame(FRAME_TYPE_AMQP, channel, disp)

            if session.cbs_reply_handle is not None:
                reply_props = Properties(correlation_id=corr_id)
                reply_msg = Message(
                    body=b"",
                    properties=reply_props,
                    application_properties={"statusCode": 202, "statusDescription": "Accepted"},
                )
                cbs_transfer = Transfer(
                    handle=session.cbs_reply_handle,
                    delivery_id=session.next_outgoing_id,
                    delivery_tag=b"cbs-reply",
                    settled=True,
                )
                session.next_outgoing_id += 1
                self.send_frame(FRAME_TYPE_AMQP, channel, cbs_transfer, reply_msg.encode())
            return

        # 2. Management ($management) renew-lock node
        if "$management" in link.address:
            msg = Message.decode(full_payload)
            op = msg.application_properties.get("operation") if msg.application_properties else None
            corr_id = msg.properties.message_id if msg.properties else None

            disp = Disposition(role=True, first=delivery_id, last=delivery_id, settled=True, state=Accepted())
            self.send_frame(FRAME_TYPE_AMQP, channel, disp)

            if op == "com.microsoft:renew-lock":
                body_map = msg.body if isinstance(msg.body, dict) else {}
                lock_tokens = body_map.get("lock-tokens", [])
                expirations: list[Timestamp] = []
                lock_lost = False

                topic = session.mgmt_topic or link.topic_name
                sub = session.mgmt_sub or link.sub_name or topic
                store = self._get_store()

                for tok in lock_tokens:
                    tok_str = str(tok)
                    if isinstance(tok, bytes) and len(tok) == 16:
                        tok_str = str(uuid.UUID(bytes=tok))
                    try:
                        new_vis = sb_renew_lock(store, topic, sub, lock=tok_str)
                        expirations.append(Timestamp(int(new_vis * 1000)))
                    except ServiceBusError as e:
                        if getattr(e, "status", None) == 410 or "LockLost" in getattr(e, "code", "") or "LockLost" in str(e):
                            lock_lost = True
                            break

                if session.mgmt_reply_handle is not None:
                    if lock_lost or not expirations:
                        reply_msg = Message(
                            body={},
                            properties=Properties(correlation_id=corr_id),
                            application_properties={
                                "statusCode": 410,
                                "statusDescription": "The lock supplied has expired.",
                                "errorCondition": Symbol("com.microsoft:message-lock-lost"),
                            },
                        )
                    else:
                        reply_msg = Message(
                            body={"expirations": expirations},
                            properties=Properties(correlation_id=corr_id),
                            application_properties={
                                "statusCode": 200,
                                "statusDescription": "OK",
                            },
                        )
                    mgmt_transfer = Transfer(
                        handle=session.mgmt_reply_handle,
                        delivery_id=session.next_outgoing_id,
                        delivery_tag=b"mgmt-reply",
                        settled=True,
                    )
                    session.next_outgoing_id += 1
                    self.send_frame(FRAME_TYPE_AMQP, channel, mgmt_transfer, reply_msg.encode())
            return

        # 3. Entity Sender Handler (Topic Send)
        resolution = self.resolve_address(link.address)
        if resolution:
            topic_name, _, _ = resolution
            if transfer.message_format == SERVICE_BUS_BATCH_FORMAT:
                msgs = Message.decode_batch(full_payload)
            else:
                msgs = [Message.decode(full_payload)]

            store = self._get_store()
            for m in msgs:
                body_bytes = (
                    m.body if isinstance(m.body, (bytes, bytearray)) else str(m.body).encode("utf-8")
                )
                sb_send(
                    store=store,
                    topic_name=topic_name,
                    body=body_bytes,
                    message_id=str(m.properties.message_id) if m.properties and m.properties.message_id else None,
                    correlation_id=str(m.properties.correlation_id) if m.properties and m.properties.correlation_id else None,
                    subject=m.properties.subject if m.properties else None,
                    reply_to=m.properties.reply_to if m.properties else None,
                    content_type=str(m.properties.content_type) if m.properties and m.properties.content_type else None,
                    application_properties=m.application_properties,
                )

            disp = Disposition(
                role=True,
                first=delivery_id,
                last=delivery_id,
                settled=True,
                state=Accepted(),
            )
            self.send_frame(FRAME_TYPE_AMQP, channel, disp)

    def _on_disposition(self, channel: int, disposition: Disposition) -> None:
        session = self.sessions.get(channel)
        if not session:
            return

        store = self._get_store()
        first = int(disposition.first)
        last = int(disposition.last) if disposition.last is not None else first

        for deliv_id in range(first, last + 1):
            info = None
            for link in session.links.values():
                if deliv_id in link.deliveries:
                    info = link.deliveries.pop(deliv_id)
                    break
            if not info:
                continue

            lock_token = info["lock_token"]
            topic = info["topic"]
            sub = info["sub"]
            seq = info["seq"]
            is_dlq = info["is_dlq"]
            state = disposition.state

            if isinstance(state, Accepted):
                try:
                    sb_complete(store, topic, sub, seq=seq, lock=lock_token, is_dlq=is_dlq)
                except ServiceBusError as e:
                    if getattr(e, "status", None) == 410 or "LockLost" in getattr(e, "code", "") or "LockLost" in str(e):
                        err = Error(Symbol("com.microsoft:message-lock-lost"), "The lock supplied has expired.")
                        self.send_frame(
                            FRAME_TYPE_AMQP,
                            channel,
                            Disposition(role=True, first=deliv_id, last=deliv_id, settled=True, state=Rejected(err)),
                        )
            elif isinstance(state, Modified):
                try:
                    sb_abandon(store, topic, sub, seq=seq, lock=lock_token, is_dlq=is_dlq)
                except ServiceBusError as e:
                    if getattr(e, "status", None) == 410 or "LockLost" in getattr(e, "code", "") or "LockLost" in str(e):
                        err = Error(Symbol("com.microsoft:message-lock-lost"), "The lock supplied has expired.")
                        self.send_frame(
                            FRAME_TYPE_AMQP,
                            channel,
                            Disposition(role=True, first=deliv_id, last=deliv_id, settled=True, state=Rejected(err)),
                        )
            elif isinstance(state, Rejected):
                reason = "ExplicitDeadLetter"
                desc = None
                if state.error:
                    reason = str(state.error.condition)
                    desc = state.error.description
                    if state.error.info:
                        reason = state.error.info.get("DeadLetterReason", reason)
                        desc = state.error.info.get("DeadLetterErrorDescription", desc)
                try:
                    sb_dead_letter(store, topic, sub, seq=seq, lock=lock_token, reason=reason, description=desc)
                except ServiceBusError:
                    pass

    def check_idle_keepalive(self, now: float | None = None) -> None:
        """Check if an idle heartbeat (empty frame) is due to be sent."""
        if self.state not in (ConnectionState.OPENED, ConnectionState.HDR_EXCHANGED):
            return

        current_time = now if now is not None else time.time()
        target_timeout_ms = self.remote_idle_timeout_ms or self.server_idle_timeout_ms
        heartbeat_interval_sec = (target_timeout_ms / 1000.0) / 2.0

        if (current_time - self.last_write_time) >= heartbeat_interval_sec:
            self.send_empty_frame()
