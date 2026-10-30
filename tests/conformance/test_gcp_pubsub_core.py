"""GCP Pub/Sub core conformance — the GCP eventing analogue of
test_gcp_storage_core.py, asserting the native **Pub/Sub REST API v1** wire
semantics (projects/{p}/topics + subscriptions resource names, base64 message
data, publish→messageIds, pull→receivedMessages+ackId, acknowledge, topic
fan-out, google.rpc NOT_FOUND errors). Proving google-cloud-pubsub (REST
transport) can drive the core unchanged.

Same file runs on host CPython and under Pyodide/WASM and must be green on both.

Run on host:    python3 tests/conformance/test_gcp_pubsub_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import gcp_pubsub_core as ps
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import gcp_pubsub_core as ps  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = InMemoryMessagingStore()
    P = "demo-project"
    TOPIC = f"projects/{P}/topics/orders"
    SUB1 = f"projects/{P}/subscriptions/sub-a"
    SUB2 = f"projects/{P}/subscriptions/sub-b"

    # 1. create topic -> 200 with resource name
    r = ps.dispatch(st, "PUT", f"/v1/{TOPIC}", {}, {}, b"{}")
    _check("create topic 200", r.status == 200)
    _check("create topic name", _jbody(r)["name"] == TOPIC)

    # 1b. duplicate topic -> 409 ALREADY_EXISTS
    dup = ps.dispatch(st, "PUT", f"/v1/{TOPIC}", {}, {}, b"{}")
    _check("duplicate topic 409", dup.status == 409)
    _check("duplicate topic status", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2. list topics
    lt = ps.dispatch(st, "GET", f"/v1/projects/{P}/topics", {}, {}, b"")
    _check("list topics has orders", any(t["name"] == TOPIC for t in _jbody(lt)["topics"]))

    # 3. create subscription with topic ref -> 200
    body = json.dumps({"topic": TOPIC}).encode()
    cs = ps.dispatch(st, "PUT", f"/v1/{SUB1}", {}, {}, body)
    _check("create subscription 200", cs.status == 200)
    _check("subscription topic ref", _jbody(cs)["topic"] == TOPIC)
    _check("subscription name", _jbody(cs)["name"] == SUB1)

    # 3b. subscription for missing topic -> 404 NOT_FOUND
    bad = ps.dispatch(st, "PUT", f"/v1/projects/{P}/subscriptions/orphan", {}, {},
                      json.dumps({"topic": f"projects/{P}/topics/ghost"}).encode())
    _check("subscription missing topic 404", bad.status == 404
           and _jbody(bad)["error"]["status"] == "NOT_FOUND")

    # 4. list subscriptions
    ls = ps.dispatch(st, "GET", f"/v1/projects/{P}/subscriptions", {}, {}, b"")
    _check("list subscriptions has sub-a", any(s["name"] == SUB1 for s in _jbody(ls)["subscriptions"]))

    # 5. publish -> messageIds
    payload = b"hello pub/sub"
    data_b64 = base64.b64encode(payload).decode()
    pub = ps.dispatch(st, "POST", f"/v1/{TOPIC}:publish", {}, {},
                      json.dumps({"messages": [{"data": data_b64,
                                                "attributes": {"origin": "vyomi"}}]}).encode())
    _check("publish 200", pub.status == 200)
    mids = _jbody(pub)["messageIds"]
    _check("publish returns one messageId", len(mids) == 1 and mids[0])

    # 6. pull -> receivedMessages with base64 data round-tripping + attributes
    pull = ps.dispatch(st, "POST", f"/v1/{SUB1}:pull", {}, {},
                       json.dumps({"maxMessages": 10}).encode())
    _check("pull 200", pull.status == 200)
    recv = _jbody(pull)["receivedMessages"]
    _check("pull returns one message", len(recv) == 1)
    msg = recv[0]["message"]
    _check("pull data round-trips", base64.b64decode(msg["data"]) == payload)
    _check("pull attributes preserved", msg["attributes"].get("origin") == "vyomi")
    _check("pull messageId matches publish", msg["messageId"] == mids[0])
    _check("pull publishTime present", bool(msg.get("publishTime")))
    ack_id = recv[0]["ackId"]
    _check("pull ackId present", bool(ack_id))

    # 7. acknowledge -> next pull is empty
    ack = ps.dispatch(st, "POST", f"/v1/{SUB1}:acknowledge", {}, {},
                      json.dumps({"ackIds": [ack_id]}).encode())
    _check("acknowledge 200", ack.status == 200)
    empty = ps.dispatch(st, "POST", f"/v1/{SUB1}:pull", {}, {},
                        json.dumps({"maxMessages": 10}).encode())
    _check("acknowledged message gone", _jbody(empty).get("receivedMessages", []) == [])

    # 8. fan-out: a second subscription on the same topic gets its own copy
    ps.dispatch(st, "PUT", f"/v1/{SUB2}", {}, {}, json.dumps({"topic": TOPIC}).encode())
    fan = ps.dispatch(st, "POST", f"/v1/{TOPIC}:publish", {}, {},
                      json.dumps({"messages": [{"data": base64.b64encode(b"fanned").decode()}]}).encode())
    fan_mid = _jbody(fan)["messageIds"][0]
    p1 = ps.dispatch(st, "POST", f"/v1/{SUB1}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    p2 = ps.dispatch(st, "POST", f"/v1/{SUB2}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    r1 = _jbody(p1)["receivedMessages"]
    r2 = _jbody(p2)["receivedMessages"]
    _check("fan-out sub-a got the message", len(r1) == 1
           and base64.b64decode(r1[0]["message"]["data"]) == b"fanned")
    _check("fan-out sub-b got the message", len(r2) == 1
           and base64.b64decode(r2[0]["message"]["data"]) == b"fanned")
    _check("fan-out shared messageId", r1[0]["message"]["messageId"] == fan_mid
           == r2[0]["message"]["messageId"])

    # 9. delete subscription -> gone -> pull 404
    ds = ps.dispatch(st, "DELETE", f"/v1/{SUB2}", {}, {}, b"")
    _check("delete subscription 200", ds.status == 200)
    miss_sub = ps.dispatch(st, "POST", f"/v1/{SUB2}:pull", {}, {}, json.dumps({"maxMessages": 1}).encode())
    _check("deleted subscription 404 NOT_FOUND", miss_sub.status == 404
           and _jbody(miss_sub)["error"]["status"] == "NOT_FOUND")

    # 10. delete topic -> gone -> get 404 NOT_FOUND
    dt = ps.dispatch(st, "DELETE", f"/v1/{TOPIC}", {}, {}, b"")
    _check("delete topic 200", dt.status == 200)
    miss_topic = ps.dispatch(st, "GET", f"/v1/{TOPIC}", {}, {}, b"")
    _check("deleted topic 404 NOT_FOUND", miss_topic.status == 404
           and _jbody(miss_topic)["error"]["status"] == "NOT_FOUND")

    # 11. topic config: labels, CMEK, retention, schema settings round-trip + patch
    T2 = f"projects/{P}/topics/orders2"
    ct2 = ps.dispatch(st, "PUT", f"/v1/{T2}", {}, {}, json.dumps({
        "labels": {"env": "prod"}, "kmsKeyName": "projects/p/locations/g/keyRings/r/cryptoKeys/k",
        "messageRetentionDuration": "600s",
    }).encode())
    t2body = _jbody(ct2)
    _check("topic config stored", t2body.get("labels", {}).get("env") == "prod"
           and t2body.get("kmsKeyName", "").endswith("/k") and t2body.get("messageRetentionDuration") == "600s")
    patched = ps.dispatch(st, "PATCH", f"/v1/{T2}", {}, {}, json.dumps({
        "topic": {"labels": {"env": "staging"}}, "updateMask": "labels",
    }).encode())
    _check("topic patch updates labels", _jbody(patched)["labels"]["env"] == "staging")

    # 12. publish with an ordering key -> echoed back on pull
    SUB3 = f"projects/{P}/subscriptions/sub-ordering"
    ps.dispatch(st, "PUT", f"/v1/{SUB3}", {}, {}, json.dumps({"topic": T2, "enableMessageOrdering": True}).encode())
    ps.dispatch(st, "POST", f"/v1/{T2}:publish", {}, {}, json.dumps({
        "messages": [{"data": base64.b64encode(b"ordered").decode(), "orderingKey": "k1"}],
    }).encode())
    opull = ps.dispatch(st, "POST", f"/v1/{SUB3}:pull", {}, {}, json.dumps({"maxMessages": 1}).encode())
    _check("ordering key round-trips", _jbody(opull)["receivedMessages"][0]["message"]["orderingKey"] == "k1")

    # 13. subscription config: labels, dead-letter policy, retry policy round-trip + patch
    SUB4 = f"projects/{P}/subscriptions/sub-config"
    cs4 = ps.dispatch(st, "PUT", f"/v1/{SUB4}", {}, {}, json.dumps({
        "topic": T2, "labels": {"team": "core"}, "retainAckedMessages": True,
        "deadLetterPolicy": {"deadLetterTopic": T2, "maxDeliveryAttempts": 2},
        "retryPolicy": {"minimumBackoff": "10s", "maximumBackoff": "600s"},
    }).encode())
    s4body = _jbody(cs4)
    _check("subscription config stored", s4body["labels"]["team"] == "core" and s4body["retainAckedMessages"] is True
           and s4body["deadLetterPolicy"]["maxDeliveryAttempts"] == 2 and s4body["retryPolicy"]["minimumBackoff"] == "10s")
    patched_sub = ps.dispatch(st, "PATCH", f"/v1/{SUB4}", {}, {}, json.dumps({
        "subscription": {"ackDeadlineSeconds": 30}, "updateMask": "ackDeadlineSeconds",
    }).encode())
    _check("subscription patch updates ack deadline", _jbody(patched_sub)["ackDeadlineSeconds"] == 30)

    # 14. retain acknowledged messages: acked message stays out of future pulls but isn't dropped
    ps.dispatch(st, "POST", f"/v1/{T2}:publish", {}, {}, json.dumps({"messages": [{"data": base64.b64encode(b"keepme").decode()}]}).encode())
    rp = ps.dispatch(st, "POST", f"/v1/{SUB4}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    rack = _jbody(rp)["receivedMessages"][-1]["ackId"]
    ps.dispatch(st, "POST", f"/v1/{SUB4}:acknowledge", {}, {}, json.dumps({"ackIds": [rack]}).encode())
    rp2 = ps.dispatch(st, "POST", f"/v1/{SUB4}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    _check("acked message (retain) absent from next pull", not _jbody(rp2).get("receivedMessages"))

    # 15. dead-lettering: a message redelivered past maxDeliveryAttempts lands on the DLQ topic
    SUB5 = f"projects/{P}/subscriptions/sub-dlq"
    dlq_topic = f"projects/{P}/topics/orders-dlq"
    ps.dispatch(st, "PUT", f"/v1/{dlq_topic}", {}, {}, b"{}")
    ps.dispatch(st, "PUT", f"/v1/{SUB5}", {}, {}, json.dumps({
        "topic": T2, "ackDeadlineSeconds": 10,
        "deadLetterPolicy": {"deadLetterTopic": dlq_topic, "maxDeliveryAttempts": 2},
    }).encode())
    DLQ_SUB = f"projects/{P}/subscriptions/sub-dlq-reader"
    ps.dispatch(st, "PUT", f"/v1/{DLQ_SUB}", {}, {}, json.dumps({"topic": dlq_topic}).encode())
    ps.dispatch(st, "POST", f"/v1/{T2}:publish", {}, {}, json.dumps({"messages": [{"data": base64.b64encode(b"poison").decode()}]}).encode())
    for _ in range(3):   # 2 deliveries without ack == maxDeliveryAttempts; the 3rd goes to the DLQ instead
        pr = ps.dispatch(st, "POST", f"/v1/{SUB5}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
        st.advance(11)   # past the 10s ack deadline -> eligible for redelivery / DLQ on next pull
    dlq_read = ps.dispatch(st, "POST", f"/v1/{DLQ_SUB}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    _check("poison message forwarded to dead-letter topic", any(
        base64.b64decode(m["message"]["data"]) == b"poison" for m in _jbody(dlq_read).get("receivedMessages", [])))

    # 16. message retention pruning: an old, un-acked message disappears once retention elapses
    SUB6 = f"projects/{P}/subscriptions/sub-retention"
    ps.dispatch(st, "PUT", f"/v1/{SUB6}", {}, {}, json.dumps({"topic": T2, "messageRetentionDuration": "5s"}).encode())
    ps.dispatch(st, "POST", f"/v1/{T2}:publish", {}, {}, json.dumps({"messages": [{"data": base64.b64encode(b"stale").decode()}]}).encode())
    st.advance(10)
    pruned = ps.dispatch(st, "POST", f"/v1/{SUB6}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    _check("message pruned once retention elapses", not _jbody(pruned).get("receivedMessages"))

    # 17. snapshots: create from a subscription, list, seek restores the captured backlog
    SUB7 = f"projects/{P}/subscriptions/sub-snap"
    ps.dispatch(st, "PUT", f"/v1/{SUB7}", {}, {}, json.dumps({"topic": T2}).encode())
    ps.dispatch(st, "POST", f"/v1/{T2}:publish", {}, {}, json.dumps({"messages": [{"data": base64.b64encode(b"snapme").decode()}]}).encode())
    SNAP = f"projects/{P}/snapshots/snap-a"
    snc = ps.dispatch(st, "PUT", f"/v1/{SNAP}", {}, {}, json.dumps({"subscription": SUB7}).encode())
    _check("create snapshot 200", snc.status == 200 and _jbody(snc)["subscription"] == SUB7)
    lsnap = ps.dispatch(st, "GET", f"/v1/projects/{P}/snapshots", {}, {}, b"")
    _check("list snapshots has snap-a", any(s["name"] == SNAP for s in _jbody(lsnap)["snapshots"]))
    drain = ps.dispatch(st, "POST", f"/v1/{SUB7}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    ps.dispatch(st, "POST", f"/v1/{SUB7}:acknowledge", {}, {}, json.dumps({"ackIds": [m["ackId"] for m in _jbody(drain)["receivedMessages"]]}).encode())
    seek = ps.dispatch(st, "POST", f"/v1/{SUB7}:seek", {}, {}, json.dumps({"snapshot": SNAP}).encode())
    _check("seek to snapshot 200", seek.status == 200)
    replayed = ps.dispatch(st, "POST", f"/v1/{SUB7}:pull", {}, {}, json.dumps({"maxMessages": 10}).encode())
    _check("seek restores snapshotted backlog", any(
        base64.b64decode(m["message"]["data"]) == b"snapme" for m in _jbody(replayed).get("receivedMessages", [])))
    dsnap = ps.dispatch(st, "DELETE", f"/v1/{SNAP}", {}, {}, b"")
    _check("delete snapshot 200", dsnap.status == 200)
    miss_snap = ps.dispatch(st, "GET", f"/v1/{SNAP}", {}, {}, b"")
    _check("deleted snapshot 404 NOT_FOUND", miss_snap.status == 404)

    # 18. schemas: create (BASIC + FULL views), list, delete
    SCHEMA = f"projects/{P}/schemas/order-v1"
    scc = ps.dispatch(st, "POST", f"/v1/projects/{P}/schemas", {"schemaId": "order-v1"}, {},
                      json.dumps({"type": "AVRO", "definition": '{"type":"record","name":"Order","fields":[]}'}).encode())
    _check("create schema 200 returns definition", scc.status == 200 and "Order" in _jbody(scc)["definition"])
    basic = ps.dispatch(st, "GET", f"/v1/{SCHEMA}", {}, {}, b"")
    _check("get schema BASIC view omits definition", "definition" not in _jbody(basic))
    full = ps.dispatch(st, "GET", f"/v1/{SCHEMA}", {"view": "FULL"}, {}, b"")
    _check("get schema FULL view includes definition", "Order" in _jbody(full)["definition"])
    lschema = ps.dispatch(st, "GET", f"/v1/projects/{P}/schemas", {}, {}, b"")
    _check("list schemas has order-v1", any(s["name"] == SCHEMA for s in _jbody(lschema)["schemas"]))
    dschema = ps.dispatch(st, "DELETE", f"/v1/{SCHEMA}", {}, {}, b"")
    _check("delete schema 200", dschema.status == 200)
    miss_schema = ps.dispatch(st, "GET", f"/v1/{SCHEMA}", {}, {}, b"")
    _check("deleted schema 404 NOT_FOUND", miss_schema.status == 404)

    print("\nGCP Pub/Sub-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
