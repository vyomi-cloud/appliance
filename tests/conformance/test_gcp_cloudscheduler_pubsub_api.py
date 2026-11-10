"""Cloud Scheduler pubsubTarget `:run` must land in the same Pub/Sub store the user's
subscriber pulls from (emulator container when present): data + attributes arrive (#149)."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
try:   # the GCP space's project ID
    PROJECT = requests.get(f"{BASE}/api/gcp/catalog", timeout=60).json()["project"]
except Exception:   # appliance not up yet (collection)
    PROJECT = "vyomi-project"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


tag = uuid.uuid4().hex[:6]
ps = f"{BASE}/api/gcp/pubsub/v1/projects/{PROJECT}"
jobs = f"{BASE}/v1/projects/{PROJECT}/locations/us-central1/jobs"
topic, sub, job = f"sp-t-{tag}", f"sp-s-{tag}", f"sp-j-{tag}"
r = requests.put(f"{ps}/topics/{topic}", json={}, timeout=60)
check("create topic", r.status_code < 300, r.text[:120])
r = requests.put(f"{ps}/subscriptions/{sub}", json={"topic": f"projects/{PROJECT}/topics/{topic}"}, timeout=60)
check("create subscription", r.status_code < 300, r.text[:120])
r = requests.post(jobs, json={"name": f"projects/{PROJECT}/locations/us-central1/jobs/{job}",
    "schedule": "0 0 1 1 *", "pubsubTarget": {"topicName": f"projects/{PROJECT}/topics/{topic}",
    "data": base64.b64encode(b"hello-sched").decode(), "attributes": {"k": "v"}}}, timeout=60)
check("create job", r.status_code < 300, r.text[:160])
r = requests.post(f"{jobs}/{job}:run", json={}, timeout=60)
check("run job", r.status_code < 300, r.text[:160])
r = requests.post(f"{BASE}/v1/projects/{PROJECT}/subscriptions/{sub}:pull", json={"maxMessages": 10}, timeout=60)
msgs = r.json().get("receivedMessages", []) if r.status_code < 300 else []
check("message pulled from the subscription", len(msgs) == 1, r.text[:200])
if msgs:
    m = msgs[0]["message"]
    check("data preserved", base64.b64decode(m.get("data", "")) == b"hello-sched", m)
    check("attributes preserved", (m.get("attributes") or {}).get("k") == "v", m)
requests.delete(f"{jobs}/{job}", timeout=60)
requests.delete(f"{ps}/subscriptions/{sub}", timeout=60)
requests.delete(f"{ps}/topics/{topic}", timeout=60)
sys.exit(1 if failed else 0)
