"""GCP Cloud KMS key import conformance: importJobs + cryptoKeyVersions:import
(RSA-OAEP + AES-KWP wrapped key material) and an encrypt/decrypt round-trip with the
imported material. Run: PYTHONPATH=. python tests/conformance/test_gcp_kms_import_core.py"""
import base64
import json
import os

try:
    from core.kms_keystore import InMemoryKeyStore
    from core import gcp_kms_core as gk, gcp_kms_import as imp
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import InMemoryKeyStore  # type: ignore
    import gcp_kms_core as gk  # type: ignore
    import gcp_kms_import as imp  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode())


def _call(st, m, path, body=None, q=None):
    return gk.dispatch(st, m, path, q or {}, {}, json.dumps(body or {}).encode())


def run() -> int:
    st = InMemoryKeyStore()
    LOC = "/v1/projects/demo/locations/global"
    RING = f"{LOC}/keyRings/imp"
    _call(st, "POST", f"{LOC}/keyRings", {}, {"keyRingId": "imp"})
    # AES-KWP / RSA-OAEP primitives
    rk = imp._expand_key(bytes(range(32)))
    _check("AES-256 FIPS-197 vector", imp._aes_encrypt_block(rk, bytes.fromhex("00112233445566778899aabbccddeeff")).hex() == "8ea2b7ca516745bfeafc49904b496089")
    for n in (1, 8, 32, 33):
        kek, x = os.urandom(32), os.urandom(n)
        _check(f"KWP round-trip {n}B", imp.kwp_unwrap(kek, imp.kwp_wrap(kek, x)) == x)

    # job validation
    r = _call(st, "POST", f"{RING}/importJobs", {"importMethod": "NOPE"}, {"importJobId": "j"})
    _check("bad importMethod 400", r.status == 400)
    r = _call(st, "POST", f"/v1/projects/demo/locations/global/keyRings/missing/importJobs",
              {"importMethod": "RSA_OAEP_3072_SHA256_AES_256"}, {"importJobId": "j"})
    _check("missing ring 404", r.status == 404)
    r = _call(st, "POST", f"{RING}/importJobs", {"importMethod": "RSA_OAEP_3072_SHA256_AES_256"}, {"importJobId": "job1"})
    _check("create importJob 200", r.status == 200)
    job = _j(r)
    _check("job ACTIVE + public key", job["state"] == "ACTIVE" and "BEGIN PUBLIC KEY" in job["publicKey"]["pem"])
    _check("job name", job["name"].endswith("/keyRings/imp/importJobs/job1"))
    _check("duplicate job 409", _call(st, "POST", f"{RING}/importJobs", {"importMethod": "RSA_OAEP_3072_SHA256_AES_256"}, {"importJobId": "job1"}).status == 409)
    _check("list jobs", len(_j(_call(st, "GET", f"{RING}/importJobs"))["importJobs"]) == 1)
    _check("get job", _call(st, "GET", f"{RING}/importJobs/job1").status == 200)
    _check("get missing job 404", _call(st, "GET", f"{RING}/importJobs/zz").status == 404)

    # import-only key has no primary version until import
    r = _call(st, "POST", f"{RING}/cryptoKeys", {"importOnly": True, "purpose": "ENCRYPT_DECRYPT"}, {"cryptoKeyId": "k", "skipInitialVersionCreation": "true"})
    _check("import-only key created", r.status == 200 and _j(r).get("importOnly") is True and "primary" not in _j(r))
    KEY = f"{RING}/cryptoKeys/k"
    _check("encrypt before import refused", _call(st, "POST", f"{KEY}:encrypt", {"plaintext": base64.b64encode(b"x").decode()}).status == 400)
    _check("no versions yet", _j(_call(st, "GET", f"{KEY}/cryptoKeyVersions"))["cryptoKeyVersions"] == [])

    # wrap as the customer's tool would, with the job's public key
    n, e = imp.rsa_public_from_pem(job["publicKey"]["pem"])
    target = os.urandom(32)
    wrapped = imp.wrap_for_import("RSA_OAEP_3072_SHA256_AES_256", n, e, target)
    body = {"importJob": job["name"], "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
            "rsaAesWrappedKey": base64.b64encode(wrapped).decode()}
    # tampered wrapping refused
    bad = bytearray(wrapped); bad[-1] ^= 1
    r = _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", dict(body, rsaAesWrappedKey=base64.b64encode(bytes(bad)).decode()))
    _check("tampered wrapped key refused", r.status == 400)
    _check("wrong algorithm refused", _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", dict(body, algorithm="RSA_SIGN_PSS_2048_SHA256")).status == 400)
    _check("unknown job 404", _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", dict(body, importJob=job["name"] + "x")).status == 404)
    short = imp.wrap_for_import("RSA_OAEP_3072_SHA256_AES_256", n, e, os.urandom(16))
    _check("16-byte key refused", _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", dict(body, rsaAesWrappedKey=base64.b64encode(short).decode())).status == 400)
    r = _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", body)
    _check("import 200", r.status == 200)
    v = _j(r)
    _check("version ENABLED with importJob", v["state"] == "ENABLED" and v["importJob"] == job["name"] and v["name"].endswith("/cryptoKeyVersions/1"))
    _check("key now has primary", _j(_call(st, "GET", KEY))["primary"]["name"].endswith("/cryptoKeyVersions/1"))

    # encrypt/decrypt round trip, then prove the imported material is what is used
    pt = b"imported key round trip"
    r = _call(st, "POST", f"{KEY}:encrypt", {"plaintext": base64.b64encode(pt).decode()})
    _check("encrypt 200", r.status == 200)
    ct = _j(r)["ciphertext"]
    r = _call(st, "POST", f"{KEY}:decrypt", {"ciphertext": ct})
    _check("decrypt round-trip", base64.b64decode(_j(r)["plaintext"]) == pt)
    _check("ciphertext decrypts with the customer's own key bytes",
           st.engine.decrypt(target, base64.b64decode(ct)) == pt)

    # direct-RSA methods (no AES wrap) + SHA1 variant + second version into an existing key
    r = _call(st, "POST", f"{RING}/importJobs", {"importMethod": "RSA_OAEP_3072_SHA1_AES_256"}, {"importJobId": "job2"})
    j2 = _j(r)
    n2, e2 = imp.rsa_public_from_pem(j2["publicKey"]["pem"])
    t2 = os.urandom(32)
    r = _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", {"importJob": j2["name"], "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
              "rsaAesWrappedKey": base64.b64encode(imp.wrap_for_import("RSA_OAEP_3072_SHA1_AES_256", n2, e2, t2)).decode()})
    _check("SHA1 import v2", r.status == 200 and _j(r)["name"].endswith("/2"))
    # job1 wrapped blob is not valid under job2
    r = _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", dict(body, importJob=j2["name"]))
    _check("cross-job wrapped key refused", r.status == 400)
    r = _call(st, "POST", f"{RING}/importJobs", {"importMethod": "RSA_OAEP_3072_SHA256"}, {"importJobId": "job3"})
    j3 = _j(r)
    n3, e3 = imp.rsa_public_from_pem(j3["publicKey"]["pem"])
    r = _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", {"importJob": j3["name"], "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
              "rsaAesWrappedKey": base64.b64encode(imp.wrap_for_import("RSA_OAEP_3072_SHA256", n3, e3, os.urandom(32))).decode()})
    _check("direct method needs wrappedKey", r.status == 400)
    r = _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", {"importJob": j3["name"], "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
              "wrappedKey": base64.b64encode(imp.wrap_for_import("RSA_OAEP_3072_SHA256", n3, e3, os.urandom(32))).decode()})
    _check("RSA_OAEP_3072_SHA256 wrappedKey import", r.status == 200 and _j(r)["name"].endswith("/3"))
    _check("versions listed", len(_j(_call(st, "GET", f"{KEY}/cryptoKeyVersions"))["cryptoKeyVersions"]) == 3)
    _check("v1 ciphertext still decrypts after more imports",
           base64.b64decode(_j(_call(st, "POST", f"{KEY}:decrypt", {"ciphertext": ct}))["plaintext"]) == pt)

    # expiry
    st.gcp_key_rings[RING.split("/v1/")[1]]["importJobs"][job["name"]]["expireTime"] = "2020-01-01T00:00:00.000000Z"
    _check("expired job state", _j(_call(st, "GET", f"{RING}/importJobs/job1"))["state"] == "EXPIRED")
    _check("import via expired job refused", _call(st, "POST", f"{KEY}/cryptoKeyVersions:import", body).status == 400)
    # regular key unaffected
    r = _call(st, "POST", f"{RING}/cryptoKeys", {}, {"cryptoKeyId": "plain"})
    _check("plain key still gets v1", _j(r)["primary"]["name"].endswith("/1"))
    print("test_gcp_kms_import_core: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
