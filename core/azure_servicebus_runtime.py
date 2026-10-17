"""Azure Service Bus shared runtime store and topology manager.

Provides a thread-safe singleton store accessor (`get_store()`) and RLock
(`get_lock()`) shared by:
  - Wire ingress / REST router (core/wire_ingress.py, core/aws_wire_router.py)
  - Console data plane (core/console_azure_servicebus.py)
  - AMQP 1.0 listener (core/servicebus_amqp/)

Also provides topology bootstrap for Siftly's 5 topic/subscription pairs.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from core.messaging_store import MessagingStore

_STORE: Any = None
_STORE_LOCK = threading.RLock()

# Siftly's canonical 5 topic/subscription pairs
SIFTLY_TOPICS = [
    "scrapper_responses",
    "partner-scraper-responses",
    "llm-analysis",
    "linkedin-draft",
    "traffic-ingest",
]


def get_lock() -> threading.RLock:
    return _STORE_LOCK


def get_store(backend_path: str | None = None) -> Any:
    """Return the shared PersistentMessagingStore singleton for Azure Service Bus."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            from core.persistent_store import SqliteStateBackend, PersistentMessagingStore
            db_path = backend_path or os.environ.get("VYOMI_AZSB_DB", "/tmp/vyomi-azsb.sqlite")
            backend = SqliteStateBackend(db_path)
            _STORE = PersistentMessagingStore(backend, store_id="azsb")
            bootstrap_siftly_topology(_STORE)
        return _STORE


def reset_store(new_store: Any = None) -> None:
    """Reset the singleton store (used by tests or custom injection)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = new_store


def bootstrap_siftly_topology(store: MessagingStore | None = None) -> None:
    """Ensure Siftly's 5 canonical topic/subscription pairs exist in the store."""
    from core import azure_servicebus_core as sb
    st = store or get_store()
    with _STORE_LOCK:
        for name in SIFTLY_TOPICS:
            # Create topic if missing
            if not st.get_topic(name):
                sb.dispatch(st, "PUT", f"/{name}")
            # Ensure matching subscription exists with 60s lock duration and maxDeliveryCount 10
            t = st.get_topic(name)
            if t and name not in t.get("subscriptions", {}):
                sb.dispatch(st, "PUT", f"/{name}/subscriptions/{name}")
        st.persist()
