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

v4 C0c (the offline appliance now serves AWS KMS through this core — see
tests/conformance/test_c0c_legacy_parity_core.py): a DISABLED key fails with
DisabledException (pending deletion stays KMSInvalidStateException), as real AWS
does; Encrypt / GenerateDataKey need an ENCRYPT_DECRYPT key (InvalidKeyUsageException
otherwise); EnableKeyRotation honours
an explicit RotationPeriodInDays; UpdateKeyDescription; custom key stores live in
`store.custom_key_stores` (persisted state); and an optional
`store.legacy_decrypt(key_ref, blob)` hook decrypts ciphertext minted by the
pre-v4 Vault-transit handler.

Scope (v1 slice): CreateKey, DescribeKey, ListKeys, Encrypt, Decrypt,
GenerateDataKey(+WithoutPlaintext), GenerateRandom, EnableKey, DisableKey,
ScheduleKeyDeletion, CreateAlias, ListAliases. Grants / key policies / rotation /
tagging reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
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


def _require_active_key(store: KeyStore, ref: str, auto_provision: bool = False) -> str:
    key_id = _resolve_key_id(store, ref)
    if not key_id and auto_provision and _is_aws_managed_ref(ref):
        key_id = _provision_aws_managed_key(store, ref)
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{ref}' does not exist.", 400)
    _require_enabled_state(store, key_id)
    return key_id


def _require_enabled_state(store: KeyStore, key_id: str) -> None:
    """Real AWS: a Disabled key → DisabledException; any other non-Enabled state
    (PendingDeletion, PendingImport, …) → KMSInvalidStateException."""
    state = store.get_key(key_id).get("KeyState", "Enabled")
    if state == "Disabled":
        raise KmsError("DisabledException", f"{_key_arn(store, key_id)} is disabled.", 400)
    if state != "Enabled":
        raise KmsError("KMSInvalidStateException",
                       f"{_key_arn(store, key_id)} is {state}.", 400)


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
        "KeyManager": k.get("KeyManager", "CUSTOMER"),
        "KeySpec": spec,
        "CustomerMasterKeySpec": spec,
        "MultiRegion": False,
    }
    if md["KeyUsage"] == "ENCAPSULATE_DECAPSULATE":
        md["EncapsulationAlgorithms"] = ["ML_KEM"]
    elif md["KeyUsage"] == "SIGN_VERIFY":
        md["SigningAlgorithms"] = sorted(_SIGNING_ALGORITHMS)
    elif md["KeyUsage"] == "GENERATE_VERIFY_MAC":
        md["MacAlgorithms"] = sorted(_MAC_ALGORITHMS)
    else:
        md["EncryptionAlgorithms"] = ["SYMMETRIC_DEFAULT"]
    if "DeletionDate" in k:
        md["DeletionDate"] = k["DeletionDate"]
    if k.get("MaterialId"):
        md["KeyMaterialId"] = k["MaterialId"]
    if k.get("LastUsedDate"):
        md["LastUsedDate"] = k["LastUsedDate"]
    if k.get("KeyRotationEnabled"):
        md["RotationPeriodInDays"] = int(k.get("RotationPeriodInDays", 365))
    return md


def _touch_last_used(store: KeyStore, key_id: str) -> None:
    k = store.get_key(key_id)
    if k is not None:
        k["LastUsedDate"] = time.time()


_DATA_KEY_BYTES = {"AES_256": 32, "AES_128": 16}


def _default_key_policy(store: KeyStore) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Id": "key-default-1",
        "Statement": [{
            "Sid": "Enable IAM User Permissions",
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{store.account_id}:root"},
            "Action": "kms:*",
            "Resource": "*",
        }],
    }, indent=2)


# ── operations ──────────────────────────────────────────────────────────────
def _create_key(store: KeyStore, body: dict) -> dict:
    key_id = uuid.uuid4().hex
    material_id = uuid.uuid4().hex
    store.put_key(key_id, {
        "KeyState": "Enabled",
        "Description": str(body.get("Description", "")),
        "KeyUsage": str(body.get("KeyUsage", "ENCRYPT_DECRYPT")),
        "KeySpec": str(body.get("KeySpec") or body.get("CustomerMasterKeySpec") or "SYMMETRIC_DEFAULT"),
        "Origin": str(body.get("Origin", "AWS_KMS")),
        "KeyManager": "CUSTOMER",
        "CreationDate": time.time(),
        "MaterialId": material_id,
        "Tags": {t["TagKey"]: t.get("TagValue", "") for t in body.get("Tags") or [] if t.get("TagKey")},
    }, store.engine.new_key_material())
    k = store.get_key(key_id)
    k["Policy"] = str(body.get("Policy") or "") or _default_key_policy(store)
    store.mirror_create_key(key_id, k)
    store.persist()
    return {"KeyMetadata": _key_metadata(store, key_id)}


def _is_aws_managed_ref(ref: str) -> bool:
    ref = ref or ""
    if ":alias/" in ref:
        ref = "alias/" + ref.split(":alias/", 1)[1]
    return ref.startswith("alias/aws/")


def _provision_aws_managed_key(store: KeyStore, ref: str) -> str:
    """AWS provisions the `aws/<service>` managed key the first time a service
    uses it (Encrypt/GenerateDataKey with that alias) rather than at account
    creation. Vyomi mirrors that: the alias auto-provisions its key on first use
    instead of raising NotFoundException."""
    alias = ref
    if ":alias/" in alias:
        alias = "alias/" + alias.split(":alias/", 1)[1]
    service = alias[len("alias/aws/"):] or "service"
    key_id = uuid.uuid4().hex
    material_id = uuid.uuid4().hex
    store.put_key(key_id, {
        "KeyState": "Enabled",
        "Description": f"Default master key that protects my {service} data when no other key is defined",
        "KeyUsage": "ENCRYPT_DECRYPT",
        "KeySpec": "SYMMETRIC_DEFAULT",
        "Origin": "AWS_KMS",
        "KeyManager": "AWS",
        "CreationDate": time.time(),
        "MaterialId": material_id,
        "Tags": {},
    }, store.engine.new_key_material())
    k = store.get_key(key_id)
    k["Policy"] = _default_key_policy(store)
    store.mirror_create_key(key_id, k)
    store.set_alias(alias, key_id)
    store.persist()
    return key_id


def _describe_key(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    return {"KeyMetadata": _key_metadata(store, key_id)}


def _list_keys(store: KeyStore, body: dict) -> dict:
    return {"Keys": [{"KeyId": kid, "KeyArn": _key_arn(store, kid)} for kid in store.key_ids()],
            "Truncated": False}


def _require_encrypt_usage(store: KeyStore, key_id: str) -> None:
    usage = store.get_key(key_id).get("KeyUsage", "ENCRYPT_DECRYPT")
    if usage != "ENCRYPT_DECRYPT":
        raise KmsError("InvalidKeyUsageException",
                       f"{_key_arn(store, key_id)} key usage is {usage}, not ENCRYPT_DECRYPT.", 400)


def _encrypt(store: KeyStore, body: dict) -> dict:
    key_id = _require_active_key(store, body.get("KeyId", ""), auto_provision=True)
    _require_encrypt_usage(store, key_id)
    plaintext = _b64d(body.get("Plaintext", ""))
    if not plaintext:
        raise KmsError("ValidationException", "Plaintext must not be empty.", 400)
    blob = store.engine.encrypt(store.get_material(key_id), key_id, plaintext)
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "CiphertextBlob": _b64e(blob),
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT"}


def _decrypt_with_history(store: KeyStore, key_id: str, blob: bytes) -> bytes:
    """KMS keeps old key material after a rotation so ciphertext encrypted under
    an earlier backing key still decrypts. Try the current material first, then
    prior versions (newest first)."""
    k = store.get_key(key_id) or {}
    candidates = [store.get_material(key_id), *reversed(k.get("MaterialHistory", []))]
    last_exc: Exception | None = None
    for mat in candidates:
        if not mat:
            continue
        try:
            return store.engine.decrypt(mat, blob)
        except Exception as e:  # noqa: BLE001 - try the next material version
            last_exc = e
    raise last_exc or ValueError("no key material")


def _legacy_decrypt(store: KeyStore, body: dict) -> dict | None:
    """Pre-v4 ciphertext (`vault:v1:…`, no embedded key id) through the store's
    optional legacy hook. The retired handler wrapped the Vault string in base64
    (Encrypt) or returned it raw (GenerateDataKey) — accept both."""
    hook = getattr(store, "legacy_decrypt", None)
    if hook is None:
        return None
    raw = str(body.get("CiphertextBlob") or "")
    blob = raw.encode() if raw.startswith("vault:") else _b64d(raw)
    if not blob.startswith(b"vault:"):
        return None
    got = hook(str(body.get("KeyId") or ""), blob)
    if not got:
        raise KmsError("InvalidCiphertextException",
                       "The ciphertext could not be decrypted with any known key.", 400)
    key_id, plaintext = got
    if key_id and store.key_exists(key_id):
        _require_enabled_state(store, key_id)
        _touch_last_used(store, key_id)
        store.persist()
        return {"KeyId": _key_arn(store, key_id), "Plaintext": _b64e(plaintext),
                "EncryptionAlgorithm": "SYMMETRIC_DEFAULT"}
    return {"KeyId": _key_arn(store, key_id or ""), "Plaintext": _b64e(plaintext),
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT"}


def _decrypt(store: KeyStore, body: dict) -> dict:
    if str(body.get("CiphertextBlob") or "").startswith("vault:"):
        legacy = _legacy_decrypt(store, body)
        if legacy is not None:
            return legacy
    blob = _b64d(body.get("CiphertextBlob", ""))
    key_id = store.engine.key_id_in(blob)
    if not key_id and blob.startswith(b"vault:"):
        legacy = _legacy_decrypt(store, body)
        if legacy is not None:
            return legacy
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
    _require_enabled_state(store, key_id)
    try:
        plaintext = _decrypt_with_history(store, key_id, blob)
    except Exception as e:
        raise KmsError("InvalidCiphertextException", str(e), 400)
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "Plaintext": _b64e(plaintext),
            "EncryptionAlgorithm": "SYMMETRIC_DEFAULT"}


_SHARED_SECRET_BYTES = 32


def _encapsulation_key(store: KeyStore, body: dict) -> str:
    if str(body.get("EncapsulationAlgorithm") or "") != "ML_KEM":
        raise KmsError("ValidationException",
                       "EncapsulationAlgorithm must be ML_KEM.", 400)
    key_id = _require_active_key(store, body.get("KeyId", ""))
    if store.get_key(key_id).get("KeyUsage") != "ENCAPSULATE_DECAPSULATE":
        raise KmsError("InvalidKeyUsageException",
                       f"{_key_arn(store, key_id)} key usage is not ENCAPSULATE_DECAPSULATE.", 400)
    return key_id


def _encapsulate(store: KeyStore, body: dict) -> dict:
    """ML-KEM Encapsulate. Simulated: the shared secret is random and the
    ciphertext is that secret sealed under the key's material, so Decapsulate on
    the same key recovers it (no real lattice math — wire shape and key-usage/state
    rules match AWS)."""
    import os
    key_id = _encapsulation_key(store, body)
    secret = os.urandom(_SHARED_SECRET_BYTES)
    blob = store.engine.encrypt(store.get_material(key_id), key_id, secret)
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "SharedSecret": _b64e(secret),
            "SharedSecretCiphertextBlob": _b64e(blob), "EncapsulationAlgorithm": "ML_KEM"}


def _decapsulate(store: KeyStore, body: dict) -> dict:
    key_id = _encapsulation_key(store, body)
    blob = _b64d(body.get("SharedSecretCiphertextBlob", ""))
    if store.engine.key_id_in(blob) != key_id:
        raise KmsError("IncorrectKeyException",
                       "The key supplied does not match the ciphertext's key.", 400)
    try:
        secret = store.engine.decrypt(store.get_material(key_id), blob)
    except Exception as e:
        raise KmsError("InvalidCiphertextException", str(e), 400)
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "SharedSecret": _b64e(secret),
            "EncapsulationAlgorithm": "ML_KEM"}


# ── asymmetric sign/verify + HMAC generate/verify-mac (simulated: same stdlib-only
# authenticated primitive as encrypt/decrypt — wire shape and key-usage/state rules
# match AWS; no real RSA/ECC/ML-DSA math, exactly the ML-KEM Encapsulate pattern above) ─
_SIGNING_ALGORITHMS = {
    "RSASSA_PKCS1_V1_5_SHA_256", "RSASSA_PKCS1_V1_5_SHA_384", "RSASSA_PKCS1_V1_5_SHA_512",
    "RSASSA_PSS_SHA_256", "RSASSA_PSS_SHA_384", "RSASSA_PSS_SHA_512",
    "ECDSA_SHA_256", "ECDSA_SHA_384", "ECDSA_SHA_512",
    "ML_DSA_SHAKE_256",
}
_MAC_ALGORITHMS = {
    "HMAC_SHA_224": hashlib.sha224, "HMAC_SHA_256": hashlib.sha256,
    "HMAC_SHA_384": hashlib.sha384, "HMAC_SHA_512": hashlib.sha512,
}


def _require_usage_key(store: KeyStore, body: dict, usage: str) -> str:
    key_id = _require_active_key(store, body.get("KeyId", ""))
    if store.get_key(key_id).get("KeyUsage") != usage:
        raise KmsError("InvalidKeyUsageException",
                       f"{_key_arn(store, key_id)} key usage is not {usage}.", 400)
    return key_id


def _sign(store: KeyStore, body: dict) -> dict:
    algo = str(body.get("SigningAlgorithm") or "")
    if algo not in _SIGNING_ALGORITHMS:
        raise KmsError("ValidationException", f"Unsupported SigningAlgorithm '{algo}'.", 400)
    key_id = _require_usage_key(store, body, "SIGN_VERIFY")
    message = _b64d(body.get("Message", ""))
    if not message:
        raise KmsError("ValidationException", "Message must not be empty.", 400)
    sig = hmac.new(store.get_material(key_id), algo.encode() + b"|" + message, hashlib.sha256).digest()
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "Signature": _b64e(sig), "SigningAlgorithm": algo}


def _verify(store: KeyStore, body: dict) -> dict:
    algo = str(body.get("SigningAlgorithm") or "")
    if algo not in _SIGNING_ALGORITHMS:
        raise KmsError("ValidationException", f"Unsupported SigningAlgorithm '{algo}'.", 400)
    key_id = _require_usage_key(store, body, "SIGN_VERIFY")
    message = _b64d(body.get("Message", ""))
    signature = _b64d(body.get("Signature", ""))
    expected = hmac.new(store.get_material(key_id), algo.encode() + b"|" + message, hashlib.sha256).digest()
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "SignatureValid": hmac.compare_digest(expected, signature),
            "SigningAlgorithm": algo}


def _generate_mac(store: KeyStore, body: dict) -> dict:
    algo = str(body.get("MacAlgorithm") or "")
    digest = _MAC_ALGORITHMS.get(algo)
    if not digest:
        raise KmsError("ValidationException", f"Unsupported MacAlgorithm '{algo}'.", 400)
    key_id = _require_usage_key(store, body, "GENERATE_VERIFY_MAC")
    message = _b64d(body.get("Message", ""))
    if not message:
        raise KmsError("ValidationException", "Message must not be empty.", 400)
    mac = hmac.new(store.get_material(key_id), message, digest).digest()
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "Mac": _b64e(mac), "MacAlgorithm": algo}


def _verify_mac(store: KeyStore, body: dict) -> dict:
    algo = str(body.get("MacAlgorithm") or "")
    digest = _MAC_ALGORITHMS.get(algo)
    if not digest:
        raise KmsError("ValidationException", f"Unsupported MacAlgorithm '{algo}'.", 400)
    key_id = _require_usage_key(store, body, "GENERATE_VERIFY_MAC")
    message = _b64d(body.get("Message", ""))
    mac = _b64d(body.get("Mac", ""))
    expected = hmac.new(store.get_material(key_id), message, digest).digest()
    _touch_last_used(store, key_id)
    return {"KeyId": _key_arn(store, key_id), "MacValid": hmac.compare_digest(expected, mac), "MacAlgorithm": algo}


def _generate_data_key(store: KeyStore, body: dict, with_plaintext: bool = True) -> dict:
    key_id = _require_active_key(store, body.get("KeyId", ""), auto_provision=True)
    _require_encrypt_usage(store, key_id)
    n = int(body.get("NumberOfBytes") or _DATA_KEY_BYTES.get(str(body.get("KeySpec", "AES_256")), 32))
    if n < 1 or n > 1024:
        raise KmsError("ValidationException", "NumberOfBytes must be 1..1024.", 400)
    import os
    data_key = os.urandom(n)
    blob = store.engine.encrypt(store.get_material(key_id), key_id, data_key)
    _touch_last_used(store, key_id)
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


def _set_key_rotation(store: KeyStore, body: dict, enabled: bool) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    k = store.get_key(key_id)
    if k.get("KeyState") == "PendingDeletion":
        raise KmsError("KMSInvalidStateException", "Key is pending deletion.", 400)
    k["KeyRotationEnabled"] = enabled
    if enabled:
        days = int(body.get("RotationPeriodInDays") or k.get("RotationPeriodInDays") or 365)
        if days < 90 or days > 2560:
            raise KmsError("ValidationException", "RotationPeriodInDays must be 90..2560.", 400)
        k["RotationPeriodInDays"] = days
    store.persist()
    return {}


def _get_key_rotation_status(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    k = store.get_key(key_id)
    out = {"KeyId": key_id, "KeyRotationEnabled": bool(k.get("KeyRotationEnabled", False))}
    if k.get("KeyRotationEnabled"):
        out["RotationPeriodInDays"] = int(k.get("RotationPeriodInDays", 365))
    return out


def _rotate_key_on_demand(store: KeyStore, body: dict, rotation_type: str = "CUSTOMER_INITIATED") -> dict:
    """Rotate the backing key material now: fresh material, but the key id and all
    prior ciphertexts stay valid (KMS keeps old versions for decrypt — see
    _decrypt_with_history)."""
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    k = store.get_key(key_id)
    if k.get("KeyState") == "PendingDeletion":
        raise KmsError("KMSInvalidStateException", "Key is pending deletion.", 400)
    old_material = store.get_material(key_id)
    if old_material:
        k.setdefault("MaterialHistory", []).append(old_material)
    store.material[key_id] = store.engine.new_key_material()
    material_id = uuid.uuid4().hex
    k["MaterialId"] = material_id
    k.setdefault("RotationHistory", []).append({
        "KeyMaterialId": material_id, "RotationDate": time.time(), "RotationType": rotation_type,
    })
    k["RotationCount"] = int(k.get("RotationCount", 0)) + 1
    store.persist()
    return {"KeyId": _key_arn(store, key_id)}


def _list_key_rotations(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    history = store.get_key(key_id).get("RotationHistory", [])
    rotations = [{"KeyId": key_id, **r} for r in history]
    return {"Rotations": rotations, "Truncated": False}


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


def _delete_alias(store: KeyStore, body: dict) -> dict:
    alias = str(body.get("AliasName", ""))
    if not alias or store.alias_target(alias) is None:
        raise KmsError("NotFoundException", f"Alias '{alias}' does not exist.", 400)
    store.aliases.pop(alias, None)
    store.persist()
    return {}


def _update_alias(store: KeyStore, body: dict) -> dict:
    alias = str(body.get("AliasName", ""))
    if store.alias_target(alias) is None:
        raise KmsError("NotFoundException", f"Alias '{alias}' does not exist.", 400)
    target = body.get("TargetKeyId", "")
    key_id = _resolve_key_id(store, target)
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Target key '{target}' does not exist.", 400)
    store.set_alias(alias, key_id)
    store.persist()
    return {}


def _update_key_description(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    k = store.get_key(key_id)
    if k.get("KeyState") == "PendingDeletion":
        raise KmsError("KMSInvalidStateException", "Key is pending deletion.", 400)
    k["Description"] = str(body.get("Description", ""))
    store.persist()
    return {}


def _cancel_key_deletion(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    k = store.get_key(key_id)
    if k.get("KeyState") != "PendingDeletion":
        raise KmsError("KMSInvalidStateException", "Key is not pending deletion.", 400)
    k["KeyState"] = "Disabled"
    k.pop("DeletionDate", None)
    store.persist()
    return {"KeyId": _key_arn(store, key_id), "KeyState": "Disabled"}


# ── tags ─────────────────────────────────────────────────────────────────
def _tag_resource(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    tags = store.get_key(key_id).setdefault("Tags", {})
    for t in body.get("Tags") or []:
        if t.get("TagKey"):
            tags[t["TagKey"]] = t.get("TagValue", "")
    store.persist()
    return {}


def _untag_resource(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    tags = store.get_key(key_id).setdefault("Tags", {})
    for tag_key in body.get("TagKeys") or []:
        tags.pop(tag_key, None)
    store.persist()
    return {}


def _list_resource_tags(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    tags = store.get_key(key_id).get("Tags", {})
    return {"Tags": [{"TagKey": k, "TagValue": v} for k, v in tags.items()], "Truncated": False}


# ── key policy (stored, not evaluated — Vyomi does not authorize calls against it) ─
def _put_key_policy(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    policy = body.get("Policy")
    if not policy:
        raise KmsError("ValidationException", "Policy must not be empty.", 400)
    try:
        json.loads(policy)
    except Exception:
        raise KmsError("MalformedPolicyDocumentException", "The policy document is not valid JSON.", 400)
    store.get_key(key_id)["Policy"] = policy
    store.persist()
    return {}


def _get_key_policy(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    return {"Policy": store.get_key(key_id).get("Policy") or _default_key_policy(store)}


def _list_key_policies(store: KeyStore, body: dict) -> dict:
    key_id = _resolve_key_id(store, body.get("KeyId", ""))
    if not key_id or not store.key_exists(key_id):
        raise KmsError("NotFoundException", f"Key '{body.get('KeyId','')}' does not exist.", 400)
    return {"PolicyNames": ["default"], "Truncated": False}


# ── custom key stores (AWS CloudHSM / external key stores) ─────────────────
# Metadata CRUD is real and stateful. Connecting is honestly simulated: Vyomi has
# no real CloudHSM cluster or external XKS proxy to reach, so ConnectCustomKeyStore
# fails exactly as it would in AWS without live backing infrastructure — never a
# faked CONNECTED state. No key ever stores its material in a custom key store.
def _custom_key_stores(store: KeyStore) -> dict:
    cks = getattr(store, "custom_key_stores", None)
    if cks is None:      # a store subclass that skipped KeyStore.__init__
        cks = store.__dict__.setdefault("custom_key_stores", {})
    return cks


def _create_custom_key_store(store: KeyStore, body: dict) -> dict:
    name = str(body.get("CustomKeyStoreName") or "")
    if not name:
        raise KmsError("ValidationException", "CustomKeyStoreName is required.", 400)
    stores = _custom_key_stores(store)
    if any(s["CustomKeyStoreName"] == name for s in stores.values()):
        raise KmsError("CustomKeyStoreNameInUseException",
                       f"Custom key store name '{name}' is already in use.", 400)
    store_type = str(body.get("CustomKeyStoreType") or "AWS_CLOUDHSM")
    store_id = "cks-" + uuid.uuid4().hex[:16]
    record = {
        "CustomKeyStoreId": store_id,
        "CustomKeyStoreName": name,
        "CustomKeyStoreType": store_type,
        "ConnectionState": "DISCONNECTED",
        "CreationDate": time.time(),
    }
    if store_type == "EXTERNAL_KEY_STORE":
        record["XksProxyConfiguration"] = {
            "Connectivity": str(body.get("XksProxyConnectivity") or "PUBLIC_ENDPOINT"),
            "UriEndpoint": str(body.get("XksProxyUriEndpoint") or ""),
            "UriPath": str(body.get("XksProxyUriPath") or "/kms/xks/v1"),
        }
    else:
        record["CloudHsmClusterId"] = str(body.get("CloudHsmClusterId") or "")
        record["TrustAnchorCertificate"] = str(body.get("TrustAnchorCertificate") or "")
    stores[store_id] = record
    store.persist()
    return {"CustomKeyStoreId": store_id}


def _require_custom_key_store(store: KeyStore, body: dict) -> dict:
    rec = _custom_key_stores(store).get(body.get("CustomKeyStoreId"))
    if not rec:
        raise KmsError("CustomKeyStoreNotFoundException",
                       "The request was rejected because the custom key store was not found.", 400)
    return rec


def _describe_custom_key_stores(store: KeyStore, body: dict) -> dict:
    want_id, want_name = body.get("CustomKeyStoreId"), body.get("CustomKeyStoreName")
    out = []
    for rec in _custom_key_stores(store).values():
        if want_id and rec["CustomKeyStoreId"] != want_id:
            continue
        if want_name and rec["CustomKeyStoreName"] != want_name:
            continue
        out.append(dict(rec))
    if (want_id or want_name) and not out:
        raise KmsError("CustomKeyStoreNotFoundException",
                       "The request was rejected because the custom key store was not found.", 400)
    return {"CustomKeyStores": out, "Truncated": False}


def _connect_custom_key_store(store: KeyStore, body: dict) -> dict:
    rec = _require_custom_key_store(store, body)
    rec["ConnectionState"] = "FAILED"
    rec["ConnectionErrorCode"] = "NETWORK_ERRORS"
    store.persist()
    return {}


def _disconnect_custom_key_store(store: KeyStore, body: dict) -> dict:
    rec = _require_custom_key_store(store, body)
    rec["ConnectionState"] = "DISCONNECTED"
    rec.pop("ConnectionErrorCode", None)
    store.persist()
    return {}


def _update_custom_key_store(store: KeyStore, body: dict) -> dict:
    rec = _require_custom_key_store(store, body)
    if body.get("NewCustomKeyStoreName"):
        rec["CustomKeyStoreName"] = str(body["NewCustomKeyStoreName"])
    if body.get("CloudHsmClusterId"):
        rec["CloudHsmClusterId"] = str(body["CloudHsmClusterId"])
    if "XksProxyConfiguration" in rec:
        for field in ("XksProxyUriEndpoint", "XksProxyUriPath"):
            if field in body:
                rec["XksProxyConfiguration"][field[len("XksProxy"):]] = str(body[field])
    store.persist()
    return {}


def _delete_custom_key_store(store: KeyStore, body: dict) -> dict:
    stores = _custom_key_stores(store)
    rec = stores.get(body.get("CustomKeyStoreId"))
    if not rec:
        raise KmsError("CustomKeyStoreNotFoundException",
                       "The request was rejected because the custom key store was not found.", 400)
    if rec["ConnectionState"] not in ("DISCONNECTED", "FAILED"):
        raise KmsError("KMSInvalidStateException",
                       "The custom key store must be disconnected before it can be deleted.", 400)
    del stores[body["CustomKeyStoreId"]]
    store.persist()
    return {}


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
        if action == "Encapsulate":
            return _ok(_encapsulate(store, body))
        if action == "Decapsulate":
            return _ok(_decapsulate(store, body))
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
        if action == "EnableKeyRotation":
            return _ok(_set_key_rotation(store, body, enabled=True))
        if action == "DisableKeyRotation":
            return _ok(_set_key_rotation(store, body, enabled=False))
        if action == "GetKeyRotationStatus":
            return _ok(_get_key_rotation_status(store, body))
        if action == "RotateKeyOnDemand":
            return _ok(_rotate_key_on_demand(store, body))
        if action == "ListKeyRotations":
            return _ok(_list_key_rotations(store, body))
        if action == "UpdateKeyDescription":
            return _ok(_update_key_description(store, body))
        if action == "CancelKeyDeletion":
            return _ok(_cancel_key_deletion(store, body))
        if action == "CreateAlias":
            return _ok(_create_alias(store, body))
        if action == "ListAliases":
            return _ok(_list_aliases(store, body))
        if action == "DeleteAlias":
            return _ok(_delete_alias(store, body))
        if action == "UpdateAlias":
            return _ok(_update_alias(store, body))
        if action == "TagResource":
            return _ok(_tag_resource(store, body))
        if action == "UntagResource":
            return _ok(_untag_resource(store, body))
        if action == "ListResourceTags":
            return _ok(_list_resource_tags(store, body))
        if action == "PutKeyPolicy":
            return _ok(_put_key_policy(store, body))
        if action == "GetKeyPolicy":
            return _ok(_get_key_policy(store, body))
        if action == "ListKeyPolicies":
            return _ok(_list_key_policies(store, body))
        if action == "Sign":
            return _ok(_sign(store, body))
        if action == "Verify":
            return _ok(_verify(store, body))
        if action == "GenerateMac":
            return _ok(_generate_mac(store, body))
        if action == "VerifyMac":
            return _ok(_verify_mac(store, body))
        if action == "CreateCustomKeyStore":
            return _ok(_create_custom_key_store(store, body))
        if action == "DescribeCustomKeyStores":
            return _ok(_describe_custom_key_stores(store, body))
        if action == "ConnectCustomKeyStore":
            return _ok(_connect_custom_key_store(store, body))
        if action == "DisconnectCustomKeyStore":
            return _ok(_disconnect_custom_key_store(store, body))
        if action == "UpdateCustomKeyStore":
            return _ok(_update_custom_key_store(store, body))
        if action == "DeleteCustomKeyStore":
            return _ok(_delete_custom_key_store(store, body))
        return _error("UnknownOperationException", f"The action {action} is not implemented.", 400)
    except KmsError as e:
        return _error(e.code, e.message, e.status)


def _ok(body: dict) -> KmsResponse:
    return KmsResponse(status=200, body=body, headers={"x-amzn-requestid": _req_id()})


def _error(code: str, message: str, status: int = 400) -> KmsResponse:
    return KmsResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id()})
