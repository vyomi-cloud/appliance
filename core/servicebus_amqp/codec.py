"""Pure-Python AMQP 1.0 Codec and Framing.

Complies with OASIS AMQP 1.0 Part 1 (Types) and Part 2 (Transport).
Zero external dependencies; completely self-contained.
"""

from __future__ import annotations

import struct
import uuid
from typing import Any, Sequence, Union


# Protocol Headers
AMQP_HEADER = b"AMQP\x00\x01\x00\x00"
SASL_HEADER = b"AMQP\x03\x01\x00\x00"

# Frame Types
FRAME_TYPE_AMQP = 0x00
FRAME_TYPE_SASL = 0x01

# Primitive Type Format Codes
FORMAT_DESCRIBED = 0x00

FORMAT_NULL = 0x40
FORMAT_BOOLEAN_TRUE = 0x41
FORMAT_BOOLEAN_FALSE = 0x42
FORMAT_UINT0 = 0x43
FORMAT_ULONG0 = 0x44
FORMAT_LIST0 = 0x45

FORMAT_UBYTE = 0x50
FORMAT_BYTE = 0x51
FORMAT_SMALLUINT = 0x52
FORMAT_SMALLINT = 0x54
FORMAT_SMALLULONG = 0x53
FORMAT_SMALLLONG = 0x55
FORMAT_BOOLEAN = 0x56

FORMAT_USHORT = 0x60
FORMAT_SHORT = 0x61

FORMAT_UINT = 0x70
FORMAT_INT = 0x71
FORMAT_FLOAT = 0x72

FORMAT_ULONG = 0x80
FORMAT_LONG = 0x81
FORMAT_DOUBLE = 0x82
FORMAT_TIMESTAMP = 0x83

FORMAT_UUID = 0x98

FORMAT_VBIN8 = 0xA0
FORMAT_STR8_UTF8 = 0xA1
FORMAT_SYM8 = 0xA3

FORMAT_VBIN32 = 0xB0
FORMAT_STR32_UTF8 = 0xB1
FORMAT_SYM32 = 0xB3

FORMAT_LIST8 = 0xC0
FORMAT_MAP8 = 0xC1

FORMAT_LIST32 = 0xD0
FORMAT_MAP32 = 0xD1

FORMAT_ARRAY8 = 0xE0
FORMAT_ARRAY32 = 0xF0


class Symbol(str):
    """AMQP 1.0 Symbol type (ASCII identifier)."""
    pass


class Ulong(int):
    """AMQP 1.0 Unsigned 64-bit integer."""
    pass


class Uint(int):
    """AMQP 1.0 Unsigned 32-bit integer."""
    pass


class Ushort(int):
    """AMQP 1.0 Unsigned 16-bit integer."""
    pass


class Ubyte(int):
    """AMQP 1.0 Unsigned 8-bit integer."""
    pass


class Timestamp(int):
    """AMQP 1.0 Timestamp (milliseconds since Unix epoch)."""
    pass


class DescribedType:
    """AMQP 1.0 Described Type (0x00 <descriptor> <value>)."""

    def __init__(self, descriptor: Any, value: Any):
        self.descriptor = descriptor
        self.value = value

    def __repr__(self) -> str:
        return f"DescribedType(descriptor={self.descriptor!r}, value={self.value!r})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, DescribedType):
            return self.descriptor == other.descriptor and self.value == other.value
        return False


def encode(val: Any) -> bytes:
    """Encode a Python value into AMQP 1.0 binary format."""
    if val is None:
        return bytes([FORMAT_NULL])

    if isinstance(val, bool):
        return bytes([FORMAT_BOOLEAN_TRUE if val else FORMAT_BOOLEAN_FALSE])

    if hasattr(val, "to_described_type"):
        return encode(val.to_described_type())

    if isinstance(val, DescribedType):
        return bytes([FORMAT_DESCRIBED]) + encode(val.descriptor) + encode(val.value)

    if isinstance(val, Symbol):
        raw = val.encode("ascii")
        if len(raw) <= 255:
            return bytes([FORMAT_SYM8, len(raw)]) + raw
        return bytes([FORMAT_SYM32]) + struct.pack(">I", len(raw)) + raw

    if isinstance(val, str):
        raw = val.encode("utf-8")
        if len(raw) <= 255:
            return bytes([FORMAT_STR8_UTF8, len(raw)]) + raw
        return bytes([FORMAT_STR32_UTF8]) + struct.pack(">I", len(raw)) + raw

    if isinstance(val, (bytes, bytearray)):
        raw = bytes(val)
        if len(raw) <= 255:
            return bytes([FORMAT_VBIN8, len(raw)]) + raw
        return bytes([FORMAT_VBIN32]) + struct.pack(">I", len(raw)) + raw

    if isinstance(val, uuid.UUID):
        return bytes([FORMAT_UUID]) + val.bytes

    if isinstance(val, Timestamp):
        return bytes([FORMAT_TIMESTAMP]) + struct.pack(">q", int(val))

    if isinstance(val, Ubyte):
        return bytes([FORMAT_UBYTE, int(val) & 0xFF])

    if isinstance(val, Ushort):
        return bytes([FORMAT_USHORT]) + struct.pack(">H", int(val) & 0xFFFF)

    if isinstance(val, Uint):
        v = int(val)
        if v == 0:
            return bytes([FORMAT_UINT0])
        if 0 <= v <= 255:
            return bytes([FORMAT_SMALLUINT, v])
        return bytes([FORMAT_UINT]) + struct.pack(">I", v & 0xFFFFFFFF)

    if isinstance(val, Ulong):
        v = int(val)
        if v == 0:
            return bytes([FORMAT_ULONG0])
        if 0 <= v <= 255:
            return bytes([FORMAT_SMALLULONG, v])
        return bytes([FORMAT_ULONG]) + struct.pack(">Q", v)

    if isinstance(val, int):
        # Default integer encoding: compact where possible
        if val == 0:
            return bytes([FORMAT_UINT0])
        if 0 <= val <= 255:
            return bytes([FORMAT_SMALLUINT, val])
        if -128 <= val <= 127:
            return bytes([FORMAT_SMALLINT, val & 0xFF])
        if 0 <= val <= 0xFFFFFFFF:
            return bytes([FORMAT_UINT]) + struct.pack(">I", val)
        if -0x80000000 <= val <= 0x7FFFFFFF:
            return bytes([FORMAT_INT]) + struct.pack(">i", val)
        if 0 <= val <= 0xFFFFFFFFFFFFFFFF:
            return bytes([FORMAT_ULONG]) + struct.pack(">Q", val)
        return bytes([FORMAT_LONG]) + struct.pack(">q", val)

    if isinstance(val, float):
        return bytes([FORMAT_DOUBLE]) + struct.pack(">d", val)

    if isinstance(val, (list, tuple)):
        if len(val) == 0:
            return bytes([FORMAT_LIST0])
        items_buf = b"".join(encode(item) for item in val)
        count = len(val)
        size = 1 + len(items_buf)  # 1 byte for count + payload
        if size <= 255 and count <= 255:
            return bytes([FORMAT_LIST8, size, count]) + items_buf
        size = 4 + len(items_buf)  # 4 bytes for count + payload
        return bytes([FORMAT_LIST32]) + struct.pack(">II", size, count) + items_buf

    if isinstance(val, dict):
        if len(val) == 0:
            return bytes([FORMAT_MAP8, 1, 0])
        items_buf = b"".join(encode(k) + encode(v) for k, v in val.items())
        count = len(val) * 2  # Total number of key and value items
        size = 1 + len(items_buf)
        if size <= 255 and count <= 255:
            return bytes([FORMAT_MAP8, size, count]) + items_buf
        size = 4 + len(items_buf)
        return bytes([FORMAT_MAP32]) + struct.pack(">II", size, count) + items_buf

    raise ValueError(f"Cannot encode unsupported AMQP type: {type(val)} ({val!r})")


def decode(data: bytes, offset: int = 0) -> tuple[Any, int]:
    """Decode an AMQP 1.0 binary value from data at the given offset.

    Returns:
        (decoded_value, new_offset)
    """
    if offset >= len(data):
        raise ValueError(f"Unexpected end of data at offset {offset}")

    code = data[offset]
    offset += 1

    if code == FORMAT_DESCRIBED:
        descriptor, offset = decode(data, offset)
        value, offset = decode(data, offset)
        return DescribedType(descriptor, value), offset

    if code == FORMAT_NULL:
        return None, offset

    if code == FORMAT_BOOLEAN_TRUE:
        return True, offset

    if code == FORMAT_BOOLEAN_FALSE:
        return False, offset

    if code == FORMAT_BOOLEAN:
        val = data[offset] != 0
        return val, offset + 1

    if code == FORMAT_UINT0:
        return Uint(0), offset

    if code == FORMAT_ULONG0:
        return Ulong(0), offset

    if code == FORMAT_LIST0:
        return [], offset

    if code == FORMAT_UBYTE:
        return Ubyte(data[offset]), offset + 1

    if code == FORMAT_BYTE:
        val = struct.unpack_from(">b", data, offset)[0]
        return val, offset + 1

    if code == FORMAT_SMALLUINT:
        return Uint(data[offset]), offset + 1

    if code == FORMAT_SMALLINT:
        val = struct.unpack_from(">b", data, offset)[0]
        return val, offset + 1

    if code == FORMAT_SMALLULONG:
        return Ulong(data[offset]), offset + 1

    if code == FORMAT_SMALLLONG:
        val = struct.unpack_from(">b", data, offset)[0]
        return val, offset + 1

    if code == FORMAT_USHORT:
        val = struct.unpack_from(">H", data, offset)[0]
        return Ushort(val), offset + 2

    if code == FORMAT_SHORT:
        val = struct.unpack_from(">h", data, offset)[0]
        return val, offset + 2

    if code == FORMAT_UINT:
        val = struct.unpack_from(">I", data, offset)[0]
        return Uint(val), offset + 4

    if code == FORMAT_INT:
        val = struct.unpack_from(">i", data, offset)[0]
        return val, offset + 4

    if code == FORMAT_ULONG:
        val = struct.unpack_from(">Q", data, offset)[0]
        return Ulong(val), offset + 8

    if code == FORMAT_LONG:
        val = struct.unpack_from(">q", data, offset)[0]
        return val, offset + 8

    if code == FORMAT_FLOAT:
        val = struct.unpack_from(">f", data, offset)[0]
        return val, offset + 4

    if code == FORMAT_DOUBLE:
        val = struct.unpack_from(">d", data, offset)[0]
        return val, offset + 8

    if code == FORMAT_TIMESTAMP:
        val = struct.unpack_from(">q", data, offset)[0]
        return Timestamp(val), offset + 8

    if code == FORMAT_UUID:
        val = uuid.UUID(bytes=data[offset : offset + 16])
        return val, offset + 16

    if code == FORMAT_VBIN8:
        length = data[offset]
        offset += 1
        return data[offset : offset + length], offset + length

    if code == FORMAT_VBIN32:
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        return data[offset : offset + length], offset + length

    if code == FORMAT_STR8_UTF8:
        length = data[offset]
        offset += 1
        return data[offset : offset + length].decode("utf-8"), offset + length

    if code == FORMAT_STR32_UTF8:
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        return data[offset : offset + length].decode("utf-8"), offset + length

    if code == FORMAT_SYM8:
        length = data[offset]
        offset += 1
        return Symbol(data[offset : offset + length].decode("ascii")), offset + length

    if code == FORMAT_SYM32:
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        return Symbol(data[offset : offset + length].decode("ascii")), offset + length

    if code == FORMAT_LIST8:
        size = data[offset]
        count = data[offset + 1]
        offset += 2
        items = []
        for _ in range(count):
            item, offset = decode(data, offset)
            items.append(item)
        return items, offset

    if code == FORMAT_LIST32:
        size, count = struct.unpack_from(">II", data, offset)
        offset += 8
        items = []
        for _ in range(count):
            item, offset = decode(data, offset)
            items.append(item)
        return items, offset

    if code == FORMAT_MAP8:
        size = data[offset]
        count = data[offset + 1]
        offset += 2
        mapping = {}
        for _ in range(count // 2):
            k, offset = decode(data, offset)
            v, offset = decode(data, offset)
            mapping[k] = v
        return mapping, offset

    if code == FORMAT_MAP32:
        size, count = struct.unpack_from(">II", data, offset)
        offset += 8
        mapping = {}
        for _ in range(count // 2):
            k, offset = decode(data, offset)
            v, offset = decode(data, offset)
            mapping[k] = v
        return mapping, offset

    if code == FORMAT_ARRAY8:
        size = data[offset]
        count = data[offset + 1]
        offset += 2
        if count == 0:
            return [], offset
        return _decode_array_elements(data, offset, count)

    if code == FORMAT_ARRAY32:
        size, count = struct.unpack_from(">II", data, offset)
        offset += 8
        if count == 0:
            return [], offset
        return _decode_array_elements(data, offset, count)

    raise ValueError(f"Unknown AMQP format code 0x{code:02x} at offset {offset - 1}")


def _decode_array_elements(data: bytes, offset: int, count: int) -> tuple[list, int]:
    """Decode `count` AMQP array elements sharing one constructor at `offset`.

    Per the AMQP 1.0 array encoding, the constructor (format code, or
    0x00 + descriptor + format code for a described type) appears ONCE
    before the elements, not once per element.
    """
    elem_code = data[offset]
    offset += 1
    descriptor = None
    if elem_code == FORMAT_DESCRIBED:
        descriptor, offset = decode(data, offset)
        elem_code = data[offset]
        offset += 1

    items = []
    for _ in range(count):
        item, offset = _decode_raw_primitive(elem_code, data, offset)
        if descriptor is not None:
            item = DescribedType(descriptor, item)
        items.append(item)
    return items, offset


def _decode_raw_primitive(code: int, data: bytes, offset: int) -> tuple[Any, int]:
    """Helper to decode array elements that omit constructor tags."""
    if code == FORMAT_NULL:
        return None, offset
    if code == FORMAT_BOOLEAN_TRUE:
        return True, offset
    if code == FORMAT_BOOLEAN_FALSE:
        return False, offset
    if code == FORMAT_BOOLEAN:
        return data[offset] != 0, offset + 1
    if code == FORMAT_UBYTE:
        return Ubyte(data[offset]), offset + 1
    if code == FORMAT_BYTE:
        return struct.unpack_from(">b", data, offset)[0], offset + 1
    if code == FORMAT_SMALLUINT:
        return Uint(data[offset]), offset + 1
    if code == FORMAT_SMALLINT:
        return struct.unpack_from(">b", data, offset)[0], offset + 1
    if code == FORMAT_SMALLULONG:
        return Ulong(data[offset]), offset + 1
    if code == FORMAT_SMALLLONG:
        return struct.unpack_from(">b", data, offset)[0], offset + 1
    if code == FORMAT_USHORT:
        return Ushort(struct.unpack_from(">H", data, offset)[0]), offset + 2
    if code == FORMAT_SHORT:
        return struct.unpack_from(">h", data, offset)[0], offset + 2
    if code == FORMAT_UINT:
        return Uint(struct.unpack_from(">I", data, offset)[0]), offset + 4
    if code == FORMAT_INT:
        return struct.unpack_from(">i", data, offset)[0], offset + 4
    if code == FORMAT_ULONG:
        return Ulong(struct.unpack_from(">Q", data, offset)[0]), offset + 8
    if code == FORMAT_LONG:
        return struct.unpack_from(">q", data, offset)[0], offset + 8
    if code == FORMAT_FLOAT:
        return struct.unpack_from(">f", data, offset)[0], offset + 4
    if code == FORMAT_DOUBLE:
        return struct.unpack_from(">d", data, offset)[0], offset + 8
    if code == FORMAT_SYM8:
        length = data[offset]
        offset += 1
        return Symbol(data[offset : offset + length].decode("ascii")), offset + length
    if code == FORMAT_STR8_UTF8:
        length = data[offset]
        offset += 1
        return data[offset : offset + length].decode("utf-8"), offset + length
    # Fallback to general decode if needed
    fake = bytes([code]) + data[offset:]
    val, new_offset = decode(fake, 0)
    return val, offset + (new_offset - 1)


# --- Framing ---

EMPTY_FRAME = struct.pack(">IBBH", 8, 2, FRAME_TYPE_AMQP, 0)


def encode_frame(
    frame_type: int,
    channel: int,
    performative: DescribedType | None,
    payload: bytes = b"",
) -> bytes:
    """Encode an AMQP or SASL frame."""
    if performative is None:
        # Empty frame / heartbeat
        return struct.pack(">IBBH", 8, 2, frame_type, channel)

    body = encode(performative) + payload
    doff = 2  # 2 * 4 = 8 bytes data offset
    size = 8 + len(body)
    header = struct.pack(">IBBH", size, doff, frame_type, channel)
    return header + body


class FrameError(ValueError):
    """Raised when a frame header declares an invalid size/data-offset."""
    pass


def decode_frame(
    buf: bytes,
) -> tuple[int, int, int, int, Any, bytes, bytes] | None:
    """Decode a single AMQP or SASL frame from the buffer.

    Returns:
        (size, doff, frame_type, channel, performative, payload, remaining_buf)
        or None if buffer has fewer bytes than the complete frame.

    Raises:
        FrameError: the frame header declares a size/doff that can't
            describe a valid frame (size < 8, or doff*4 > size).
    """
    if len(buf) < 8:
        return None

    size, doff, frame_type, channel = struct.unpack_from(">IBBH", buf, 0)
    if size < 8:
        raise FrameError(f"Frame declares size={size}, which is smaller than the minimum 8-byte header")

    offset = doff * 4
    if offset > size:
        raise FrameError(f"Frame data offset {offset} exceeds declared frame size {size}")

    if len(buf) < size:
        return None

    if size == 8:
        # Empty heartbeat frame
        return (size, doff, frame_type, channel, None, b"", buf[size:])

    body_bytes = buf[offset:size]
    performative, consumed = decode(body_bytes, 0)
    payload = body_bytes[consumed:]
    return (size, doff, frame_type, channel, performative, payload, buf[size:])
