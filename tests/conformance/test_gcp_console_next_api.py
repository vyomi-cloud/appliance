"""GCP console-next data-plane routes (/api/console/gcp-pubsub, gcp-secrets, gcp-kms): a full
lifecycle through the HTTP API the widgets call, and GCP-shaped identifiers (Cloud KMS keys are
named projects/…/cryptoKeys/…, never AWS ARNs; key state is ENABLED)."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000") + "/api/console"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def call(method, path, **kw):
    r = requests.request(method, BASE + path, timeout=60, **kw)
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, body


def pubsub(tag):
    q, t = f"q-{tag}", f"t-{tag}"
    topic_arn = f"projects/cloudlearn/topics/{t}"
    s, b = call("POST", "/gcp-pubsub/subscriptions", json={"name": q})
    check("pubsub: create subscription", s == 200 and b.get("queue_name") == q, b)
    s, b = call("POST", f"/gcp-pubsub/subscriptions/{q}/send", json={"body": "hello"})
    check("pubsub: send message", s == 200 and b.get("message_id"), b)
    s, b = call("GET", f"/gcp-pubsub/subscriptions/{q}/peek")
    check("pubsub: peek sees the message", s == 200 and b.get("count") == 1, b)
    s, b = call("POST", f"/gcp-pubsub/subscriptions/{q}/receive", json={"max": 5})
    check("pubsub: receive returns the body", s == 200 and [m["Body"] for m in b.get("messages", [])] == ["hello"], b)
    s, b = call("POST", "/gcp-pubsub/topics", json={"name": t})
    check("pubsub: create topic", s == 200 and b.get("topic_arn") == topic_arn, b)
    s, b = call("GET", "/gcp-pubsub/topics")
    check("pubsub: topic listed", any(x["name"] == t for x in b.get("topics", [])), b)
    s, b = call("POST", "/gcp-pubsub/topics/subscribe", json={"topic_arn": topic_arn, "queue": q})
    check("pubsub: subscribe", s == 200 and b.get("subscribed") is True, b)
    s, b = call("GET", "/gcp-pubsub/topics/subscriptions", params={"topic_arn": topic_arn})
    check("pubsub: subscription listed on topic", b.get("count") == 1, b)
    s, b = call("POST", "/gcp-pubsub/topics/publish", json={"topic_arn": topic_arn, "message": "m1"})
    check("pubsub: publish fans out", s == 200 and b.get("fanned_out_to") == 1, b)
    s, b = call("POST", f"/gcp-pubsub/subscriptions/{q}/purge")
    check("pubsub: purge", s == 200 and b.get("purged") is True, b)
    s, b = call("POST", "/gcp-pubsub/topics/delete", json={"topic_arn": topic_arn})
    check("pubsub: delete topic", s == 200 and b.get("deleted") is True, b)
    s, b = call("DELETE", f"/gcp-pubsub/subscriptions/{q}")
    check("pubsub: delete subscription", s == 200 and b.get("deleted") is True, b)
    s, b = call("GET", "/gcp-pubsub/subscriptions")
    check("pubsub: subscription gone", not any(x["queue_name"] == q for x in b.get("queues", [])), b)


def secrets(tag):
    n = f"sec-{tag}"
    s, b = call("POST", "/gcp-secrets/secrets", json={"name": n, "secret_string": "v1", "description": "d"})
    check("secrets: create", s == 200 and b.get("arn") == f"projects/cloudlearn/secrets/{n}", b)
    s, b = call("GET", f"/gcp-secrets/secrets/{n}")
    check("secrets: describe has description and created", s == 200 and b.get("description") == "d" and b.get("created"), b)
    s, b = call("GET", f"/gcp-secrets/secrets/{n}/value")
    check("secrets: value is v1", b.get("secret_string") == "v1", b)
    s, b = call("POST", f"/gcp-secrets/secrets/{n}/value", json={"secret_string": "v2"})
    check("secrets: add version", s == 200 and b.get("version_id"), b)
    s, b = call("GET", f"/gcp-secrets/secrets/{n}/value")
    check("secrets: latest value is v2", b.get("secret_string") == "v2", b)
    s, b = call("GET", "/gcp-secrets/secrets")
    check("secrets: listed", any(x["name"] == n for x in b.get("secrets", [])), b)
    s, b = call("DELETE", f"/gcp-secrets/secrets/{n}")
    check("secrets: delete", s == 200 and b.get("deleted") is True, b)


def kms(tag):
    s, b = call("POST", "/gcp-kms/keys", json={"description": f"key {tag}"})
    kid = b.get("key_id", "")
    check("kms: create key", s == 200 and kid, b)
    check("kms: key name is a Cloud KMS resource name, not an ARN",
          b.get("arn", "").startswith("projects/") and "/cryptoKeys/" + kid in b.get("arn", "") and "arn:aws" not in b.get("arn", ""), b)
    check("kms: key state is ENABLED", b.get("state") == "ENABLED", b)
    s, b = call("GET", f"/gcp-kms/keys/{kid}")
    check("kms: describe", s == 200 and b.get("key_id") == kid and b.get("state") == "ENABLED" and b.get("created"), b)
    s, b = call("GET", "/gcp-kms/keys")
    row = next((k for k in b.get("keys", []) if k["key_id"] == kid), {})
    check("kms: listed with a GCP name", row.get("arn", "").startswith("projects/"), row)
    plain = base64.b64encode(b"secret payload").decode()
    s, b = call("POST", "/gcp-kms/encrypt", json={"key_id": kid, "plaintext": plain})
    blob = b.get("ciphertext_blob", "")
    check("kms: encrypt", s == 200 and blob, b)
    s, b = call("POST", "/gcp-kms/decrypt", json={"ciphertext_blob": blob})
    check("kms: decrypt round-trips", s == 200 and b.get("plaintext") == plain, b)
    s, b = call("POST", "/gcp-kms/data-key", json={"key_id": kid})
    check("kms: data key", s == 200 and b.get("plaintext") and b.get("ciphertext_blob"), b)


def main():
    tag = uuid.uuid4().hex[:6]
    pubsub(tag)
    secrets(tag)
    kms(tag)
    sys.exit(1 if failed else 0)


main()
