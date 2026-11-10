# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AMQP 1.0 protocol engine (OASIS AMQP 1.0, ISO/IEC 19464) — substrate-free.

Pure Python, bytes in / bytes out, NO sockets / asyncio / threads, so the very same engine runs
in the offline appliance (asyncio TCP + WebSocket transport, core/amqp_server.py) and inside
Pyodide in a Nano tab (frames arrive over the relay's WebSocket bridge). Loads under Pyodide.

What it implements
  * type system codec (null, bool, ubyte..ulong, byte..long, float, double, timestamp, uuid,
    binary, string, symbol, list, map, array, described) — `encode()` / `decode()`;
  * framing (AMQP + SASL frame types, protocol headers, extended headers, empty keep-alives);
  * SASL server (ANONYMOUS / PLAIN / EXTERNAL / MSSBCBS accepted; credentials are NOT
    verified — same stance as the REST core);
  * connection / session / link state machines (open, begin, attach, flow, transfer,
    disposition, detach, end, close), session windows, link credit, drain, multi-frame
    transfers in both directions, idle-timeout keep-alives;
  * a small `Container` callback interface a broker implements (core/azure_servicebus_amqp.py).

Not implemented: TLS (a transport concern), SASL SCRAM/XOAUTH, transactions (coordinator
links are refused), link resume / recovery of unsettled state across reconnects.
"""
from __future__ import annotations

import struct
import uuid as _uuid

import os as _os
TRACE = bool(_os.environ.get("VYOMI_AMQP_TRACE"))
PROTO_AMQP = b"AMQP\x00\x01\x00\x00"
PROTO_TLS = b"AMQP\x02\x01\x00\x00"
PROTO_SASL = b"AMQP\x03\x01\x00\x00"
MIN_MAX_FRAME = 512


# ── type system ─────────────────────────────────────────────────────────────
class Symbol(str):
    __slots__ = ()


class UByte(int):
    pass


class UShort(int):
    pass


class UInt(int):
    pass


class ULong(int):
    pass


class Timestamp(int):
    """milliseconds since the Unix epoch"""


class Described:
    __slots__ = ("descriptor", "value")

    def __init__(self, descriptor, value):
        self.descriptor, self.value = descriptor, value

    def __repr__(self):
        return "Described(%r, %r)" % (self.descriptor, self.value)

    def __eq__(self, o):
        return isinstance(o, Described) and o.descriptor == self.descriptor and o.value == self.value

    __hash__ = None


class SymbolArray(list):
    """encodes as an AMQP array of symbols (the `multiple` fields: capabilities, locales...)"""


def _enc_size(code_small: int, code_big: int, body: bytes) -> bytes:
    if len(body) < 256:
        return bytes([code_small, len(body)]) + body
    return bytes([code_big]) + struct.pack(">I", len(body)) + body


def encode(v) -> bytes:
    if v is None:
        return b"\x40"
    if v is True:
        return b"\x41"
    if v is False:
        return b"\x42"
    if isinstance(v, Described):
        return b"\x00" + encode(v.descriptor) + encode(v.value)
    if isinstance(v, Symbol):
        return _enc_size(0xA3, 0xB3, v.encode("ascii"))
    if isinstance(v, str):
        return _enc_size(0xA1, 0xB1, v.encode("utf-8"))
    if isinstance(v, (bytes, bytearray, memoryview)):
        return _enc_size(0xA0, 0xB0, bytes(v))
    if isinstance(v, UByte):
        return bytes([0x50, v & 0xFF])
    if isinstance(v, UShort):
        return b"\x60" + struct.pack(">H", v)
    if isinstance(v, UInt):
        if v == 0:
            return b"\x43"
        if v < 256:
            return bytes([0x52, v])
        return b"\x70" + struct.pack(">I", v)
    if isinstance(v, ULong):
        if v == 0:
            return b"\x44"
        if v < 256:
            return bytes([0x53, v])
        return b"\x80" + struct.pack(">Q", v)
    if isinstance(v, Timestamp):
        return b"\x83" + struct.pack(">q", int(v))
    if isinstance(v, int):
        if -2147483648 <= v <= 2147483647:
            return b"\x71" + struct.pack(">i", v)
        return b"\x81" + struct.pack(">q", v)
    if isinstance(v, float):
        return b"\x82" + struct.pack(">d", v)
    if isinstance(v, _uuid.UUID):
        return b"\x98" + v.bytes
    if isinstance(v, SymbolArray):
        if not v:
            return b"\x45"
        body = b"".join(struct.pack(">I", len(str(x))) + str(x).encode("ascii") for x in v)
        return b"\xf0" + struct.pack(">II", len(body) + 5, len(v)) + b"\xb3" + body
    if isinstance(v, (list, tuple)):
        if not v:
            return b"\x45"
        items = b"".join(encode(x) for x in v)
        if len(items) + 1 < 256 and len(v) < 256:
            return b"\xc0" + bytes([len(items) + 1, len(v)]) + items
        return b"\xd0" + struct.pack(">II", len(items) + 4, len(v)) + items
    if isinstance(v, dict):
        items = b"".join(encode(k) + encode(x) for k, x in v.items())
        n = len(v) * 2
        if len(items) + 1 < 256 and n < 256:
            return b"\xc1" + bytes([len(items) + 1, n]) + items
        return b"\xd1" + struct.pack(">II", len(items) + 4, n) + items
    raise TypeError("cannot AMQP-encode %r" % type(v))


_FIXED = {0x40: 0, 0x41: 0, 0x42: 0, 0x43: 0, 0x44: 0, 0x45: 0, 0x50: 1, 0x51: 1, 0x52: 1, 0x53: 1, 0x54: 1, 0x55: 1,
          0x56: 1, 0x60: 2, 0x61: 2, 0x70: 4, 0x71: 4, 0x72: 4, 0x73: 4, 0x74: 4, 0x80: 8, 0x81: 8, 0x82: 8, 0x83: 8,
          0x84: 8, 0x94: 16, 0x98: 16}


def _decode_fixed(code: int, b: bytes):
    if code == 0x40:
        return None
    if code == 0x42:
        return False
    if code == 0x43 or code == 0x44 or code == 0x45:
        return 0 if code != 0x45 else []
    if code == 0x56:
        return b[0] != 0
    if code in (0x50, 0x52, 0x53):
        return b[0]
    if code == 0x51:
        return struct.unpack(">b", b)[0]
    if code in (0x54, 0x55):
        return struct.unpack(">b", b)[0]
    if code in (0x60,):
        return struct.unpack(">H", b)[0]
    if code == 0x61:
        return struct.unpack(">h", b)[0]
    if code == 0x70:
        return struct.unpack(">I", b)[0]
    if code == 0x71:
        return struct.unpack(">i", b)[0]
    if code == 0x72:
        return struct.unpack(">f", b)[0]
    if code == 0x80:
        return struct.unpack(">Q", b)[0]
    if code == 0x81:
        return struct.unpack(">q", b)[0]
    if code == 0x82:
        return struct.unpack(">d", b)[0]
    if code == 0x83:
        return Timestamp(struct.unpack(">q", b)[0])
    if code == 0x98:
        return _uuid.UUID(bytes=bytes(b))
    return bytes(b)


def decode(buf: bytes, pos: int = 0):
    """-> (value, next_pos)"""
    code = buf[pos]
    pos += 1
    if code == 0x00:
        desc, pos = decode(buf, pos)
        val, pos = decode(buf, pos)
        return Described(desc, val), pos
    return _decode_body(buf, pos, code)


def _decode_body(buf, pos, code):
    if code == 0x41:
        return True, pos
    if code in _FIXED:
        n = _FIXED[code]
        return _decode_fixed(code, buf[pos:pos + n]), pos + n
    kind = code & 0xF0
    if kind in (0xA0, 0xB0):       # variable width: 0xa=1B size, 0xb=4B size
        if kind == 0xA0:
            n = buf[pos]
            pos += 1
        else:
            n = struct.unpack_from(">I", buf, pos)[0]
            pos += 4
        raw = bytes(buf[pos:pos + n])
        pos += n
        c = code & 0x0F
        if c == 0:
            return raw, pos
        if c == 1:
            return raw.decode("utf-8", "replace"), pos
        return Symbol(raw.decode("ascii", "replace")), pos
    if code in (0xC0, 0xD0, 0xC1, 0xD1):
        if code in (0xC0, 0xC1):
            size, count = buf[pos], buf[pos + 1]
            pos += 2
        else:
            size, count = struct.unpack_from(">II", buf, pos)
            pos += 8
        out = []
        for _ in range(count):
            x, pos = decode(buf, pos)
            out.append(x)
        if code in (0xC0, 0xD0):
            return out, pos
        d = {}
        for i in range(0, len(out) - 1, 2):
            k = out[i]
            try:
                d[k] = out[i + 1]
            except TypeError:
                d[repr(k)] = out[i + 1]
        return d, pos
    if code in (0xE0, 0xF0):
        if code == 0xE0:
            size, count = buf[pos], buf[pos + 1]
            pos += 2
        else:
            size, count = struct.unpack_from(">II", buf, pos)
            pos += 8
        ec = buf[pos]
        pos += 1
        out = []
        if ec == 0x00:   # described array: descriptor then elements
            _d, pos = decode(buf, pos)
            ec = buf[pos]
            pos += 1
        for _ in range(count):
            x, pos = _decode_body(buf, pos, ec)
            out.append(x)
        return out, pos
    raise ValueError("unsupported AMQP type code 0x%02x" % code)


# ── performatives ───────────────────────────────────────────────────────────
PERF = {
    0x10: ("open", ["container_id", "hostname", "max_frame_size", "channel_max", "idle_time_out", "outgoing_locales",
                    "incoming_locales", "offered_capabilities", "desired_capabilities", "properties"]),
    0x11: ("begin", ["remote_channel", "next_outgoing_id", "incoming_window", "outgoing_window", "handle_max",
                     "offered_capabilities", "desired_capabilities", "properties"]),
    0x12: ("attach", ["name", "handle", "role", "snd_settle_mode", "rcv_settle_mode", "source", "target", "unsettled",
                      "incomplete_unsettled", "initial_delivery_count", "max_message_size", "offered_capabilities",
                      "desired_capabilities", "properties"]),
    0x13: ("flow", ["next_incoming_id", "incoming_window", "next_outgoing_id", "outgoing_window", "handle",
                    "delivery_count", "link_credit", "available", "drain", "echo", "properties"]),
    0x14: ("transfer", ["handle", "delivery_id", "delivery_tag", "message_format", "settled", "more", "rcv_settle_mode",
                        "state", "resume", "aborted", "batchable"]),
    0x15: ("disposition", ["role", "first", "last", "settled", "state", "batchable"]),
    0x16: ("detach", ["handle", "closed", "error"]),
    0x17: ("end", ["error"]),
    0x18: ("close", ["error"]),
    0x40: ("sasl-mechanisms", ["sasl_server_mechanisms"]),
    0x41: ("sasl-init", ["mechanism", "initial_response", "hostname"]),
    0x42: ("sasl-challenge", ["challenge"]),
    0x43: ("sasl-response", ["response"]),
    0x44: ("sasl-outcome", ["code", "additional_data"]),
}
_PERF_BY_NAME = {v[0]: (k, v[1]) for k, v in PERF.items()}
_TYPED = {   # fields whose AMQP type must be exact for strict peers
    "open": {"max_frame_size": UInt, "channel_max": UShort, "idle_time_out": UInt, "outgoing_locales": SymbolArray,
             "incoming_locales": SymbolArray, "offered_capabilities": SymbolArray, "desired_capabilities": SymbolArray},
    "begin": {"remote_channel": UShort, "next_outgoing_id": UInt, "incoming_window": UInt, "outgoing_window": UInt,
              "handle_max": UInt, "offered_capabilities": SymbolArray, "desired_capabilities": SymbolArray},
    "attach": {"handle": UInt, "role": bool, "snd_settle_mode": UByte, "rcv_settle_mode": UByte,
               "initial_delivery_count": UInt, "max_message_size": ULong, "offered_capabilities": SymbolArray,
               "desired_capabilities": SymbolArray},
    "flow": {"next_incoming_id": UInt, "incoming_window": UInt, "next_outgoing_id": UInt, "outgoing_window": UInt,
             "handle": UInt, "delivery_count": UInt, "link_credit": UInt, "available": UInt},
    "transfer": {"handle": UInt, "delivery_id": UInt, "message_format": UInt, "rcv_settle_mode": UByte},
    "disposition": {"first": UInt, "last": UInt},
    "detach": {"handle": UInt},
    "sasl-outcome": {"code": UByte},
}
AMQP_ROLE_SENDER, AMQP_ROLE_RECEIVER = False, True    # `role` field: false = sender, true = receiver

D_RECEIVED, D_ACCEPTED, D_REJECTED, D_RELEASED, D_MODIFIED = 0x23, 0x24, 0x25, 0x26, 0x27
D_SOURCE, D_TARGET, D_ERROR, D_COORDINATOR = 0x28, 0x29, 0x1D, 0x30
D_HEADER, D_DELIV_ANN, D_MSG_ANN, D_PROPS, D_APP_PROPS, D_DATA, D_SEQ, D_VALUE, D_FOOTER = (
    0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78)


def _desc_num(d):
    if isinstance(d, int):
        return int(d)
    return d    # symbol descriptors (e.g. com.microsoft:session-filter) stay as-is


def make_perf(name: str, /, **fields) -> bytes:
    code, names = _PERF_BY_NAME[name]
    types = _TYPED.get(name, {})
    vals = []
    for n in names:
        v = fields.get(n)
        t = types.get(n)
        if v is not None and t is not None and t is not bool:
            v = v if isinstance(v, t) else (t(v) if t is not SymbolArray else SymbolArray(v if isinstance(v, (list, tuple)) else [v]))
        vals.append(v)
    while vals and vals[-1] is None:
        vals.pop()
    return encode(Described(ULong(code), vals))


def parse_perf(body: bytes):
    """-> (kind, fields-dict, next_pos)"""
    d, pos = decode(body, 0)
    if not isinstance(d, Described):
        raise ValueError("frame body is not a described performative")
    num = _desc_num(d.descriptor)
    if num not in PERF:
        raise ValueError("unknown performative 0x%x" % (num if isinstance(num, int) else 0))
    kind, names = PERF[num]
    vals = d.value if isinstance(d.value, list) else []
    f = {n: (vals[i] if i < len(vals) else None) for i, n in enumerate(names)}
    return kind, f, pos


def error(condition: str, description: str = "", info: dict | None = None) -> Described:
    return Described(ULong(D_ERROR), [Symbol(condition), description, info])


def terminus(kind: int, address=None, **kw):
    """source (0x28) / target (0x29) terminus, keeping the fields a peer may rely on"""
    if kind == D_SOURCE:
        v = [address, kw.get("durable"), kw.get("expiry_policy"), kw.get("timeout"), kw.get("dynamic"),
             kw.get("dynamic_node_properties"), kw.get("distribution_mode"), kw.get("filter"),
             kw.get("default_outcome"), kw.get("outcomes"), kw.get("capabilities")]
    else:
        v = [address, kw.get("durable"), kw.get("expiry_policy"), kw.get("timeout"), kw.get("dynamic"),
             kw.get("dynamic_node_properties"), kw.get("capabilities")]
    while v and v[-1] is None:
        v.pop()
    return Described(ULong(kind), v)


def terminus_fields(t) -> dict:
    """decode a source/target terminus Described into a dict (None-safe)"""
    if not isinstance(t, Described):
        return {}
    names = (["address", "durable", "expiry_policy", "timeout", "dynamic", "dynamic_node_properties",
              "distribution_mode", "filter", "default_outcome", "outcomes", "capabilities"]
             if _desc_num(t.descriptor) == D_SOURCE else
             ["address", "durable", "expiry_policy", "timeout", "dynamic", "dynamic_node_properties", "capabilities"])
    vals = t.value if isinstance(t.value, list) else []
    return {n: (vals[i] if i < len(vals) else None) for i, n in enumerate(names)}


def delivery_state(kind: int, *vals):
    return Described(ULong(kind), list(vals))


def state_kind(state):
    return _desc_num(state.descriptor) if isinstance(state, Described) else None


# ── message sections ────────────────────────────────────────────────────────
PROPS_FIELDS = ["message_id", "user_id", "to", "subject", "reply_to", "correlation_id", "content_type",
                "content_encoding", "absolute_expiry_time", "creation_time", "group_id", "group_sequence",
                "reply_to_group_id"]
HEADER_FIELDS = ["durable", "priority", "ttl", "first_acquirer", "delivery_count"]


def parse_message(payload: bytes) -> dict:
    """Split an AMQP message into its sections.
    -> {header:{}, delivery_annotations:{}, message_annotations:{}, properties:{}, application_properties:{},
        body_kind:'data'|'value'|'sequence', body:[...], footer:{}, raw_body:bytes, pre:bytes}
    `raw_body` is the byte-exact encoding of the body section(s) (round-tripped untouched)."""
    out = {"header": {}, "delivery_annotations": {}, "message_annotations": {}, "properties": {},
           "application_properties": {}, "footer": {}, "body_kind": "data", "body": [], "raw_body": b""}
    pos = 0
    body_start = None
    rest = []
    n = len(payload)
    while pos < n:
        start = pos
        sec, pos = decode(payload, pos)
        if not isinstance(sec, Described):
            raise ValueError("message section is not described")
        d = _desc_num(sec.descriptor)
        v = sec.value
        if d == D_HEADER:
            vals = v if isinstance(v, list) else []
            out["header"] = {k: (vals[i] if i < len(vals) else None) for i, k in enumerate(HEADER_FIELDS)}
        elif d == D_DELIV_ANN:
            out["delivery_annotations"] = v if isinstance(v, dict) else {}
        elif d == D_MSG_ANN:
            out["message_annotations"] = v if isinstance(v, dict) else {}
        elif d == D_PROPS:
            vals = v if isinstance(v, list) else []
            out["properties"] = {k: (vals[i] if i < len(vals) else None) for i, k in enumerate(PROPS_FIELDS)}
        elif d == D_APP_PROPS:
            out["application_properties"] = v if isinstance(v, dict) else {}
        elif d in (D_DATA, D_SEQ, D_VALUE):
            if body_start is None:
                body_start = start
            out["body_kind"] = {D_DATA: "data", D_SEQ: "sequence", D_VALUE: "value"}[d]
            out["body"].append(v)
            out["raw_body"] = payload[body_start:pos]
        elif d == D_FOOTER:
            out["footer"] = v if isinstance(v, dict) else {}
        if d in (D_PROPS, D_APP_PROPS, D_DATA, D_SEQ, D_VALUE, D_FOOTER):
            rest.append(payload[start:pos])
    out["rest"] = b"".join(rest)     # properties + application-properties + body + footer, byte-exact
    return out


def build_message(header=None, message_annotations=None, properties=None, application_properties=None,
                  raw_body: bytes = b"", delivery_annotations=None, footer=None) -> bytes:
    out = b""
    if header:
        vals = [header.get(k) for k in HEADER_FIELDS]
        for i, k in enumerate(HEADER_FIELDS):
            if vals[i] is not None and k in ("priority",):
                vals[i] = UByte(vals[i])
            elif vals[i] is not None and k in ("ttl", "delivery_count"):
                vals[i] = UInt(vals[i])
        while vals and vals[-1] is None:
            vals.pop()
        if vals:
            out += encode(Described(ULong(D_HEADER), vals))
    if delivery_annotations:
        out += encode(Described(ULong(D_DELIV_ANN), delivery_annotations))
    if message_annotations:
        out += encode(Described(ULong(D_MSG_ANN), message_annotations))
    if properties:
        vals = [properties.get(k) for k in PROPS_FIELDS]
        for i, k in enumerate(PROPS_FIELDS):
            if vals[i] is not None and k in ("absolute_expiry_time", "creation_time") and not isinstance(vals[i], Timestamp):
                vals[i] = Timestamp(vals[i])
            elif vals[i] is not None and k == "group_sequence":
                vals[i] = UInt(vals[i])
        while vals and vals[-1] is None:
            vals.pop()
        if vals:
            out += encode(Described(ULong(D_PROPS), vals))
    if application_properties:
        out += encode(Described(ULong(D_APP_PROPS), application_properties))
    out += raw_body
    if footer:
        out += encode(Described(ULong(D_FOOTER), footer))
    return out


def data_section(b: bytes) -> bytes:
    return encode(Described(ULong(D_DATA), bytes(b)))


# ── frames ──────────────────────────────────────────────────────────────────
def frame(ftype: int, channel: int, body: bytes = b"") -> bytes:
    return struct.pack(">IBBH", 8 + len(body), 2, ftype, channel) + body


# ── connection engine ───────────────────────────────────────────────────────
class Delivery:
    __slots__ = ("id", "tag", "link", "payload", "settled", "state", "remote_settled", "format", "data", "t_sent")

    def __init__(self, id, tag, link):
        self.id, self.tag, self.link = id, tag, link
        self.payload = b""
        self.settled = False
        self.remote_settled = False
        self.state = None
        self.format = 0
        self.data = None       # container scratch (e.g. the broker message)
        self.t_sent = 0.0


class Link:
    """One end of a link, from the SERVER's point of view (role 'sender' = we send to the client)."""

    def __init__(self, session, name, handle, role_sender: bool):
        self.session, self.name, self.handle = session, name, handle
        self.sender = role_sender
        self.remote_handle = None
        self.source = None
        self.target = None
        self.snd_settle_mode = 2
        self.rcv_settle_mode = 0
        self.delivery_count = 0
        self.credit = 0                  # sender: credit granted by the client; receiver: credit we granted
        self.drain = False
        self.max_message_size = 0
        self.address = None
        self.unsettled = {}              # delivery_id -> Delivery (those we sent, awaiting disposition)
        self._partial = None             # reassembly of a multi-frame inbound transfer
        self.closed = False
        self.attached = False
        self.ctx = {}                    # broker scratch

    @property
    def conn(self):
        return self.session.conn

    def send_transfer(self, payload: bytes, tag: bytes, settled: bool = False, state=None) -> Delivery:
        return self.session._send_delivery(self, payload, tag, settled, state)

    def detach(self, err=None):
        self.session._detach(self, err)

    def grant(self, credit: int):
        """receiver link: (re)issue `credit` to the peer"""
        self.credit = credit
        self.session._send_flow(self)

    def window_open(self) -> bool:
        return self.session.remote_incoming_window > 0


class Session:
    def __init__(self, conn, channel, remote_channel):
        self.conn = conn
        self.channel, self.remote_channel = channel, remote_channel
        self.next_outgoing_id = 0
        self.next_incoming_id = 0
        self.remote_incoming_window = 2048
        self.remote_outgoing_window = 2048
        self.incoming_window = 1 << 20
        self.links = {}                  # local handle -> Link
        self.by_remote = {}              # remote handle -> Link
        self.by_name = {}
        self.delivery_to_link = {}       # our outgoing delivery_id -> Link
        self.ended = False
        self._since_flow = 0
        self.ctx = {}

    # -- outbound helpers
    def _emit(self, body: bytes, payload: bytes = b""):
        self.conn._emit(0, self.channel, body + payload)

    def _send_flow(self, link=None):
        f = dict(next_incoming_id=self.next_incoming_id, incoming_window=self.incoming_window,
                 next_outgoing_id=self.next_outgoing_id, outgoing_window=1 << 20)
        if link is not None:
            f.update(handle=link.handle, delivery_count=link.delivery_count & 0xFFFFFFFF, link_credit=max(link.credit, 0),
                     drain=link.drain or None)
        self._emit(make_perf("flow", **f))

    def _send_delivery(self, link, payload, tag, settled, state):
        did = self.next_outgoing_id
        self.next_outgoing_id = (did + 1) & 0xFFFFFFFF
        d = Delivery(did, tag, link)
        d.payload, d.settled = payload, settled
        link.delivery_count = (link.delivery_count + 1) & 0xFFFFFFFF
        link.credit -= 1
        self.remote_incoming_window -= 1
        if not settled:
            link.unsettled[did] = d
            self.delivery_to_link[did] = d.link
        max_body = max(self.conn.remote_max_frame - 8 - 64, MIN_MAX_FRAME)
        chunks = [payload[i:i + max_body] for i in range(0, len(payload), max_body)] or [b""]
        for i, ch in enumerate(chunks):
            first, last = i == 0, i == len(chunks) - 1
            if first:
                perf = make_perf("transfer", handle=link.handle, delivery_id=did, delivery_tag=bytes(tag),
                                 message_format=UInt(0), settled=bool(settled), more=(not last) or None, state=state)
            else:
                perf = make_perf("transfer", handle=link.handle, more=(not last) or None)
            self._emit(perf, ch)
        return d

    def _detach(self, link, err=None):
        if link.closed:
            return
        link.closed = True
        self._emit(make_perf("detach", handle=link.handle, closed=True, error=err))

    def _settle_range(self, first, last, state, role_receiver: bool, settled=True):
        self._emit(make_perf("disposition", role=role_receiver, first=first, last=last, settled=settled, state=state))


class Container:
    """Callbacks a broker implements. Defaults accept everything and do nothing."""

    def sasl_mechanisms(self):
        return ["ANONYMOUS", "PLAIN", "EXTERNAL", "MSSBCBS"]

    def sasl_ok(self, conn, mechanism, initial_response) -> bool:
        return True

    def on_open(self, conn):
        pass

    def on_attach(self, link):
        """return None to accept, or (condition, description) to refuse"""
        return None

    def on_transfer(self, link, delivery):
        """a complete inbound message. return a delivery-state (Described) to settle with, or None."""
        return delivery_state(D_ACCEPTED)

    def on_flow(self, link):
        pass

    def on_disposition(self, link, delivery, state, settled):
        pass

    def on_detach(self, link):
        pass

    def on_session_end(self, session):
        pass

    def on_close(self, conn):
        pass


class Connection:
    """Server side of one AMQP connection. Feed it bytes; collect bytes with take()."""

    SERVER_MAX_FRAME = 65536

    def __init__(self, container: Container, now=None):
        import time as _t
        self.container = container
        self._now = now or _t.time
        self.buf = bytearray()
        self.out = bytearray()
        self.state = "header"        # header -> sasl -> header2 -> open -> closed
        self.sasl_done = False
        self.sasl_authenticated = False
        self.peer = {}
        self.remote_max_frame = 512
        self.remote_idle_ms = 0
        self.last_sent = self._now()
        self.last_recv = self._now()
        self.sessions = {}           # remote channel -> Session
        self.by_local = {}           # local channel -> Session
        self.closed = False
        self.close_after_flush = False
        self.container_id = "vyomi-servicebus"
        self.ctx = {}                # broker scratch (claims, cbs tokens, name...)
        self.on_output = None        # transport hook, invoked whenever bytes were appended

    # ---- public
    def feed(self, data: bytes):
        if self.closed:
            return
        self.last_recv = self._now()
        self.buf += data
        try:
            self._process()
        except (ValueError, struct.error, IndexError, TypeError, KeyError) as e:
            self._fatal("amqp:decode-error", "malformed AMQP input: %s" % e)
        self._notify()

    def take(self) -> bytes:
        b = bytes(self.out)
        self.out.clear()
        return b

    def tick(self):
        """call periodically: keep-alive frames toward a peer that advertised an idle-timeout"""
        if self.closed or self.state != "open":
            return
        if self.remote_idle_ms and (self._now() - self.last_sent) * 1000 >= self.remote_idle_ms / 2:
            self.out += struct.pack(">IBBH", 8, 2, 0, 0)
            self.last_sent = self._now()
            self._notify()

    def kick(self):
        """a broker changed state out-of-band: let the transport flush"""
        self._notify()

    # ---- internals
    def _notify(self):
        if self.out and self.on_output:
            self.on_output()

    def _emit(self, ftype, channel, body):
        if TRACE and body:
            try:
                k, f, _p = parse_perf(body)
                print("AMQP ->", channel, k, {a: b for a, b in f.items() if b is not None and a != "source" and a != "target"}, flush=True)
            except Exception:
                pass
        self.out += frame(ftype, channel, body)
        self.last_sent = self._now()

    def _fatal(self, cond, desc):
        if self.state == "open" or self.sasl_done:
            self._emit(0, 0, make_perf("close", error=error(cond, desc)))
        self.closed = True
        self.close_after_flush = True

    def _process(self):
        while True:
            if self.state == "header":
                if len(self.buf) < 8:
                    return
                hdr = bytes(self.buf[:8])
                del self.buf[:8]
                if hdr == PROTO_SASL:
                    self.out += PROTO_SASL
                    self.state = "sasl"
                    mechs = SymbolArray([Symbol(m) for m in self.container.sasl_mechanisms()])
                    self._emit(1, 0, make_perf("sasl-mechanisms", sasl_server_mechanisms=mechs))
                elif hdr == PROTO_AMQP:
                    self.out += PROTO_AMQP
                    self.state = "open"
                    self.sasl_done = True
                else:
                    # unsupported (TLS-in-protocol, bad version): reply with what we do speak and hang up
                    self.out += PROTO_AMQP
                    self.closed = True
                    self.close_after_flush = True
                    return
                continue
            if self.state == "header2":
                if len(self.buf) < 8:
                    return
                hdr = bytes(self.buf[:8])
                del self.buf[:8]
                if hdr != PROTO_AMQP:
                    self.out += PROTO_AMQP
                    self.closed = True
                    self.close_after_flush = True
                    return
                self.out += PROTO_AMQP
                self.state = "open"
                continue
            # frames
            if len(self.buf) < 4:
                return
            size = struct.unpack_from(">I", self.buf, 0)[0]
            if size < 8 or size > (1 << 24):
                return self._fatal("amqp:connection:framing-error", "bad frame size %d" % size)
            if len(self.buf) < size:
                return
            fr = bytes(self.buf[:size])
            del self.buf[:size]
            doff, ftype, channel = fr[4], fr[5], struct.unpack_from(">H", fr, 6)[0]
            body = fr[doff * 4:]
            if not body:
                continue        # keep-alive
            if ftype == 1:
                self._on_sasl(body)
                if self.closed:
                    return
            else:
                self._on_amqp(channel, body)
                if self.closed and not self.close_after_flush:
                    return

    # ---- SASL
    def _on_sasl(self, body):
        kind, f, _ = parse_perf(body)
        if kind == "sasl-init":
            ok = self.container.sasl_ok(self, str(f["mechanism"]), f.get("initial_response"))
            self._emit(1, 0, make_perf("sasl-outcome", code=UByte(0 if ok else 1)))
            if ok:
                self.sasl_done = True
                self.sasl_authenticated = True
                self.state = "header2"
            else:
                self.closed = True
                self.close_after_flush = True
        elif kind == "sasl-response":
            self._emit(1, 0, make_perf("sasl-outcome", code=UByte(0)))
            self.state = "header2"

    # ---- AMQP
    def _on_amqp(self, channel, body):
        kind, f, pos = parse_perf(body)
        payload = body[pos:]
        if TRACE:
            print("AMQP <-", channel, kind, {k: v for k, v in f.items() if v is not None}, len(payload), flush=True)
        h = getattr(self, "_h_" + kind, None)
        if h is None:
            return
        if kind in ("open", "close"):
            return h(f)
        if kind == "begin":
            return h(channel, f)
        sess = self.sessions.get(channel)
        if sess is None:
            return self._fatal("amqp:session:unattached-handle", "no session on channel %d" % channel)
        return h(sess, f, payload) if kind == "transfer" else h(sess, f)

    def _h_open(self, f):
        self.peer = f
        self.remote_max_frame = int(f.get("max_frame_size") or 65536)
        self.remote_idle_ms = int(f.get("idle_time_out") or 0)
        mine = min(self.remote_max_frame, self.SERVER_MAX_FRAME) if f.get("max_frame_size") else self.SERVER_MAX_FRAME
        self.remote_max_frame = max(min(self.remote_max_frame, 1 << 20), MIN_MAX_FRAME)
        self._emit(0, 0, make_perf("open", container_id=self.container_id, hostname=f.get("hostname"),
                                    max_frame_size=mine, channel_max=UShort(255)))
        self.container.on_open(self)

    def _h_close(self, f):
        if not self.closed or self.close_after_flush:
            self._emit(0, 0, make_perf("close"))
        self.closed = True
        self.close_after_flush = True
        self._teardown_once()

    def _teardown(self):
        for s in list(self.by_local.values()):
            if not s.ended:
                s.ended = True
                for lk in list(s.links.values()):
                    if not lk.closed:
                        lk.closed = True
                        try:
                            self.container.on_detach(lk)
                        except Exception:
                            pass
                self.container.on_session_end(s)
        self.container.on_close(self)

    def connection_lost(self):
        if not self.closed:
            self.closed = True
        else:
            pass
        self._teardown_once()

    def _teardown_once(self):
        if getattr(self, "_torn", False):
            return
        self._torn = True
        self._teardown()

    def _h_begin(self, channel, f):
        local = 0
        while local in self.by_local:
            local += 1
        s = Session(self, local, channel)
        s.remote_incoming_window = int(f.get("incoming_window") or 0)
        s.next_incoming_id = int(f.get("next_outgoing_id") or 0)
        self.sessions[channel] = s
        self.by_local[local] = s
        self._emit(0, local, make_perf("begin", remote_channel=channel, next_outgoing_id=s.next_outgoing_id,
                                        incoming_window=s.incoming_window, outgoing_window=1 << 20,
                                        handle_max=UInt(1023)))

    def _h_end(self, s, f):
        if not s.ended:
            s.ended = True
            for lk in list(s.links.values()):
                if not lk.closed:
                    lk.closed = True
                    try:
                        self.container.on_detach(lk)
                    except Exception:
                        pass
            self.container.on_session_end(s)
            s._emit(make_perf("end"))
        self.sessions.pop(s.remote_channel, None)
        self.by_local.pop(s.channel, None)

    def _h_attach(self, s, f):
        remote_is_sender = not bool(f["role"])      # role=false -> remote is the sender
        lk = Link(s, str(f["name"]), 0, role_sender=not remote_is_sender)   # we are the opposite end
        h = 0
        while h in s.links:
            h += 1
        lk.handle = h
        lk.remote_handle = int(f["handle"])
        lk.source, lk.target = f.get("source"), f.get("target")
        lk.snd_settle_mode = f.get("snd_settle_mode") if f.get("snd_settle_mode") is not None else 2
        lk.rcv_settle_mode = f.get("rcv_settle_mode") or 0
        lk.max_message_size = int(f.get("max_message_size") or 0)
        lk.peer_attach = f
        if not lk.sender:       # the client sends -> we receive; adopt its initial delivery count
            lk.delivery_count = int(f.get("initial_delivery_count") or 0)
        tf = terminus_fields(lk.target) if lk.sender is False else terminus_fields(lk.source)
        lk.address = tf.get("address")
        s.links[h] = lk
        s.by_remote[lk.remote_handle] = lk
        s.by_name[lk.name] = lk
        # coordinator (transactions) are not offered
        if isinstance(lk.target, Described) and _desc_num(lk.target.descriptor) == D_COORDINATOR:
            err = ("amqp:not-implemented", "transactions are not supported by this simulator")
        else:
            err = self.container.on_attach(lk)
        resp = dict(name=lk.name, handle=lk.handle, role=bool(lk.sender is False),   # our role: receiver=true
                    snd_settle_mode=UByte(lk.snd_settle_mode), rcv_settle_mode=UByte(lk.rcv_settle_mode),
                    source=lk.source, target=lk.target,
                    initial_delivery_count=UInt(lk.delivery_count) if lk.sender else None,
                    max_message_size=ULong(lk.max_message_size or 1048576 * 100), properties=getattr(lk, "attach_props", None))
        if err:
            resp["source"] = None
            resp["target"] = None
            s._emit(make_perf("attach", **resp))
            lk.closed = True
            s._emit(make_perf("detach", handle=lk.handle, closed=True, error=error(err[0], err[1])))
            return
        lk.attached = True
        s._emit(make_perf("attach", **resp))
        if not lk.sender:       # we receive: grant initial credit
            lk.credit = 1000
            s._send_flow(lk)

    def _h_flow(self, s, f):
        nid = f.get("next_incoming_id")
        if nid is not None:
            s.remote_incoming_window = (int(nid) + int(f.get("incoming_window") or 0) - s.next_outgoing_id) & 0xFFFFFFFF
            if s.remote_incoming_window > (1 << 31):
                s.remote_incoming_window = 0
        else:
            s.remote_incoming_window = int(f.get("incoming_window") or 0)
        h = f.get("handle")
        if h is None:
            if f.get("echo"):
                s._send_flow()
            for lk in list(s.links.values()):
                if lk.sender and not lk.closed:
                    self.container.on_flow(lk)
            return
        lk = s.by_remote.get(int(h))
        if lk is None or lk.closed:
            return
        if lk.sender:
            dc = int(f.get("delivery_count") or 0)
            lc = int(f.get("link_credit") or 0)
            lk.credit = ((dc + lc) - lk.delivery_count) & 0xFFFFFFFF
            if lk.credit > (1 << 31):
                lk.credit = 0
            lk.drain = bool(f.get("drain"))
            self.container.on_flow(lk)
            if lk.drain and lk.credit > 0 and not lk.closed:
                lk.delivery_count = (lk.delivery_count + lk.credit) & 0xFFFFFFFF
                lk.credit = 0
                s._send_flow(lk)
                lk.drain = False
            elif f.get("echo"):
                s._send_flow(lk)

    def _h_transfer(self, s, f, payload):
        lk = s.by_remote.get(int(f["handle"]))
        if lk is None or lk.closed:
            return self._fatal("amqp:session:unattached-handle", "transfer on unattached handle")
        if lk._partial is None:
            s.next_incoming_id = (s.next_incoming_id + 1) & 0xFFFFFFFF
            lk._partial = Delivery(int(f["delivery_id"]) if f.get("delivery_id") is not None else 0,
                                   bytes(f.get("delivery_tag") or b""), lk)
            lk._partial.settled = bool(f.get("settled"))
            lk._partial.format = int(f.get("message_format") or 0)
            lk._partial.state = f.get("state")
        d = lk._partial
        if f.get("aborted"):
            lk._partial = None
            return
        d.payload += payload
        if f.get("more"):
            return
        lk._partial = None
        lk.delivery_count = (lk.delivery_count + 1) & 0xFFFFFFFF
        lk.credit -= 1
        s._since_flow += 1
        outcome = self.container.on_transfer(lk, d)
        if not d.settled:
            if outcome is not None:
                s._settle_range(d.id, d.id, outcome, True, True)
        # replenish credit / session window
        if lk.credit < 500 and not lk.closed:
            lk.credit = 1000
            s._send_flow(lk)
        elif s._since_flow >= 256:
            s._since_flow = 0
            s._send_flow()

    def _h_disposition(self, s, f):
        first, last = int(f["first"]), int(f.get("last") if f.get("last") is not None else f["first"])
        remote_is_receiver = bool(f.get("role"))
        if not remote_is_receiver:
            return          # remote sender settling something we received: nothing to do
        did = first
        reply = []
        while True:
            lk = s.delivery_to_link.get(did)
            if lk is not None:
                d = lk.unsettled.get(did)
                if d is not None:
                    d.state = f.get("state") or d.state
                    self.container.on_disposition(lk, d, f.get("state"), bool(f.get("settled")))
                    if f.get("settled"):
                        lk.unsettled.pop(did, None)
                        s.delivery_to_link.pop(did, None)
                    else:
                        reply.append(did)     # rcv-settle-mode=second: sender replies settled
            if did == last:
                break
            did = (did + 1) & 0xFFFFFFFF
        for did in reply:
            lk = s.delivery_to_link.pop(did, None)
            if lk is not None:
                lk.unsettled.pop(did, None)
                st = f.get("state")
                if state_kind(st) == D_REJECTED:
                    st = delivery_state(D_REJECTED)     # echo the outcome WITHOUT the error: an error in it reads as "failed to apply"
                s._settle_range(did, did, st, False, True)

    def _h_detach(self, s, f):
        lk = s.by_remote.pop(int(f["handle"]), None)
        if lk is None:
            return
        if not lk.closed:
            lk.closed = True
            try:
                self.container.on_detach(lk)
            except Exception:
                pass
            s._emit(make_perf("detach", handle=lk.handle, closed=True))
        s.links.pop(lk.handle, None)
        s.by_name.pop(lk.name, None)
