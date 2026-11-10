"""#149: a Cloud Scheduler pubsubTarget job, created and run with the real gcloud CLI,
must deliver its data + attributes to `gcloud pubsub subscriptions pull` (same store)."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import uuid

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/") + "/"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def main():
    env = dict(os.environ, CLOUDSDK_CONFIG=tempfile.mkdtemp(), CLOUDSDK_AUTH_ACCESS_TOKEN="fake",
               CLOUDSDK_CORE_PROJECT="vyomi-project", CLOUDSDK_CORE_DISABLE_PROMPTS="1",
               CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB=BASE, CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDSCHEDULER=BASE)

    def g(*a):
        r = subprocess.run(["gcloud", *a], env=env, capture_output=True, text=True, timeout=90)
        return r.returncode, r.stdout, r.stderr

    t = uuid.uuid4().hex[:6]
    topic, sub, job = f"st-{t}", f"ss-{t}", f"sj-{t}"
    check("create topic", g("pubsub", "topics", "create", topic)[0] == 0)
    check("create subscription", g("pubsub", "subscriptions", "create", sub, "--topic", topic)[0] == 0)
    rc, _, err = g("scheduler", "jobs", "create", "pubsub", job, "--location", "us-central1", "--schedule",
                   "0 0 1 1 *", "--topic", topic, "--message-body", "hello", "--attributes", "a=b")
    check("create scheduler pubsub job", rc == 0, err[-200:])
    rc, _, err = g("scheduler", "jobs", "run", job, "--location", "us-central1")
    check("run job", rc == 0, err[-200:])
    rc, out, err = g("pubsub", "subscriptions", "pull", sub, "--auto-ack", "--format=json")
    msgs = json.loads(out) if rc == 0 and out.strip() else []
    check("pull returns the scheduled message", len(msgs) == 1, err[-200:] or out)
    if msgs:
        m = msgs[0]["message"]
        check("data matches", base64.b64decode(m.get("data", "")) == b"hello", m)
        check("attributes match", m.get("attributes") == {"a": "b"}, m)
    g("scheduler", "jobs", "delete", job, "--location", "us-central1")
    g("pubsub", "subscriptions", "delete", sub)
    g("pubsub", "topics", "delete", topic)


main()
sys.exit(1 if failed else 0)
