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

    print("\nGCP Pub/Sub-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
