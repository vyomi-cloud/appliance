"""Customer-managed-key (CMK) envelope encryption shared by the Azure data planes
(Cosmos DB, Service Bus, App Configuration, and SQL Always Encrypted).

Real Azure CMK is envelope encryption: a per-resource data-encryption key (DEK) encrypts the
data, and the DEK is WRAPPED by the customer's Key Vault key (KEK).  This module does exactly
that against the simulator's own Key Vault keys core (core/azure_keyvault_keys_core.py):

  seal(kv_store, key_uri, plaintext)  -> envelope  (random DEK; ciphertext = keystream XOR with an
                                         HMAC-SHA256 tag; the DEK is wrapped by Key Vault `wrapKey`)
  unseal(kv_store, envelope)          -> plaintext (Key Vault `unwrapKey`; fails like real Azure when the
                                         key is disabled / deleted / expired — the data stays on disk but
                                         is unreadable until the key is usable again)
  rewrap(kv_store, envelope, key_uri) -> envelope  (key rotation: only the DEK is re-wrapped under the
                                         latest key version; the data ciphertext is not touched)

Sealed-state helper (`SealedState`): a service keeps a JSON-able blob (items, messages, documents).  At rest
it holds ONLY the envelope; the plaintext exists only while a request is being served.

HONEST LIMITS: the cipher for the bulk data is an HMAC-SHA256 stream construction (stdlib only, loads
under Pyodide) — not AES-GCM.  The key-wrap is the Key Vault core's real wrapKey (RSA-OAEP when the
`cryptography` package is present, the KMS envelope cipher otherwise).  Key material never leaves the
Key Vault store.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading

try:
    from core import azure_keyvault_keys_core as kvk
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_keyvault_keys_core as kvk  # type: ignore

MAGIC = "vyomi-cmk-v1"

_BOUND = {"keys": None}
# Sealed state exists in plaintext only inside a request; concurrent requests on a CMK-protected store are serialised.
LOCK = threading.RLock()


def bind(kv_store) -> None:
    """The router binds the space's Key Vault keys store once; services resolve it via keys()."""
    _BOUND["keys"] = kv_store


def keys(override=None):
    return override if override is not None else _BOUND["keys"]


class CmkError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def parse_key_uri(uri: str):
    """'https://v.vault.azure.net/keys/{name}[/{version}]' -> (name, version|None)."""
    parts = [p for p in str(uri or "").split("/") if p]
    if "keys" not in parts:
        return None, None
    i = parts.index("keys")
    name = parts[i + 1] if len(parts) > i + 1 else None
    return name, (parts[i + 2] if len(parts) > i + 2 else None)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _stream(dek: bytes, nonce: bytes, n: int) -> bytes:
    out, ctr = bytearray(), 0
    while len(out) < n:
        out += hmac.new(dek, b"enc" + nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:n])


def _kv_call(kv_store, op: str, name: str, version: str, value: bytes):
    path = f"/keys/{name}/{version}/{op}" if version else f"/keys/{name}/{op}"
    r = kvk.dispatch(kv_store, "POST", path, {}, {}, json.dumps({"alg": "RSA-OAEP", "value": _b64(value)}).encode())
    try:
        body = json.loads(r.body or b"{}")
    except ValueError:
        body = {}
    if r.status >= 400:
        err = body.get("error") or {}
        code = err.get("code") or "KeyVaultKeyInaccessible"
        raise CmkError(403 if r.status in (403, 404) else r.status, "KeyVaultKeyInaccessible",
                       f"The customer-managed key '{name}'{'/' + version if version else ''} cannot be used "
                       f"({code}: {err.get('message', 'key unavailable')}). Data encrypted with it is unreadable until "
                       "the key is enabled / recovered.")
    return body


def seal(kv_store, key_uri: str, plaintext: bytes) -> dict:
    name, version = parse_key_uri(key_uri)
    if not name:
        raise CmkError(400, "InvalidKeyIdentifier", "The key identifier is not a Key Vault key URI.")
    dek = os.urandom(32)
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(plaintext, _stream(dek, nonce, len(plaintext))))
    tag = hmac.new(dek, b"mac" + nonce + ct, hashlib.sha256).digest()
    wrapped = _kv_call(kv_store, "wrapkey", name, version or "", dek)
    kid = wrapped.get("kid", "")
    return {"fmt": MAGIC, "kid": kid, "keyName": name, "keyVersion": kid.rstrip("/").rsplit("/", 1)[-1],
            "wrappedDek": wrapped["value"], "nonce": _b64(nonce), "ct": _b64(ct), "tag": _b64(tag)}


def is_envelope(x) -> bool:
    return isinstance(x, dict) and x.get("fmt") == MAGIC


def unseal(kv_store, env: dict) -> bytes:
    if not is_envelope(env):
        raise CmkError(400, "InvalidEnvelope", "Not a CMK envelope.")
    dek = _unb64(_kv_call(kv_store, "unwrapkey", env["keyName"], env["keyVersion"], _unb64(env["wrappedDek"]))["value"])
    nonce, ct = _unb64(env["nonce"]), _unb64(env["ct"])
    if not hmac.compare_digest(hmac.new(dek, b"mac" + nonce + ct, hashlib.sha256).digest(), _unb64(env["tag"])):
        raise CmkError(400, "DataIntegrity", "Ciphertext failed authentication (tampered or wrong key).")
    return bytes(a ^ b for a, b in zip(ct, _stream(dek, nonce, len(ct))))


def rewrap(kv_store, env: dict, key_uri: str) -> dict:
    """Key rotation: unwrap the DEK with the old key version, wrap it under `key_uri` (latest when versionless)."""
    old = _kv_call(kv_store, "unwrapkey", env["keyName"], env["keyVersion"], _unb64(env["wrappedDek"]))
    name, version = parse_key_uri(key_uri)
    new = _kv_call(kv_store, "wrapkey", name, version or "", _unb64(old["value"]))
    kid = new.get("kid", "")
    return dict(env, kid=kid, keyName=name, keyVersion=kid.rstrip("/").rsplit("/", 1)[-1], wrappedDek=new["value"])


def usable(kv_store, key_uri: str):
    """(ok, reason) — is the key present, enabled and inside its validity window right now?"""
    name, version = parse_key_uri(key_uri)
    if not name:
        return False, "malformed key identifier"
    st = kvk.key_enabled(kv_store, name, version)
    if st is None:
        return False, "key not found (deleted or never created)"
    if st is False:
        return False, "key is disabled"
    return True, ""


class SealedState:
    """Seal / open a JSON-able blob held in `holder[slot]`.  At rest: `holder[sealed_slot]` = envelope and
    `holder[slot]` is absent.  `open()` returns the plaintext object (raises CmkError when the key is unusable);
    `close(obj, key_uri)` seals it again (always under the latest/specified key version)."""

    def __init__(self, holder: dict, slot: str, sealed_slot: str):
        self.h, self.slot, self.sealed = holder, slot, sealed_slot

    def is_sealed(self) -> bool:
        return self.sealed in self.h and self.slot not in self.h

    def open(self, kv_store):
        if self.sealed in self.h:
            raw = unseal(kv_store, self.h[self.sealed])
            self.h[self.slot] = json.loads(raw.decode("utf-8"))
        return self.h.get(self.slot)

    def close(self, kv_store, key_uri: str):
        if self.slot not in self.h:
            return
        raw = json.dumps(self.h[self.slot], sort_keys=True, default=str).encode("utf-8")
        self.h[self.sealed] = seal(kv_store, key_uri, raw)
        del self.h[self.slot]

    def rotate(self, kv_store, key_uri: str):
        if self.sealed in self.h:
            self.h[self.sealed] = rewrap(kv_store, self.h[self.sealed], key_uri)
