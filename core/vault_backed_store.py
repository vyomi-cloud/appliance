"""Vault-backed KMS substrate (v2.4.0 Phase 3) — Pro/Max only.

Real crypto for the KMS/Key-Vault-keys cores via HashiCorp Vault's Transit
secrets engine. The key material lives IN Vault (never in the store), so this is
genuine key management — and it closes the Nano "KV-keys real-crypto" straggler:
azure_keyvault_keys / gcp_kms / aws kms all route crypto through `store.engine`,
so swapping the engine to VaultKmsEngine makes every KMS core use real Vault
crypto behind the unchanged KeyStore seam.

Stdlib urllib only (no hvac dep), but it does talk to a Vault server → Pro/Max
only, never vendored to WASM. Nano keeps the in-WASM authenticated-envelope engine.
"""
from __future__ import annotations

import base64
import json
import urllib.request

from core.kms_keystore import KmsEngine, InMemoryKeyStore
from core.kv_store import InMemoryKvStore


def _safe(key_id: str) -> str:
    """Map an arbitrary key id (may contain '/', ':' for GCP/Azure resource names)
    to a Vault Transit key name (Vault allows alnum, '-', '_', '.')."""
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key_id)[:200]


class VaultKmsEngine(KmsEngine):
    def __init__(self, addr: str = "http://localhost:8200", token: str = "vyomi-dev-token",
                 mount: str = "transit"):
        self._addr = addr.rstrip("/")
        self._token = token
        self._mount = mount
        self._enable_transit()

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self._addr}/v1/{path}", data=data, method=method,
                                     headers={"X-Vault-Token": self._token,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code in (400, 204) and method in ("POST", "PUT"):
                return {}   # already-enabled / no-content — benign
            raise

    def _enable_transit(self) -> None:
        try:
            self._req("POST", f"sys/mounts/{self._mount}", {"type": "transit"})
        except Exception:
            pass   # already mounted

    def _ensure_key(self, name: str) -> None:
        self._req("POST", f"{self._mount}/keys/{name}", {})

    # ── KmsEngine seam ────────────────────────────────────────────────────
    def new_key_material(self) -> bytes:
        # Vault holds the real material; the store keeps only a placeholder. The
        # named Transit key is created lazily on first encrypt (which has the id).
        return b"vault-transit"

    def encrypt(self, key_material: bytes, key_id: str, plaintext: bytes) -> bytes:
        name = _safe(key_id)
        self._ensure_key(name)
        r = self._req("POST", f"{self._mount}/encrypt/{name}",
                      {"plaintext": base64.b64encode(plaintext).decode()})
        ct = r["data"]["ciphertext"]                 # "vault:v1:...."
        return (key_id + "|" + ct).encode("utf-8")   # embed id so decrypt can route

    def key_id_in(self, blob: bytes) -> str | None:
        try:
            return blob.decode("utf-8").split("|", 1)[0]
        except Exception:
            return None

    def decrypt(self, key_material: bytes, blob: bytes) -> bytes:
        key_id, ct = blob.decode("utf-8").split("|", 1)
        r = self._req("POST", f"{self._mount}/decrypt/{_safe(key_id)}", {"ciphertext": ct})
        return base64.b64decode(r["data"]["plaintext"])


def _vault_req(addr, token, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{addr.rstrip('/')}/v1/{path}", data=data, method=method,
                                 headers={"X-Vault-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _k(name):   # opaque single-level Vault key (reversible, no slashes)
    return base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")


def _unk(k):
    return base64.urlsafe_b64decode(k + "=" * (-len(k) % 4)).decode()


class VaultBackedKvStore(InMemoryKvStore):
    """Secrets on Vault KV v2 (Secrets Manager / GCP Secret Manager / Azure KV secrets
    share the KvStore seam). Keeps the in-memory dict authoritative (so direct
    `store.secrets` access + all seam reads work) and write-throughs to Vault on
    persist()/drop; loads on init. Pro/Max only (talks to Vault) — never WASM."""

    def __init__(self, addr: str = "http://localhost:8200", token: str = "vyomi-dev-token",
                 mount: str = "secret", prefix: str = "vyomi/", account_id: str | None = None):
        if account_id is None:
            super().__init__()
        else:
            super().__init__(account_id=account_id)
        self._addr, self._token, self._mount, self._prefix = addr, token, mount, prefix
        self._load()

    def _path(self, kind, name):   # kind = "data" | "metadata"
        return f"{self._mount}/{kind}/{self._prefix}{_k(name)}"

    def _load(self):
        r = _vault_req(self._addr, self._token, "GET",
                       f"{self._mount}/metadata/{self._prefix}?list=true")
        for key in ((r or {}).get("data", {}) or {}).get("keys", []):
            try:
                name = _unk(key)
            except Exception:
                continue
            got = _vault_req(self._addr, self._token, "GET", self._path("data", name))
            if got:
                self.secrets[name] = got["data"]["data"]

    def persist(self):   # write-through the current secret set (cores call this after mutation)
        for name, record in self.secrets.items():
            _vault_req(self._addr, self._token, "POST", self._path("data", name), {"data": record})

    def drop_secret(self, name):
        super().drop_secret(name)
        _vault_req(self._addr, self._token, "DELETE", self._path("metadata", name))


class VaultBackedKeyStore(InMemoryKeyStore):
    """KeyStore whose crypto engine is Vault Transit. Metadata/aliases stay local;
    all encrypt/decrypt is done by Vault, so a fresh store still decrypts."""

    def __init__(self, addr: str = "http://localhost:8200", token: str = "vyomi-dev-token",
                 account_id: str | None = None):
        eng = VaultKmsEngine(addr, token)
        if account_id is None:
            super().__init__(engine=eng)
        else:
            super().__init__(engine=eng, account_id=account_id)
