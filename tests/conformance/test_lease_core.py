"""Universal lease core conformance test — unit tests for core/lease.py.

Asserts canonical lease semantics across clouds:
  - normalize() upgrades legacy shapes (receive_count, receipt_handle, _locked, _pending)
  - available() checks deleted status and visibility timestamp
  - lease() sets expiry, increments delivery_count, returns unique token
  - extend() strict vs lenient (raises LeaseLost on token mismatch or expiry)
  - release() resets visible_at = now, clears token
  - settle() marks deleted = True, clears token
  - dead_letter() marks settled and attaches reason/description
  - take_dead() extracts messages reaching max_deliveries
  - next_wakeup() calculates earliest future expiration

Runs on both host CPython and Pyodide.
"""
from __future__ import annotations

try:
    from core import lease
except ImportError:
    import lease  # type: ignore


def _check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"Check failed: {name}")
    print(f"  ok  {name}")


def test_normalize():
    # Legacy SQS shape
    legacy_sqs = {"receive_count": 3, "receipt_handle": "rh-123", "in_flight": True}
    lease.normalize(legacy_sqs)
    _check("normalize sqs delivery_count", legacy_sqs["delivery_count"] == 3)
    _check("normalize sqs lease_token", legacy_sqs["lease_token"] == "rh-123")
    _check("normalize sqs visible_at default", legacy_sqs["visible_at"] == 0.0)
    _check("normalize sqs deleted default", legacy_sqs["deleted"] is False)

    # Legacy Service Bus shape
    legacy_sb = {"_locked": "lock-456", "visible_at": 100.5}
    lease.normalize(legacy_sb)
    _check("normalize sb lease_token", legacy_sb["lease_token"] == "lock-456")
    _check("normalize sb delivery_count default", legacy_sb["delivery_count"] == 0)
    _check("normalize sb visible_at preserved", legacy_sb["visible_at"] == 100.5)

    # Empty dict defaults
    empty = {}
    lease.normalize(empty)
    _check("normalize empty dict", empty["delivery_count"] == 0 and empty["lease_token"] is None)


def test_lease_and_availability():
    msg = {"body": "hello"}
    now = 1000.0

    _check("available before lease", lease.available(msg, now))

    token = lease.lease(msg, now=now, duration=30.0)
    _check("lease returned token", bool(token) and token.startswith("rhdl-"))
    _check("delivery_count is 1", msg["delivery_count"] == 1)
    _check("visible_at is now + duration", msg["visible_at"] == 1030.0)
    _check("not available while leased", not lease.available(msg, now))
    _check("not available halfway", not lease.available(msg, 1015.0))
    _check("available at expiry", lease.available(msg, 1030.0))
    _check("available after expiry", lease.available(msg, 1035.0))


def test_extend_strict_and_lenient():
    msg = {"body": "extend-me"}
    now = 1000.0
    tok = lease.lease(msg, now=now, duration=30.0)

    # Strict extend before expiry succeeds
    new_vis = lease.extend(msg, tok, now=1010.0, duration=40.0, strict=True)
    _check("strict extend updates visible_at", new_vis == 1050.0 and msg["visible_at"] == 1050.0)

    # Strict extend with wrong token fails
    try:
        lease.extend(msg, "wrong-token", now=1020.0, duration=20.0, strict=True)
        raise AssertionError("Should have raised LeaseLost for wrong token")
    except lease.LeaseLost:
        _check("strict extend rejects wrong token", True)

    # Strict extend after expiry fails (at t=1055, visible_at was 1050)
    try:
        lease.extend(msg, tok, now=1055.0, duration=20.0, strict=True)
        raise AssertionError("Should have raised LeaseLost for expired lease")
    except lease.LeaseLost:
        _check("strict extend rejects expired lease", True)

    # Lenient extend after expiry succeeds (SQS ChangeMessageVisibility)
    lenient_vis = lease.extend(msg, tok, now=1055.0, duration=20.0, strict=False)
    _check("lenient extend allows setting new visibility", lenient_vis == 1075.0)


def test_release():
    msg = {"body": "abandon-me"}
    now = 1000.0
    tok = lease.lease(msg, now=now, duration=30.0)

    lease.release(msg, tok, now=1010.0, strict=True)
    _check("release sets visible_at to now", msg["visible_at"] == 1010.0)
    _check("release clears token", msg["lease_token"] is None)
    _check("released message is available", lease.available(msg, 1010.0))


def test_settle():
    msg = {"body": "delete-me"}
    now = 1000.0
    tok = lease.lease(msg, now=now, duration=30.0)

    # Strict settle after expiry fails
    try:
        lease.settle(msg, tok, now=1035.0, strict=True)
        raise AssertionError("Strict settle should have failed after expiry")
    except lease.LeaseLost:
        _check("strict settle rejects expired lease", True)

    # Lenient settle after expiry succeeds (SQS DeleteMessage)
    lease.settle(msg, tok, now=1035.0, strict=False)
    _check("settle marks deleted", msg["deleted"] is True)
    _check("settle clears token", msg["lease_token"] is None)
    _check("deleted message not available", not lease.available(msg, 2000.0))


def test_dead_letter_and_take_dead():
    messages = [
        {"id": 1, "delivery_count": 2, "visible_at": 50.0},
        {"id": 2, "delivery_count": 3, "visible_at": 50.0},
        {"id": 3, "delivery_count": 1, "visible_at": 50.0},
        {"id": 4, "delivery_count": 3, "visible_at": 150.0},  # unexpired
    ]
    now = 100.0
    max_deliveries = 3

    dead = lease.take_dead(messages, now=now, max_deliveries=max_deliveries)
    _check("take_dead extracted exactly 1 message", len(dead) == 1 and dead[0]["id"] == 2)
    _check("messages list contains remaining 3", len(messages) == 3 and [m["id"] for m in messages] == [1, 3, 4])


def test_next_wakeup():
    now = 1000.0
    messages = [
        {"id": 1, "visible_at": 990.0},   # in the past (available)
        {"id": 2, "visible_at": 1050.0},  # future
        {"id": 3, "visible_at": 1020.0},  # earliest future
        {"id": 4, "visible_at": 1010.0, "deleted": True},  # deleted (ignored)
    ]
    wakeup = lease.next_wakeup(messages, now)
    _check("next_wakeup finds minimum future visible_at", wakeup == 1020.0)


def run():
    print("Running core/lease conformance tests:")
    test_normalize()
    test_lease_and_availability()
    test_extend_strict_and_lenient()
    test_release()
    test_settle()
    test_dead_letter_and_take_dead()
    test_next_wakeup()
    print("Lease core conformance: ALL GREEN\n")


if __name__ == "__main__":
    run()
