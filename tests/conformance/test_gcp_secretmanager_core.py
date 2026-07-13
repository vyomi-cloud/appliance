"""GCP Secret Manager core conformance — the GCP analogue of the AWS
test_secrets_core.py, in the GCS test style.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Secret Manager REST API v1** wire semantics (secret /
version resource names, ?secretId= create, :addVersion / :access custom methods,
base64 payload round-trip, auto-incrementing integer versions, "latest" alias,
delete then 404 NOT_FOUND), proving google-cloud-secret-manager can drive the
core unchanged.

Run on host:    python3 tests/conformance/test_gcp_secretmanager_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json

try:
    from core.kv_store import InMemoryKvStore
    from core import gcp_secretmanager_core as sm
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kv_store import InMemoryKvStore  # type: ignore
    import gcp_secretmanager_core as sm  # type: ignore

PROJECT = "demo-project"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def run() -> int:
    st = InMemoryKvStore()
    base = f"/v1/projects/{PROJECT}/secrets"

    # 1. create secret -> 200 secret resource with canonical name
    r = sm.dispatch(st, "POST", base, {"secretId": "db-password"},
                    {"content-type": "application/json"},
                    json.dumps({"replication": {"automatic": {}}}).encode())
    _check("create secret 200", r.status == 200)
    body = _jbody(r)
    _check("create secret name", body["name"] == f"projects/{PROJECT}/secrets/db-password")
    _check("create secret createTime present", "createTime" in body)
    _check("create secret replication echoed", body["replication"] == {"automatic": {}})

    # 1b. duplicate secret -> 409 ALREADY_EXISTS
    dup = sm.dispatch(st, "POST", base, {"secretId": "db-password"},
                      {"content-type": "application/json"},
                      json.dumps({"replication": {"automatic": {}}}).encode())
    _check("duplicate secret 409", dup.status == 409)
    _check("duplicate secret ALREADY_EXISTS", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2. addVersion -> versions/1, ENABLED
    secret1 = b"super-secret-value-1"
    av = sm.dispatch(st, "POST", f"{base}/db-password:addVersion", {},
                     {"content-type": "application/json"},
                     json.dumps({"payload": {"data": _b64(secret1)}}).encode())
    _check("addVersion 200", av.status == 200)
    avb = _jbody(av)
    _check("addVersion name versions/1", avb["name"] == f"projects/{PROJECT}/secrets/db-password/versions/1")
    _check("addVersion state ENABLED", avb["state"] == "ENABLED")

    # 3. access latest -> exact bytes round-trip via base64
    ac = sm.dispatch(st, "GET", f"{base}/db-password/versions/latest:access", {}, {}, b"")
    _check("access latest 200", ac.status == 200)
    acb = _jbody(ac)
    _check("access latest name versions/1", acb["name"].endswith("/versions/1"))
    _check("access latest bytes round-trip", base64.b64decode(acb["payload"]["data"]) == secret1)

    # 3b. access by explicit version number 1
    ac1 = sm.dispatch(st, "GET", f"{base}/db-password/versions/1:access", {}, {}, b"")
    _check("access v1 bytes round-trip", base64.b64decode(_jbody(ac1)["payload"]["data"]) == secret1)

    # 4. add second version -> versions/2 and latest reflects it
    secret2 = b"rotated-secret-value-2"
    av2 = sm.dispatch(st, "POST", f"{base}/db-password:addVersion", {},
                      {"content-type": "application/json"},
                      json.dumps({"payload": {"data": _b64(secret2)}}).encode())
    _check("addVersion 2 name versions/2", _jbody(av2)["name"].endswith("/versions/2"))
    ac2 = sm.dispatch(st, "GET", f"{base}/db-password/versions/latest:access", {}, {}, b"")
    acb2 = _jbody(ac2)
    _check("latest now versions/2", acb2["name"].endswith("/versions/2"))
    _check("latest bytes = second version", base64.b64decode(acb2["payload"]["data"]) == secret2)
    # v1 still independently accessible
    ac1b = sm.dispatch(st, "GET", f"{base}/db-password/versions/1:access", {}, {}, b"")
    _check("v1 still returns first bytes", base64.b64decode(_jbody(ac1b)["payload"]["data"]) == secret1)

    # 5. list secrets + list versions
    ls = sm.dispatch(st, "GET", base, {}, {}, b"")
    lsb = _jbody(ls)
    _check("list secrets totalSize 1", lsb["totalSize"] == 1)
    _check("list secrets has db-password",
           any(s["name"].endswith("/secrets/db-password") for s in lsb["secrets"]))
    lv = sm.dispatch(st, "GET", f"{base}/db-password/versions", {}, {}, b"")
    lvb = _jbody(lv)
    _check("list versions has both", lvb["totalSize"] == 2)

    # 6. delete secret -> 200, then access -> 404 NOT_FOUND
    dele = sm.dispatch(st, "DELETE", f"{base}/db-password", {}, {}, b"")
    _check("delete secret 200", dele.status == 200)
    miss = sm.dispatch(st, "GET", f"{base}/db-password/versions/latest:access", {}, {}, b"")
    _check("deleted secret access 404", miss.status == 404)
    _check("deleted secret NOT_FOUND", _jbody(miss)["error"]["status"] == "NOT_FOUND")

    print("\nGCP Secret Manager core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
