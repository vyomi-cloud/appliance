"""The REAL Python `azure-servicebus` SDK (AMQP 1.0, unchanged) against the simulator's Service Bus AMQP data plane
over a real TCP socket. Skips cleanly when the SDK is not installed.

Run:  python3 -m pytest tests/conformance/test_azure_servicebus_amqp_python_sdk.py -q
"""
import time
import uuid

import pytest

pytest.importorskip("azure.servicebus")

from azure.servicebus import (NEXT_AVAILABLE_SESSION, ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode,  # noqa: E402
                               ServiceBusSubQueue)
from azure.servicebus.exceptions import (MessageLockLostError, ServiceBusError,  # noqa: E402
                                          MessagingEntityNotFoundError)

from tests.conformance._sb_amqp_harness import Broker  # noqa: E402


@pytest.fixture(scope="module")
def broker():
    b = Broker().start()
    yield b
    b.stop()


@pytest.fixture()
def client(broker):
    with ServiceBusClient.from_connection_string(broker.conn_str) as c:
        yield c


def q(broker, **opts):
    name = "q" + uuid.uuid4().hex[:8]
    broker.create(name, **opts)
    return name


def drain(client, name, n=10, wait=2, **kw):
    with client.get_queue_receiver(name, max_wait_time=wait, **kw) as r:
        return r.receive_messages(max_message_count=n, max_wait_time=wait)


def test_send_receive_complete_roundtrips_properties(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage(b"payload-1", message_id="m-1", subject="hello", content_type="text/x",
                                          correlation_id="c-1", to="dest", reply_to="rt", partition_key=None,
                                          application_properties={"n": 7, "s": "str", "f": 1.5, "b": True}))
    with client.get_queue_receiver(name, max_wait_time=3) as r:
        msgs = r.receive_messages(max_message_count=5, max_wait_time=3)
        assert len(msgs) == 1
        m = msgs[0]
        assert b"".join(m.body) == b"payload-1"
        assert m.message_id == "m-1" and m.subject == "hello" and m.content_type == "text/x"
        assert m.correlation_id == "c-1" and m.to == "dest" and m.reply_to == "rt"
        norm = lambda x: x.decode() if isinstance(x, bytes) else x  # noqa: E731  (pyamqp hands strings back as bytes)
        assert {norm(k): norm(v) for k, v in m.application_properties.items()} == \
            {"n": 7, "s": "str", "f": 1.5, "b": True}
        assert m.sequence_number > 0 and m.enqueued_time_utc is not None and m.locked_until_utc is not None
        assert m.delivery_count == 0
        r.complete_message(m)
    assert drain(client, name, wait=1) == []
    assert broker.store.topics[name]["messages"] == []


def test_abandon_redelivers_and_counts(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("x"))
    with client.get_queue_receiver(name, max_wait_time=3) as r:
        m = r.receive_messages(1, max_wait_time=3)[0]
        assert m.delivery_count == 0
        r.abandon_message(m)
        m2 = r.receive_messages(1, max_wait_time=3)[0]
        assert m2.delivery_count == 1 and m2.sequence_number == m.sequence_number
        r.complete_message(m2)


def test_dead_letter_with_reason_and_dlq_receive(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("poison", application_properties={"k": "v"}))
    with client.get_queue_receiver(name, max_wait_time=3) as r:
        m = r.receive_messages(1, max_wait_time=3)[0]
        r.dead_letter_message(m, reason="BadThing", error_description="it broke")
    assert drain(client, name, wait=1) == []
    with client.get_queue_receiver(name, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=3) as r:
        d = r.receive_messages(1, max_wait_time=3)[0]
        assert b"".join(d.body) == b"poison"
        assert d.dead_letter_reason == "BadThing" and d.dead_letter_error_description == "it broke"
        r.complete_message(d)
    with client.get_queue_receiver(name, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=1) as r:
        assert r.receive_messages(1, max_wait_time=1) == []


def test_defer_and_receive_deferred_by_sequence_number(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        s.send_messages([ServiceBusMessage("a"), ServiceBusMessage("b")])
    with client.get_queue_receiver(name, max_wait_time=3) as r:
        first = r.receive_messages(1, max_wait_time=3)[0]
        seq = first.sequence_number
        r.defer_message(first)
        second = r.receive_messages(1, max_wait_time=3)[0]
        assert b"".join(second.body) == b"b"          # the deferred one is skipped
        r.complete_message(second)
        got = r.receive_deferred_messages([seq])
        assert len(got) == 1 and b"".join(got[0].body) == b"a"
        r.complete_message(got[0])
    assert broker.store.topics[name]["messages"] == []


def test_receive_and_delete_mode(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        s.send_messages([ServiceBusMessage(str(i)) for i in range(3)])
    with client.get_queue_receiver(name, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE, max_wait_time=3) as r:
        got = r.receive_messages(3, max_wait_time=3)
        assert sorted(b"".join(m.body) for m in got) == [b"0", b"1", b"2"]
    assert broker.store.topics[name]["messages"] == []


def test_peek_does_not_consume(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        s.send_messages([ServiceBusMessage("p1"), ServiceBusMessage("p2")])
    with client.get_queue_receiver(name, max_wait_time=2) as r:
        peeked = r.peek_messages(max_message_count=10)
        assert [b"".join(m.body) for m in peeked] == [b"p1", b"p2"]
        again = r.peek_messages(max_message_count=10, sequence_number=peeked[1].sequence_number)
        assert [b"".join(m.body) for m in again] == [b"p2"]
    assert len(drain(client, name, wait=1, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE)) == 2


def test_batch_send(broker, client):
    name = q(broker)
    with client.get_queue_sender(name) as s:
        batch = s.create_message_batch()
        for i in range(5):
            batch.add_message(ServiceBusMessage("b%d" % i))
        s.send_messages(batch)
    got = drain(client, name, 10, 2, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE)
    assert [b"".join(m.body) for m in got] == [b"b%d" % i for i in range(5)]


def test_scheduled_message_and_cancel(broker, client):
    name = q(broker)
    from datetime import datetime, timedelta, timezone
    with client.get_queue_sender(name) as s:
        when = datetime.now(timezone.utc) + timedelta(seconds=2)
        seqs = s.schedule_messages([ServiceBusMessage("later")], when)
        cancel = s.schedule_messages([ServiceBusMessage("never")], datetime.now(timezone.utc) + timedelta(seconds=30))
        assert len(seqs) == 1 and seqs[0] > 0
        s.cancel_scheduled_messages(cancel)
    assert drain(client, name, wait=1) == []                    # not yet due
    time.sleep(2.0)
    got = drain(client, name, wait=3)
    assert [b"".join(m.body) for m in got] == [b"later"]
    assert broker.store.topics[name]["scheduled"] == []


def test_lock_expiry_and_renew(broker, client):
    name = q(broker, lockDuration=1)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("l"))
    with client.get_queue_receiver(name, max_wait_time=3) as r:
        m = r.receive_messages(1, max_wait_time=3)[0]
        t0 = m.locked_until_utc
        t1 = r.renew_message_lock(m)
        assert t1 >= t0
        time.sleep(2.6)
        with pytest.raises(MessageLockLostError):
            r.complete_message(m)
        again = r.receive_messages(1, max_wait_time=3)[0]
        assert again.delivery_count == 1
        r.complete_message(again)


def test_max_delivery_count_dead_letters(broker, client):
    name = q(broker, maxDeliveryCount=2)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("loop"))
    with client.get_queue_receiver(name, max_wait_time=2) as r:
        for _ in range(2):
            m = r.receive_messages(1, max_wait_time=3)[0]
            r.abandon_message(m)
        assert r.receive_messages(1, max_wait_time=1) == []
    with client.get_queue_receiver(name, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=3) as r:
        d = r.receive_messages(1, max_wait_time=3)[0]
        assert d.dead_letter_reason == "MaxDeliveryCountExceeded"
        r.complete_message(d)


def test_ttl_expiry_dead_letters_when_configured(broker, client):
    from datetime import timedelta
    name = q(broker, deadLetteringOnMessageExpiration=True)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("short", time_to_live=timedelta(seconds=1)))
    time.sleep(1.8)
    assert drain(client, name, wait=1) == []
    with client.get_queue_receiver(name, sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=3) as r:
        d = r.receive_messages(1, max_wait_time=3)[0]
        assert d.dead_letter_reason == "TTLExpiredException"


def test_duplicate_detection(broker, client):
    name = q(broker, requiresDuplicateDetection=True)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("one", message_id="dup"))
        s.send_messages(ServiceBusMessage("two", message_id="dup"))
        s.send_messages(ServiceBusMessage("three", message_id="other"))
    got = drain(client, name, 10, 2, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE)
    assert [b"".join(m.body) for m in got] == [b"one", b"three"]


def test_sessions_state_and_isolation(broker, client):
    name = q(broker, requiresSession=True)
    with client.get_queue_sender(name) as s:
        s.send_messages([ServiceBusMessage("a1", session_id="A"), ServiceBusMessage("b1", session_id="B"),
                         ServiceBusMessage("a2", session_id="A")])
        with pytest.raises(ServiceBusError):
            s.send_messages(ServiceBusMessage("no-session"))
    with client.get_queue_receiver(name, session_id="A", max_wait_time=3) as r:
        assert r.session.session_id == "A"
        r.session.set_state(b"state-A")
        assert r.session.get_state() == b"state-A"
        assert r.session.renew_lock() is not None
        got = r.receive_messages(5, max_wait_time=3)
        assert [b"".join(m.body) for m in got] == [b"a1", b"a2"]
        assert all(m.session_id == "A" for m in got)
        for m in got:
            r.complete_message(m)
    with client.get_queue_receiver(name, session_id=NEXT_AVAILABLE_SESSION, max_wait_time=3) as r:     # next available session
        assert r.session.session_id == "B"
        got = r.receive_messages(5, max_wait_time=3)
        assert [b"".join(m.body) for m in got] == [b"b1"]
        r.complete_message(got[0])
    with client.get_queue_receiver(name, session_id="A", max_wait_time=1) as r:
        assert r.session.get_state() == b"state-A"


def test_session_locked_by_other_receiver(broker, client):
    name = q(broker, requiresSession=True)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("x", session_id="S"))
    with client.get_queue_receiver(name, session_id="S", max_wait_time=2):
        with pytest.raises(ServiceBusError):
            with client.get_queue_receiver(name, session_id="S", max_wait_time=1) as r2:
                r2.receive_messages(1, max_wait_time=1)


def test_topic_fanout_to_subscriptions_and_sub_dlq(broker, client):
    topic = "t" + uuid.uuid4().hex[:8]
    broker.create(topic)
    broker.create_sub(topic, "s1")
    broker.create_sub(topic, "s2")
    with client.get_topic_sender(topic) as s:
        s.send_messages(ServiceBusMessage("fan", application_properties={"color": "red"}))
    for sub in ("s1", "s2"):
        with client.get_subscription_receiver(topic, sub, max_wait_time=3) as r:
            m = r.receive_messages(1, max_wait_time=3)[0]
            assert b"".join(m.body) == b"fan"
            if sub == "s1":
                r.dead_letter_message(m, reason="r1")
            else:
                r.complete_message(m)
    with client.get_subscription_receiver(topic, "s1", sub_queue=ServiceBusSubQueue.DEAD_LETTER, max_wait_time=3) as r:
        d = r.receive_messages(1, max_wait_time=3)[0]
        assert d.dead_letter_reason == "r1"
        r.complete_message(d)


def test_rest_and_amqp_share_one_state(broker, client):
    name = q(broker)
    # REST send -> AMQP receive
    broker.rest("POST", "/%s/messages" % name, b"from-rest", {"content-type": "text/plain",
                                                               "BrokerProperties": '{"MessageId": "rest-1"}'})
    with client.get_queue_receiver(name, max_wait_time=3) as r:
        m = r.receive_messages(1, max_wait_time=3)[0]
        assert b"".join(m.body) == b"from-rest" and m.message_id == "rest-1" and m.content_type == "text/plain"
        r.abandon_message(m)
    # AMQP send -> REST explorer sees it (and the abandoned REST one, delivery count 1)
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage("from-amqp", message_id="amqp-1", subject="lbl"))
    import json
    peek = json.loads(broker.rest("GET", "/%s/messages" % name).body)["messages"]
    by_id = {x["MessageId"]: x for x in peek}
    assert by_id["amqp-1"]["Body"] == "from-amqp" and by_id["amqp-1"]["Label"] == "lbl"
    assert by_id["rest-1"]["DeliveryCount"] == 1
    # REST complete by sequence number -> gone for AMQP
    broker.rest("POST", "/%s/messages/%s/complete" % (name, by_id["rest-1"]["SequenceNumber"]))
    got = drain(client, name, 5, 2, receive_mode=ServiceBusReceiveMode.RECEIVE_AND_DELETE)
    assert [b"".join(m.body) for m in got] == [b"from-amqp"]


def test_entity_not_found(broker, client):
    with pytest.raises(ServiceBusError) as e:
        with client.get_queue_sender("does-not-exist") as s:
            s.send_messages(ServiceBusMessage("x"))
    assert isinstance(e.value, MessagingEntityNotFoundError) or "not" in str(e.value).lower()


def test_cbs_path_with_named_key_credential(broker):
    """a credential-based client (no emulator flag): SASL + $cbs put-token + plain TCP"""
    from azure.core.credentials import AzureNamedKeyCredential
    name = q(broker)
    cred = AzureNamedKeyCredential("RootManageSharedAccessKey", "c2VjcmV0")
    with ServiceBusClient("localhost:%d" % broker.port, cred, use_tls=False) as c:
        with c.get_queue_sender(name) as s:
            s.send_messages(ServiceBusMessage("via-cbs"))
        with c.get_queue_receiver(name, max_wait_time=3) as r:
            m = r.receive_messages(1, max_wait_time=3)[0]
            assert b"".join(m.body) == b"via-cbs"
            r.complete_message(m)


def test_many_connections_and_large_message(broker, client):
    name = q(broker)
    big = b"x" * (700 * 1024)         # multi-frame transfer both ways
    with client.get_queue_sender(name) as s:
        s.send_messages(ServiceBusMessage(big))
    with client.get_queue_receiver(name, max_wait_time=5) as r:
        m = r.receive_messages(1, max_wait_time=5)[0]
        assert b"".join(m.body) == big
        r.complete_message(m)
