"""Azure Key Vault certificates-core conformance — the Azure analogue of
test_azure_keyvault_secrets_core.py / test_azure_keyvault_keys_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on
both. It asserts the native **Key Vault Certificates REST API** wire semantics
(create completes synchronously with a certificate bundle, full https `id`
including a 32-hex version, unix-epoch attributes with an expiration derived
from the policy's validity, list envelope with nextLink, soft-delete bundle
with recoveryId, CertificateNotFound 404 errors).

Run on host:    python3 tests/conformance/test_azure_keyvault_certificates_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.kv_store import InMemoryKvStore
    from core import azure_keyvault_certificates_core as kv
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kv_store import InMemoryKvStore  # type: ignore
    import azure_keyvault_certificates_core as kv  # type: ignore

API = {"api-version": "7.4"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = InMemoryKvStore()

    # 1. create (self-signed, completes synchronously) -> 200, full https id w/ 32-hex version
    r = kv.dispatch(st, "POST", "/certificates/tls-cert/create", API,
                     {"content-type": "application/json"},
                     json.dumps({"policy": {"x509_certificate_properties": {"validity_in_months": 6}},
                                 "tags": {"env": "prod"}}).encode())
    _check("create 200", r.status == 200)
    b1 = _jbody(r)
    _check("create id is full https url", b1["id"].startswith("https://") and "/certificates/tls-cert/" in b1["id"])
    v1 = b1["id"].rsplit("/", 1)[1]
    _check("version is 32-hex", len(v1) == 32 and all(c in "0123456789abcdef" for c in v1))
    _check("x5t present", isinstance(b1["x5t"], str) and len(b1["x5t"]) > 0)
    _check("cer present", isinstance(b1["cer"], str) and len(b1["cer"]) > 0)
    _check("attributes enabled", b1["attributes"]["enabled"] is True)
    _check("attributes created is int epoch", isinstance(b1["attributes"]["created"], int))
    _check("expiration derived from validity", b1["attributes"]["exp"] - b1["attributes"]["created"] == 6 * 30 * 24 * 3600)
    _check("tags echoed", b1["tags"] == {"env": "prod"})

    # 2. get latest == what create returned
    g = kv.dispatch(st, "GET", "/certificates/tls-cert", API, {}, b"")
    _check("get 200", g.status == 200)
    bg = _jbody(g)
    _check("get id matches create", bg["id"] == b1["id"])
    _check("get x5t matches create (deterministic)", bg["x5t"] == b1["x5t"])

    # 3. re-create (renew) -> a new version
    r2 = kv.dispatch(st, "POST", "/certificates/tls-cert/create", API,
                      {"content-type": "application/json"}, json.dumps({}).encode())
    _check("recreate 200", r2.status == 200)
    v2 = _jbody(r2)["id"].rsplit("/", 1)[1]
    _check("recreate is a new version", v2 != v1)
    _check("recreate default validity 12mo",
           _jbody(r2)["attributes"]["exp"] - _jbody(r2)["attributes"]["created"] == 12 * 30 * 24 * 3600)

    # 4. list includes the name
    ls = kv.dispatch(st, "GET", "/certificates", API, {}, b"")
    _check("list 200", ls.status == 200)
    ids = [it["id"] for it in _jbody(ls)["value"]]
    _check("list includes tls-cert", any(i.endswith("/certificates/tls-cert") for i in ids))
    _check("list nextLink null", _jbody(ls)["nextLink"] is None)

    # 5. delete -> deleted bundle w/ recoveryId, then get 404 CertificateNotFound
    d = kv.dispatch(st, "DELETE", "/certificates/tls-cert", API, {}, b"")
    _check("delete 200", d.status == 200)
    bd = _jbody(d)
    _check("delete bundle has recoveryId", bd["recoveryId"].endswith("/deletedcertificates/tls-cert"))
    _check("delete bundle has deletedDate", isinstance(bd["deletedDate"], int))
    miss = kv.dispatch(st, "GET", "/certificates/tls-cert", API, {}, b"")
    _check("deleted get 404", miss.status == 404)
    _check("deleted get CertificateNotFound", _jbody(miss)["error"]["code"] == "CertificateNotFound")

    # 6. get an entirely unknown certificate -> 404 CertificateNotFound
    unk = kv.dispatch(st, "GET", "/certificates/never-existed", API, {}, b"")
    _check("unknown certificate 404", unk.status == 404 and _jbody(unk)["error"]["code"] == "CertificateNotFound")

    # 7. missing api-version -> 400
    noapi = kv.dispatch(st, "GET", "/certificates/tls-cert", {}, {}, b"")
    _check("missing api-version 400", noapi.status == 400)

    print("\nAzure Key Vault certificates-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
