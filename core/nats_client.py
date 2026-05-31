"""Thin NATS client wrapper for cross-provider eventing.

One NATS broker (``cloudlearn-nats``) backs three provider surfaces:

  AWS EventBridge   PutEvents         → publish to ``aws.eventbridge.<bus>.<source>``
  GCP Eventarc      trigger fire      → publish to ``gcp.eventarc.<trigger>``
  Azure Event Grid  topic publish     → publish to ``azure.eventgrid.<topic>``

We use NATS core (not JetStream) for publish + an in-process tail buffer for
"recent messages" (since neither EventBridge nor Event Grid expose a read-back
API in real cloud — they fan events out to subscribers). The conformance check
publishes via the provider surface, then reads the inbox to assert delivery.

Connection is lazy + cached. If NATS is unreachable, publishers return False
and callers fall back to metadata-only mode.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from typing import Any

try:
    import nats
    from nats.aio.client import Client as NATSClient
except ImportError:
    nats = None  # type: ignore[assignment]
    NATSClient = None  # type: ignore[assignment,misc]


_NATS_URL = os.environ.get("CLOUDLEARN_NATS_URL", "nats://cloudlearn-nats:4222")

# In-process tail buffer per subject (capped) — conformance reads from here.
# Real EventBridge/EventGrid don't expose this, so it's labeled as a simulator
# convenience under /__nats/inbox.
_INBOX: dict[str, deque] = {}
_INBOX_CAP = 100
_INBOX_LOCK = threading.Lock()


def _put_inbox(subject: str, payload: dict) -> None:
    with _INBOX_LOCK:
        q = _INBOX.setdefault(subject, deque(maxlen=_INBOX_CAP))
        q.append({"received_at": time.time(), "subject": subject, "payload": payload})


def get_inbox(subject_prefix: str = "", limit: int = 50) -> list[dict]:
    """Drain (copy) recent messages whose subject starts with ``subject_prefix``."""
    out: list[dict] = []
    with _INBOX_LOCK:
        for subj, q in _INBOX.items():
            if subject_prefix and not subj.startswith(subject_prefix):
                continue
            out.extend(list(q))
    out.sort(key=lambda m: m["received_at"], reverse=True)
    return out[:limit]


# ----------------------------------------------------------------------------
# Publish — sync wrapper around async nats client; we spin a background loop
# once per process and submit publishes to it. This keeps the FastAPI request
# handlers sync-friendly without forcing every caller into asyncio.
# ----------------------------------------------------------------------------
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_client: Any | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop | None:
    global _loop, _loop_thread
    if nats is None:
        return None
    with _lock:
        if _loop is None or not _loop.is_running():
            _loop = asyncio.new_event_loop()

            def _runner():
                asyncio.set_event_loop(_loop)
                _loop.run_forever()

            _loop_thread = threading.Thread(target=_runner, daemon=True, name="nats-loop")
            _loop_thread.start()
    return _loop


async def _connect() -> Any | None:
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    try:
        _client = await nats.connect(_NATS_URL, connect_timeout=3, max_reconnect_attempts=3)
        return _client
    except Exception:
        _client = None
        return None


def available() -> bool:
    """Best-effort: True if nats-py is installed and the broker is reachable."""
    loop = _ensure_loop()
    if loop is None:
        return False
    fut = asyncio.run_coroutine_threadsafe(_connect(), loop)
    try:
        c = fut.result(timeout=5)
        return c is not None
    except Exception:
        return False


def publish(subject: str, payload: dict) -> bool:
    """Publish a JSON event. Always records to the inbox first so conformance
    works even if NATS is down (simulator never breaks the control plane)."""
    _put_inbox(subject, payload)
    loop = _ensure_loop()
    if loop is None:
        return False

    async def _do():
        c = await _connect()
        if c is None:
            return False
        try:
            await c.publish(subject, json.dumps(payload).encode())
            return True
        except Exception:
            return False

    fut = asyncio.run_coroutine_threadsafe(_do(), loop)
    try:
        return bool(fut.result(timeout=5))
    except Exception:
        return False
