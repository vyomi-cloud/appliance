"""/api/console/azure-{cosmos,servicebus,kv-secrets,kv-keys}/* — the data-plane facades behind the Azure console."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000") + "/api/console"
failed = False
SB = "sb://vyomi-sb.servicebus.windows.net"


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def call(method, path, **kw):
    r = requests.request(method, BASE + path, timeout=30, **kw)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def cosmos(sfx):
    c = f"cvc{sfx}"
    s, b = call("POST", "/azure-cosmos/containers", json={"name": c})
    check("cosmos create container returns an ACTIVE container with a dbs/…/colls/ resource id",
          s == 200 and b["table"]["table_status"] == "ACTIVE" and b["table"]["table_arn"].endswith(f"/colls/{c}"))
    s, b = call("GET", "/azure-cosmos/containers")
    check("cosmos list contains the container", c in b.get("table_names", []))
    s, b = call("GET", f"/azure-cosmos/containers/{c}")
    check("cosmos get container", s == 200 and b["table"]["table_name"] == c)
    s, b = call("POST", f"/azure-cosmos/containers/{c}/items", json={"item": {"id": "a", "v": 1}})
    check("cosmos upsert document", s == 200 and b["item"]["item"]["v"] == 1)
    s, b = call("GET", f"/azure-cosmos/containers/{c}/items")
    check("cosmos list documents", b.get("count") == 1)
    s, b = call("POST", f"/azure-cosmos/containers/{c}/query", json={"partition_key_value": "a"})
    check("cosmos query by partition key finds the document", b.get("count") == 1)
    s, b = call("DELETE", f"/azure-cosmos/containers/{c}/items", json={"key": {"id": "a"}})
    check("cosmos delete document", s == 200 and b.get("deleted") is True)
    s, b = call("GET", f"/azure-cosmos/containers/{c}/items")
    check("cosmos container empty after delete", b.get("count") == 0)
    s, b = call("DELETE", f"/azure-cosmos/containers/{c}")
    check("cosmos delete container", s == 200 and b.get("deleted") is True)


def servicebus(sfx):
    q, t = f"cvq{sfx}", f"cvt{sfx}"
    ta = f"{SB}/{t}"
    s, b = call("POST", "/azure-servicebus/queues", json={"name": q})
    check("servicebus create queue has an sb:// url", s == 200 and b["queue_url"] == f"{SB}/{q}")
    s, b = call("POST", f"/azure-servicebus/queues/{q}/send", json={"body": "hello"})
    check("servicebus send returns a message id", bool(b.get("message_id")))
    s, b = call("GET", f"/azure-servicebus/queues/{q}/peek")
    check("servicebus peek shows the message without consuming it",
          b.get("count") == 1 and b["messages"][0]["Body"] == "hello" and b["messages"][0]["receive_count"] == 0)
    s, b = call("POST", f"/azure-servicebus/queues/{q}/receive", json={})
    check("servicebus receive returns the message", b.get("count") == 1 and b["messages"][0]["Body"] == "hello")
    s, b = call("POST", f"/azure-servicebus/queues/{q}/purge")
    check("servicebus purge", b.get("purged") is True)
    s, b = call("POST", "/azure-servicebus/topics", json={"name": t})
    check("servicebus create topic", b.get("topic_arn") == ta)
    s, b = call("GET", "/azure-servicebus/topics")
    check("servicebus list topics", any(x["topic_arn"] == ta for x in b.get("topics", [])))
    s, b = call("POST", "/azure-servicebus/topics/subscribe", json={"topic_arn": ta, "queue": q})
    check("servicebus subscribe queue to topic", b.get("subscribed") is True)
    s, b = call("GET", "/azure-servicebus/topics/subscriptions", params={"topic_arn": ta})
    check("servicebus list subscriptions", b.get("count") == 1 and b["subscriptions"][0]["queue"] == q)
    s, b = call("POST", "/azure-servicebus/topics/publish", json={"topic_arn": ta, "message": "m1", "subject": "s"})
    check("servicebus publish fans out to the subscribed queue", b.get("fanned_out_to") == 1)
    s, b = call("GET", f"/azure-servicebus/queues/{q}/peek")
    check("servicebus published message landed in the queue", b.get("count") == 1 and "m1" in b["messages"][0]["Body"])
    s, b = call("POST", "/azure-servicebus/topics/delete", json={"topic_arn": ta})
    check("servicebus delete topic", b.get("deleted") is True)
    s, b = call("DELETE", f"/azure-servicebus/queues/{q}")
    check("servicebus delete queue", b.get("deleted") is True)


def secrets(sfx):
    n = f"cvs{sfx}"
    s, b = call("POST", "/azure-kv-secrets/secrets", json={"name": n, "secret_string": "v1", "description": "d"})
    check("kv secret create returns a vault.azure.net versioned id",
          s == 200 and b["arn"].startswith(f"https://vyomi-kv.vault.azure.net/secrets/{n}/") and b["version_id"])
    s, b = call("GET", "/azure-kv-secrets/secrets")
    check("kv secret list", any(x["name"] == n for x in b.get("secrets", [])))
    s, b = call("GET", f"/azure-kv-secrets/secrets/{n}")
    check("kv secret describe has one current version", len(b.get("versions", [])) == 1)
    s, b = call("POST", f"/azure-kv-secrets/secrets/{n}/value", json={"secret_string": "v2"})
    check("kv secret put value creates a new version", s == 200 and bool(b.get("version_id")))
    s, b = call("GET", f"/azure-kv-secrets/secrets/{n}/value")
    check("kv secret value returns the latest value", b.get("secret_string") == "v2")
    s, b = call("DELETE", f"/azure-kv-secrets/secrets/{n}")
    check("kv secret delete", b.get("deleted") is True)


def keys():
    s, b = call("POST", "/azure-kv-keys/keys", json={"description": "conformance"})
    kid = b.get("key_id", "")
    check("kv key create returns a Key Vault key uri, not an AWS ARN",
          s == 200 and b.get("arn") == f"https://vyomi-kv.vault.azure.net/keys/{kid}")
    s, b = call("GET", "/azure-kv-keys/keys")
    mine = [k for k in b.get("keys", []) if k["key_id"] == kid]
    check("kv key list uses Key Vault key uris", bool(mine) and mine[0]["arn"].startswith("https://") and "aws" not in mine[0]["arn"])
    s, b = call("GET", f"/azure-kv-keys/keys/{kid}")
    check("kv key describe uses a Key Vault key uri and is Enabled",
          b.get("arn", "").endswith(f"/keys/{kid}") and b.get("state") == "Enabled")
    pt = base64.b64encode(b"hello vault").decode()
    s, b = call("POST", "/azure-kv-keys/encrypt", json={"key_id": kid, "plaintext": pt})
    ct = b.get("ciphertext_blob", "")
    check("kv key encrypt returns ciphertext", s == 200 and bool(ct) and ct != pt)
    s, b = call("POST", "/azure-kv-keys/decrypt", json={"ciphertext_blob": ct})
    check("kv key decrypt round-trips the plaintext", b.get("plaintext") == pt)
    s, b = call("POST", "/azure-kv-keys/data-key", json={"key_id": kid})
    check("kv key data-key returns plaintext and wrapped key", bool(b.get("plaintext")) and bool(b.get("ciphertext_blob")))


def blob(sfx):
    c = f"cvb{sfx}"
    s, b = call("POST", f"/azure-blob/containers/{c}")
    check("blob create container", s == 200)
    s, b = call("GET", "/azure-blob/containers")
    names = [x.get("name") or x.get("bucket_name") or x.get("Name") for x in (b.get("containers") or b.get("buckets") or [])]
    check("blob list containers contains it", c in names)


def main():
    sfx = uuid.uuid4().hex[:6]
    cosmos(sfx)
    servicebus(sfx)
    secrets(sfx)
    keys()
    blob(sfx)
    sys.exit(1 if failed else 0)


main()
