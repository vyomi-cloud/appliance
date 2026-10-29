"""Azure console lens routes: Key Vault secrets/keys (/api/console/azure-kv-*),
Blob containers/blobs (/api/console/azure-blob/*) and Functions (/api/console/azure-functions/*)."""
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


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=60, **kw)


def key_vault(tag):
    name = f"lens-sec-{tag}"
    sp = "/api/console/azure-kv-secrets/secrets"
    r = call("POST", sp, json={"name": name, "secret_string": "one", "description": "d"})
    check("create secret", r.status_code < 300, r.text[:150])
    r = call("GET", sp)
    check("secret listed", r.ok and name in r.text, r.text[:200])
    r = call("GET", f"{sp}/{name}")
    check("describe secret", r.ok and name in r.text, r.text[:150])
    r = call("POST", f"{sp}/{name}/value", json={"secret_string": "two"})
    check("add secret version", r.status_code < 300, r.text[:150])
    r = call("GET", f"{sp}/{name}/value")
    check("value is newest version", r.ok and "two" in r.text, r.text[:150])
    r = call("DELETE", f"{sp}/{name}")
    check("delete secret", r.status_code < 300, r.text[:150])
    r = call("GET", f"{sp}/{name}")
    check("deleted secret no longer describes", r.status_code >= 400, r.text[:150])

    kp = "/api/console/azure-kv-keys/keys"
    r = call("POST", kp, json={"description": f"lens-{tag}"})
    check("create key", r.status_code < 300, r.text[:150])
    body = r.json() if r.ok else {}
    kid = body.get("key_id") or body.get("KeyId") or (body.get("key") or {}).get("key_id") or ""
    check("key has an id", bool(kid), body)
    r = call("GET", kp)
    check("key listed", r.ok and kid and kid in r.text, r.text[:200])
    r = call("GET", f"{kp}/{kid}")
    check("describe key", r.ok and kid in r.text, r.text[:150])
    r = call("POST", "/api/console/azure-kv-keys/encrypt", json={"key_id": kid, "plaintext": "aGVsbG8="})
    check("encrypt", r.ok, r.text[:150])
    blob = r.json().get("ciphertext_blob", "") if r.ok else ""
    r = call("POST", "/api/console/azure-kv-keys/decrypt", json={"ciphertext_blob": blob, "key_id": kid})
    check("decrypt round trip", r.ok and "aGVsbG8=" in r.text, r.text[:150])
    r = call("POST", "/api/console/azure-kv-keys/data-key", json={"key_id": kid})
    check("data key", r.ok, r.text[:150])
    r = call("POST", "/api/console/azure-kv-keys/encrypt", json={"plaintext": "x"})
    check("encrypt without key_id is 400", r.status_code == 400, r.status_code)
    r = call("POST", "/api/console/azure-kv-keys/decrypt", json={})
    check("decrypt without ciphertext is 400", r.status_code == 400, r.status_code)
    r = call("POST", "/api/console/azure-kv-keys/data-key", json={})
    check("data key without key_id is 400", r.status_code == 400, r.status_code)


def blob(tag):
    c = f"lens{tag}"
    bp = "/api/console/azure-blob/containers"
    r = call("POST", f"{bp}/{c}")
    check("create container", r.status_code < 300, r.text[:150])
    r = call("GET", bp)
    check("container listed", r.ok and c in r.text, r.text[:200])
    r = call("POST", f"{bp}/{c}/blobs", json={"key": "dir/a.txt", "content": "hello azure"})
    check("upload blob (json)", r.status_code < 300, r.text[:150])
    r = call("POST", f"{bp}/{c}/blobs", files={"file": ("b.txt", b"multipart body", "text/plain")})
    check("upload blob (multipart)", r.status_code < 300, r.text[:150])
    r = call("GET", f"{bp}/{c}/blobs")
    check("blobs listed", r.ok and "a.txt" in r.text and "b.txt" in r.text, r.text[:200])
    r = call("GET", f"{bp}/{c}/blobs", params={"prefix": "dir/"})
    check("prefix filter", r.ok and "a.txt" in r.text and "b.txt" not in r.text, r.text[:200])
    r = call("GET", f"{bp}/{c}/blobs/dir/a.txt/meta")
    check("blob meta", r.ok and "a.txt" in r.text, r.text[:150])
    r = call("GET", f"{bp}/{c}/blobs/dir/a.txt/download")
    check("blob download", r.ok and r.content == b"hello azure", r.content[:80])
    r = call("GET", f"{bp}/{c}/blobs/nope.txt/meta")
    check("missing blob meta is 404", r.status_code == 404, r.status_code)


def functions(tag):
    name = f"lensfn{tag}"
    fp = "/api/console/azure-functions/functions"
    r = call("POST", fp, json={})
    check("create function without name is 400", r.status_code == 400, r.status_code)
    r = call("POST", fp, json={"function_name": name, "code": "def main(event):\n    return {'ok': True}\n"})
    check("create function", r.status_code < 300, r.text[:150])
    r = call("GET", fp)
    check("function listed", r.ok and name in r.text, r.text[:200])
    r = call("GET", f"{fp}/{name}")
    check("get function", r.ok and name in r.text, r.text[:150])
    r = call("POST", f"{fp}/{name}/invoke", json={"payload": {"x": 1}})
    check("invoke function", r.status_code < 300, r.text[:200])
    r = call("DELETE", f"{fp}/{name}")
    check("delete function", r.status_code < 300, r.text[:150])
    r = call("GET", f"{fp}/{name}")
    check("deleted function is gone", r.status_code >= 400, r.text[:150])


def main():
    tag = uuid.uuid4().hex[:6]
    key_vault(tag)
    blob(tag)
    functions(tag)
    sys.exit(1 if failed else 0)


main()
