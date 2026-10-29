# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Cloud KMS core — substrate-independent, the GCP analogue of core/kms_core.py.
Speaks the native **Cloud KMS REST API v1** (`/v1/projects/{p}/locations/{l}/
keyRings/...`) so the native `google-cloud-kms` SDK and `gcloud kms` work unchanged
against it (point them at the endpoint via api_endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Reuses the SAME seams as AWS KMS (core/kms_keystore.py): the KeyStore holds the
key material and the KmsEngine does the real (stdlib, deterministic, authenticated)
envelope crypto — so encrypt/decrypt round-trip and the CryptoKey resource name is
recovered from the ciphertext exactly as AWS recovers its KeyId. GCP just gets its
own store instance, so key rings / crypto keys are cloud-namespaced.

Wire shape follows the REST resource model:
    projects/{p}/locations/{l}/keyRings/{kr}
    projects/{p}/locations/{l}/keyRings/{kr}/cryptoKeys/{k}
    projects/{p}/locations/{l}/keyRings/{kr}/cryptoKeys/{k}/cryptoKeyVersions/{v}
Custom methods use the `:verb` suffix (`:encrypt`, `:decrypt`). `plaintext` /
`ciphertext` fields are base64 per the REST wire. Errors use the Google shape
`{"error":{"code","message","status"}}` (status e.g. NOT_FOUND / INVALID_ARGUMENT).

Scope (v1 slice): keyRings create/get/list, cryptoKeys create/get/list,
cryptoKeyVersions get/list, :encrypt, :decrypt. IAM policy, rotation, asymmetric
keys, and key-version lifecycle reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.kms_keystore import KeyStore


# ── transport type ─────────────────────────────────────────────────────────
@dataclass
class GcpKmsResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ─────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _err(status: int, gcp_status: str, message: str) -> GcpKmsResponse:
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return GcpKmsResponse(status=status, body=json.dumps(body).encode())


def _json(status: int, obj: dict) -> GcpKmsResponse:
    return GcpKmsResponse(status=status, body=json.dumps(obj).encode())


# ── GCP key-ring bookkeeping (crypto-key material lives in the KeyStore seam) ─
def _rings(store: KeyStore) -> dict:
    # Key rings hold no secret material, so they hang off the store instance
    # (which is dedicated to this GCP KMS namespace) rather than the key map.
    return store.__dict__.setdefault("gcp_key_rings", {})


# ── resource views ─────────────────────────────────────────────────────────
def _key_ring_view(name: str, entry: dict) -> dict:
    return {"name": name, "createTime": entry.get("createTime", _now())}


def _version_name(key_name: str, ver: str) -> str:
    return f"{key_name}/cryptoKeyVersions/{ver}"


def _version_view(key_name: str, ver: str, entry: dict) -> dict:
    return {
        "name": _version_name(key_name, ver),
        "state": entry.get("state", "ENABLED"),
        "protectionLevel": entry.get("protectionLevel", "SOFTWARE"),
        "algorithm": entry.get("algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
        "createTime": entry.get("createTime", _now()),
        "generateTime": entry.get("createTime", _now()),
    }


def _crypto_key_view(store: KeyStore, name: str) -> dict:
    meta = store.get_key(name) or {}
    primary = str(meta.get("primary", "1"))
    versions = meta.get("versions", {primary: {}})
    return {
        "name": name,
        "primary": _version_view(name, primary, versions.get(primary, {})),
        "purpose": meta.get("purpose", "ENCRYPT_DECRYPT"),
        "createTime": meta.get("createTime", _now()),
        "versionTemplate": {
            "protectionLevel": "SOFTWARE",
            "algorithm": meta.get("algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
        },
    }


# ── path parsing ───────────────────────────────────────────────────────────
def _parse(path: str) -> tuple[list, str | None]:
    """Strip the /v1 prefix + query, split off a trailing `:verb` custom method,
    and return (segments, verb)."""
    p = path
    if p.startswith("/v1/") or p == "/v1":
        p = p[3:]
    p = p.split("?", 1)[0]
    verb = None
    # The custom-method colon is only ever in the LAST path segment.
    last_slash = p.rfind("/")
    tail = p[last_slash + 1:]
    if ":" in tail:
        tail, verb = tail.split(":", 1)
        p = p[: last_slash + 1] + tail
    segs = [s for s in p.strip("/").split("/") if s]
    return segs, verb


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store: KeyStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcpKmsResponse:
    query = query or {}
    method = method.upper()
    segs, verb = _parse(path)

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    if len(segs) < 5 or segs[0] != "projects" or segs[2] != "locations" or segs[4] != "keyRings":
        return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")

    parent = "/".join(segs[:5])  # projects/{p}/locations/{l}/keyRings

    # ── keyRings collection: .../keyRings ──────────────────────────────────
    if len(segs) == 5:
        rings = _rings(store)
        if method == "POST":
            ring_id = query.get("keyRingId") or payload.get("keyRingId")
            if not ring_id:
                return _err(400, "INVALID_ARGUMENT", "keyRingId is required.")
            name = f"{parent}/{ring_id}"
            if name in rings:
                return _err(409, "ALREADY_EXISTS", f"KeyRing {name} already exists.")
            rings[name] = {"createTime": _now()}
            return _json(200, _key_ring_view(name, rings[name]))
        if method == "GET":
            items = [_key_ring_view(n, e) for n, e in sorted(rings.items())
                     if n.startswith(parent + "/") and n.count("/") == 5]
            return _json(200, {"keyRings": items})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on keyRings")

    # ── single keyRing: .../keyRings/{kr} ──────────────────────────────────
    if len(segs) == 6:
        rings = _rings(store)
        name = "/".join(segs)
        if method == "GET":
            if name not in rings:
                return _err(404, "NOT_FOUND", f"KeyRing {name} not found.")
            return _json(200, _key_ring_view(name, rings[name]))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on keyRing")

    # From here on the 7th segment must be cryptoKeys.
    if segs[6] != "cryptoKeys":
        return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")

    ring_name = "/".join(segs[:6])

    # ── cryptoKeys collection: .../cryptoKeys ──────────────────────────────
    if len(segs) == 7:
        rings = _rings(store)
        if method == "POST":
            if ring_name not in rings:
                return _err(404, "NOT_FOUND", f"KeyRing {ring_name} not found.")
            key_id = query.get("cryptoKeyId") or payload.get("cryptoKeyId")
            if not key_id:
                return _err(400, "INVALID_ARGUMENT", "cryptoKeyId is required.")
            name = f"{ring_name}/cryptoKeys/{key_id}"
            if store.key_exists(name):
                return _err(409, "ALREADY_EXISTS", f"CryptoKey {name} already exists.")
            now = _now()
            store.put_key(name, {
                "purpose": str(payload.get("purpose", "ENCRYPT_DECRYPT")),
                "algorithm": (payload.get("versionTemplate", {}) or {}).get(
                    "algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
                "createTime": now,
                "primary": "1",
                "versions": {"1": {"state": "ENABLED", "createTime": now}},
            }, store.engine.new_key_material())
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        if method == "GET":
            items = [_crypto_key_view(store, n) for n in store.key_ids()
                     if n.startswith(ring_name + "/cryptoKeys/")
                     and n.count("/") == 7]
            return _json(200, {"cryptoKeys": items})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on cryptoKeys")

    # ── single cryptoKey + custom methods: .../cryptoKeys/{k}[:verb] ────────
    if len(segs) == 8:
        name = "/".join(segs)
        if verb == "encrypt":
            return _encrypt(store, name, payload)
        if verb == "decrypt":
            return _decrypt(store, name, payload)
        if verb:
            return _err(400, "INVALID_ARGUMENT", f"Unknown method :{verb}")
        if method == "GET":
            if not store.key_exists(name):
                return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
            return _json(200, _crypto_key_view(store, name))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on cryptoKey")

    # ── cryptoKeyVersions: .../cryptoKeys/{k}/cryptoKeyVersions[/{v}] ───────
    if len(segs) >= 9 and segs[8] == "cryptoKeyVersions":
        key_name = "/".join(segs[:8])
        if not store.key_exists(key_name):
            return _err(404, "NOT_FOUND", f"CryptoKey {key_name} not found.")
        meta = store.get_key(key_name) or {}
        versions = meta.get("versions", {})
        if len(segs) == 9 and method == "GET":       # list versions
            items = [_version_view(key_name, v, versions[v]) for v in sorted(versions)]
            return _json(200, {"cryptoKeyVersions": items})
        if len(segs) == 10 and method == "GET":      # get one version
            ver = segs[9]
            if ver not in versions:
                return _err(404, "NOT_FOUND", f"CryptoKeyVersion {ver} not found.")
            return _json(200, _version_view(key_name, ver, versions[ver]))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported request on cryptoKeyVersions")

    return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")


# ── crypto operations (reuse the AWS KMS engine + key material) ─────────────
def _encrypt(store: KeyStore, name: str, payload: dict) -> GcpKmsResponse:
    if not store.key_exists(name):
        return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
    try:
        plaintext = base64.b64decode(payload.get("plaintext", "") or "")
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "plaintext must be valid base64.")
    if not plaintext:
        return _err(400, "INVALID_ARGUMENT", "plaintext must not be empty.")
    blob = store.engine.encrypt(store.get_material(name), name, plaintext)
    return _json(200, {
        "name": name,
        "ciphertext": _b64e(blob),
        "ciphertextCrc32c": None,
        "protectionLevel": "SOFTWARE",
    })


def _decrypt(store: KeyStore, name: str, payload: dict) -> GcpKmsResponse:
    if not store.key_exists(name):
        return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
    try:
        blob = base64.b64decode(payload.get("ciphertext", "") or "")
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "ciphertext must be valid base64.")
    # The ciphertext self-identifies its crypto key; it must match this resource.
    embedded = store.engine.key_id_in(blob)
    if embedded and embedded != name:
        return _err(400, "INVALID_ARGUMENT",
                    "Decryption failed: the ciphertext is for a different CryptoKey.")
    try:
        plaintext = store.engine.decrypt(store.get_material(name), blob)
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Decryption failed: the ciphertext is invalid.")
    return _json(200, {"plaintext": _b64e(plaintext), "protectionLevel": "SOFTWARE"})
