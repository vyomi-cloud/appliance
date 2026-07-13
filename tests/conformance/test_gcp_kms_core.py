"""GCP Cloud KMS core conformance — the GCP analogue of test_kms_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Cloud KMS REST API v1** wire semantics (keyRing / cryptoKey
resources, base64 plaintext/ciphertext, `:encrypt` / `:decrypt` custom methods,
Google `{"error":{...,"status"}}` shape), proving google-cloud-kms / gcloud kms can
drive the core unchanged. The envelope crypto is the SAME reused KeyStore/KmsEngine
seam as AWS KMS, so encrypt/decrypt round-trip with real authenticated crypto.

Run on host:    python3 tests/conformance/test_gcp_kms_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import json

try:
    from core.kms_keystore import InMemoryKeyStore
    from core import gcp_kms_core as gkms
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import gcp_kms_core as gkms  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


def run() -> int:
    st = InMemoryKeyStore()
    LOC = "/v1/projects/demo/locations/global"
    RING = f"{LOC}/keyRings/app-ring"
    KEY = f"{RING}/cryptoKeys/app-key"
    ring_name = "projects/demo/locations/global/keyRings/app-ring"
    key_name = f"{ring_name}/cryptoKeys/app-key"

    # 1. create key ring
    r = gkms.dispatch(st, "POST", f"{LOC}/keyRings", {"keyRingId": "app-ring"}, {}, b"{}")
    _check("create keyRing 200", r.status == 200)
    _check("create keyRing name", _jbody(r)["name"] == ring_name)
    _check("create keyRing createTime", "createTime" in _jbody(r))

    # 1b. duplicate key ring -> 409 ALREADY_EXISTS
    dup = gkms.dispatch(st, "POST", f"{LOC}/keyRings", {"keyRingId": "app-ring"}, {}, b"{}")
    _check("duplicate keyRing 409", dup.status == 409)
    _check("duplicate keyRing status", _jbody(dup)["error"]["status"] == "ALREADY_EXISTS")

    # 2. get key ring + list key rings
    gr = gkms.dispatch(st, "GET", RING, {}, {}, b"")
    _check("get keyRing 200", gr.status == 200 and _jbody(gr)["name"] == ring_name)
    lr = gkms.dispatch(st, "GET", f"{LOC}/keyRings", {}, {}, b"")
    _check("list keyRings has ring", any(k["name"] == ring_name for k in _jbody(lr)["keyRings"]))

    # 3. create crypto key
    ck = gkms.dispatch(st, "POST", f"{RING}/cryptoKeys", {"cryptoKeyId": "app-key"},
                       {"content-type": "application/json"},
                       json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
    _check("create cryptoKey 200", ck.status == 200)
    cko = _jbody(ck)
    _check("create cryptoKey name", cko["name"] == key_name)
    _check("create cryptoKey purpose", cko["purpose"] == "ENCRYPT_DECRYPT")
    _check("create cryptoKey primary version", cko["primary"]["name"].endswith("/cryptoKeyVersions/1"))
    _check("create cryptoKey primary enabled", cko["primary"]["state"] == "ENABLED")

    # 3b. create crypto key on unknown ring -> 404
    badring = gkms.dispatch(st, "POST", f"{LOC}/keyRings/nope/cryptoKeys",
                            {"cryptoKeyId": "k"}, {}, b"{}")
    _check("cryptoKey on missing ring 404", badring.status == 404)

    # 4. get crypto key + list crypto keys
    gk = gkms.dispatch(st, "GET", KEY, {}, {}, b"")
    _check("get cryptoKey 200", gk.status == 200 and _jbody(gk)["name"] == key_name)
    lk = gkms.dispatch(st, "GET", f"{RING}/cryptoKeys", {}, {}, b"")
    _check("list cryptoKeys has key", any(k["name"] == key_name for k in _jbody(lk)["cryptoKeys"]))

    # 5. encrypt -> ciphertext != plaintext, echoes the crypto key name
    secret = b"the launch codes are 0000"
    enc = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {},
                        {"content-type": "application/json"},
                        json.dumps({"plaintext": base64.b64encode(secret).decode()}).encode())
    _check("encrypt 200", enc.status == 200)
    eo = _jbody(enc)
    _check("encrypt name is cryptoKey", eo["name"] == key_name)
    _check("encrypt returns ciphertext", bool(eo.get("ciphertext")))
    ciphertext = base64.b64decode(eo["ciphertext"])
    _check("ciphertext != plaintext", ciphertext != secret)

    # 5b. empty plaintext -> 400 INVALID_ARGUMENT
    empty = gkms.dispatch(st, "POST", f"{KEY}:encrypt", {},
                          {"content-type": "application/json"},
                          json.dumps({"plaintext": ""}).encode())
    _check("empty plaintext 400", empty.status == 400 and
           _jbody(empty)["error"]["status"] == "INVALID_ARGUMENT")

    # 6. decrypt -> recovers the EXACT plaintext
    dec = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {},
                        {"content-type": "application/json"},
                        json.dumps({"ciphertext": eo["ciphertext"]}).encode())
    _check("decrypt 200", dec.status == 200)
    recovered = base64.b64decode(_jbody(dec)["plaintext"])
    _check("decrypt round-trips exact plaintext", recovered == secret)

    # 6b. tampered ciphertext -> 400 (authenticated crypto rejects it)
    bad = bytearray(ciphertext)
    bad[-1] ^= 0xFF
    tamper = gkms.dispatch(st, "POST", f"{KEY}:decrypt", {},
                           {"content-type": "application/json"},
                           json.dumps({"ciphertext": base64.b64encode(bytes(bad)).decode()}).encode())
    _check("tampered ciphertext 400", tamper.status == 400)

    # 7. get / encrypt on unknown crypto key -> 404 NOT_FOUND
    miss = gkms.dispatch(st, "GET", f"{RING}/cryptoKeys/ghost", {}, {}, b"")
    _check("unknown cryptoKey 404", miss.status == 404)
    _check("unknown cryptoKey status", _jbody(miss)["error"]["status"] == "NOT_FOUND")
    missenc = gkms.dispatch(st, "POST", f"{RING}/cryptoKeys/ghost:encrypt", {},
                            {"content-type": "application/json"},
                            json.dumps({"plaintext": base64.b64encode(b"x").decode()}).encode())
    _check("encrypt unknown key 404", missenc.status == 404)

    print("\nGCP Cloud KMS core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
