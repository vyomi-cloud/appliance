"""Phase 3 — KMS cores with REAL Vault Transit crypto (closes the KV-keys straggler).

The key material lives in Vault, so a FRESH store (no local material) can still
decrypt — proving Vault does the crypto. Host-only (needs a running Vault); not
part of the WASM bundle. Exercises the GCP Cloud KMS core; the same engine backs
aws kms + azure keyvault-keys unchanged.

Run:  PYTHONPATH=. python3 tests/conformance/test_vault_backed_store.py
"""
import base64
import json

from core.vault_backed_store import VaultBackedKeyStore
from core import gcp_kms_core as kms

P = "/v1/projects/demo/locations/global/keyRings/r/cryptoKeys"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def run() -> int:
    a = VaultBackedKeyStore()
    kms.dispatch(a, "POST", "/v1/projects/demo/locations/global/keyRings", {"keyRingId": "r"}, {}, b"{}")
    kms.dispatch(a, "POST", P, {"cryptoKeyId": "k"}, {}, json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
    enc = _j(kms.dispatch(a, "POST", f"{P}/k:encrypt", {}, {},
                          json.dumps({"plaintext": base64.b64encode(b"vault-real-crypto").decode()}).encode()))
    ct_b64 = enc["ciphertext"]
    # the wire ciphertext embeds a genuine Vault Transit token
    _check("ciphertext is a real Vault Transit token", b"vault:v1:" in base64.b64decode(ct_b64))

    # FRESH store — no local key material; only Vault can decrypt this.
    b = VaultBackedKeyStore()
    kms.dispatch(b, "POST", "/v1/projects/demo/locations/global/keyRings", {"keyRingId": "r"}, {}, b"{}")
    kms.dispatch(b, "POST", P, {"cryptoKeyId": "k"}, {}, json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
    dec = _j(kms.dispatch(b, "POST", f"{P}/k:decrypt", {}, {}, json.dumps({"ciphertext": ct_b64}).encode()))
    _check("fresh store decrypts via Vault (key material never left Vault)",
           base64.b64decode(dec["plaintext"]) == b"vault-real-crypto")

    print("\nPHASE 3: ALL GREEN — KMS cores run real Vault Transit crypto; the KV-keys "
          "real-crypto straggler is CLOSED (key material lives in Vault, fresh store decrypts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
