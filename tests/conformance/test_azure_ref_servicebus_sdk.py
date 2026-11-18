"""Azure reference architecture lane 3 (Service Bus), proved with the REAL azure-mgmt-servicebus + azure-servicebus SDKs against the
real appliance app: no seeding, no store shortcuts.

  1. ONE entity store: queues / topics / subscriptions / rules created through ARM (azure-mgmt-servicebus) are immediately usable over
     AMQP 1.0 (azure-servicebus) and over the REST wire, and an entity created over the REST wire is usable over AMQP; ARM delete removes it.
  2. LIVE delivery: a receiver ALREADY attached (receive_messages with max_wait_time, the iterator, and the async iterator) is handed a
     message sent LATER. Peek-lock settlement (complete / abandon / dead-letter / renew lock), scheduled messages, sessions, ARM rule filters.
There is no open-source Service Bus emulator we can run (Microsoft's is not viable), so the broker is Vyomi's own core behind our pure-Python
AMQP 1.0 wire; the SDKs speak the real protocol to it unchanged.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_ref_servicebus_sdk.py   (skips when the Azure SDKs are absent)
"""
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _az_ref_harness as H  # noqa: E402


def main():
    try:
        import azure.servicebus, azure.mgmt.servicebus, azure.mgmt.resource, requests  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print(f"[SKIP] needs the Azure SDKs ({e})")
        return 0
    base, amqp = H.start()
    H.ensure_rg(base)
    from azure.mgmt.servicebus import ServiceBusManagementClient
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    from azure.servicebus.exceptions import MessagingEntityNotFoundError
    import requests

    mgmt = H.arm(ServiceBusManagementClient, base)
    NS = "facilities-bus"
    mgmt.namespaces.begin_create_or_update(H.RG, NS, {"location": H.LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
    cs = H.sb_conn(amqp)
    SBH = {"x-vyomi-namespace": NS}        # marks a namespace-root request as Service Bus (what the console and SDK adapters send)
    uid = lambda p: p + uuid.uuid4().hex[:6]  # noqa: E731

    def later(fn, delay=1.5):
        threading.Thread(target=lambda: (time.sleep(delay), fn()), daemon=True).start()

    def body(m):
        return b"".join(m.body).decode()

    def t_arm_topic_sub_amqp():
        t, s = uid("t"), "approver-inbox"
        mgmt.topics.create_or_update(H.RG, NS, t, {})
        mgmt.subscriptions.create_or_update(H.RG, NS, t, s, {"properties": {"lockDuration": "PT30S", "maxDeliveryCount": 4}})
        with ServiceBusClient.from_connection_string(cs) as c:
            with c.get_topic_sender(t) as snd:
                snd.send_messages(ServiceBusMessage('{"request_id":"r1"}', subject="approval", application_properties={"kind": "approval"}))
            with c.get_subscription_receiver(t, s, max_wait_time=5) as r:
                ms = r.receive_messages(max_message_count=1, max_wait_time=5)
                assert len(ms) == 1 and "r1" in body(ms[0]), ms
                assert ms[0].subject == "approval"
                r.complete_message(ms[0])
            with c.get_subscription_receiver(t, s, max_wait_time=2) as r:
                assert not r.receive_messages(max_message_count=1, max_wait_time=2)
        r = requests.get(f"{base}/{t}", headers=SBH, timeout=10)
        assert r.status_code == 200, f"ARM-created topic not on the REST wire: {r.status_code}"
        r = requests.get(f"{base}/{t}/subscriptions/{s}", headers=SBH, timeout=10)
        assert r.status_code == 200, f"ARM-created subscription not on the REST wire: {r.status_code}"

    def t_arm_queue_amqp():
        q = uid("q")
        mgmt.queues.create_or_update(H.RG, NS, q, {"properties": {"lockDuration": "PT45S"}})
        with ServiceBusClient.from_connection_string(cs) as c:
            with c.get_queue_sender(q) as snd:
                snd.send_messages([ServiceBusMessage("a"), ServiceBusMessage("b")])
            with c.get_queue_receiver(q, max_wait_time=5) as r:
                ms = r.receive_messages(max_message_count=5, max_wait_time=5)
                assert sorted(body(m) for m in ms) == ["a", "b"], [body(m) for m in ms]
                for m in ms:
                    r.complete_message(m)

    def t_rest_created_visible_to_amqp():
        t = uid("rt")
        assert requests.put(f"{base}/{t}", headers=SBH, timeout=10).status_code in (200, 201)
        assert requests.put(f"{base}/{t}/subscriptions/s1", headers=SBH, timeout=10).status_code in (200, 201)
        with ServiceBusClient.from_connection_string(cs) as c:
            with c.get_topic_sender(t) as snd:
                snd.send_messages(ServiceBusMessage("via-rest-entity"))
            with c.get_subscription_receiver(t, "s1", max_wait_time=5) as r:
                ms = r.receive_messages(max_message_count=1, max_wait_time=5)
                assert len(ms) == 1 and body(ms[0]) == "via-rest-entity"
                r.complete_message(ms[0])

    def t_arm_delete_removes():
        q = uid("qd")
        mgmt.queues.create_or_update(H.RG, NS, q, {})
        mgmt.queues.delete(H.RG, NS, q)
        assert requests.get(f"{base}/{q}", headers=SBH, timeout=10).status_code == 404, "deleted queue still on the REST wire"
        try:
            with ServiceBusClient.from_connection_string(cs) as c:
                with c.get_queue_sender(q) as snd:
                    snd.send_messages(ServiceBusMessage("x"))
        except MessagingEntityNotFoundError:
            return
        raise AssertionError("deleted queue still accepts messages")

    def t_late_delivery_queue_iterator():
        q = uid("ql")
        mgmt.queues.create_or_update(H.RG, NS, q, {})
        with ServiceBusClient.from_connection_string(cs) as c, ServiceBusClient.from_connection_string(cs) as c2:
            def send():
                with c2.get_queue_sender(q) as snd:
                    snd.send_messages(ServiceBusMessage("late"))
            with c.get_queue_receiver(q, max_wait_time=10) as r:
                later(send)
                t0 = time.time()
                got = None
                for m in r:          # attached BEFORE the send
                    got = m
                    r.complete_message(m)
                    break
                assert got is not None and body(got) == "late", got
                assert time.time() - t0 < 8

    def t_late_delivery_subscription_batch():
        t = uid("tl")
        mgmt.topics.create_or_update(H.RG, NS, t, {})
        mgmt.subscriptions.create_or_update(H.RG, NS, t, "inbox", {})
        with ServiceBusClient.from_connection_string(cs) as c, ServiceBusClient.from_connection_string(cs) as c2:
            def send():
                with c2.get_topic_sender(t) as snd:
                    snd.send_messages(ServiceBusMessage("late-topic"))
            with c.get_subscription_receiver(t, "inbox", max_wait_time=10) as r:
                later(send)
                ms = r.receive_messages(max_message_count=1, max_wait_time=10)
                assert len(ms) == 1 and body(ms[0]) == "late-topic", ms
                r.complete_message(ms[0])

    def t_late_delivery_async_iterator():
        import asyncio
        from azure.servicebus.aio import ServiceBusClient as AClient
        q = uid("qa")
        mgmt.queues.create_or_update(H.RG, NS, q, {})

        async def go():
            async with AClient.from_connection_string(cs) as c, AClient.from_connection_string(cs) as c2:
                async def send():
                    await asyncio.sleep(1.5)
                    async with c2.get_queue_sender(q) as snd:
                        await snd.send_messages(ServiceBusMessage("late-async"))
                async with c.get_queue_receiver(q, max_wait_time=10) as r:
                    task = asyncio.create_task(send())
                    got = None
                    async for m in r:
                        got = body(m)
                        await r.complete_message(m)
                        break
                    await task
                    return got
        assert asyncio.run(go()) == "late-async"

    def t_abandon_deadletter_renew():
        q = uid("qs")
        mgmt.queues.create_or_update(H.RG, NS, q, {"properties": {"maxDeliveryCount": 3, "lockDuration": "PT30S"}})
        with ServiceBusClient.from_connection_string(cs) as c:
            with c.get_queue_sender(q) as snd:
                snd.send_messages(ServiceBusMessage("m1"))
            with c.get_queue_receiver(q, max_wait_time=5) as r:
                m = r.receive_messages(max_message_count=1, max_wait_time=5)[0]
                until = r.renew_message_lock(m)
                assert until is not None
                r.abandon_message(m)
            with c.get_queue_receiver(q, max_wait_time=5) as r:
                m = r.receive_messages(max_message_count=1, max_wait_time=5)[0]
                assert m.delivery_count >= 1, m.delivery_count
                r.dead_letter_message(m, reason="poison", error_description="bad payload")
            with c.get_queue_receiver(q, max_wait_time=5, sub_queue="deadletter") as r:
                ms = r.receive_messages(max_message_count=1, max_wait_time=5)
                assert len(ms) == 1 and body(ms[0]) == "m1", ms
                assert ms[0].dead_letter_reason == "poison"
                r.complete_message(ms[0])

    def t_scheduled():
        q = uid("qsch")
        mgmt.queues.create_or_update(H.RG, NS, q, {})
        with ServiceBusClient.from_connection_string(cs) as c:
            from datetime import datetime, timedelta, timezone
            with c.get_queue_sender(q) as snd:
                seq = snd.schedule_messages(ServiceBusMessage("later"), datetime.now(timezone.utc) + timedelta(seconds=3))
                assert seq
            with c.get_queue_receiver(q, max_wait_time=1) as r:
                assert not r.receive_messages(max_message_count=1, max_wait_time=1), "scheduled message delivered early"
            with c.get_queue_receiver(q, max_wait_time=8) as r:
                ms = r.receive_messages(max_message_count=1, max_wait_time=8)
                assert len(ms) == 1 and body(ms[0]) == "later"
                r.complete_message(ms[0])

    def t_sessions():
        q = uid("qses")
        mgmt.queues.create_or_update(H.RG, NS, q, {"properties": {"requiresSession": True}})
        with ServiceBusClient.from_connection_string(cs) as c:
            with c.get_queue_sender(q) as snd:
                snd.send_messages([ServiceBusMessage("s1-a", session_id="S1"), ServiceBusMessage("s1-b", session_id="S1")])
            with c.get_queue_receiver(q, session_id="S1", max_wait_time=5) as r:
                ms = r.receive_messages(max_message_count=5, max_wait_time=5)
                assert [body(m) for m in ms] == ["s1-a", "s1-b"], [body(m) for m in ms]
                for m in ms:
                    r.complete_message(m)

    def t_arm_rule_filter():
        t = uid("tr")
        mgmt.topics.create_or_update(H.RG, NS, t, {})
        mgmt.subscriptions.create_or_update(H.RG, NS, t, "hi", {})
        mgmt.subscriptions.create_or_update(H.RG, NS, t, "lo", {})
        for sub, expr in (("hi", "amount > 500"), ("lo", "amount <= 500")):
            mgmt.rules.create_or_update(H.RG, NS, t, sub, "r", {"properties": {"filterType": "SqlFilter", "sqlFilter": {"sqlExpression": expr}}})
            mgmt.rules.delete(H.RG, NS, t, sub, "$Default")
        with ServiceBusClient.from_connection_string(cs) as c:
            with c.get_topic_sender(t) as snd:
                snd.send_messages(ServiceBusMessage("big", application_properties={"amount": 900}))
                snd.send_messages(ServiceBusMessage("small", application_properties={"amount": 10}))
            with c.get_subscription_receiver(t, "hi", max_wait_time=4) as r:
                ms = r.receive_messages(max_message_count=5, max_wait_time=4)
                assert [body(m) for m in ms] == ["big"], [body(m) for m in ms]
            with c.get_subscription_receiver(t, "lo", max_wait_time=4) as r:
                ms = r.receive_messages(max_message_count=5, max_wait_time=4)
                assert [body(m) for m in ms] == ["small"], [body(m) for m in ms]

    H.run_cases([
        ("ARM topic+subscription -> AMQP send/receive/complete (+REST wire sees it)", t_arm_topic_sub_amqp),
        ("ARM queue -> AMQP batch send/receive", t_arm_queue_amqp),
        ("REST-wire topic+subscription -> AMQP", t_rest_created_visible_to_amqp),
        ("ARM queue delete -> REST + AMQP entity not found", t_arm_delete_removes),
        ("attached queue receiver (iterator) gets a message sent later", t_late_delivery_queue_iterator),
        ("attached subscription receiver (receive_messages) gets a message sent later", t_late_delivery_subscription_batch),
        ("attached ASYNC queue receiver (async for) gets a message sent later", t_late_delivery_async_iterator),
        ("peek-lock: renew lock, abandon (delivery_count), dead-letter + DLQ receive", t_abandon_deadletter_renew),
        ("scheduled message (schedule_messages)", t_scheduled),
        ("sessions: session receiver gets its session in order", t_sessions),
        ("ARM SQL rule filters route to the matching subscription only", t_arm_rule_filter),
    ])


if __name__ == "__main__":
    sys.exit(main())
