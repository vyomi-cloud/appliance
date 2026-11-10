"""AWS SQS/SNS console data-plane routes (/api/console/messaging/*): queue create/send/peek/
receive/purge/delete and topic create/subscribe/publish/delete, end to end."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def J(r):
    try:
        return r.json()
    except Exception:
        return {}


def main():
    tag = uuid.uuid4().hex[:6]
    q, t = f"cm-q-{tag}", f"cm-t-{tag}"
    m = BASE + "/api/console/messaging"
    r = requests.post(f"{m}/queues", json={"name": q}, timeout=60)
    check("create queue", r.status_code < 300, r.text[:150])
    r = requests.get(f"{m}/queues", timeout=60)
    check("list queues includes it", q in r.text, r.text[:150])
    r = requests.post(f"{m}/queues/{q}/send", json={"body": "hello"}, timeout=60)
    check("send message", r.status_code < 300, r.text[:150])
    r = requests.get(f"{m}/queues/{q}/peek", timeout=60)
    check("peek shows message", r.status_code < 300 and "hello" in r.text, r.text[:150])
    r = requests.post(f"{m}/queues/{q}/receive", json={"max": 5}, timeout=60)
    check("receive returns message", r.status_code < 300 and "hello" in r.text, r.text[:150])
    requests.post(f"{m}/queues/{q}/send", json={"body": "second"}, timeout=60)
    r = requests.post(f"{m}/queues/{q}/purge", timeout=60)
    check("purge", r.status_code < 300, r.text[:150])
    r = requests.get(f"{m}/queues/{q}/peek", timeout=60)
    check("peek after purge is empty", "second" not in r.text, r.text[:150])

    r = requests.post(f"{m}/topics", json={"name": t}, timeout=60)
    check("create topic", r.status_code < 300, r.text[:150])
    arn = J(r).get("topic_arn") or J(r).get("arn") or J(r).get("TopicArn") or ""
    if not arn:
        for x in requests.get(f"{m}/topics", timeout=60).json() or []:
            s = x if isinstance(x, str) else (x.get("topic_arn") or x.get("arn") or "")
            if s.endswith(":" + t):
                arn = s
    check("topic has an ARN", arn.startswith("arn:aws:sns:") and arn.endswith(t), arn)
    r = requests.post(f"{m}/topics/subscribe", json={"topic_arn": arn, "queue": q}, timeout=60)
    check("subscribe queue", r.status_code < 300, r.text[:150])
    r = requests.get(f"{m}/topics/subscriptions", params={"topic_arn": arn}, timeout=60)
    check("list subscriptions", r.status_code < 300 and q in r.text, r.text[:150])
    r = requests.post(f"{m}/topics/publish", json={"topic_arn": arn, "message": "fanout"}, timeout=60)
    check("publish", r.status_code < 300, r.text[:150])
    r = requests.get(f"{m}/queues/{q}/peek", timeout=60)
    check("published message fans out to queue", "fanout" in r.text, r.text[:200])
    r = requests.post(f"{m}/topics/delete", json={"topic_arn": arn}, timeout=60)
    check("delete topic", r.status_code < 300, r.text[:150])
    r = requests.delete(f"{m}/queues/{q}", timeout=60)
    check("delete queue", r.status_code < 300, r.text[:150])
    r = requests.get(f"{m}/queues", timeout=60)
    check("queue gone from list", q not in r.text)
    sys.exit(1 if failed else 0)


main()
