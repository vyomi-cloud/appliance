"""#149 (SDK half): a Cloud Scheduler pubsubTarget job run via the REST API must be delivered to
the official Python Pub/Sub SDK subscriber (REST transport, endpoint changed only)."""
import json
import os
import sys
import urllib.request
import uuid

from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import pubsub_v1

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
P = "vyomi-project"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def http(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


t = uuid.uuid4().hex[:6]
opts = ClientOptions(api_endpoint=BASE)
pub = pubsub_v1.PublisherClient(credentials=AnonymousCredentials(), transport="rest", client_options=opts)
sub = pubsub_v1.SubscriberClient(credentials=AnonymousCredentials(), transport="rest", client_options=opts)
topic = pub.topic_path(P, f"pt-{t}")
subp = sub.subscription_path(P, f"ps-{t}")
pub.create_topic(request={"name": topic})
sub.create_subscription(request={"name": subp, "topic": topic})
check("sdk created topic + subscription", True)

loc = f"projects/{P}/locations/us-central1"
job = f"{loc}/jobs/pj-{t}"
http("POST", f"/v1/{loc}/jobs", {"name": job, "schedule": "0 0 1 1 *", "timeZone": "UTC",
     "pubsubTarget": {"topicName": topic, "data": "c2RrLWhlbGxv", "attributes": {"k": "v"}}})
http("POST", f"/v1/{job}:run", {})
resp = sub.pull(request={"subscription": subp, "max_messages": 5})
msgs = resp.received_messages
check("SDK subscriber pulls the scheduled message", len(msgs) == 1, len(msgs))
if msgs:
    m = msgs[0].message
    check("data matches", m.data == b"sdk-hello", m.data)
    check("attributes match", dict(m.attributes) == {"k": "v"}, dict(m.attributes))
    sub.acknowledge(request={"subscription": subp, "ack_ids": [msgs[0].ack_id]})
try:
    http("DELETE", f"/v1/{job}")
    sub.delete_subscription(request={"subscription": subp})
    pub.delete_topic(request={"topic": topic})
except Exception:
    pass
sys.exit(1 if failed else 0)
