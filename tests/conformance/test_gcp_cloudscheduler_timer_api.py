"""Cloud Scheduler must fire due jobs on its own (background timer), without any scheduler
call: an ENABLED `* * * * *` Pub/Sub job delivers to the subscription and stamps
lastAttemptTime; a PAUSED job in the same window does not fire (#147)."""
import base64
import os
import sys
import time
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def main():
    tag = uuid.uuid4().hex[:6]
    ps = f"{BASE}/api/gcp/pubsub/v1/projects/cloudlearn"
    jobs = f"{BASE}/v1/projects/cloudlearn/locations/us-central1/jobs"
    topic, sub = f"sch-t-{tag}", f"sch-s-{tag}"
    r = requests.put(f"{ps}/topics/{topic}", json={}, timeout=60)
    check("create topic", r.status_code < 300, r.text[:120])
    r = requests.put(f"{ps}/subscriptions/{sub}", json={"topic": f"projects/cloudlearn/topics/{topic}"}, timeout=60)
    check("create subscription", r.status_code < 300, r.text[:120])
    body = {"schedule": "* * * * *", "pubsubTarget": {
        "topicName": f"projects/cloudlearn/topics/{topic}", "data": base64.b64encode(b"tick").decode()}}
    r = requests.post(jobs, json={**body, "name": f"projects/cloudlearn/locations/us-central1/jobs/on-{tag}"}, timeout=60)
    check("create ENABLED job", r.status_code < 300, r.text[:160])
    r = requests.post(jobs, json={**body, "name": f"projects/cloudlearn/locations/us-central1/jobs/off-{tag}"}, timeout=60)
    check("create job to pause", r.status_code < 300, r.text[:160])
    r = requests.post(f"{jobs}/off-{tag}:pause", json={}, timeout=60)
    check("pause job", r.status_code < 300 and r.json().get("state") == "PAUSED", r.text[:160])

    # no scheduler calls while we wait for the minute boundary + a tick
    msgs, end = [], time.time() + 85
    while time.time() < end and not msgs:
        time.sleep(5)
        r = requests.post(f"{BASE}/v1/projects/cloudlearn/subscriptions/{sub}:pull", json={"maxMessages": 10}, timeout=60)
        msgs = r.json().get("receivedMessages", []) if r.status_code < 300 else []
    check("scheduled message reached the subscription with no scheduler call", len(msgs) >= 1, "none within 85s")
    if msgs:
        data = base64.b64decode(msgs[0]["message"].get("data", "")).decode()
        check("message carries the job data", data == "tick", data)
    on = requests.get(f"{jobs}/on-{tag}", timeout=60).json()
    check("lastAttemptTime stamped", bool(on.get("lastAttemptTime")), on)
    off = requests.get(f"{jobs}/off-{tag}", timeout=60).json()
    check("paused job did not fire", not off.get("lastAttemptTime"), off)
    for j in (f"on-{tag}", f"off-{tag}"):
        requests.delete(f"{jobs}/{j}", timeout=60)
    requests.delete(f"{ps}/subscriptions/{sub}", timeout=60)
    requests.delete(f"{ps}/topics/{topic}", timeout=60)
    sys.exit(1 if failed else 0)


main()
