"""console-next Key Vault (keys) facade (Azure) — the Azure lens's kms-crypto-view
data plane.

The SAME kms-crypto-view widget renders under lens=azure; the ONLY difference is the
manifest `api` block pointing at /api/console/azure-kv-keys/* instead of
/api/console/kms/* (§15.2 — no if(cloud) branching in the widget). This module is the
Azure Key Vault (keys) sibling of the GCP Cloud KMS console facade
(core/console_gcp_kms.py) and the AWS KMS facade (core/console_kms.py): it returns the
SAME JSON response shapes the widget consumes (list keys, describe a key, create a key,
and the encrypt→ciphertext / decrypt→plaintext round-trip + generate-data-key), so the
widget stays cloud-agnostic.

Crypto is REAL and shared: this facade reuses the substrate-agnostic KMS core
(core/kms_core.py) exactly like console_kms / console_gcp_kms do — it does NOT
reimplement crypto. The Azure lens simply drives the core over its OWN independent
KeyStore (a separate module-level InMemoryKeyStore), so the Azure lens's key state is
isolated from the AWS/GCP lenses', mirroring how core/console_gcp_kms holds an
independent key store. It never touches the appliance's native Key Vault handlers or
the shared KeyStore the AWS/GCP KMS facades use.

Ciphertext/plaintext cross the wire base64-encoded (the native KMS shape), so the
widget sends/receives honest blobs. Encrypt embeds the KeyId in the blob, so Decrypt
round-trips without being told the key — real symmetric-crypto semantics.
"""

from __future__ import annotations

from core import kms_core
from core.kms_keystore import InMemoryKeyStore

# ── one shared store for the Azure-lens Key Vault (keys) vertical (module singleton),
#    independent from the AWS/GCP KMS console facades' stores ──
_STORE = InMemoryKeyStore()


def store() -> InMemoryKeyStore:
    return _STORE


def reset() -> None:  # test hook
    global _STORE
    _STORE = InMemoryKeyStore()


class AzureKvKeysError(Exception):
    """Facade error carrying an HTTP status + message (mapped to HTTPException)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _call(action: str, payload: dict) -> dict:
    resp = kms_core.dispatch(_STORE, f"TrentService.{action}", payload)
    body = resp.body if isinstance(resp.body, dict) else {}
    if resp.status >= 400:
        raise AzureKvKeysError(
            str(body.get("message") or body.get("__type") or action + " failed"),
            resp.status,
        )
    return body


# ── list / describe / create ──────────────────────────────────────────────
def list_keys() -> dict:
    """List keys with a short describe summary (state, description, usage) — SAME JSON
    shape console_kms.list_keys returns."""
    body = _call("ListKeys", {})
    out = []
    for k in body.get("Keys", []):
        kid = k.get("KeyId", "")
        try:
            md = _call("DescribeKey", {"KeyId": kid}).get("KeyMetadata", {})
        except AzureKvKeysError:
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
    """Generate a data key under a Key Vault key: returns the plaintext data key AND
    its encrypted CiphertextBlob (both base64) — envelope-encryption primitive."""
    body = _call("GenerateDataKey", {"KeyId": key_id, "KeySpec": key_spec})
    return {"key_id": body.get("KeyId", ""),
            "plaintext": body.get("Plaintext", ""),
            "ciphertext_blob": body.get("CiphertextBlob", "")}
