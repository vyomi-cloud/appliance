"""Azure Key Vault secrets-core conformance — the Azure analogue of
test_gcp_storage_core.py / test_secrets_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Key Vault Secrets REST API** wire semantics (versioned
secret bundles, full https `id` including version, unix-epoch attributes, list
secrets/versions envelopes with nextLink, soft-delete bundle with recoveryId,
SecretNotFound 404 errors), proving azure-keyvault-secrets can drive the core
unchanged.

Run on host:    python3 tests/conformance/test_azure_keyvault_secrets_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.kv_store import InMemoryKvStore
    from core import azure_keyvault_secrets_core as kv
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kv_store import InMemoryKvStore  # type: ignore
    import azure_keyvault_secrets_core as kv  # type: ignore

API = {"api-version": "7.4"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = InMemoryKvStore()

    # 1. set secret -> 200, id has /secrets/{name}/{version} (32-hex) + value echoed
    r = kv.dispatch(st, "PUT", "/secrets/db-password", API,
                    {"content-type": "application/json"},
                    json.dumps({"value": "s3cr3t-v1", "contentType": "text/plain",
                                "tags": {"env": "prod"}}).encode())
    _check("set secret 200", r.status == 200)
    b1 = _jbody(r)
    _check("set secret value echoed", b1["value"] == "s3cr3t-v1")
    _check("set secret id is full https url", b1["id"].startswith("https://") and "/secrets/db-password/" in b1["id"])
    v1 = b1["id"].rsplit("/", 1)[1]
    _check("version is 32-hex", len(v1) == 32 and all(c in "0123456789abcdef" for c in v1))
    _check("attributes enabled", b1["attributes"]["enabled"] is True)
    _check("attributes created is int epoch", isinstance(b1["attributes"]["created"], int))
    _check("contentType echoed", b1["contentType"] == "text/plain")
    _check("tags echoed", b1["tags"] == {"env": "prod"})

    # 2. get current == the version just set
    g = kv.dispatch(st, "GET", "/secrets/db-password", API, {}, b"")
    _check("get current 200", g.status == 200)
    bg = _jbody(g)
    _check("get current value", bg["value"] == "s3cr3t-v1")
    _check("get current id == v1", bg["id"].rsplit("/", 1)[1] == v1)

    # 3. set 2nd version -> new version id, current reflects it
    r2 = kv.dispatch(st, "PUT", "/secrets/db-password", API,
                     {"content-type": "application/json"},
                     json.dumps({"value": "s3cr3t-v2"}).encode())
    _check("set v2 200", r2.status == 200)
    b2 = _jbody(r2)
    v2 = b2["id"].rsplit("/", 1)[1]
    _check("v2 is a new version", v2 != v1 and len(v2) == 32)
    cur = kv.dispatch(st, "GET", "/secrets/db-password", API, {}, b"")
    _check("current reflects v2", _jbody(cur)["value"] == "s3cr3t-v2")

    # 4. 1st version still returns the old value
    old = kv.dispatch(st, "GET", f"/secrets/db-password/{v1}", API, {}, b"")
    _check("get v1 by version 200", old.status == 200)
    _check("v1 still holds old value", _jbody(old)["value"] == "s3cr3t-v1")

    # 5. list versions includes both
    lv = kv.dispatch(st, "GET", "/secrets/db-password/versions", API, {}, b"")
    _check("list versions 200", lv.status == 200)
    vids = {it["id"].rsplit("/", 1)[1] for it in _jbody(lv)["value"]}
    _check("list versions has both", v1 in vids and v2 in vids)
    _check("list versions nextLink null", _jbody(lv)["nextLink"] is None)

    # 6. list secrets includes the name
    ls = kv.dispatch(st, "GET", "/secrets", API, {}, b"")
    _check("list secrets 200", ls.status == 200)
    ids = [it["id"] for it in _jbody(ls)["value"]]
    _check("list secrets includes db-password", any(i.endswith("/secrets/db-password") for i in ids))
    _check("list secrets nextLink null", _jbody(ls)["nextLink"] is None)

    # 7. delete -> deleted bundle w/ recoveryId, then get 404 SecretNotFound
    d = kv.dispatch(st, "DELETE", "/secrets/db-password", API, {}, b"")
    _check("delete 200", d.status == 200)
    bd = _jbody(d)
    _check("delete bundle has recoveryId", bd["recoveryId"].endswith("/deletedsecrets/db-password"))
    _check("delete bundle has deletedDate", isinstance(bd["deletedDate"], int))
    miss = kv.dispatch(st, "GET", "/secrets/db-password", API, {}, b"")
    _check("deleted get 404", miss.status == 404)
    _check("deleted get SecretNotFound", _jbody(miss)["error"]["code"] == "SecretNotFound")

    # 8. get an entirely unknown secret -> 404 SecretNotFound
    unk = kv.dispatch(st, "GET", "/secrets/never-existed", API, {}, b"")
    _check("unknown secret 404", unk.status == 404 and _jbody(unk)["error"]["code"] == "SecretNotFound")

    # 9. missing api-version -> 400
    noapi = kv.dispatch(st, "GET", "/secrets/db-password", {}, {}, b"")
    _check("missing api-version 400", noapi.status == 400)

    # 10. any 7.x api-version accepted
    v75 = kv.dispatch(st, "PUT", "/secrets/other", {"api-version": "7.5"},
                      {"content-type": "application/json"},
                      json.dumps({"value": "x"}).encode())
    _check("api-version 7.5 accepted", v75.status == 200)

    print("\nAzure Key Vault secrets-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
