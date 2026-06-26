"""KeyStore + KmsEngine — the data-plane + crypto-primitive seams for KMS (ADR-001).

The KMS protocol logic (key lifecycle, aliases, key state, native wire shapes)
is substrate-independent and lives in core/kms_core.py. THESE are the two seams
it persists/operates through, so the same handler runs on any substrate:

    Pro/Max : KeyStore + a Vault-transit engine (AES-256-GCM via hvac)
    Nano    : InMemoryKeyStore + InMemoryKmsEngine (pure-Python, in-WASM)
    tests   : InMemoryKeyStore + InMemoryKmsEngine

The crypto is a SEAM (KmsEngine), exactly as the appliance delegates to Vault
transit. Per the native-SDK-conformance principle the backing primitive is our
private pick — what must conform is the WIRE (Encrypt→CiphertextBlob, Decrypt
round-trips and recovers the KeyId, GenerateDataKey returns Plaintext +
CiphertextBlob, tamper is rejected). The Nano engine is a REAL authenticated
cipher (SHA-256 keystream + encrypt-then-MAC, HMAC-SHA256) using only the stdlib
(hashlib/hmac/os.urandom) — so it runs identically on host CPython and Pyodide,
with no native `cryptography`/openssl dep (which fails under Pyodide). A
WebCrypto/SubtleCrypto engine (real AES-GCM) can replace this in-browser later
behind the SAME interface.

Nothing here imports fastapi / boto3 / socket / hvac, so it loads under Pyodide.

State shapes:
    keys     : { key_id -> metadata }   (public KeyMetadata fields, AWS-shaped)
    material : { key_id -> bytes }       (the secret key material, NEVER serialised)
    aliases  : { "alias/name" -> key_id }
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID
_MAGIC = b"VYK1"  # Vyomi-KMS blob v1


class KmsEngine:
    """Crypto-primitive seam. Subclass to back encrypt/decrypt with a different
    primitive (Vault transit in Pro/Max, WebCrypto AES-GCM in the browser)."""

    def new_key_material(self) -> bytes:  # pragma: no cover - overridden
        raise NotImplementedError

    def encrypt(self, key_material: bytes, key_id: str, plaintext: bytes) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def decrypt(self, key_material: bytes, blob: bytes) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def key_id_in(self, blob: bytes) -> str | None:  # pragma: no cover
        raise NotImplementedError


class InMemoryKmsEngine(KmsEngine):
    """Authenticated symmetric encryption from the stdlib only — runs identically
    on host CPython and Pyodide. Construction: a SHA-256 keystream (HMAC-SHA256 in
    counter mode over a random 16-byte nonce) XORed with the plaintext, then
    encrypt-then-MAC (HMAC-SHA256 over the whole record). The KeyId is embedded so
    Decrypt recovers it from the blob WITHOUT being told (real symmetric-KMS
    semantics). This is genuine crypto — key separation + tamper detection are
    real — not a base64 stub."""

    def new_key_material(self) -> bytes:
        return os.urandom(32)

    @staticmethod
    def _keystream(key_material: bytes, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(hmac.new(key_material, nonce + counter.to_bytes(8, "big"),
                                hashlib.sha256).digest())
            counter += 1
        return bytes(out[:length])

    @staticmethod
    def _xor(data: bytes, ks: bytes) -> bytes:
        return bytes(b ^ k for b, k in zip(data, ks))

    def _header(self, key_id: str, nonce: bytes) -> bytes:
        kid = key_id.encode()
        return _MAGIC + len(kid).to_bytes(2, "big") + kid + nonce

    def encrypt(self, key_material: bytes, key_id: str, plaintext: bytes) -> bytes:
        nonce = os.urandom(16)
        header = self._header(key_id, nonce)
        ct = self._xor(plaintext, self._keystream(key_material, nonce, len(plaintext)))
        tag = hmac.new(key_material, header + ct, hashlib.sha256).digest()
        return header + ct + tag

    def key_id_in(self, blob: bytes) -> str | None:
        if len(blob) < 6 or blob[:4] != _MAGIC:
            return None
        klen = int.from_bytes(blob[4:6], "big")
        if len(blob) < 6 + klen:
            return None
        return blob[6:6 + klen].decode(errors="replace")

    def decrypt(self, key_material: bytes, blob: bytes) -> bytes:
        if len(blob) < 6 or blob[:4] != _MAGIC:
            raise ValueError("InvalidCiphertext: bad magic")
        klen = int.from_bytes(blob[4:6], "big")
        header_len = 6 + klen + 16  # magic+len+key_id+nonce(16)
        if len(blob) < header_len + 32:
            raise ValueError("InvalidCiphertext: truncated")
        header, body = blob[:header_len], blob[header_len:]
        nonce = blob[6 + klen:header_len]
        ct, tag = body[:-32], body[-32:]
        expected = hmac.new(key_material, header + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, tag):
            raise ValueError("InvalidCiphertext: authentication failed")
        return self._xor(ct, self._keystream(key_material, nonce, len(ct)))


class KeyStore:
    """Base seam. In-memory by default; subclass to add a mirror / persistence."""

    def __init__(self, engine: KmsEngine | None = None,
                 account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.keys: dict[str, dict[str, Any]] = {}
        self.material: dict[str, bytes] = {}
        self.aliases: dict[str, str] = {}
        self.engine: KmsEngine = engine or InMemoryKmsEngine()
        self.account_id = account_id

    # ── key map accessors ─────────────────────────────────────────────
    def key_exists(self, key_id: str) -> bool:
        return key_id in self.keys

    def get_key(self, key_id: str) -> dict | None:
        k = self.keys.get(key_id)
        return k if isinstance(k, dict) else None

    def put_key(self, key_id: str, metadata: dict, material: bytes) -> None:
        self.keys[key_id] = metadata
        self.material[key_id] = material

    def get_material(self, key_id: str) -> bytes | None:
        return self.material.get(key_id)

    def drop_key(self, key_id: str) -> None:
        self.keys.pop(key_id, None)
        self.material.pop(key_id, None)
        for alias in [a for a, k in self.aliases.items() if k == key_id]:
            self.aliases.pop(alias, None)

    def key_ids(self) -> list[str]:
        return sorted(self.keys)

    # ── alias accessors ───────────────────────────────────────────────
    def alias_target(self, alias: str) -> str | None:
        return self.aliases.get(alias)

    def set_alias(self, alias: str, key_id: str) -> None:
        self.aliases[alias] = key_id

    def alias_items(self) -> list[tuple[str, str]]:
        return sorted(self.aliases.items())

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def persist(self) -> None:
        """Flush state to durable storage (appliance ctx in Pro/Max, IDB/OPFS in
        Nano later)."""

    def mirror_create_key(self, key_id: str, metadata: dict) -> None:
        """Best-effort key provision in an external backend (Vault transit)."""

    def mirror_delete_key(self, key_id: str) -> None:
        """Best-effort key delete in the external mirror."""


class InMemoryKeyStore(KeyStore):
    """The Nano / test substrate: pure in-memory, zero external deps."""
