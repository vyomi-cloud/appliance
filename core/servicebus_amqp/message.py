"""AMQP 1.0 Message and Section Definitions.

Complies with OASIS AMQP 1.0 Part 3 (Messaging).
Handles encoding/decoding of single messages and batched messages
(Service Bus batch format 0x80013700).
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from .codec import (
    DescribedType,
    Symbol,
    Timestamp,
    Ubyte,
    Uint,
    Ulong,
    decode,
    encode,
)

# Descriptor Constants
DESCRIPTOR_HEADER = Ulong(0x70)
DESCRIPTOR_DELIVERY_ANNOTATIONS = Ulong(0x71)
DESCRIPTOR_MESSAGE_ANNOTATIONS = Ulong(0x72)
DESCRIPTOR_PROPERTIES = Ulong(0x73)
DESCRIPTOR_APPLICATION_PROPERTIES = Ulong(0x74)
DESCRIPTOR_DATA = Ulong(0x75)
DESCRIPTOR_AMQP_SEQUENCE = Ulong(0x76)
DESCRIPTOR_AMQP_VALUE = Ulong(0x77)
DESCRIPTOR_FOOTER = Ulong(0x78)

# Azure Service Bus Batch Message Format
SERVICE_BUS_BATCH_FORMAT = 0x80013700  # 2147563264


def _truncate_trailing_nulls(lst: list[Any]) -> list[Any]:
    while lst and lst[-1] is None:
        lst.pop()
    return lst


class Header:
    """AMQP 1.0 Message Header (descriptor 0x70)."""

    DESCRIPTOR = DESCRIPTOR_HEADER

    def __init__(
        self,
        durable: bool = False,
        priority: int = 4,
        ttl: int | None = None,
        first_acquirer: bool = False,
        delivery_count: int = 0,
    ):
        self.durable = durable
        self.priority = Ubyte(priority)
        self.ttl = Uint(ttl) if ttl is not None else None
        self.first_acquirer = first_acquirer
        self.delivery_count = Uint(delivery_count)

    def to_described_type(self) -> DescribedType:
        fields = [
            self.durable if self.durable else None,
            self.priority if self.priority != 4 else None,
            self.ttl,
            self.first_acquirer if self.first_acquirer else None,
            self.delivery_count if self.delivery_count != 0 else None,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Header:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            durable=bool(f[0]) if len(f) > 0 and f[0] is not None else False,
            priority=f[1] if len(f) > 1 and f[1] is not None else 4,
            ttl=f[2] if len(f) > 2 else None,
            first_acquirer=bool(f[3]) if len(f) > 3 and f[3] is not None else False,
            delivery_count=f[4] if len(f) > 4 and f[4] is not None else 0,
        )


class Properties:
    """AMQP 1.0 Message Properties (descriptor 0x73)."""

    DESCRIPTOR = DESCRIPTOR_PROPERTIES

    def __init__(
        self,
        message_id: Any = None,
        user_id: bytes | None = None,
        to: str | None = None,
        subject: str | None = None,
        reply_to: str | None = None,
        correlation_id: Any = None,
        content_type: str | Symbol | None = None,
        content_encoding: str | Symbol | None = None,
        absolute_expiry_time: int | None = None,
        creation_time: int | None = None,
        group_id: str | None = None,
        group_sequence: int | None = None,
        reply_to_group_id: str | None = None,
    ):
        self.message_id = message_id
        self.user_id = user_id
        self.to = to
        self.subject = subject
        self.reply_to = reply_to
        self.correlation_id = correlation_id
        self.content_type = Symbol(content_type) if isinstance(content_type, str) else content_type
        self.content_encoding = (
            Symbol(content_encoding) if isinstance(content_encoding, str) else content_encoding
        )
        self.absolute_expiry_time = (
            Timestamp(absolute_expiry_time) if absolute_expiry_time is not None else None
        )
        self.creation_time = Timestamp(creation_time) if creation_time is not None else None
        self.group_id = group_id
        self.group_sequence = Uint(group_sequence) if group_sequence is not None else None
        self.reply_to_group_id = reply_to_group_id

    def to_described_type(self) -> DescribedType:
        fields = [
            self.message_id,
            self.user_id,
            self.to,
            self.subject,
            self.reply_to,
            self.correlation_id,
            self.content_type,
            self.content_encoding,
            self.absolute_expiry_time,
            self.creation_time,
            self.group_id,
            self.group_sequence,
            self.reply_to_group_id,
        ]
        return DescribedType(self.DESCRIPTOR, _truncate_trailing_nulls(fields))

    @classmethod
    def from_described_type(cls, dt: DescribedType) -> Properties:
        f = dt.value if isinstance(dt.value, list) else []
        return cls(
            message_id=f[0] if len(f) > 0 else None,
            user_id=f[1] if len(f) > 1 else None,
            to=f[2] if len(f) > 2 else None,
            subject=f[3] if len(f) > 3 else None,
            reply_to=f[4] if len(f) > 4 else None,
            correlation_id=f[5] if len(f) > 5 else None,
            content_type=f[6] if len(f) > 6 else None,
            content_encoding=f[7] if len(f) > 7 else None,
            absolute_expiry_time=f[8] if len(f) > 8 else None,
            creation_time=f[9] if len(f) > 9 else None,
            group_id=f[10] if len(f) > 10 else None,
            group_sequence=f[11] if len(f) > 11 else None,
            reply_to_group_id=f[12] if len(f) > 12 else None,
        )


class Message:
    """Represents a decoded or to-be-encoded AMQP 1.0 Message."""

    def __init__(
        self,
        body: Any = b"",
        properties: Properties | None = None,
        application_properties: dict[str, Any] | None = None,
        message_annotations: dict[Any, Any] | None = None,
        delivery_annotations: dict[Any, Any] | None = None,
        header: Header | None = None,
        footer: dict[Any, Any] | None = None,
        body_type: str = "data",  # "data", "value", or "sequence"
    ):
        self.body = body
        if body_type == "data" and not isinstance(body, (bytes, bytearray)):
            self.body_type = "value"
        else:
            self.body_type = body_type
        self.properties = properties or Properties()
        self.application_properties = application_properties or {}
        self.message_annotations = message_annotations or {}
        self.delivery_annotations = delivery_annotations or {}
        self.header = header
        self.footer = footer or {}

    def encode(self) -> bytes:
        """Serialize this Message into AMQP 1.0 byte sections."""
        out = bytearray()
        if self.header:
            out.extend(encode(self.header.to_described_type()))
        if self.delivery_annotations:
            out.extend(encode(DescribedType(DESCRIPTOR_DELIVERY_ANNOTATIONS, self.delivery_annotations)))
        if self.message_annotations:
            out.extend(encode(DescribedType(DESCRIPTOR_MESSAGE_ANNOTATIONS, self.message_annotations)))
        if self.properties:
            out.extend(encode(self.properties.to_described_type()))
        if self.application_properties:
            out.extend(encode(DescribedType(DESCRIPTOR_APPLICATION_PROPERTIES, self.application_properties)))

        # Body section
        if self.body_type == "data":
            raw_data = self.body if isinstance(self.body, (bytes, bytearray)) else str(self.body).encode("utf-8")
            out.extend(encode(DescribedType(DESCRIPTOR_DATA, bytes(raw_data))))
        elif self.body_type == "sequence":
            out.extend(encode(DescribedType(DESCRIPTOR_AMQP_SEQUENCE, self.body)))
        else:  # value
            out.extend(encode(DescribedType(DESCRIPTOR_AMQP_VALUE, self.body)))

        if self.footer:
            out.extend(encode(DescribedType(DESCRIPTOR_FOOTER, self.footer)))
        return bytes(out)

    @classmethod
    def decode(cls, data: bytes) -> Message:
        """Parse raw AMQP 1.0 message sections into a Message object."""
        offset = 0
        header: Header | None = None
        delivery_annotations: dict[Any, Any] = {}
        message_annotations: dict[Any, Any] = {}
        properties: Properties | None = None
        application_properties: dict[str, Any] = {}
        body: Any = b""
        body_type = "data"
        footer: dict[Any, Any] = {}

        while offset < len(data):
            sec, offset = decode(data, offset)
            if not isinstance(sec, DescribedType):
                continue
            desc = sec.descriptor
            desc_val = int(desc) if isinstance(desc, (int, Ulong)) else None

            if desc_val == int(DESCRIPTOR_HEADER):
                header = Header.from_described_type(sec)
            elif desc_val == int(DESCRIPTOR_DELIVERY_ANNOTATIONS):
                if isinstance(sec.value, dict):
                    delivery_annotations = sec.value
            elif desc_val == int(DESCRIPTOR_MESSAGE_ANNOTATIONS):
                if isinstance(sec.value, dict):
                    message_annotations = sec.value
            elif desc_val == int(DESCRIPTOR_PROPERTIES):
                properties = Properties.from_described_type(sec)
            elif desc_val == int(DESCRIPTOR_APPLICATION_PROPERTIES):
                if isinstance(sec.value, dict):
                    application_properties = sec.value
            elif desc_val == int(DESCRIPTOR_DATA):
                body = sec.value
                body_type = "data"
            elif desc_val == int(DESCRIPTOR_AMQP_VALUE):
                body = sec.value
                body_type = "value"
            elif desc_val == int(DESCRIPTOR_AMQP_SEQUENCE):
                body = sec.value
                body_type = "sequence"
            elif desc_val == int(DESCRIPTOR_FOOTER):
                if isinstance(sec.value, dict):
                    footer = sec.value

        return cls(
            body=body,
            properties=properties,
            application_properties=application_properties,
            message_annotations=message_annotations,
            delivery_annotations=delivery_annotations,
            header=header,
            footer=footer,
            body_type=body_type,
        )

    @classmethod
    def encode_batch(cls, messages: Sequence[Message]) -> bytes:
        """Encode a sequence of messages into a Service Bus batch payload (format 0x80013700)."""
        return b"".join(encode(DescribedType(DESCRIPTOR_DATA, m.encode())) for m in messages)

    @classmethod
    def decode_batch(cls, data: bytes) -> list[Message]:
        """Decode a batch of AMQP messages (format 0x80013700).

        A Service Bus batch transfer payload contains multiple Data sections (0x75),
        each wrapping an individually encoded AMQP message.
        """
        messages: list[Message] = []
        offset = 0
        while offset < len(data):
            sec, offset = decode(data, offset)
            if isinstance(sec, DescribedType):
                desc_val = int(sec.descriptor) if isinstance(sec.descriptor, (int, Ulong)) else None
                if desc_val == int(DESCRIPTOR_DATA) and isinstance(sec.value, (bytes, bytearray)):
                    # Inner message encoded as bytes in the Data payload
                    messages.append(cls.decode(bytes(sec.value)))
                else:
                    # Single message or non-data section
                    messages.append(cls.decode(data))
                    break
            else:
                break
        return messages if messages else [cls.decode(data)]

    def to_store_dict(self) -> dict[str, Any]:
        """Convert this Message into a Service Bus core message dict for storage."""
        # Convert body to text or raw
        if isinstance(self.body, bytes):
            try:
                body_str = self.body.decode("utf-8")
            except UnicodeDecodeError:
                body_str = self.body.hex()
        else:
            body_str = str(self.body)

        msg_id = str(self.properties.message_id) if self.properties and self.properties.message_id else str(uuid.uuid4())
        correlation_id = str(self.properties.correlation_id) if self.properties and self.properties.correlation_id else None
        subject = self.properties.subject if self.properties else None
        reply_to = self.properties.reply_to if self.properties else None
        content_type = str(self.properties.content_type) if self.properties and self.properties.content_type else "application/octet-stream"

        # Application properties
        app_props = dict(self.application_properties)

        return {
            "MessageId": msg_id,
            "CorrelationId": correlation_id,
            "Subject": subject,
            "ReplyTo": reply_to,
            "ContentType": content_type,
            "body": body_str,
            "application_properties": app_props,
            "message_annotations": dict(self.message_annotations),
        }
