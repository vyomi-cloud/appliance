"""Pub/Sub console detail tabs (/api/gcp/sub/pubsub/*) must find a topic created through the
GCP Pub/Sub REST API under the project *id* (not the project number the space stores)."""
import os
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def main():
    pid = requests.get(BASE + "/v1/projects", timeout=30).json()["projects"][0]["projectId"]
    topic = "tabs-" + uuid.uuid4().hex[:6]
    r = requests.put(f"{BASE}/api/gcp/pubsub/v1/projects/{pid}/topics/{topic}", json={}, timeout=30)
    check("create topic", r.ok, r.text[:150])
    for op in ("getLabels", "listSubscriptions", "getSchema", "listPullSubscriptions", "getEncryption"):
        r = requests.get(f"{BASE}/api/gcp/sub/pubsub/{op}/{topic}", timeout=30)
        check(f"tab op {op} finds the topic", r.status_code == 200 and r.json().get("ok") is True, r.text[:150])
    requests.delete(f"{BASE}/api/gcp/pubsub/v1/projects/{pid}/topics/{topic}", timeout=30)
    raise SystemExit(1 if failed else 0)


main()
