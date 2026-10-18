"""AMQP 1.0 Performatives and Composite Types.

Complies with OASIS AMQP 1.0 Part 2 (Transport) and Part 5 (Security).
Provides bidirectional mapping to/from DescribedType.
"""

from __future__ import annotations

from typing import Any, Sequence

from .codec import DescribedType, Symbol, Ubyte, Uint, Ulong, Ushort


def _truncate_trailing_nulls(lst: list[Any]) -> list[Any]:
    """Trim trailing None values from an AMQP described list."""
    while lst and lst[-1] is None:
        lst.pop()
    return lst


class Error:
    """AMQP 1.0 Error (descriptor 0x1d)."""

    DESCRIPTOR = Ulong(0x1D)

    def __init__(
        self,
        condition: str | Symbol,
        description: str | None = None,
        info: dict[Any, Any] | None = None,
    ):
        self.condition = Symbol(condition) if isinstance(condition, str) else condition
        self.description = description
        self.info = info or {}

    def to_described_type(self) -> DescribedType:
        fields = [self.condition, self.description, self.info if self.info else None]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Error:
        fields = dt.value if isinstance(dt.value, list) else []
        condition = fields[0] if len(fields) > 0 else Symbol("amqp:internal-error")
        description = fields[1] if len(fields) > 1 else None
        info = fields[2] if len(fields) > 2 else {}
        return cls(condition, description, info)

    def __repr__(self) -> str:
        return f"Error(condition={self.condition!r}, description={self.description!r})"


# --- Connection Performatives ---


class Open:
    """AMQP 1.0 Open performative (descriptor 0x10)."""

    DESCRIPTOR = Ulong(0x10)

    def __init__(
        self,
        container_id: str,
        hostname: str | None = None,
        max_frame_size: int | None = 65536,
        channel_max: int | None = 65535,
        idle_time_out: int | None = None,
        incoming_locales: list[Symbol] | None = None,
        outgoing_locales: list[Symbol] | None = None,
        offered_capabilities: list[Symbol] | None = None,
        desired_capabilities: list[Symbol] | None = None,
        properties: dict[Any, Any] | None = None,
    ):
        self.container_id = container_id
        self.hostname = hostname
        self.max_frame_size = Uint(max_frame_size) if max_frame_size is not None else None
        self.channel_max = Ushort(channel_max) if channel_max is not None else None
        self.idle_time_out = Uint(idle_time_out) if idle_time_out is not None else None
        self.incoming_locales = incoming_locales
        self.outgoing_locales = outgoing_locales
        self.offered_capabilities = offered_capabilities
        self.desired_capabilities = desired_capabilities
        self.properties = properties or {}

    def to_described_type(self) -> DescribedType:
        fields = [
            self.container_id,
            self.hostname,
            self.max_frame_size,
            self.channel_max,
            self.idle_time_out,
            self.outgoing_locales,
            self.incoming_locales,
            self.offered_capabilities,
            self.desired_capabilities,
            self.properties if self.properties else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Open:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            container_id=f[0] if len(f) > 0 and f[0] is not None else "",
            hostname=f[1] if len(f) > 1 else None,
            max_frame_size=f[2] if len(f) > 2 else 65536,
            channel_max=f[3] if len(f) > 3 else 65535,
            idle_time_out=f[4] if len(f) > 4 else None,
            outgoing_locales=f[5] if len(f) > 5 else None,
            incoming_locales=f[6] if len(f) > 6 else None,
            offered_capabilities=f[7] if len(f) > 7 else None,
            desired_capabilities=f[8] if len(f) > 8 else None,
            properties=f[9] if len(f) > 9 else {},
        )

    def __repr__(self) -> str:
        return f"Open(container_id={self.container_id!r}, max_frame_size={self.max_frame_size}, idle_time_out={self.idle_time_out})"


class Close:
    """AMQP 1.0 Close performative (descriptor 0x18)."""

    DESCRIPTOR = Ulong(0x18)

    def __init__(self, error: Error | None = None):
        self.error = error

    def to_described_type(self) -> DescribedType:
        err_dt = self.error.to_described_type() if self.error else None
        fields = [err_dt]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Close:
        f = dt.value if isinstance(dt.value, list) else []
        err = Error.from_described_type(f[0]) if len(f) > 0 and isinstance(f[0], DescribedType) else None
        return cls(error=err)

    def __repr__(self) -> str:
        return f"Close(error={self.error!r})"


# --- Session Performatives ---


class Begin:
    """AMQP 1.0 Begin performative (descriptor 0x11)."""

    DESCRIPTOR = Ulong(0x11)

    def __init__(
        self,
        remote_channel: int | None = None,
        next_outgoing_id: int = 1,
        incoming_window: int = 5000,
        outgoing_window: int = 5000,
        handle_max: int | None = 4294967295,
        offered_capabilities: list[Symbol] | None = None,
        desired_capabilities: list[Symbol] | None = None,
        properties: dict[Any, Any] | None = None,
    ):
        self.remote_channel = Ushort(remote_channel) if remote_channel is not None else None
        self.next_outgoing_id = Uint(next_outgoing_id)
        self.incoming_window = Uint(incoming_window)
        self.outgoing_window = Uint(outgoing_window)
        self.handle_max = Uint(handle_max) if handle_max is not None else None
        self.offered_capabilities = offered_capabilities
        self.desired_capabilities = desired_capabilities
        self.properties = properties or {}

    def to_described_type(self) -> DescribedType:
        fields = [
            self.remote_channel,
            self.next_outgoing_id,
            self.incoming_window,
            self.outgoing_window,
            self.handle_max,
            self.offered_capabilities,
            self.desired_capabilities,
            self.properties if self.properties else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Begin:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            remote_channel=f[0] if len(f) > 0 else None,
            next_outgoing_id=f[1] if len(f) > 1 and f[1] is not None else 1,
            incoming_window=f[2] if len(f) > 2 and f[2] is not None else 5000,
            outgoing_window=f[3] if len(f) > 3 and f[3] is not None else 5000,
            handle_max=f[4] if len(f) > 4 else 4294967295,
            offered_capabilities=f[5] if len(f) > 5 else None,
            desired_capabilities=f[6] if len(f) > 6 else None,
            properties=f[7] if len(f) > 7 else {},
        )

    def __repr__(self) -> str:
        return f"Begin(remote_channel={self.remote_channel}, next_outgoing_id={self.next_outgoing_id})"


class End:
    """AMQP 1.0 End performative (descriptor 0x17)."""

    DESCRIPTOR = Ulong(0x17)

    def __init__(self, error: Error | None = None):
        self.error = error

    def to_described_type(self) -> DescribedType:
        err_dt = self.error.to_described_type() if self.error else None
        fields = [err_dt]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> End:
        f = dt.value if isinstance(dt.value, list) else []
        err = Error.from_described_type(f[0]) if len(f) > 0 and isinstance(f[0], DescribedType) else None
        return cls(error=err)

    def __repr__(self) -> str:
        return f"End(error={self.error!r})"


# --- Link Performatives ---


class Source:
    """AMQP 1.0 Source terminus (descriptor 0x28)."""

    DESCRIPTOR = Ulong(0x28)

    def __init__(
        self,
        address: str | None = None,
        durable: int = 0,
        expiry_policy: Symbol | None = None,
        timeout: int = 0,
        dynamic: bool = False,
        dynamic_node_properties: dict[Any, Any] | None = None,
        distribution_mode: Symbol | None = None,
        filter_set: dict[Any, Any] | None = None,
        default_outcome: Any = None,
        outcomes: list[Symbol] | None = None,
        capabilities: list[Symbol] | None = None,
    ):
        self.address = address
        self.durable = Uint(durable)
        self.expiry_policy = expiry_policy or Symbol("session-end")
        self.timeout = Uint(timeout)
        self.dynamic = dynamic
        self.dynamic_node_properties = dynamic_node_properties
        self.distribution_mode = distribution_mode
        self.filter_set = filter_set
        self.default_outcome = default_outcome
        self.outcomes = outcomes
        self.capabilities = capabilities

    def to_described_type(self) -> DescribedType:
        fields = [
            self.address,
            self.durable,
            self.expiry_policy,
            self.timeout,
            self.dynamic,
            self.dynamic_node_properties,
            self.distribution_mode,
            self.filter_set,
            self.default_outcome,
            self.outcomes,
            self.capabilities,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Source:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            address=f[0] if len(f) > 0 else None,
            durable=f[1] if len(f) > 1 and f[1] is not None else 0,
            expiry_policy=f[2] if len(f) > 2 else None,
            timeout=f[3] if len(f) > 3 and f[3] is not None else 0,
            dynamic=bool(f[4]) if len(f) > 4 and f[4] is not None else False,
            dynamic_node_properties=f[5] if len(f) > 5 else None,
            distribution_mode=f[6] if len(f) > 6 else None,
            filter_set=f[7] if len(f) > 7 else None,
            default_outcome=f[8] if len(f) > 8 else None,
            outcomes=f[9] if len(f) > 9 else None,
            capabilities=f[10] if len(f) > 10 else None,
        )

    def __repr__(self) -> str:
        return f"Source(address={self.address!r})"


class Target:
    """AMQP 1.0 Target terminus (descriptor 0x29)."""

    DESCRIPTOR = Ulong(0x29)

    def __init__(
        self,
        address: str | None = None,
        durable: int = 0,
        expiry_policy: Symbol | None = None,
        timeout: int = 0,
        dynamic: bool = False,
        dynamic_node_properties: dict[Any, Any] | None = None,
        capabilities: list[Symbol] | None = None,
    ):
        self.address = address
        self.durable = Uint(durable)
        self.expiry_policy = expiry_policy or Symbol("session-end")
        self.timeout = Uint(timeout)
        self.dynamic = dynamic
        self.dynamic_node_properties = dynamic_node_properties
        self.capabilities = capabilities

    def to_described_type(self) -> DescribedType:
        fields = [
            self.address,
            self.durable,
            self.expiry_policy,
            self.timeout,
            self.dynamic,
            self.dynamic_node_properties,
            self.capabilities,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Target:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            address=f[0] if len(f) > 0 else None,
            durable=f[1] if len(f) > 1 and f[1] is not None else 0,
            expiry_policy=f[2] if len(f) > 2 else None,
            timeout=f[3] if len(f) > 3 and f[3] is not None else 0,
            dynamic=bool(f[4]) if len(f) > 4 and f[4] is not None else False,
            dynamic_node_properties=f[5] if len(f) > 5 else None,
            capabilities=f[6] if len(f) > 6 else None,
        )

    def __repr__(self) -> str:
        return f"Target(address={self.address!r})"


class Attach:
    """AMQP 1.0 Attach performative (descriptor 0x12)."""

    DESCRIPTOR = Ulong(0x12)

    def __init__(
        self,
        name: str,
        handle: int,
        role: bool,  # False = sender, True = receiver
        snd_settle_mode: int | None = 2,
        rcv_settle_mode: int | None = 0,
        source: Source | None = None,
        target: Target | None = None,
        unsettled: dict[Any, Any] | None = None,
        incomplete_unsettled: bool | None = None,
        initial_delivery_count: int | None = 0,
        max_message_size: int | None = 262144,  # 256 KB
        offered_capabilities: list[Symbol] | None = None,
        desired_capabilities: list[Symbol] | None = None,
        properties: dict[Any, Any] | None = None,
    ):
        self.name = name
        self.handle = Uint(handle)
        self.role = role
        self.snd_settle_mode = Ubyte(snd_settle_mode) if snd_settle_mode is not None else None
        self.rcv_settle_mode = Ubyte(rcv_settle_mode) if rcv_settle_mode is not None else None
        self.source = source
        self.target = target
        self.unsettled = unsettled
        self.incomplete_unsettled = incomplete_unsettled
        self.initial_delivery_count = (
            Uint(initial_delivery_count) if initial_delivery_count is not None else None
        )
        self.max_message_size = (
            Ulong(max_message_size) if max_message_size is not None else None
        )
        self.offered_capabilities = offered_capabilities
        self.desired_capabilities = desired_capabilities
        self.properties = properties or {}

    def to_described_type(self) -> DescribedType:
        src_dt = self.source.to_described_type() if self.source else None
        tgt_dt = self.target.to_described_type() if self.target else None
        fields = [
            self.name,
            self.handle,
            self.role,
            self.snd_settle_mode,
            self.rcv_settle_mode,
            src_dt,
            tgt_dt,
            self.unsettled,
            self.incomplete_unsettled,
            self.initial_delivery_count,
            self.max_message_size,
            self.offered_capabilities,
            self.desired_capabilities,
            self.properties if self.properties else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Attach:
        f = dt.value if isinstance(dt.value, list) else []
        src = Source.from_described_type(f[5]) if len(f) > 5 and isinstance(f[5], DescribedType) else None
        tgt = Target.from_described_type(f[6]) if len(f) > 6 and isinstance(f[6], DescribedType) else None
        return cls(
            name=f[0] if len(f) > 0 else "",
            handle=f[1] if len(f) > 1 and f[1] is not None else 0,
            role=bool(f[2]) if len(f) > 2 and f[2] is not None else False,
            snd_settle_mode=f[3] if len(f) > 3 else 2,
            rcv_settle_mode=f[4] if len(f) > 4 else 0,
            source=src,
            target=tgt,
            unsettled=f[7] if len(f) > 7 else None,
            incomplete_unsettled=f[8] if len(f) > 8 else None,
            initial_delivery_count=f[9] if len(f) > 9 else 0,
            max_message_size=f[10] if len(f) > 10 else 262144,
            offered_capabilities=f[11] if len(f) > 11 else None,
            desired_capabilities=f[12] if len(f) > 12 else None,
            properties=f[13] if len(f) > 13 else {},
        )

    def __repr__(self) -> str:
        role_str = "receiver" if self.role else "sender"
        return f"Attach(name={self.name!r}, handle={self.handle}, role={role_str})"


class Detach:
    """AMQP 1.0 Detach performative (descriptor 0x16)."""

    DESCRIPTOR = Ulong(0x16)

    def __init__(self, handle: int, closed: bool = False, error: Error | None = None):
        self.handle = Uint(handle)
        self.closed = closed
        self.error = error

    def to_described_type(self) -> DescribedType:
        err_dt = self.error.to_described_type() if self.error else None
        fields = [self.handle, self.closed, err_dt]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Detach:
        f = dt.value if isinstance(dt.value, list) else []
        handle = f[0] if len(f) > 0 and f[0] is not None else 0
        closed = bool(f[1]) if len(f) > 1 and f[1] is not None else False
        err = Error.from_described_type(f[2]) if len(f) > 2 and isinstance(f[2], DescribedType) else None
        return cls(handle=handle, closed=closed, error=err)

    def __repr__(self) -> str:
        return f"Detach(handle={self.handle}, closed={self.closed}, error={self.error!r})"


class Flow:
    """AMQP 1.0 Flow performative (descriptor 0x13)."""

    DESCRIPTOR = Ulong(0x13)

    def __init__(
        self,
        next_incoming_id: int | None = 1,
        incoming_window: int = 5000,
        next_outgoing_id: int = 1,
        outgoing_window: int = 5000,
        handle: int | None = None,
        delivery_count: int | None = None,
        link_credit: int | None = None,
        available: int | None = None,
        drain: bool = False,
        echo: bool = False,
        properties: dict[Any, Any] | None = None,
    ):
        self.next_incoming_id = Uint(next_incoming_id) if next_incoming_id is not None else None
        self.incoming_window = Uint(incoming_window)
        self.next_outgoing_id = Uint(next_outgoing_id)
        self.outgoing_window = Uint(outgoing_window)
        self.handle = Uint(handle) if handle is not None else None
        self.delivery_count = Uint(delivery_count) if delivery_count is not None else None
        self.link_credit = Uint(link_credit) if link_credit is not None else None
        self.available = Uint(available) if available is not None else None
        self.drain = drain
        self.echo = echo
        self.properties = properties or {}

    def to_described_type(self) -> DescribedType:
        fields = [
            self.next_incoming_id,
            self.incoming_window,
            self.next_outgoing_id,
            self.outgoing_window,
            self.handle,
            self.delivery_count,
            self.link_credit,
            self.available,
            self.drain if self.drain else None,
            self.echo if self.echo else None,
            self.properties if self.properties else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Flow:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            next_incoming_id=f[0] if len(f) > 0 else None,
            incoming_window=f[1] if len(f) > 1 and f[1] is not None else 5000,
            next_outgoing_id=f[2] if len(f) > 2 and f[2] is not None else 1,
            outgoing_window=f[3] if len(f) > 3 and f[3] is not None else 5000,
            handle=f[4] if len(f) > 4 else None,
            delivery_count=f[5] if len(f) > 5 else None,
            link_credit=f[6] if len(f) > 6 else None,
            available=f[7] if len(f) > 7 else None,
            drain=bool(f[8]) if len(f) > 8 and f[8] is not None else False,
            echo=bool(f[9]) if len(f) > 9 and f[9] is not None else False,
            properties=f[10] if len(f) > 10 else {},
        )

    def __repr__(self) -> str:
        return f"Flow(handle={self.handle}, credit={self.link_credit}, drain={self.drain})"


# --- SASL Performatives (Part 5: Security) ---


class SaslMechanisms:
    """AMQP 1.0 SASL Mechanisms (descriptor 0x40)."""

    DESCRIPTOR = Ulong(0x40)

    def __init__(self, mechanisms: Sequence[str | Symbol]):
        self.mechanisms = [Symbol(m) if isinstance(m, str) else m for m in mechanisms]

    def to_described_type(self) -> DescribedType:
        return DescribedType(self.DESCRIPTOR, [self.mechanisms])

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> SaslMechanisms:
        f = dt.value if isinstance(dt.value, list) else []
        mechs = f[0] if len(f) > 0 and isinstance(f[0], list) else []
        return cls(mechanisms=mechs)

    def __repr__(self) -> str:
        return f"SaslMechanisms({self.mechanisms!r})"


class SaslInit:
    """AMQP 1.0 SASL Init (descriptor 0x41)."""

    DESCRIPTOR = Ulong(0x41)

    def __init__(
        self,
        mechanism: str | Symbol,
        initial_response: bytes | None = None,
        hostname: str | None = None,
    ):
        self.mechanism = Symbol(mechanism) if isinstance(mechanism, str) else mechanism
        self.initial_response = initial_response
        self.hostname = hostname

    def to_described_type(self) -> DescribedType:
        fields = [self.mechanism, self.initial_response, self.hostname]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> SaslInit:
        f = dt.value if isinstance(dt.value, list) else []
        mech = f[0] if len(f) > 0 and f[0] is not None else Symbol("ANONYMOUS")
        resp = f[1] if len(f) > 1 else None
        host = f[2] if len(f) > 2 else None
        return cls(mechanism=mech, initial_response=resp, hostname=host)

    def __repr__(self) -> str:
        return f"SaslInit(mechanism={self.mechanism!r})"


class SaslOutcome:
    """AMQP 1.0 SASL Outcome (descriptor 0x44)."""

    DESCRIPTOR = Ulong(0x44)

    OK = 0
    AUTH = 1
    SYS = 2
    SYS_PERM = 3
    SYS_TEMP = 4

    def __init__(self, code: int = 0, additional_data: bytes | None = None):
        self.code = Ubyte(code)
        self.additional_data = additional_data

    def to_described_type(self) -> DescribedType:
        fields = [self.code, self.additional_data]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> SaslOutcome:
        f = dt.value if isinstance(dt.value, list) else []
        code = f[0] if len(f) > 0 and f[0] is not None else 0
        data = f[1] if len(f) > 1 else None
        return cls(code=code, additional_data=data)

    def __repr__(self) -> str:
        return f"SaslOutcome(code={self.code})"


class Transfer:
    """AMQP 1.0 Transfer performative (descriptor 0x14)."""

    DESCRIPTOR = Ulong(0x14)

    def __init__(
        self,
        handle: int,
        delivery_id: int | None = None,
        delivery_tag: bytes | None = None,
        message_format: int | None = 0,
        settled: bool | None = None,
        more: bool = False,
        rcv_settle_mode: int | None = None,
        state: Any = None,
        resume: bool = False,
        aborted: bool = False,
        batchable: bool = False,
    ):
        self.handle = Uint(handle)
        self.delivery_id = Uint(delivery_id) if delivery_id is not None else None
        self.delivery_tag = delivery_tag
        self.message_format = Uint(message_format) if message_format is not None else None
        self.settled = settled
        self.more = more
        self.rcv_settle_mode = Ubyte(rcv_settle_mode) if rcv_settle_mode is not None else None
        self.state = state
        self.resume = resume
        self.aborted = aborted
        self.batchable = batchable

    def to_described_type(self) -> DescribedType:
        state_dt = self.state.to_described_type() if hasattr(self.state, "to_described_type") else self.state
        fields = [
            self.handle,
            self.delivery_id,
            self.delivery_tag,
            self.message_format,
            self.settled,
            self.more if self.more else None,
            self.rcv_settle_mode,
            state_dt,
            self.resume if self.resume else None,
            self.aborted if self.aborted else None,
            self.batchable if self.batchable else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Transfer:
        f = dt.value if isinstance(dt.value, list) else []
        state_raw = f[7] if len(f) > 7 else None
        state = parse_performative(state_raw) if isinstance(state_raw, DescribedType) else state_raw
        return cls(
            handle=f[0] if len(f) > 0 and f[0] is not None else 0,
            delivery_id=f[1] if len(f) > 1 else None,
            delivery_tag=f[2] if len(f) > 2 else None,
            message_format=f[3] if len(f) > 3 and f[3] is not None else 0,
            settled=bool(f[4]) if len(f) > 4 and f[4] is not None else None,
            more=bool(f[5]) if len(f) > 5 and f[5] is not None else False,
            rcv_settle_mode=f[6] if len(f) > 6 else None,
            state=state,
            resume=bool(f[8]) if len(f) > 8 and f[8] is not None else False,
            aborted=bool(f[9]) if len(f) > 9 and f[9] is not None else False,
            batchable=bool(f[10]) if len(f) > 10 and f[10] is not None else False,
        )

    def __repr__(self) -> str:
        return f"Transfer(handle={self.handle}, id={self.delivery_id}, format={self.message_format}, more={self.more})"


class Disposition:
    """AMQP 1.0 Disposition performative (descriptor 0x15)."""

    DESCRIPTOR = Ulong(0x15)

    def __init__(
        self,
        role: bool,  # False = sender, True = receiver
        first: int,
        last: int | None = None,
        settled: bool = False,
        state: Any = None,
        batchable: bool = False,
    ):
        self.role = role
        self.first = Uint(first)
        self.last = Uint(last) if last is not None else None
        self.settled = settled
        self.state = state
        self.batchable = batchable

    def to_described_type(self) -> DescribedType:
        state_dt = self.state.to_described_type() if hasattr(self.state, "to_described_type") else self.state
        fields = [
            self.role,
            self.first,
            self.last,
            self.settled,
            state_dt,
            self.batchable if self.batchable else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Disposition:
        f = dt.value if isinstance(dt.value, list) else []
        state_raw = f[4] if len(f) > 4 else None
        state = parse_performative(state_raw) if isinstance(state_raw, DescribedType) else state_raw
        return cls(
            role=bool(f[0]) if len(f) > 0 and f[0] is not None else False,
            first=f[1] if len(f) > 1 and f[1] is not None else 0,
            last=f[2] if len(f) > 2 else None,
            settled=bool(f[3]) if len(f) > 3 and f[3] is not None else False,
            state=state,
            batchable=bool(f[5]) if len(f) > 5 and f[5] is not None else False,
        )

    def __repr__(self) -> str:
        return f"Disposition(role={self.role}, first={self.first}, last={self.last}, settled={self.settled}, state={self.state!r})"


# --- Delivery Outcomes ---


class Accepted:
    """AMQP 1.0 Accepted outcome (descriptor 0x24)."""

    DESCRIPTOR = Ulong(0x24)

    def to_described_type(self) -> DescribedType:
        return DescribedType(self.DESCRIPTOR, [])

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Accepted:
        return cls()

    def __repr__(self) -> str:
        return "Accepted()"


class Released:
    """AMQP 1.0 Released outcome (descriptor 0x26)."""

    DESCRIPTOR = Ulong(0x26)

    def to_described_type(self) -> DescribedType:
        return DescribedType(self.DESCRIPTOR, [])

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Released:
        return cls()

    def __repr__(self) -> str:
        return "Released()"


class Rejected:
    """AMQP 1.0 Rejected outcome (descriptor 0x25)."""

    DESCRIPTOR = Ulong(0x25)

    def __init__(self, error: Error | None = None):
        self.error = error

    def to_described_type(self) -> DescribedType:
        err_dt = self.error.to_described_type() if self.error else None
        fields = [err_dt]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Rejected:
        f = dt.value if isinstance(dt.value, list) else []
        err = Error.from_described_type(f[0]) if len(f) > 0 and isinstance(f[0], DescribedType) else None
        return cls(error=err)

    def __repr__(self) -> str:
        return f"Rejected(error={self.error!r})"


class Modified:
    """AMQP 1.0 Modified outcome (descriptor 0x27)."""

    DESCRIPTOR = Ulong(0x27)

    def __init__(
        self,
        delivery_failed: bool = False,
        undeliverable_here: bool = False,
        message_annotations: dict[Any, Any] | None = None,
    ):
        self.delivery_failed = delivery_failed
        self.undeliverable_here = undeliverable_here
        self.message_annotations = message_annotations or {}

    def to_described_type(self) -> DescribedType:
        fields = [
            self.delivery_failed if self.delivery_failed else None,
            self.undeliverable_here if self.undeliverable_here else None,
            self.message_annotations if self.message_annotations else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Modified:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            delivery_failed=bool(f[0]) if len(f) > 0 and f[0] is not None else False,
            undeliverable_here=bool(f[1]) if len(f) > 1 and f[1] is not None else False,
            message_annotations=f[2] if len(f) > 2 and isinstance(f[2], dict) else {},
        )

    def __repr__(self) -> str:
        return f"Modified(delivery_failed={self.delivery_failed})"


# Dispatch table for parsing incoming DescribedTypes into performative objects
PERFORMATIVE_DISPATCH = {
    Open.DESCRIPTOR: Open.from_described_type,
    Begin.DESCRIPTOR: Begin.from_described_type,
    Attach.DESCRIPTOR: Attach.from_described_type,
    Flow.DESCRIPTOR: Flow.from_described_type,
    Transfer.DESCRIPTOR: Transfer.from_described_type,
    Disposition.DESCRIPTOR: Disposition.from_described_type,
    Detach.DESCRIPTOR: Detach.from_described_type,
    End.DESCRIPTOR: End.from_described_type,
    Close.DESCRIPTOR: Close.from_described_type,
    SaslMechanisms.DESCRIPTOR: SaslMechanisms.from_described_type,
    SaslInit.DESCRIPTOR: SaslInit.from_described_type,
    SaslOutcome.DESCRIPTOR: SaslOutcome.from_described_type,
    Error.DESCRIPTOR: Error.from_described_type,
    Accepted.DESCRIPTOR: Accepted.from_described_type,
    Released.DESCRIPTOR: Released.from_described_type,
    Rejected.DESCRIPTOR: Rejected.from_described_type,
    Modified.DESCRIPTOR: Modified.from_described_type,
}


def parse_performative(dt: Any) -> Any:
    """Convert a raw DescribedType into a typed Performative, if known."""
    if not isinstance(dt, DescribedType):
        return dt
    descriptor = dt.descriptor
    # Match descriptor numeric value
    if isinstance(descriptor, (int, Ulong)):
        parser = PERFORMATIVE_DISPATCH.get(Ulong(int(descriptor)))
        if parser:
            return parser(dt)
    return dt
