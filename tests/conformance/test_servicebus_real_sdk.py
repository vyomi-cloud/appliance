#!/usr/bin/env python3
"""Service Bus AMQP listener against the REAL Azure SDK (azure-servicebus).

The other AMQP suites drive the listener with hand-built frames, so they can
only check what the listener was written to expect. This suite connects the
actual `azure-servicebus` client (the one Siftly ships, 7.14.x, pure-Python
`_pyamqp` stack) to an in-process listener and exercises what Siftly's workers
do: send / batch send, peek-lock receive, complete, abandon + redelivery,
lock renewal, receive-and-delete, and the error for an unknown entity.

Skips (exit 0) when azure-servicebus is not installed.

    PYTHONPATH=. python3 tests/conformance/test_servicebus_real_sdk.py
"""
from __future__ import annotations

import asyncio
import sys
import threading

try:
    from azure.servicebus import (
        ServiceBusClient,
        ServiceBusMessage,
        ServiceBusReceiveMode,
    )
    from azure.servicebus.exceptions import ServiceBusError
except ImportError:  # pragma: no cover - environment dependent
    print("SKIP: azure-servicebus not installed (pip install azure-servicebus)")
    sys.exit(0)

from core.azure_servicebus_runtime import bootstrap_siftly_topology, reset_store
from core.persistent_store import PersistentMessagingStore, SqliteStateBackend
from core.servicebus_amqp.server import AmqpServer

TOPIC = "scrapper_responses"
SUB = "scrapper_responses"


def _check(name: str, cond: bool, detail: object = "") -> None:
    if not cond:
        raise AssertionError(f"{name}: {detail}")
    print(f"  ok  {name}")


def _start_listener() -> tuple[AmqpServer, asyncio.AbstractEventLoop, int]:
    reset_store(PersistentMessagingStore(SqliteStateBackend(":memory:"), store_id="azsb"))
    bootstrap_siftly_topology()
    loop = asyncio.new_event_loop()
    server = AmqpServer(host="127.0.0.1", port=0)
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.start())
        ready.set()
        loop.run_forever()

    threading.Thread(target=_run, name="amqp-listener", daemon=True).start()
    if not ready.wait(10):
        raise RuntimeError("AMQP listener did not start")
    return server, loop, server.actual_port


def _drain(client: ServiceBusClient) -> None:
    with client.get_subscription_receiver(
        TOPIC, SUB, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE, max_wait_time=1
    ) as r:
        while r.receive_messages(max_message_count=50, max_wait_time=1):
            pass


def main() -> None:
    print("Service Bus AMQP listener vs real azure-servicebus SDK:")
    server, loop, port = _start_listener()
    cs = (
        f"Endpoint=sb://127.0.0.1:{port};SharedAccessKeyName=RootManageSharedAccessKey;"
        "SharedAccessKey=dGVzdGtleQ==;UseDevelopmentEmulator=true;"
    )
    try:
        with ServiceBusClient.from_connection_string(cs, retry_total=0) as c:
            # 1. send -> peek-lock -> complete, with properties
            with c.get_topic_sender(TOPIC) as s:
                s.send_messages(
                    ServiceBusMessage(b'{"job":1}', application_properties={"kind": "probe"}, subject="s1")
                )
            with c.get_subscription_receiver(TOPIC, SUB, max_wait_time=5) as r:
                ms = r.receive_messages(max_wait_time=5)
                _check("message received", len(ms) == 1, ms)
                m = ms[0]
                _check("body round-trips", list(m.body) == [b'{"job":1}'], list(m.body))
                _check("application properties round-trip",
                       (m.application_properties or {}).get(b"kind") == b"probe", m.application_properties)
                _check("first delivery has delivery_count 0", m.delivery_count == 0, m.delivery_count)
                _check("lock token is a GUID", len(str(m.lock_token)) == 36, m.lock_token)
                _check("locked_until is set", m.locked_until_utc is not None)
                r.complete_message(m)

            # 2. abandon -> redelivery
            with c.get_topic_sender(TOPIC) as s:
                s.send_messages(ServiceBusMessage("retry-me"))
            with c.get_subscription_receiver(TOPIC, SUB, max_wait_time=5) as r:
                m = r.receive_messages(max_wait_time=5)[0]
                r.abandon_message(m)
                m2 = r.receive_messages(max_wait_time=5)[0]
                _check("abandoned message is redelivered",
                       list(m2.body) == [b"retry-me"] and m2.delivery_count == 1,
                       (list(m2.body), m2.delivery_count))
                before = m2.locked_until_utc
                r.renew_message_lock(m2)
                _check("renew_message_lock extends the lock", m2.locked_until_utc >= before)
                r.complete_message(m2)

            # 3. batch send keeps every message, in order
            with c.get_topic_sender(TOPIC) as s:
                batch = s.create_message_batch()
                for i in range(5):
                    batch.add_message(ServiceBusMessage(f"b{i}"))
                s.send_messages(batch)
                s.send_messages([ServiceBusMessage("l0"), ServiceBusMessage("l1")])
            got: list[bytes] = []
            with c.get_subscription_receiver(
                TOPIC, SUB, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE, max_wait_time=3
            ) as r:
                for _ in range(10):
                    chunk = r.receive_messages(max_message_count=10, max_wait_time=2)
                    if not chunk:
                        break
                    got += [b"".join(x.body) for x in chunk]
            _check("batch + list sends deliver all 7 messages in order",
                   got == [b"b0", b"b1", b"b2", b"b3", b"b4", b"l0", b"l1"], got)

            # 4. unknown entity fails fast with a Service Bus error (no hang)
            try:
                with c.get_topic_sender("does-not-exist") as s:
                    s.send_messages(ServiceBusMessage("x"))
                raise AssertionError("send to unknown topic succeeded")
            except ServiceBusError:
                _check("unknown entity raises ServiceBusError", True)

            _drain(c)
    finally:
        asyncio.run_coroutine_threadsafe(server.stop(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
    print("Service Bus real-SDK conformance: ALL GREEN")


if __name__ == "__main__":
    main()
