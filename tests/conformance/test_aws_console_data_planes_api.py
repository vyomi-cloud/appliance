"""AWS console data-plane routes: SQS/SNS messaging (/api/console/messaging/*), Secrets Manager
(/api/console/secrets/*) and KMS (/api/console/kms/*): create -> use -> read back -> delete."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False
U = uuid.uuid4().hex[:8]


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:300]}")
    failed = failed or not ok


def call(method, path, body=None):
    r = requests.request(method, BASE + path, json=body, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


# ── messaging: queues ───────────────────────────────────────────────────
q = f"cov-q-{U}"
s, b = call("POST", "/api/console/messaging/queues", {"name": q})
check("create queue -> queue_url", s == 200 and b["queue_url"].endswith("/" + q), (s, b))
s, b = call("POST", "/api/console/messaging/queues", {"name": ""})
check("create queue without name -> 400", s == 400, (s, b))
s, b = call("GET", "/api/console/messaging/queues")
check("list queues includes it", s == 200 and any(x.get("queue_name", x.get("name")) == q for x in b["queues"]), (s, b))
s, b = call("POST", f"/api/console/messaging/queues/{q}/send", {"body": "hello"})
check("send -> message_id + md5", s == 200 and b["message_id"] and len(b["md5_of_body"]) == 32, (s, b))
s, b = call("GET", f"/api/console/messaging/queues/{q}/peek")
check("peek shows body without consuming", s == 200 and b["count"] == 1 and b["messages"][0]["Body"] == "hello", (s, b))
s, b = call("POST", f"/api/console/messaging/queues/{q}/receive", {"max": 5, "visibility": 30})
check("receive -> ReceiptHandle", s == 200 and b["count"] == 1 and b["messages"][0]["ReceiptHandle"], (s, b))
s, b = call("POST", f"/api/console/messaging/queues/{q}/send", {"body": "two"})
s, b = call("POST", f"/api/console/messaging/queues/{q}/purge")
check("purge", s == 200 and b["purged"] is True, (s, b))
s, b = call("GET", f"/api/console/messaging/queues/{q}/peek")
check("peek after purge empty", s == 200 and b["count"] == 0, (s, b))

# ── messaging: topics + fan-out to the queue ────────────────────────────
t = f"cov-t-{U}"
s, b = call("POST", "/api/console/messaging/topics", {"name": t})
arn = b.get("topic_arn", "") if b else ""
check("create topic -> ARN", s == 200 and arn.startswith("arn:aws:sns:") and arn.endswith(":" + t), (s, b))
s, b = call("GET", "/api/console/messaging/topics")
check("list topics includes it", s == 200 and any(x["topic_arn"] == arn for x in b["topics"]), (s, b))
s, b = call("POST", "/api/console/messaging/topics/subscribe", {"topic_arn": arn, "queue": q})
check("subscribe queue", s == 200, (s, b))
s, b = call("POST", "/api/console/messaging/topics/subscribe", {"topic_arn": arn})
check("subscribe without queue -> 400", s == 400, (s, b))
s, b = call("GET", "/api/console/messaging/topics/subscriptions?topic_arn=" + arn)
check("list subscriptions", s == 200 and len(b.get("subscriptions", [])) == 1, (s, b))
s, b = call("POST", "/api/console/messaging/topics/publish", {"topic_arn": arn, "message": "fan", "subject": "s"})
check("publish", s == 200, (s, b))
s, b = call("GET", f"/api/console/messaging/queues/{q}/peek")
check("published message reached subscribed queue", s == 200 and b["count"] == 1 and "fan" in b["messages"][0]["Body"], (s, b))
s, b = call("POST", "/api/console/messaging/topics/publish", {"message": "x"})
check("publish without topic_arn -> 400", s == 400, (s, b))
s, b = call("POST", "/api/console/messaging/topics/delete", {"topic_arn": arn})
check("delete topic", s == 200, (s, b))
s, b = call("GET", "/api/console/messaging/topics")
check("topic gone", s == 200 and not any(x["topic_arn"] == arn for x in b["topics"]), (s, b))
s, b = call("DELETE", f"/api/console/messaging/queues/{q}")
check("delete queue", s == 200, (s, b))
s, b = call("GET", f"/api/console/messaging/queues/{q}/peek")
check("peek deleted queue -> 404", s == 404, (s, b))

# ── secrets ─────────────────────────────────────────────────────────────
n = f"cov/secret-{U}"
s, b = call("POST", "/api/console/secrets", {"name": n, "secret_string": "v1", "description": "d"})
check("create secret -> ARN + version", s == 200 and b["arn"].startswith("arn:aws:secretsmanager:") and b["version_id"], (s, b))
s, b = call("GET", "/api/console/secrets")
check("list secrets includes it", s == 200 and any(x["name"] == n for x in b["secrets"]), (s, b))
s, b = call("GET", f"/api/console/secrets/{n}")
check("describe secret: description + AWSCURRENT", s == 200 and b["description"] == "d" and b["versions"][0]["stages"] == ["AWSCURRENT"], (s, b))
s, b = call("GET", f"/api/console/secrets/{n}/value")
check("get value", s == 200 and b["secret_string"] == "v1", (s, b))
s, b = call("POST", f"/api/console/secrets/{n}/value", {"secret_string": "v2"})
check("put new value -> new version", s == 200 and b["version_id"], (s, b))
s, b = call("GET", f"/api/console/secrets/{n}/value")
check("get value returns v2", s == 200 and b["secret_string"] == "v2", (s, b))
s, b = call("GET", f"/api/console/secrets/{n}")
check("describe shows two versions", s == 200 and len(b["versions"]) == 2, (s, b))
s, b = call("DELETE", f"/api/console/secrets/{n}")
check("delete secret", s == 200, (s, b))
s, b = call("GET", f"/api/console/secrets/{n}/value")
check("value of deleted secret -> error", s >= 400, (s, b))

# ── KMS ─────────────────────────────────────────────────────────────────
s, b = call("POST", "/api/console/kms/keys", {"description": f"cov-{U}"})
kid = b.get("key_id", "") if b else ""
check("create key -> Enabled + ARN", s == 200 and b["state"] == "Enabled" and b["arn"].endswith("key/" + kid), (s, b))
s, b = call("GET", "/api/console/kms/keys")
check("list keys includes it", s == 200 and any(x["key_id"] == kid for x in b["keys"]), (s, b))
s, b = call("GET", f"/api/console/kms/keys/{kid}")
check("describe key", s == 200 and b.get("key_id") == kid and b.get("description") == f"cov-{U}", (s, b))
s, e = call("POST", "/api/console/kms/encrypt", {"key_id": kid, "plaintext": base64.b64encode(b"top secret").decode()})
blob = (e or {}).get("ciphertext_blob", "")
check("encrypt -> ciphertext_blob", s == 200 and blob and blob != "dG9wIHNlY3JldA==", (s, e))
s, d = call("POST", "/api/console/kms/decrypt", {"ciphertext_blob": blob, "key_id": kid})
check("decrypt round-trips plaintext", s == 200 and base64.b64decode(d.get("plaintext", "")) == b"top secret", (s, d))
s, b = call("POST", "/api/console/kms/data-key", {"key_id": kid, "key_spec": "AES_256"})
check("data-key returns plaintext + wrapped key", s == 200 and len(b) >= 2, (s, b))
s, b = call("POST", "/api/console/kms/encrypt", {"plaintext": "eA=="})
check("encrypt without key_id -> 400", s == 400, (s, b))

sys.exit(1 if failed else 0)
