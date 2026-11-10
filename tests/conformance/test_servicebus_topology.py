"""Service Bus runtime store and Siftly topology test.

Validates Task A5:
  - bootstrap_siftly_topology creates Siftly's 5 topic/subscription pairs
  - get_store() singleton returns a thread-safe shared store
  - console facade (console_azure_servicebus) reads directly from the runtime store
  - SQLite persistence preserves topology and messages across a fresh store instance
"""
from __future__ import annotations

import os
import tempfile

try:
    from core import azure_servicebus_core as sb
    from core import azure_servicebus_runtime as rt
    from core import console_azure_servicebus as console_sb
    from core.persistent_store import SqliteStateBackend, PersistentMessagingStore
except ImportError:
    import azure_servicebus_core as sb  # type: ignore
    import azure_servicebus_runtime as rt  # type: ignore
    import console_azure_servicebus as console_sb  # type: ignore
    from persistent_store import SqliteStateBackend, PersistentMessagingStore  # type: ignore


def _check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(f"Check failed: {name}")
    print(f"  ok  {name}")


def run():
    print("Running Service Bus shared runtime & topology tests:")

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name

    try:
        # Initialize runtime store with the temp SQLite db
        rt.reset_store(None)
        store = rt.get_store(backend_path=db_path)

        # 1. Assert all 5 Siftly topics and subscriptions were auto-provisioned
        topics = store.topic_arns()
        for name in rt.SIFTLY_TOPICS:
            _check(f"siftly topic '{name}' exists", name in topics)
            topic = store.get_topic(name)
            _check(f"topic '{name}' has subscription", name in topic.get("subscriptions", {}))

        # 2. Send message to scrapper_responses via core
        msg_id = sb.sb_send(store, "scrapper_responses", b'{"status": "ok"}', correlation_id="siftly-run-1")
        _check("send message via sb_send", bool(msg_id))

        # 3. Verify console facade sees topics and the message
        q_view = console_sb.list_queues()
        q_names = [q["queue_name"] for q in q_view["queues"]]
        _check("console sees scrapper_responses subscription queue", "scrapper_responses" in q_names)
        sr_q = next(q for q in q_view["queues"] if q["queue_name"] == "scrapper_responses")
        _check("console reports message in scrapper_responses", sr_q["total_messages"] >= 1)

        t_view = console_sb.list_topics()
        t_names = [t["name"] for t in t_view["topics"]]
        _check("console sees all 5 Siftly topics", all(name in t_names for name in rt.SIFTLY_TOPICS))

        # 4. Fresh instance loads same SQLite database
        backend2 = SqliteStateBackend(db_path)
        store2 = PersistentMessagingStore(backend2, store_id="azsb")
        _check("fresh store instance has 5 topics", len(store2.topic_arns()) >= 5)
        sr_topic = store2.get_topic("scrapper_responses")
        _check("fresh store has scrapper_responses sub", "scrapper_responses" in sr_topic["subscriptions"])
        sub_msgs = sr_topic["subscriptions"]["scrapper_responses"]["messages"]
        _check("persisted message survived in fresh store instance", len(sub_msgs) >= 1 and sub_msgs[0]["MessageId"] == msg_id)

    finally:
        rt.reset_store(None)
        if os.path.exists(db_path):
            os.remove(db_path)

    print("Service Bus runtime & topology conformance: ALL GREEN\n")


if __name__ == "__main__":
    run()
