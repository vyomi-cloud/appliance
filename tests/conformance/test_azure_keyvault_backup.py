"""Key Vault key + secret backup/restore (data plane). Run: PYTHONPATH=. python tests/conformance/test_azure_keyvault_backup.py"""
import json
from core.kms_keystore import KeyStore
from core import azure_keyvault_keys_core as K, azure_keyvault_secrets_core as S
try:
    from core.azure_keyvault_secrets_core import InMemoryKvStore
except ImportError:
    from core.kv_store import InMemoryKvStore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def main():
    ks = KeyStore()
    kd = lambda m, p, b=None: K.dispatch(ks, m, p, {}, {}, json.dumps(b).encode() if b is not None else b"")
    _check("backup missing key", kd("POST", "/keys/nokey/backup").status == 404)
    kd("POST", "/keys/k1/create", {"kty": "RSA", "key_size": 2048})
    kd("POST", "/keys/k1/create", {"kty": "RSA", "key_size": 2048})
    r = kd("POST", "/keys/k1/backup")
    blob = json.loads(r.body)["value"]
    _check("backup blob", r.status == 200 and blob)
    _check("restore over existing = 409", kd("POST", "/keys/restore", {"value": blob}).status == 409)
    _check("tampered blob rejected", kd("POST", "/keys/restore", {"value": blob[:-4] + "AAAA"}).status == 400)
    vers = json.loads(kd("GET", "/keys/k1").body)["key"]["kid"]
    ct = json.loads(kd("POST", "/keys/k1/encrypt", {"alg": "RSA-OAEP", "value": "aGVsbG8"}).body)["value"]
    kd("DELETE", "/keys/k1")
    _check("deleted", kd("GET", "/keys/k1").status == 404)
    r = kd("POST", "/keys/restore", {"value": blob})
    _check("restore creates key", r.status == 200 and json.loads(r.body)["key"]["kid"] == vers)
    pt = json.loads(kd("POST", "/keys/k1/decrypt", {"alg": "RSA-OAEP", "value": ct}).body)["value"]
    _check("restored key material decrypts old ciphertext", pt == "aGVsbG8")
    _check("restore secret blob into keys rejected", kd("POST", "/keys/restore", {"value": json.loads(S.dispatch(ss := InMemoryKvStore(), "PUT", "/secrets/s1", {"api-version": "7.4"}, {}, b'{"value":"v"}').body)["id"]}).status == 400)
    sd = lambda m, p, b=None: S.dispatch(ss, m, p, {"api-version": "7.4"}, {}, json.dumps(b).encode() if b is not None else b"")
    S.dispatch(ss, "PUT", "/secrets/s1", {"api-version": "7.4"}, {}, b'{"value":"v2"}')
    r = sd("POST", "/secrets/s1/backup")
    sb = json.loads(r.body)["value"]
    _check("secret backup", r.status == 200)
    _check("secret restore conflict", sd("POST", "/secrets/restore", {"value": sb}).status == 409)
    sd("DELETE", "/secrets/s1")
    ss.secrets.pop("s1", None) if hasattr(ss, "secrets") else None
    r = sd("POST", "/secrets/restore", {"value": sb})
    _check("secret restored with value", r.status == 200 and json.loads(sd("GET", "/secrets/s1").body)["value"] == "v2")
    _check("key blob into secrets rejected", sd("POST", "/secrets/restore", {"value": blob}).status == 400)
    print("keyvault backup: all checks passed")


main()
