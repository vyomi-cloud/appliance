"""Python `azure-servicebus` (native, unchanged) against the NANO substrate: relay raw-AMQP listener -> tab socket ->
Pyodide AMQP engine on the router's Service Bus store (fixture: wasm/relay/test-amqp-bridge.mjs). Also proves the
engine loads and runs in Pyodide (the fixture boots the vendored runtime with the real Nano core list).
Skips when node / Pyodide / the SDK are missing.   python3 wasm/fetch_pyodide.py && python3 wasm/build_cores.py first.
"""
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("azure.servicebus")
from azure.servicebus import (NEXT_AVAILABLE_SESSION, ServiceBusClient, ServiceBusMessage,  # noqa: E402
                               ServiceBusReceiveMode, ServiceBusSubQueue)

from tests.conformance._sb_amqp_harness import NanoBroker  # noqa: E402

PYODIDE = os.path.join(os.path.dirname(__file__), "..", "..", "wasm", "vendor", "pyodide", "pyodide.mjs")
pytestmark = pytest.mark.skipif(not shutil.which("node") or not os.path.exists(PYODIDE),
                                reason="node or wasm/vendor/pyodide missing")


@pytest.fixture(scope="module")
def nano():
    try:
        import ws  # noqa: F401  (not needed in python; the relay needs the node `ws` package)
    except ImportError:
        pass
    if not os.environ.get("VYOMI_SB_JS_NODE_MODULES"):
        pytest.skip("set VYOMI_SB_JS_NODE_MODULES to a node_modules containing `ws` (the relay needs it)")
    b = NanoBroker().start()
    yield b
    b.stop()


@pytest.fixture()
def c(nano):
    with ServiceBusClient.from_connection_string(nano.conn_str) as client:
        yield client


def body(m):
    return b"".join(m.body)


def test_roundtrip_complete_and_rest_visibility(nano, c):
    nano.create("pq")
    with c.get_queue_sender("pq") as s:
        s.send_messages(ServiceBusMessage("hi", message_id="x1", subject="S", application_properties={"k": 1}))
    assert nano.peek("pq")[0]["Body"] == "hi"                # the REST explorer surface sees the AMQP send
    with c.get_queue_receiver("pq", max_wait_time=3) as r:
        m = r.receive_messages(1, max_wait_time=3)[0]
        assert body(m) == b"hi" and m.message_id == "x1" and m.subject == "S" and m.sequence_number > 0
        r.complete_message(m)
    assert nano.peek("pq") == []


def test_abandon_deadletter_defer(nano, c):
    nano.create("pq2")
    with c.get_queue_sender("pq2") as s:
        s.send_messages([ServiceBusMessage("a"), ServiceBusMessage("b"), ServiceBusMessage("c")])
    with c.get_queue_receiver("pq2", max_wait_time=3) as r:
        a = r.receive_messages(1, max_wait_time=3)[0]
        r.abandon_message(a)
        a2 = r.receive_messages(1, max_wait_time=3)[0]
        assert body(a2) == b"a" and a2.delivery_count == 1
        r.dead_letter_message(a2, reason="why", error_description="because")
        b = r.receive_messages(1, max_wait_time=3)[0]
        seq = b.sequence_number
        r.defer_message(b)
        cc = r.receive_messages(1, max_wait_time=3)[0]
        assert body(cc) == b"c"
        r.complete_message(cc)
        d = r.receive_deferred_messages([seq])[0]
        assert body(d) == b"b"
        r.complete_message(d)
    with c.get_queue_receiver("pq2", sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=3) as r:
        dm = r.receive_messages(1, max_wait_time=3)[0]
        assert body(dm) == b"a" and dm.dead_letter_reason == "why"


def test_schedule_sessions_and_topic(nano, c):
    nano.create("pq3")
    with c.get_queue_sender("pq3") as s:
        s.schedule_messages(ServiceBusMessage("later"), datetime.now(timezone.utc) + timedelta(seconds=2))
    with c.get_queue_receiver("pq3", max_wait_time=1) as r:
        assert r.receive_messages(1, max_wait_time=1) == []
    time.sleep(2.2)
    with c.get_queue_receiver("pq3", receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE, max_wait_time=3) as r:
        assert [body(m) for m in r.receive_messages(2, max_wait_time=3)] == [b"later"]

    nano.create("ps", requiresSession=True)
    with c.get_queue_sender("ps") as s:
        s.send_messages([ServiceBusMessage("x1", session_id="X"), ServiceBusMessage("y1", session_id="Y")])
    with c.get_queue_receiver("ps", session_id="Y", max_wait_time=3) as r:
        r.session.set_state(b"sy")
        assert r.session.get_state() == b"sy"
        got = r.receive_messages(2, max_wait_time=3)
        assert [body(m) for m in got] == [b"y1"]
        r.complete_message(got[0])
    with c.get_queue_receiver("ps", session_id=NEXT_AVAILABLE_SESSION, max_wait_time=3) as r:
        assert r.session.session_id == "X"

    nano.create("pt")
    nano.create_sub("pt", "s1")
    nano.create_sub("pt", "s2")
    with c.get_topic_sender("pt") as s:
        s.send_messages(ServiceBusMessage("fan"))
    for sub in ("s1", "s2"):
        with c.get_subscription_receiver("pt", sub, max_wait_time=3) as r:
            assert body(r.receive_messages(1, max_wait_time=3)[0]) == b"fan"


def test_large_multi_frame_message(nano, c):
    nano.create("pq4")
    big = b"z" * (600 * 1024)
    with c.get_queue_sender("pq4") as s:
        s.send_messages(ServiceBusMessage(big))
    with c.get_queue_receiver("pq4", max_wait_time=8) as r:
        m = r.receive_messages(1, max_wait_time=8)[0]
        assert body(m) == big
        r.complete_message(m)
