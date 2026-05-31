"""Thin Vault client wrapper for KMS + Secrets across all 3 providers.

Vault gives us **one real backend** that the simulator's six surfaces map onto:

  AWS KMS         GenerateDataKey / Encrypt / Decrypt   → transit
  AWS SecretsMgr  GetSecretValue / PutSecretValue       → kv (v2)
  GCP Cloud KMS   :encrypt / :decrypt                   → transit
  GCP Secret Mgr  :access (latest version)              → kv (v2)
  Azure KeyVault  /keys/{name}/encrypt|decrypt|wrap     → transit
  Azure KeyVault  /secrets/{name}                       → kv (v2)

Provider-side keys/secrets are namespaced into separate Vault paths so a tenant's
AWS KMS key alias/`my-app-key` can coexist with their GCP Cloud KMS
`app-encryption-key` without collision.

This module is import-safe — Vault is lazy-connected on first use; if Vault is
unreachable, callers should fall back to metadata-only mode (preserving the
"never break the control plane" rule).
"""
from __future__ import annotations

import os
import time
from typing import Any

try:
    import hvac
except ImportError:  # hvac not installed yet — keep import-safe.
    hvac = None  # type: ignore[assignment]


_VAULT_URL = os.environ.get("CLOUDLEARN_VAULT_URL", "http://cloudlearn-vault:8200")
_VAULT_TOKEN = os.environ.get("CLOUDLEARN_VAULT_TOKEN", "cloudlearn-dev-token")

# Provider → vault path prefix. Keep these stable; conformance asserts on them.
_TRANSIT_PREFIX = {
    "aws":   "aws-kms",          # transit/keys/aws-kms/<space>/<key>
    "gcp":   "gcp-kms",
    "azure": "azure-kv-keys",
}
_KV_PREFIX = {
    "aws":   "aws-secrets",      # kv/data/aws-secrets/<space>/<name>
    "gcp":   "gcp-secrets",
    "azure": "azure-kv-secrets",
}

# Mount points; created lazily on first call to _ensure_mounts().
_TRANSIT_MOUNT = "transit"
_KV_MOUNT = "secret"  # Vault dev-mode ships secret/ as kv-v2 by default.

_client_cache: dict[str, Any] = {"client": None, "ensured_at": 0.0}


def _client() -> Any | None:
    """Return a cached authenticated hvac.Client, or None if Vault is unavailable.

    hvac is optional — if it's not installed, return None and let callers decide
    whether to fall back to metadata-only mode.
    """
    if hvac is None:
        return None
    c = _client_cache.get("client")
    if c is not None:
        return c
    try:
        c = hvac.Client(url=_VAULT_URL, token=_VAULT_TOKEN, timeout=3)
        if not c.is_authenticated():
            return None
        _client_cache["client"] = c
        _ensure_mounts(c)
        return c
    except Exception:
        return None


def _ensure_mounts(c: Any) -> None:
    """Idempotently enable the transit + kv-v2 mounts. Re-check at most every
    60 s so we don't beat on Vault if many calls come in.
    """
    now = time.time()
    if now - float(_client_cache.get("ensured_at", 0.0)) < 60:
        return
    _client_cache["ensured_at"] = now
    try:
        existing = c.sys.list_mounted_secrets_engines().get("data", {})
    except Exception:
        return
    if f"{_TRANSIT_MOUNT}/" not in existing:
        try:
            c.sys.enable_secrets_engine(backend_type="transit", path=_TRANSIT_MOUNT)
        except Exception:
            pass
    # secret/ is enabled by default in dev mode; skip otherwise.


def available() -> bool:
    """True if Vault is reachable + authenticated + hvac is installed."""
    return _client() is not None


# ----------------------------------------------------------------------------
# Transit (KMS-style symmetric crypto)
# ----------------------------------------------------------------------------
def _transit_key_name(provider: str, space_id: str, key: str) -> str:
    prefix = _TRANSIT_PREFIX.get(provider.lower(), provider.lower())
    safe = key.replace("/", "_").replace(":", "_")
    return f"{prefix}__{space_id}__{safe}"


def transit_create_key(provider: str, space_id: str, key: str,
                       key_type: str = "aes256-gcm96") -> bool:
    """Provision a transit key. Idempotent; returns True on success or if it
    already exists. False only on real failure (Vault down, bad type)."""
    c = _client()
    if c is None:
        return False
    name = _transit_key_name(provider, space_id, key)
    try:
        c.secrets.transit.create_key(name=name, key_type=key_type, mount_point=_TRANSIT_MOUNT)
        return True
    except Exception as exc:
        # hvac raises on 4xx; "key already exists" is fine.
        msg = str(exc).lower()
        if "exists" in msg or "204" in msg:
            return True
        return False


def transit_encrypt(provider: str, space_id: str, key: str, plaintext_b64: str) -> str | None:
    """Encrypt — returns Vault ciphertext (``vault:v1:<base64>``) or None."""
    c = _client()
    if c is None:
        return None
    name = _transit_key_name(provider, space_id, key)
    try:
        r = c.secrets.transit.encrypt_data(name=name, plaintext=plaintext_b64,
                                           mount_point=_TRANSIT_MOUNT)
        return r["data"]["ciphertext"]
    except Exception:
        return None


def transit_decrypt(provider: str, space_id: str, key: str, ciphertext: str) -> str | None:
    """Decrypt — returns base64 plaintext, or None on failure."""
    c = _client()
    if c is None:
        return None
    name = _transit_key_name(provider, space_id, key)
    try:
        r = c.secrets.transit.decrypt_data(name=name, ciphertext=ciphertext,
                                           mount_point=_TRANSIT_MOUNT)
        return r["data"]["plaintext"]
    except Exception:
        return None


def transit_generate_data_key(provider: str, space_id: str, key: str,
                              key_spec: str = "aes_256") -> dict | None:
    """Mirror of AWS KMS GenerateDataKey: returns both Plaintext and CiphertextBlob."""
    c = _client()
    if c is None:
        return None
    name = _transit_key_name(provider, space_id, key)
    try:
        bits = 256 if key_spec.upper() in ("AES_256", "AES256") else 128
        r = c.secrets.transit.generate_data_key(
            name=name, key_type="plaintext", bits=bits, mount_point=_TRANSIT_MOUNT
        )
        return {
            "Plaintext": r["data"]["plaintext"],
            "CiphertextBlob": r["data"]["ciphertext"],
            "KeyId": name,
        }
    except Exception:
        return None


# ----------------------------------------------------------------------------
# KV v2 (Secrets Manager / Secret Manager / Key Vault secrets)
# ----------------------------------------------------------------------------
def _kv_path(provider: str, space_id: str, name: str) -> str:
    prefix = _KV_PREFIX.get(provider.lower(), provider.lower())
    safe = name.replace("/", "_").replace(":", "_")
    return f"{prefix}/{space_id}/{safe}"


def kv_put(provider: str, space_id: str, name: str, value: str | dict) -> dict | None:
    """Write a secret. Returns version metadata or None."""
    c = _client()
    if c is None:
        return None
    path = _kv_path(provider, space_id, name)
    payload = value if isinstance(value, dict) else {"value": value}
    try:
        r = c.secrets.kv.v2.create_or_update_secret(
            path=path, secret=payload, mount_point=_KV_MOUNT
        )
        return r["data"]
    except Exception:
        return None


def kv_get(provider: str, space_id: str, name: str, version: int | None = None) -> dict | None:
    """Read a secret (latest by default). Returns {data, metadata} or None."""
    c = _client()
    if c is None:
        return None
    path = _kv_path(provider, space_id, name)
    try:
        kwargs = {"path": path, "mount_point": _KV_MOUNT}
        if version is not None:
            kwargs["version"] = version
        r = c.secrets.kv.v2.read_secret_version(**kwargs)
        return r["data"]
    except Exception:
        return None


def kv_delete(provider: str, space_id: str, name: str) -> bool:
    """Permanent (destroy metadata + all versions). True on success."""
    c = _client()
    if c is None:
        return False
    path = _kv_path(provider, space_id, name)
    try:
        c.secrets.kv.v2.delete_metadata_and_all_versions(path=path, mount_point=_KV_MOUNT)
        return True
    except Exception:
        return False


def kv_list_versions(provider: str, space_id: str, name: str) -> list[dict]:
    """Return a list of [{version, created_time, destroyed}, ...] for a secret."""
    c = _client()
    if c is None:
        return []
    path = _kv_path(provider, space_id, name)
    try:
        r = c.secrets.kv.v2.read_secret_metadata(path=path, mount_point=_KV_MOUNT)
        versions = r["data"].get("versions") or {}
        return [
            {"version": int(v), **meta}
            for v, meta in sorted(versions.items(), key=lambda kv: int(kv[0]))
        ]
    except Exception:
        return []
