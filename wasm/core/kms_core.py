# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""KMS core — substrate-independent, faithfully extracted from the appliance KMS
handler (core/vault_routes.py `_aws_kms_dispatch`) so the SAME logic runs in
Pro/Max (FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 / socket / hvac
imports → loads under Pyodide. Persists through the KeyStore seam and does crypto
through the KmsEngine seam (core/kms_keystore.py).

Each operation takes the parsed JSON payload and returns a `KmsResponse` (status,
body-dict, headers) — the native AWS KMS wire shapes (KeyMetadata, base64
Plaintext/CiphertextBlob, `__type` JSON errors, x-amzn-requestid). KMS speaks the
JSON1.1 protocol with the `TrentService.` X-Amz-Target prefix. A thin FastAPI
adapter (Pro/Max) or the relay/SW bridge (Nano) maps Request<->KmsResponse.

Conformance improvements over the current appliance handler (the canonical wire
the appliance converges onto): the KeyId is embedded in the CiphertextBlob so
Decrypt recovers it without being told (real symmetric-KMS semantics); KeyState
is enforced (Encrypt/Decrypt on a disabled or pending-deletion key fail with
KMSInvalidStateException); and all errors use the native {"__type","message"}
shape.

Scope (v1 slice): CreateKey, DescribeKey, ListKeys, Encrypt, Decrypt,
GenerateDataKey(+WithoutPlaintext), GenerateRandom, EnableKey, DisableKey,
ScheduleKeyDeletion, CreateAlias, ListAliases. Grants / key policies / rotation /
tagging reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass, field

from core.kms_keystore import KeyStore

KMS_REGION = "us-east-1"


# ── transport types ───────────────────────────────────────────────────────
@dataclass
class KmsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class KmsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


# ── primitives ─────────────────────────────────────────────────────────────
def _req_id() -> str:
    return str(uuid.uuid4())


def _key_arn(store: KeyStore, key_id: str) -> str:
    return f"arn:aws:kms:{KMS_REGION}:{store.account_id}:key/{key_id}"


def _alias_arn(store: KeyStore, alias: str) -> str:
    return f"arn:aws:kms:{KMS_REGION}:{store.account_id}:{alias}"


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _b64d(s: str) -> bytes:
    try:
        return base64.b64decode(s or "")
    except Exception:
        raise KmsError("InvalidCiphertextException", "Invalid base64 blob.", 400)


# ── key resolution (KeyId may be a uuid, an ARN, an alias, or an alias ARN) ─
def _resolve_key_id(store: KeyStore, ref: str) -> str | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    # alias ARN -> trailing "alias/..."
    if ":alias/" in ref:
        ref = "alias/" + ref.split(":alias/", 1)[1]
    # key ARN -> trailing key id
    elif ":key/" in ref:
        ref = ref.split(":key/", 1)[1]
    if ref.startswith("alias/"):
        return store.alias_target(ref)
    return ref if store.key_exists(ref) else None


def _require_active_key(store: KeyStore, ref: str) -> str:
    key_id = _resolve_key_id(store, ref)
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{ref}' does not exist.", 400)
    state = store.get_key(key_id).get("KeyState", "Enabled")
    if state != "Enabled":
        raise KmsError("KMSInvalidStateException",
                       f"{_key_arn(store, key_id)} is {state}.", 400)
    return key_id


def _key_metadata(store: KeyStore, key_id: str) -> dict:
    k = store.get_key(key_id) or {}
    spec = k.get("KeySpec", "SYMMETRIC_DEFAULT")
    md = {
        "AWSAccountId": store.account_id,
        "KeyId": key_id,
        "Arn": _key_arn(store, key_id),
        "CreationDate": k.get("CreationDate", time.time()),
        "Enabled": k.get("KeyState") == "Enabled",
        "Description": k.get("Description", ""),
        "KeyUsage": k.get("KeyUsage", "ENCRYPT_DECRYPT"),
        "KeyState": k.get("KeyState", "Enabled"),
        "Origin": k.get("Origin", "AWS_KMS"),
        "KeyManager": "CUSTOMER",
        "KeySpec": spec,
        "CustomerMasterKeySpec": spec,
        "EncryptionAlgorithms": ["SYMMETRIC_DEFAULT"],
        "MultiRegion": False,
    }
    if "DeletionDate" in k:
        md["DeletionDate"] = k["DeletionDate"]
    return md


_DATA_KEY_BYTES = {"AES_256": 32, "AES_128": 16}


# ── operations ──────────────────────────────────────────────────────────────
def _create_key(store: KeyStore, body: dict) -> dict:
    key_id = uuid.uuid4().hex
    store.put_key(key_id, {
        "KeyState": "Enabled",
        "Description": str(body.get("Description", "")),
        "KeyUsage": str(body.get("KeyUsage", "ENCRYPT_DECRYPT")),
        "KeySpec": str(body.get("KeySpec") or body.get("CustomerMasterKeySpec") or "SYMMETRIC_DEFAULT"),
        "Origin": str(body.get("Origin", "AWS_KMS")),
        "CreationDate": time.time(),
    }, store.engine.new_key_material())
    store.mirror_create_key(key_id, store.get_key(key_id))
    store.persist()
    return {"KeyMetadata": _key_metadata(store, key_id)}


def _describe_key(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    return {"KeyMetadata": _key_metadata(store, key_id)}


def _list_keys(store: KeyStore, body: dict) -> dict:
    return {"Keys": [{"KeyId": kid, "KeyArn": _key_arn(store, kid)} for kid in store.key_ids()],
            "Truncated": False}


def _encrypt(store: KeyStore, body: dict) -> dict:
    key_id = _require_active_key(store, body.get("KeyId", ""))
    plaintext = _b64d(body.get("Plaintext", ""))
    if not plaintext:
        raise KmsError("ValidationException", "Plaintext must not be empty.", 400)
    blob = store.engine.encrypt(store.get_material(key_id), key_id, plaintext)
    return {"KeyId": _key_arn(store, key_id), "CiphertextBlob": _b64e(blob),
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT"}


def _decrypt(store: KeyStore, body: dict) -> dict:
    blob = _b64d(body.get("CiphertextBlob", ""))
    key_id = store.engine.key_id_in(blob)
    if not key_id:
        # AWS allows/expects KeyId in the request when the blob can't self-identify.
        key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", "Key for ciphertext does not exist.", 400)
    # An explicit KeyId in the request must match the blob's key.
    if body.get("KeyId"):
        want = _resolve_key_id(store, body.get("KeyId", ""))
        if want and want != key_id:
            raise KmsError("IncorrectKeyException",
                           "The key supplied does not match the ciphertext's key.", 400)
    state = store.get_key(key_id).get("KeyState", "Enabled")
    if state != "Enabled":
        raise KmsError("KMSInvalidStateException", f"{_key_arn(store, key_id)} is {state}.", 400)
    try:
        plaintext = store.engine.decrypt(store.get_material(key_id), blob)
    except Exception as e:
        raise KmsError("InvalidCiphertextException", str(e), 400)
    return {"KeyId": _key_arn(store, key_id), "Plaintext": _b64e(plaintext),
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT"}


def _generate_data_key(store: KeyStore, body: dict, with_plaintext: bool = True) -> dict:
    key_id = _require_active_key(store, body.get("KeyId", ""))
    n = int(body.get("NumberOfBytes") or _DATA_KEY_BYTES.get(str(body.get("KeySpec", "AES_256")), 32))
    if n < 1 or n > 1024:
        raise KmsError("ValidationException", "NumberOfBytes must be 1..1024.", 400)
    import os
    data_key = os.urandom(n)
    blob = store.engine.encrypt(store.get_material(key_id), key_id, data_key)
    out = {"KeyId": _key_arn(store, key_id), "CiphertextBlob": _b64e(blob)}
    if with_plaintext:
        out["Plaintext"] = _b64e(data_key)
    return out


def _generate_random(store: KeyStore, body: dict) -> dict:
    import os
    n = int(body.get("NumberOfBytes") or 32)
    if n < 1 or n > 1024:
        raise KmsError("ValidationException", "NumberOfBytes must be 1..1024.", 400)
    return {"Plaintext": _b64e(os.urandom(n))}


def _set_key_state(store: KeyStore, body: dict, enabled: bool) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    k = store.get_key(key_id)
    if k.get("KeyState") == "PendingDeletion":
        raise KmsError("KMSInvalidStateException", "Key is pending deletion.", 400)
    k["KeyState"] = "Enabled" if enabled else "Disabled"
    store.persist()
    return {}


def _schedule_key_deletion(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    days = int(body.get("PendingWindowInDays") or 30)
    if days < 7 or days > 30:
        raise KmsError("ValidationException", "PendingWindowInDays must be 7..30.", 400)
    k = store.get_key(key_id)
    k["KeyState"] = "PendingDeletion"
    k["DeletionDate"] = time.time() + days * 86400
    store.persist()
    return {"KeyId": _key_arn(store, key_id), "DeletionDate": k["DeletionDate"],
            "KeyState": "PendingDeletion"}


def _create_alias(store: KeyStore, body: dict) -> dict:
    alias = str(body.get("AliasName", ""))
    target = body.get("TargetKeyId", "")
    if not alias or not target:
        raise KmsError("ValidationException", "AliasName and TargetKeyId are required.", 400)
    if not alias.startswith("alias/"):
        raise KmsError("ValidationException", "AliasName must start with 'alias/'.", 400)
    key_id = _resolve_key_id(store, target)
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Target key '{target}' does not exist.", 400)
    store.set_alias(alias, key_id)
    store.persist()
    return {}


def _list_aliases(store: KeyStore, body: dict) -> dict:
    want = _resolve_key_id(store, body.get("KeyId", "")) if body.get("KeyId") else None
    aliases = []
    for alias, key_id in store.alias_items():
        if want and key_id != want:
            continue
        aliases.append({"AliasName": alias, "AliasArn": _alias_arn(store, alias),
                        "TargetKeyId": key_id})
    return {"Aliases": aliases, "Truncated": False}


# ── native-wire dispatcher (X-Amz-Target action → operation) ───────────────
# The single routing point for the native AWS KMS JSON protocol (TrentService.*)
# — what an unmodified aws-cli / boto3 client speaks. `target` is the raw
# X-Amz-Target header, e.g. "TrentService.Encrypt".
def dispatch(store: KeyStore, target: str, payload: dict | None = None) -> KmsResponse:
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("MissingAction", "The request must include X-Amz-Target.", 400)
    try:
        if action == "CreateKey":
            return _ok(_create_key(store, body))
        if action == "DescribeKey":
            return _ok(_describe_key(store, body))
        if action == "ListKeys":
            return _ok(_list_keys(store, body))
        if action == "Encrypt":
            return _ok(_encrypt(store, body))
        if action == "Decrypt":
            return _ok(_decrypt(store, body))
        if action == "GenerateDataKey":
            return _ok(_generate_data_key(store, body, with_plaintext=True))
        if action == "GenerateDataKeyWithoutPlaintext":
            return _ok(_generate_data_key(store, body, with_plaintext=False))
        if action == "GenerateRandom":
            return _ok(_generate_random(store, body))
        if action == "EnableKey":
            return _ok(_set_key_state(store, body, enabled=True))
        if action == "DisableKey":
            return _ok(_set_key_state(store, body, enabled=False))
        if action == "ScheduleKeyDeletion":
            return _ok(_schedule_key_deletion(store, body))
        if action == "CreateAlias":
            return _ok(_create_alias(store, body))
        if action == "ListAliases":
            return _ok(_list_aliases(store, body))
        return _error("UnknownOperationException", f"The action {action} is not implemented.", 400)
    except KmsError as e:
        return _error(e.code, e.message, e.status)


def _ok(body: dict) -> KmsResponse:
    return KmsResponse(status=200, body=body, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400) -> KmsResponse:
    return KmsResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id()})
