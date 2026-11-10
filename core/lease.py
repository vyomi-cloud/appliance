"""Universal messaging lease state machine (AWS SQS, Azure Service Bus, GCP Pub/Sub).

Pure Python, substrate-free, runs under Pyodide and host CPython.
Canonical message fields:
    visible_at: float (timestamp when message becomes available again)
    delivery_count: int (number of times leased, starting at 1 on first delivery)
    lease_token: str | None (active lock / receipt handle / ack id)
    deleted: bool (settled / completed / acknowledged)
"""
from __future__ import annotations

import uuid
from typing import Any


class LeaseLost(Exception):
    """Raised when attempting to settle, extend, or release an expired or invalid lease."""
    pass


def normalize(msg: dict[str, Any]) -> dict[str, Any]:
    """Upgrade legacy field names in place and ensure canonical lease fields exist."""
    # delivery_count
    if "delivery_count" not in msg:
        if "receive_count" in msg:
            msg["delivery_count"] = int(msg.pop("receive_count") or 0)
        elif "deliveryAttempt" in msg:
            msg["delivery_count"] = int(msg.pop("deliveryAttempt") or 0)
        else:
            msg["delivery_count"] = 0

    # lease_token
    if "lease_token" not in msg:
        if "receipt_handle" in msg and msg["receipt_handle"]:
            msg["lease_token"] = msg.pop("receipt_handle")
        elif "_locked" in msg and msg["_locked"]:
            msg["lease_token"] = msg.pop("_locked")
        elif msg.get("ack_id"):
            msg["lease_token"] = msg.pop("ack_id")
        else:
            msg["lease_token"] = None

    # visible_at
    if "visible_at" not in msg:
        msg["visible_at"] = 0.0
    else:
        try:
            msg["visible_at"] = float(msg["visible_at"])
        except (ValueError, TypeError):
            msg["visible_at"] = 0.0

    # deleted
    if "deleted" not in msg:
        msg["deleted"] = False
    else:
        msg["deleted"] = bool(msg["deleted"])

    return msg


def available(msg: dict[str, Any], now: float) -> bool:
    """Returns True if the message is not deleted and its lease has elapsed (or was never leased)."""
    normalize(msg)
    return not msg.get("deleted", False) and float(msg.get("visible_at", 0.0)) <= now


def lease(msg: dict[str, Any], now: float, duration: float, token: str | None = None) -> str:
    """Lease the message: sets visible_at = now + duration, increments delivery_count, returns token."""
    normalize(msg)
    tok = token or ("rhdl-" + uuid.uuid4().hex)
    msg["lease_token"] = tok
    msg["visible_at"] = now + max(0.0, float(duration))
    msg["delivery_count"] = int(msg.get("delivery_count", 0)) + 1
    return tok


def extend(msg: dict[str, Any], token: str, now: float, duration: float, strict: bool = True) -> float:
    """Extend the lease. If strict=True, raises LeaseLost if token != current or lease expired."""
    normalize(msg)
    if msg.get("deleted", False):
        raise LeaseLost("Message has already been settled / deleted.")
    if msg.get("lease_token") != token:
        raise LeaseLost(f"Lease token mismatch: expected {msg.get('lease_token')}, got {token}")
    if strict and float(msg.get("visible_at", 0.0)) <= now:
        raise LeaseLost("Lease has already expired.")

    new_vis = now + max(0.0, float(duration))
    msg["visible_at"] = new_vis
    return new_vis


def release(msg: dict[str, Any], token: str, now: float, strict: bool = True) -> None:
    """Release the lease (abandon / nack / visibility 0): resets visible_at = now, clears lease_token."""
    normalize(msg)
    if msg.get("deleted", False):
        raise LeaseLost("Message has already been settled / deleted.")
    if msg.get("lease_token") != token:
        raise LeaseLost(f"Lease token mismatch: expected {msg.get('lease_token')}, got {token}")
    if strict and float(msg.get("visible_at", 0.0)) <= now:
        raise LeaseLost("Lease has already expired.")

    msg["visible_at"] = now
    msg["lease_token"] = None


def settle(msg: dict[str, Any], token: str | None, now: float, strict: bool = True) -> None:
    """Settle the message (complete / delete / ack): marks deleted = True, clears lease_token."""
    normalize(msg)
    if msg.get("deleted", False):
        raise LeaseLost("Message has already been settled / deleted.")
    if token is not None and msg.get("lease_token") != token:
        raise LeaseLost(f"Lease token mismatch: expected {msg.get('lease_token')}, got {token}")
    if token is None and msg.get("lease_token") is not None and strict:
        raise LeaseLost("Cannot strictly settle a leased message without the lease token.")
    if strict and float(msg.get("visible_at", 0.0)) <= now:
        raise LeaseLost("Lease has already expired.")

    msg["deleted"] = True
    msg["lease_token"] = None


def dead_letter(msg: dict[str, Any], token: str, now: float, strict: bool = True,
                reason: str | None = None, description: str | None = None) -> None:
    """Explicitly dead-letter the message under lease, recording reason and description."""
    settle(msg, token, now, strict=strict)
    if reason:
        msg["DeadLetterReason"] = reason
    if description:
        msg["DeadLetterErrorDescription"] = description


def take_dead(messages: list[dict[str, Any]], now: float, max_deliveries: int) -> list[dict[str, Any]]:
    """Removes and returns available messages whose delivery_count >= max_deliveries."""
    if max_deliveries <= 0:
        return []
    survivors: list[dict[str, Any]] = []
    dead: list[dict[str, Any]] = []
    for m in messages:
        normalize(m)
        if m.get("deleted", False):
            continue
        if available(m, now) and int(m.get("delivery_count", 0)) >= max_deliveries:
            dead.append(m)
        else:
            survivors.append(m)
    messages[:] = survivors
    return dead


def next_wakeup(messages: list[dict[str, Any]], now: float) -> float | None:
    """Earliest future visible_at among active (unsettled, unexpired) leased messages."""
    earliest: float | None = None
    for m in messages:
        normalize(m)
        if m.get("deleted", False):
            continue
        vis = float(m.get("visible_at", 0.0))
        if vis > now:
            if earliest is None or vis < earliest:
                earliest = vis
    return earliest
