"""console-next KMS facade — drives the substrate-agnostic KMS core (core/kms_core.py)
over a single KeyStore so the kms-crypto-view widget can list keys, create a key, and
run the encrypt→ciphertext / decrypt→plaintext (and generate-data-key) playground —
all against the appliance's KMS console REST API under /api/console/kms/*.

Why a console-scoped facade instead of the native SigV4 wire: KMS only speaks the
native JSON1.1 protocol (`TrentService.` X-Amz-Target) — there is no plain-JSON
console REST facade. Rather than teach the widget SigV4, this module maps clean JSON
functions onto the SAME core + store the Nano relay drives, so the behaviour is
byte-identical across substrates (§15). Purely additive — it touches no existing
routes, ctx state, or the real KMS handlers; it reuses the real crypto core (no fake
crypto), exactly the pattern of core/console_secrets.py.

Ciphertext/plaintext cross the wire base64-encoded (the native KMS shape), so the
widget sends/receives the honest AWS blobs. Encrypt embeds the KeyId in the blob, so
Decrypt round-trips without being told the key — real symmetric-KMS semantics.
"""

from __future__ import annotations

from core import kms_core
from core.kms_keystore import InMemoryKeyStore

# ── one shared store for the console KMS vertical (module singleton) ──
_STORE = InMemoryKeyStore()


def store() -> InMemoryKeyStore:
    return _STORE


class KmsError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _call(action: str, payload: dict) -> dict:
    resp = kms_core.dispatch(_STORE, f"TrentService.{action}", payload)
    body = resp.body if isinstance(resp.body, dict) else {}
    if resp.status >= 400:
        raise KmsError(str(body.get("message") or body.get("__type") or action + " failed"),
                       resp.status)
    return body


# ── list / describe / create ──────────────────────────────────────────────
def list_keys() -> dict:
    """List keys with a short describe summary (state, description, usage)."""
    body = _call("ListKeys", {})
    out = []
    for k in body.get("Keys", []):
        kid = k.get("KeyId", "")
        try:
            md = _call("DescribeKey", {"KeyId": kid}).get("KeyMetadata", {})
        except KmsError:
            md = {}
        out.append({
            "key_id": kid,
            "arn": k.get("KeyArn", md.get("Arn", "")),
            "description": md.get("Description", ""),
            "state": md.get("KeyState", ""),
            "enabled": bool(md.get("Enabled", False)),
            "usage": md.get("KeyUsage", ""),
            "spec": md.get("KeySpec", ""),
            "created": md.get("CreationDate"),
        })
    return {"keys": out, "count": len(out)}


def describe_key(key_id: str) -> dict:
    md = _call("DescribeKey", {"KeyId": key_id}).get("KeyMetadata", {})
    return {
        "key_id": md.get("KeyId", ""),
        "arn": md.get("Arn", ""),
        "description": md.get("Description", ""),
        "state": md.get("KeyState", ""),
        "enabled": bool(md.get("Enabled", False)),
        "usage": md.get("KeyUsage", ""),
        "spec": md.get("KeySpec", ""),
        "created": md.get("CreationDate"),
    }


def create_key(description: str = "") -> dict:
    payload: dict = {}
    if description:
        payload["Description"] = description
    md = _call("CreateKey", payload).get("KeyMetadata", {})
    return {"key_id": md.get("KeyId", ""), "arn": md.get("Arn", ""),
            "description": md.get("Description", ""), "state": md.get("KeyState", "")}


# ── crypto playground ─────────────────────────────────────────────────────
def encrypt(key_id: str, plaintext_b64: str) -> dict:
    """Encrypt a base64 plaintext blob → base64 CiphertextBlob (native KMS wire)."""
    body = _call("Encrypt", {"KeyId": key_id, "Plaintext": plaintext_b64})
    return {"key_id": body.get("KeyId", ""),
            "ciphertext_blob": body.get("CiphertextBlob", ""),
            "algorithm": body.get("EncryptionAlgorithm", "")}


def decrypt(ciphertext_b64: str, key_id: str | None = None) -> dict:
    """Decrypt a base64 CiphertextBlob → base64 Plaintext. KeyId is optional (the
    blob self-identifies its key; supply it only to assert a match)."""
    payload: dict = {"CiphertextBlob": ciphertext_b64}
    if key_id:
        payload["KeyId"] = key_id
    body = _call("Decrypt", payload)
    return {"key_id": body.get("KeyId", ""),
            "plaintext": body.get("Plaintext", ""),
            "algorithm": body.get("EncryptionAlgorithm", "")}


def generate_data_key(key_id: str, key_spec: str = "AES_256") -> dict:
    """Generate a data key under a KMS key: returns the plaintext data key AND its
    encrypted CiphertextBlob (both base64) — envelope-encryption primitive."""
    body = _call("GenerateDataKey", {"KeyId": key_id, "KeySpec": key_spec})
    return {"key_id": body.get("KeyId", ""),
            "plaintext": body.get("Plaintext", ""),
            "ciphertext_blob": body.get("CiphertextBlob", "")}
