"""AWS console data-plane routes (/api/console/messaging|secrets|kms/*): SQS queue + SNS topic
fan-out, Secrets Manager versions, KMS encrypt/decrypt/data-key round trip."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:200]}")
    failed = failed or not ok


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=60, **kw)


def main():
    t = uuid.uuid4().hex[:6]
    q, topic, sec = f"cq-{t}", f"ct-{t}", f"cs-{t}"
    # --- SQS queue
    r = call("POST", "/api/console/messaging/queues", json={"name": q})
    check("create queue", r.ok and r.json().get("queue_url", "").endswith("/" + q), r.text)
    check("create queue without name -> 400", call("POST", "/api/console/messaging/queues", json={}).status_code == 400)
    r = call("POST", f"/api/console/messaging/queues/{q}/send", json={"body": "hello"})
    check("send message", r.ok and r.json().get("md5_of_body") == "5d41402abc4b2a76b9719d911017c592", r.text)
    r = call("GET", f"/api/console/messaging/queues/{q}/peek")
    msgs = r.json().get("messages", []) if r.ok else []
    check("peek shows message without consuming", len(msgs) == 1 and msgs[0]["Body"] == "hello", r.text)
    r = call("POST", f"/api/console/messaging/queues/{q}/receive", json={"max": 5})
    got = r.json().get("messages", []) if r.ok else []
    check("receive returns message with ReceiptHandle", len(got) == 1 and got[0].get("ReceiptHandle"), r.text)
    r = call("GET", "/api/console/messaging/queues")
    row = next((x for x in r.json().get("queues", []) if x["queue_name"] == q), {}) if r.ok else {}
    check("list queues has ARN", row.get("queue_arn", "").endswith(":" + q), row)
    r = call("POST", f"/api/console/messaging/queues/{q}/purge")
    check("purge queue", r.ok and r.json().get("purged") is True, r.text)
    # --- SNS topic fan-out to the queue
    r = call("POST", "/api/console/messaging/topics", json={"name": topic})
    arn = r.json().get("topic_arn", "") if r.ok else ""
    check("create topic", arn.endswith(":" + topic), r.text)
    r = call("POST", "/api/console/messaging/topics/subscribe", json={"topic_arn": arn, "queue": q})
    check("subscribe queue", r.ok and r.json().get("subscribed") is True, r.text)
    r = call("GET", "/api/console/messaging/topics/subscriptions", params={"topic_arn": arn})
    check("list subscriptions", r.ok and r.json().get("count") == 1 and r.json()["subscriptions"][0]["protocol"] == "sqs", r.text)
    r = call("POST", "/api/console/messaging/topics/publish", json={"topic_arn": arn, "message": "m1", "subject": "s"})
    check("publish fans out to 1 queue", r.ok and r.json().get("fanned_out_to") == 1, r.text)
    r = call("GET", f"/api/console/messaging/queues/{q}/peek")
    check("published message landed in queue", r.ok and r.json().get("count") == 1, r.text)
    check("publish without topic_arn -> 400", call("POST", "/api/console/messaging/topics/publish", json={}).status_code == 400)
    call("POST", "/api/console/messaging/topics/delete", json={"topic_arn": arn})
    call("DELETE", f"/api/console/messaging/queues/{q}")
    r = call("GET", "/api/console/messaging/queues")
    check("delete queue", r.ok and all(x["queue_name"] != q for x in r.json().get("queues", [])), r.text)
    # --- Secrets Manager
    r = call("POST", "/api/console/secrets", json={"name": sec, "secret_string": "v1"})
    check("create secret returns ARN + version", r.ok and ":secret:" + sec in r.json().get("arn", "") and r.json().get("version_id"), r.text)
    v1 = r.json().get("version_id") if r.ok else None
    r = call("GET", f"/api/console/secrets/{sec}/value")
    check("get value v1", r.ok and r.json().get("secret_string") == "v1" and r.json().get("stages") == ["AWSCURRENT"], r.text)
    r = call("POST", f"/api/console/secrets/{sec}/value", json={"secret_string": "v2"})
    check("put new value", r.ok and r.json().get("version_id") != v1, r.text)
    r = call("GET", f"/api/console/secrets/{sec}/value")
    check("get value v2", r.ok and r.json().get("secret_string") == "v2", r.text)
    r = call("GET", f"/api/console/secrets/{sec}")
    stages = {v["version_id"]: v["stages"] for v in r.json().get("versions", [])} if r.ok else {}
    check("describe: v1 is AWSPREVIOUS", stages.get(v1) == ["AWSPREVIOUS"], stages)
    r = call("GET", "/api/console/secrets")
    check("list secrets has created/last_changed", r.ok and any(s["name"] == sec and s.get("created") and s.get("last_changed") for s in r.json().get("secrets", [])), r.text)
    call("DELETE", f"/api/console/secrets/{sec}")
    # --- KMS
    r = call("POST", "/api/console/kms/keys", json={"description": "probe"})
    kid = r.json().get("key_id", "") if r.ok else ""
    check("create key", r.ok and r.json().get("state") == "Enabled" and r.json().get("arn", "").endswith(kid), r.text)
    r = call("GET", f"/api/console/kms/keys/{kid}")
    check("describe key", r.ok and r.json().get("usage") == "ENCRYPT_DECRYPT" and r.json().get("spec") == "SYMMETRIC_DEFAULT", r.text)
    pt = base64.b64encode(b"hi there").decode()
    r = call("POST", "/api/console/kms/encrypt", json={"key_id": kid, "plaintext": pt})
    blob = r.json().get("ciphertext_blob", "") if r.ok else ""
    check("encrypt", bool(blob) and blob != pt, r.text)
    r = call("POST", "/api/console/kms/decrypt", json={"ciphertext_blob": blob})
    check("decrypt round trip", r.ok and r.json().get("plaintext") == pt, r.text)
    r = call("POST", "/api/console/kms/data-key", json={"key_id": kid})
    d = r.json() if r.ok else {}
    check("data key: 32-byte plaintext + ciphertext", len(base64.b64decode(d.get("plaintext", ""))) == 32 and d.get("ciphertext_blob"), r.text)
    check("encrypt without key_id -> 400", call("POST", "/api/console/kms/encrypt", json={}).status_code == 400)
    check("decrypt garbage blob rejected", call("POST", "/api/console/kms/decrypt", json={"ciphertext_blob": "!!"}).status_code >= 400)
    r = call("GET", "/api/console/kms/keys")
    check("list keys includes new key", r.ok and any(k["key_id"] == kid for k in r.json().get("keys", [])), r.text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
