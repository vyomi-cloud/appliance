"""GCP Pub/Sub lens routes (/api/console/gcp-pubsub/*): topics, subscriptions, subscribe,
publish fan-out, direct send, peek, receive, purge, delete, missing-subscription 404."""
import os
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=60, **kw)


def main():
    tag = uuid.uuid4().hex[:6]
    topic, sub = f"lens-t-{tag}", f"lens-s-{tag}"
    p = "/api/console/gcp-pubsub"
    r = call("POST", f"{p}/topics", json={"name": topic})
    arn = r.json().get("topic_arn", "") if r.ok else ""
    check("create topic", r.ok and arn.endswith(f"/topics/{topic}"), r.text[:150])
    r = call("POST", f"{p}/subscriptions", json={"name": sub})
    check("create subscription", r.ok and r.json().get("queue_name") == sub, r.text[:150])
    r = call("GET", f"{p}/topics")
    check("topic listed", r.ok and any(t.get("topic_arn") == arn for t in r.json().get("topics", [])), r.text[:200])
    r = call("GET", f"{p}/subscriptions")
    check("subscription listed", r.ok and any(q.get("queue_name") == sub for q in r.json().get("queues", [])), r.text[:200])
    r = call("POST", f"{p}/topics/subscribe", json={"topic_arn": arn, "queue": sub})
    check("subscribe subscription to topic", r.ok and r.json().get("subscribed") is True, r.text[:150])
    r = call("GET", f"{p}/topics/subscriptions", params={"topic_arn": arn})
    check("topic lists its subscription", r.ok and r.json().get("count") == 1, r.text[:200])
    r = call("POST", f"{p}/topics/publish", json={"topic_arn": arn, "message": "hello"})
    check("publish fans out to 1 subscription", r.ok and r.json().get("fanned_out_to") == 1, r.text[:150])
    r = call("POST", f"{p}/subscriptions/{sub}/send", json={"body": "direct"})
    check("send direct message", r.ok and r.json().get("message_id"), r.text[:150])
    r = call("GET", f"{p}/subscriptions/{sub}/peek")
    check("peek shows both messages", r.ok and r.json().get("count") == 2, r.text[:200])
    r = call("POST", f"{p}/subscriptions/{sub}/receive", json={"max": 10})
    bodies = [m.get("Body") for m in r.json().get("messages", [])] if r.ok else []
    check("receive returns both, incl. direct body", r.ok and "direct" in bodies and len(bodies) == 2, r.text[:200])
    r = call("POST", f"{p}/subscriptions/{sub}/purge")
    check("purge subscription", r.ok and r.json().get("purged") is True, r.text[:150])
    r = call("GET", f"{p}/subscriptions/{sub}/peek")
    check("peek empty after purge", r.ok and r.json().get("count") == 0, r.text[:150])
    r = call("POST", f"{p}/topics", json={"name": ""})
    check("create topic without name -> 400", r.status_code == 400, r.status_code)
    r = call("POST", f"{p}/topics/delete", json={"topic_arn": arn})
    check("delete topic", r.ok and r.json().get("deleted") is True, r.text[:150])
    r = call("DELETE", f"{p}/subscriptions/{sub}")
    check("delete subscription", r.ok and r.json().get("deleted") is True, r.text[:150])
    r = call("POST", f"{p}/subscriptions/{sub}/send", json={"body": "x"})
    check("send to deleted subscription -> 404", r.status_code == 404, r.status_code)
    raise SystemExit(1 if failed else 0)


main()
