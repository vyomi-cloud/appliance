"""Azure Key Vault keys (data plane) conformance — the Azure analogue of
test_gcp_storage_core.py / test_kms_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Key Vault Keys REST API** wire semantics (create → kid
ends /keys/{name}/{version} with a 32-hex version, kty:"RSA" + base64url n/e;
encrypt → ciphertext ≠ plaintext carrying the kid; decrypt recovers the exact
plaintext through a base64url round-trip; get latest + get by version; list
includes the name; unknown key → 404 KeyNotFound), proving azure-keyvault-keys
can drive the core unchanged.

Run on host:    python3 tests/conformance/test_azure_keyvault_keys_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json
import re

try:
    from core.kms_keystore import InMemoryKeyStore
    from core import azure_keyvault_keys_core as kv
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import azure_keyvault_keys_core as kv  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64url_d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


API = {"api-version": "7.4"}


def run() -> int:
    st = InMemoryKeyStore()

    # 1. create key -> kid ends /keys/{name}/{version}, RSA + base64url n/e
    cr = kv.dispatch(st, "POST", "/keys/mykey/create", API,
                     {"content-type": "application/json"},
                     json.dumps({"kty": "RSA", "key_size": 2048,
                                 "key_ops": ["encrypt", "decrypt"]}).encode())
    _check("create 200", cr.status == 200)
    cb = _jbody(cr)
    kid = cb["key"]["kid"]
    _check("create kid host+name", kid.startswith("https://") and "/keys/mykey/" in kid)
    version = kid.rsplit("/", 1)[1]
    _check("create version 32-hex", bool(re.fullmatch(r"[0-9a-f]{32}", version)))
    _check("create kty RSA", cb["key"]["kty"] == "RSA")
    _check("create key_ops echoed", cb["key"]["key_ops"] == ["encrypt", "decrypt"])
    _check("create attributes enabled", cb["attributes"]["enabled"] is True)
    # n/e are base64url (decode must succeed with the -/_ alphabet, no padding)
    n_raw = _b64url_d(cb["key"]["n"])
    _check("n base64url decodes to 256 bytes (2048-bit)", len(n_raw) == 256)
    _check("n has no padding", "=" not in cb["key"]["n"])
    _check("e is AQAB (65537)", cb["key"]["e"] == "AQAB")

    # 2. encrypt -> ciphertext != plaintext, carries the kid
    plaintext = b"attack at dawn \x00\xff binary too"
    en = kv.dispatch(st, "POST", f"/keys/mykey/{version}/encrypt", API,
                     {"content-type": "application/json"},
                     json.dumps({"alg": "RSA-OAEP", "value": _b64url(plaintext)}).encode())
    _check("encrypt 200", en.status == 200)
    eb = _jbody(en)
    ct = _b64url_d(eb["value"])
    _check("encrypt kid present", eb["kid"].endswith(f"/keys/mykey/{version}"))
    _check("ciphertext != plaintext", ct != plaintext)
    _check("encrypt value has no padding", "=" not in eb["value"])

    # 3. decrypt -> recovers the exact plaintext (base64url round-trip)
    de = kv.dispatch(st, "POST", f"/keys/mykey/{version}/decrypt", API,
                     {"content-type": "application/json"},
                     json.dumps({"alg": "RSA-OAEP", "value": eb["value"]}).encode())
    _check("decrypt 200", de.status == 200)
    recovered = _b64url_d(_jbody(de)["value"])
    _check("decrypt recovers exact plaintext", recovered == plaintext)

    # 3b. tamper the ciphertext -> rejected
    bad = bytearray(ct)
    bad[-1] ^= 0x01
    dt = kv.dispatch(st, "POST", f"/keys/mykey/{version}/decrypt", API,
                     {"content-type": "application/json"},
                     json.dumps({"value": _b64url(bytes(bad))}).encode())
    _check("tampered ciphertext rejected", dt.status == 400)

    # 4. get key (latest) + get by version
    gl = kv.dispatch(st, "GET", "/keys/mykey", API, {}, b"")
    _check("get latest 200", gl.status == 200)
    _check("get latest kid matches", _jbody(gl)["key"]["kid"] == kid)
    gv = kv.dispatch(st, "GET", f"/keys/mykey/{version}", API, {}, b"")
    _check("get by version 200", gv.status == 200)
    _check("get by version kid matches", _jbody(gv)["key"]["kid"] == kid)

    # 5. second key + list includes both names
    kv.dispatch(st, "POST", "/keys/second/create", API,
                {"content-type": "application/json"},
                json.dumps({"kty": "RSA"}).encode())
    ls = kv.dispatch(st, "GET", "/keys", API, {}, b"")
    _check("list 200", ls.status == 200)
    kids = [v["kid"] for v in _jbody(ls)["value"]]
    _check("list includes mykey", any("/keys/mykey/" in k for k in kids))
    _check("list includes second", any("/keys/second/" in k for k in kids))

    # 6. unknown key -> 404 KeyNotFound
    nf = kv.dispatch(st, "GET", "/keys/nope", API, {}, b"")
    _check("unknown key 404", nf.status == 404)
    _check("unknown key code KeyNotFound", _jbody(nf)["error"]["code"] == "KeyNotFound")
    nfe = kv.dispatch(st, "POST", "/keys/nope/abc/encrypt", API,
                      {"content-type": "application/json"},
                      json.dumps({"value": _b64url(b"x")}).encode())
    _check("encrypt unknown key 404 KeyNotFound",
           nfe.status == 404 and _jbody(nfe)["error"]["code"] == "KeyNotFound")

    # 7. delete key -> 200, then get -> 404
    dl = kv.dispatch(st, "DELETE", "/keys/mykey", API, {}, b"")
    _check("delete 200", dl.status == 200)
    _check("delete returns recoveryId", "recoveryId" in _jbody(dl))
    gone = kv.dispatch(st, "GET", "/keys/mykey", API, {}, b"")
    _check("deleted key 404", gone.status == 404 and _jbody(gone)["error"]["code"] == "KeyNotFound")

    print("\nAzure Key Vault keys-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
