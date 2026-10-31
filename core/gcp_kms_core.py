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

Scope (v1 slice): keyRings create/get/list (location "-" aggregates across locations),
cryptoKeys create/get/list/patch (location/keyRing "-" aggregates project-wide — the
console's Key inventory), :encrypt, :decrypt (encrypt requires the primary version to
be ENABLED; decrypt re-checks the state of the version that produced the ciphertext —
see cryptoKeyVersions below), :updateCryptoKeyPrimaryVersion, :getIamPolicy/:setIamPolicy.
cryptoKeyVersions get/list/create (each version is minted with its OWN key material, so
rotation — create + make primary — is genuine new crypto, not bookkeeping over shared
material), patch (enable/disable), :destroy, :restore.

v4 C0b — the offline appliance serves Cloud KMS through THIS core (over
core/appliance_stores.py) instead of the retired Vault-transit handlers in
core/vault_routes.py. Legacy behaviours ported here (pinned by
tests/conformance/test_c0b_legacy_parity_core.py): key labels / rotationPeriod /
nextRotationTime (the classic console's key settings) via PATCH cryptoKey with an
updateMask, ciphertextCrc32c / plaintextCrc32c (real CRC32C) on the wire, key rings
that persist with the store, and an optional `store.legacy_decrypt(name, blob)` hook
so ciphertext minted by the pre-v4 Vault-transit handler still decrypts.

v4 DEPTH — IAM policy on a CryptoKey is a real, enforced policy (mirrors the
per-secret enforcement in gcp_secretmanager_core.py): :encrypt/:decrypt and
:setIamPolicy are gated by the caller's granted role (identified by the
X-Cloudlearn-Principal header; an owner/root principal or an unconfigured
policy always passes). get/list/:getIamPolicy stay open. Rotation and
key-version lifecycle reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


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
    # (which is dedicated to this GCP KMS namespace) rather than the key map. A
    # store may expose its own `gcp_key_rings` mapping (the appliance's persisted
    # state); otherwise a lazy instance dict is attached (persisted stores list it
    # in their state attrs).
    rings = getattr(store, "gcp_key_rings", None)
    if rings is None:
        rings = store.__dict__.setdefault("gcp_key_rings", {})
    return rings


# ── CRC32C (Castagnoli) — the checksum the Cloud KMS wire carries ──────────
def _crc32c_table() -> list:
    tbl = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        tbl.append(c)
    return tbl


_CRC32C = _crc32c_table()


def crc32c(data: bytes) -> int:
    c = 0xFFFFFFFF
    for b in data:
        c = _CRC32C[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


# ── resource views ─────────────────────────────────────────────────────────
def _key_ring_view(name: str, entry: dict) -> dict:
    return {"name": name, "createTime": entry.get("createTime", _now())}


def _version_name(key_name: str, ver: str) -> str:
    return f"{key_name}/cryptoKeyVersions/{ver}"


def _version_view(key_name: str, ver: str, entry: dict) -> dict:
    view = {
        "name": _version_name(key_name, ver),
        "state": entry.get("state", "ENABLED"),
        "protectionLevel": entry.get("protectionLevel", "SOFTWARE"),
        "algorithm": entry.get("algorithm", "GOOGLE_SYMMETRIC_ENCRYPTION"),
        "createTime": entry.get("createTime", _now()),
        "generateTime": entry.get("createTime", _now()),
    }
    if entry.get("destroyTime"):
        view["destroyTime"] = entry["destroyTime"]
    if entry.get("destroyEventTime"):
        view["destroyEventTime"] = entry["destroyEventTime"]
    return view


def _crypto_key_view(store: KeyStore, name: str) -> dict:
    meta = store.get_key(name) or {}
    primary = str(meta.get("primary", "1"))
    versions = meta.get("versions", {primary: {}})
    view = {
        "name": name,
        "primary": _version_view(name, primary, versions.get(primary, {})),
        "purpose": _enum(meta.get("purpose"), _PURPOSES, "ENCRYPT_DECRYPT"),
        "createTime": meta.get("createTime", _now()),
        "versionTemplate": {
            "protectionLevel": "SOFTWARE",
            "algorithm": _enum(meta.get("algorithm"), _ALGORITHMS, "GOOGLE_SYMMETRIC_ENCRYPTION"),
        },
    }
    if meta.get("labels"):
        view["labels"] = dict(meta["labels"])
    if meta.get("rotationPeriod"):
        view["rotationPeriod"] = meta["rotationPeriod"]
    if meta.get("nextRotationTime"):
        view["nextRotationTime"] = meta["nextRotationTime"]
    view["destroyScheduledDuration"] = meta.get("destroyScheduledDuration", "86400s")
    return view


def _default_policy() -> dict:
    return {"version": 1, "etag": _b64e(b"0"), "bindings": []}


# ── IAM on a CryptoKey: a real, enforced policy (v4 DEPTH — was store-only) ──
# Mirrors the per-secret enforcement in gcp_secretmanager_core.py: owners/root bypass,
# an unconfigured policy denies nothing (so existing traffic keeps working), and only
# the "use the key material" + "change who can" operations are gated — get/list/
# getIamPolicy stay open, matching the real API's least-surprise default.
_OWNER_PRINCIPALS = {"", "root", "owner", "admin"}

_ROLE_PERMS: dict[str, list[str]] = {
    "roles/cloudkms.admin": [
        "cloudkms.cryptoKeys.get", "cloudkms.cryptoKeys.list", "cloudkms.cryptoKeys.update",
        "cloudkms.cryptoKeys.setIamPolicy",
        "cloudkms.cryptoKeyVersions.get", "cloudkms.cryptoKeyVersions.list",
        "cloudkms.cryptoKeyVersions.create", "cloudkms.cryptoKeyVersions.update",
        "cloudkms.cryptoKeyVersions.destroy", "cloudkms.cryptoKeyVersions.restore",
    ],
    "roles/cloudkms.cryptoKeyEncrypterDecrypter": [
        "cloudkms.cryptoKeyVersions.useToEncrypt", "cloudkms.cryptoKeyVersions.useToDecrypt",
        "cloudkms.cryptoKeys.get",
    ],
    "roles/cloudkms.cryptoKeyEncrypter": ["cloudkms.cryptoKeyVersions.useToEncrypt", "cloudkms.cryptoKeys.get"],
    "roles/cloudkms.cryptoKeyDecrypter": ["cloudkms.cryptoKeyVersions.useToDecrypt", "cloudkms.cryptoKeys.get"],
    "roles/cloudkms.cryptoKeyViewer": [
        "cloudkms.cryptoKeys.get", "cloudkms.cryptoKeys.list",
        "cloudkms.cryptoKeyVersions.get", "cloudkms.cryptoKeyVersions.list",
    ],
}


def _header(headers: dict | None, name: str) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return str(v)
    return ""


def _principal(headers: dict | None) -> str:
    return _header(headers, "x-cloudlearn-principal").strip().lower()


def _granted(meta: dict, principal: str) -> set[str]:
    perms: set[str] = set()
    for b in (meta.get("iamPolicy") or {}).get("bindings") or []:
        role = str(b.get("role") or "")
        for m in b.get("members") or []:
            ms = str(m)
            if ms in ("allUsers", "allAuthenticatedUsers") or ms.split(":", 1)[-1].lower() == principal:
                perms.update(_ROLE_PERMS.get(role, []))
                break
    return perms


def _authorized(meta: dict, principal: str, permission: str) -> bool:
    if not principal or principal in _OWNER_PRINCIPALS:
        return True
    bindings = (meta.get("iamPolicy") or {}).get("bindings") or []
    if not bindings:
        return True   # no policy configured yet: nothing to deny against
    return permission in _granted(meta, principal)


def _require(meta: dict, name: str, headers, permission: str) -> GcpKmsResponse | None:
    principal = _principal(headers)
    if _authorized(meta, principal, permission):
        return None
    return _err(403, "PERMISSION_DENIED",
                f"Permission '{permission}' denied on resource '{name}' (or it may not exist).")


# google-cloud-* REST clients send enums as numbers (`$alt=json;enum-encoding=int`).
_PURPOSES = {1: "ENCRYPT_DECRYPT", 5: "ASYMMETRIC_SIGN", 6: "ASYMMETRIC_DECRYPT",
             7: "RAW_ENCRYPT_DECRYPT", 9: "MAC"}
_ALGORITHMS = {1: "GOOGLE_SYMMETRIC_ENCRYPTION"}


def _enum(value, table: dict, default: str) -> str:
    if value in (None, "", 0, "0"):
        return default
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        return table.get(int(value), str(value))
    return str(value)


_MUTABLE = {"labels": "labels", "rotation_period": "rotationPeriod", "rotationPeriod": "rotationPeriod",
            "next_rotation_time": "nextRotationTime", "nextRotationTime": "nextRotationTime",
            "destroy_scheduled_duration": "destroyScheduledDuration", "destroyScheduledDuration": "destroyScheduledDuration"}


def _duration_seconds(d: str | None, default: int = 86400) -> int:
    """Parse a protobuf Duration string ("2592000s") used on the Cloud KMS wire."""
    try:
        return int(str(d).rstrip("s")) if d else default
    except (TypeError, ValueError):
        return default


def _apply_settings(meta: dict, payload: dict, mask: list) -> str | None:
    """Apply the mutable CryptoKey fields named by `mask` (all present ones when
    empty). Returns an error message for an unsupported mask path."""
    fields = mask or [k for k in ("labels", "rotationPeriod", "nextRotationTime", "destroyScheduledDuration") if k in payload]
    for f in fields:
        attr = _MUTABLE.get(f.strip())
        if not attr:
            return f"Unsupported update_mask path: {f}"
        val = payload.get(attr)
        if attr == "labels":
            meta["labels"] = {str(k): str(v) for k, v in (val or {}).items()} if isinstance(val, dict) else {}
        elif val:
            meta[attr] = str(val)
        else:
            meta.pop(attr, None)
    return None


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
            store.persist()
            return _json(200, _key_ring_view(name, rings[name]))
        if method == "GET":
            pseg = parent.split("/")   # projects/{p}/locations/{l-or-"-"}/keyRings
            items = [_key_ring_view(n, e) for n, e in sorted(rings.items())
                     if n.count("/") == 5 and all(p == "-" or p == n.split("/")[i] for i, p in enumerate(pseg))]
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
            meta = {
                "purpose": _enum(payload.get("purpose"), _PURPOSES, "ENCRYPT_DECRYPT"),
                "algorithm": _enum((payload.get("versionTemplate", {}) or {}).get("algorithm"),
                                   _ALGORITHMS, "GOOGLE_SYMMETRIC_ENCRYPTION"),
                "createTime": now,
                "primary": "1",
                "versions": {"1": {"state": "ENABLED", "createTime": now}},
            }
            _apply_settings(meta, payload, [])
            material = store.engine.new_key_material()
            store.put_key(name, meta, material)
            store.material[_version_name(name, "1")] = material
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        if method == "GET":
            pseg = ring_name.split("/")   # projects/{p}/locations/{l-or-"-"}/keyRings/{k-or-"-"}
            items = [_crypto_key_view(store, n) for n in store.key_ids()
                     if n.count("/") == 7 and n.split("/")[6] == "cryptoKeys"
                     and all(p == "-" or p == n.split("/")[i] for i, p in enumerate(pseg))]
            return _json(200, {"cryptoKeys": items})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on cryptoKeys")

    # ── single cryptoKey + custom methods: .../cryptoKeys/{k}[:verb] ────────
    if len(segs) == 8:
        name = "/".join(segs)
        if verb == "encrypt":
            return _encrypt(store, name, payload, headers)
        if verb == "decrypt":
            return _decrypt(store, name, payload, headers)
        if verb == "updateCryptoKeyPrimaryVersion":
            if not store.key_exists(name):
                return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
            meta = store.get_key(name)
            ver = str(payload.get("cryptoKeyVersionId") or "")
            if ver not in meta.get("versions", {}):
                return _err(400, "INVALID_ARGUMENT", f"CryptoKeyVersion {ver} not found.")
            meta["primary"] = ver
            store.put_key(name, meta, store.get_material(name))
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        if verb == "getIamPolicy":
            if not store.key_exists(name):
                return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
            meta = store.get_key(name)
            return _json(200, meta.get("iamPolicy") or _default_policy())
        if verb == "setIamPolicy":
            if not store.key_exists(name):
                return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
            meta = store.get_key(name)
            denied = _require(meta, name, headers, "cloudkms.cryptoKeys.setIamPolicy")
            if denied:
                return denied
            policy = dict(payload.get("policy") or {})
            for b in policy.get("bindings") or []:
                if not str(b.get("role") or "") or not isinstance(b.get("members"), list) or not b["members"]:
                    return _err(400, "INVALID_ARGUMENT",
                                "Each policy.bindings[] entry requires a role and a non-empty members list.")
            policy.setdefault("bindings", [])
            policy.setdefault("etag", _b64e(os.urandom(8)))
            meta["iamPolicy"] = policy
            store.put_key(name, meta, store.get_material(name))
            store.persist()
            return _json(200, policy)
        if verb:
            return _err(400, "INVALID_ARGUMENT", f"Unknown method :{verb}")
        if method == "GET":
            if not store.key_exists(name):
                return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
            return _json(200, _crypto_key_view(store, name))
        if method == "PATCH":                         # UpdateCryptoKey (labels / rotation)
            if not store.key_exists(name):
                return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
            mask = [m for m in str(query.get("updateMask") or query.get("update_mask") or "").split(",") if m]
            meta = store.get_key(name)
            bad = _apply_settings(meta, payload, mask)
            if bad:
                return _err(400, "INVALID_ARGUMENT", bad)
            store.put_key(name, meta, store.get_material(name))
            store.persist()
            return _json(200, _crypto_key_view(store, name))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on cryptoKey")

    # ── cryptoKeyVersions: .../cryptoKeys/{k}/cryptoKeyVersions[/{v}[:verb]] ─
    if len(segs) >= 9 and segs[8] == "cryptoKeyVersions":
        key_name = "/".join(segs[:8])
        if not store.key_exists(key_name):
            return _err(404, "NOT_FOUND", f"CryptoKey {key_name} not found.")
        meta = store.get_key(key_name) or {}
        versions = meta.get("versions", {})

        def _save() -> None:
            meta["versions"] = versions
            store.put_key(key_name, meta, store.get_material(key_name))
            store.persist()

        if len(segs) == 9 and method == "GET":       # list versions
            items = [_version_view(key_name, v, versions[v]) for v in sorted(versions)]
            return _json(200, {"cryptoKeyVersions": items})
        if len(segs) == 9 and method == "POST":      # create a new version with its OWN key material
            next_id = str(max((int(v) for v in versions), default=0) + 1)
            versions[next_id] = {"state": "ENABLED", "createTime": _now()}
            store.material[_version_name(key_name, next_id)] = store.engine.new_key_material()
            _save()
            return _json(200, _version_view(key_name, next_id, versions[next_id]))
        if len(segs) == 10 and method == "GET" and not verb:      # get one version
            ver = segs[9]
            if ver not in versions:
                return _err(404, "NOT_FOUND", f"CryptoKeyVersion {ver} not found.")
            return _json(200, _version_view(key_name, ver, versions[ver]))
        if len(segs) == 10 and method == "PATCH" and not verb:    # enable / disable
            ver = segs[9]
            if ver not in versions:
                return _err(404, "NOT_FOUND", f"CryptoKeyVersion {ver} not found.")
            state = payload.get("state")
            if state not in ("ENABLED", "DISABLED"):
                return _err(400, "INVALID_ARGUMENT", "state must be ENABLED or DISABLED.")
            if versions[ver].get("state") not in ("ENABLED", "DISABLED"):
                return _err(400, "FAILED_PRECONDITION",
                            f"CryptoKeyVersion {ver} is in state {versions[ver].get('state')} and cannot be updated.")
            versions[ver]["state"] = state
            _save()
            return _json(200, _version_view(key_name, ver, versions[ver]))
        if len(segs) == 10 and verb == "destroy":
            ver = segs[9]
            if ver not in versions:
                return _err(404, "NOT_FOUND", f"CryptoKeyVersion {ver} not found.")
            if versions[ver].get("state") in ("DESTROYED", "DESTROY_SCHEDULED"):
                return _err(400, "FAILED_PRECONDITION", f"CryptoKeyVersion {ver} is already scheduled for destruction.")
            versions[ver]["state"] = "DESTROY_SCHEDULED"
            versions[ver]["destroyTime"] = _future(_duration_seconds(meta.get("destroyScheduledDuration")))
            _save()
            return _json(200, _version_view(key_name, ver, versions[ver]))
        if len(segs) == 10 and verb == "restore":
            ver = segs[9]
            if ver not in versions:
                return _err(404, "NOT_FOUND", f"CryptoKeyVersion {ver} not found.")
            if versions[ver].get("state") != "DESTROY_SCHEDULED":
                return _err(400, "FAILED_PRECONDITION", f"CryptoKeyVersion {ver} is not scheduled for destruction.")
            versions[ver]["state"] = "DISABLED"
            versions[ver].pop("destroyTime", None)
            _save()
            return _json(200, _version_view(key_name, ver, versions[ver]))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported request on cryptoKeyVersions")

    return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")


# ── crypto operations (reuse the AWS KMS engine + key material) ─────────────
# Every CryptoKeyVersion gets its OWN key material (minted on create, above), so
# rotation is real: the new primary encrypts with genuinely different material, not
# the same bytes under a new label. Encrypt embeds the *version* that did the work
# (not just the CryptoKey) so Decrypt can re-check that specific version's state —
# the one piece symmetric Encrypt/Decrypt needs to enforce lifecycle correctly.
def _encrypt(store: KeyStore, name: str, payload: dict, headers: dict | None = None) -> GcpKmsResponse:
    if not store.key_exists(name):
        return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
    meta = store.get_key(name) or {}
    denied = _require(meta, name, headers, "cloudkms.cryptoKeyVersions.useToEncrypt")
    if denied:
        return denied
    primary = str(meta.get("primary", "1"))
    if meta.get("versions", {}).get(primary, {}).get("state", "ENABLED") != "ENABLED":
        return _err(400, "FAILED_PRECONDITION",
                    f"CryptoKeyVersion {name}/cryptoKeyVersions/{primary} is not enabled.")
    try:
        plaintext = base64.b64decode(payload.get("plaintext", "") or "")
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "plaintext must be valid base64.")
    if not plaintext:
        return _err(400, "INVALID_ARGUMENT", "plaintext must not be empty.")
    vname = _version_name(name, primary)
    material = store.get_material(vname) or store.get_material(name)
    blob = store.engine.encrypt(material, vname, plaintext)
    out = {
        "name": vname,
        "ciphertext": _b64e(blob),
        "ciphertextCrc32c": str(crc32c(blob)),
        "protectionLevel": "SOFTWARE",
    }
    if payload.get("plaintextCrc32c") not in (None, ""):
        if str(payload["plaintextCrc32c"]) != str(crc32c(plaintext)):
            return _err(400, "INVALID_ARGUMENT", "The checksum in field plaintext_crc32c did not match the data in field plaintext.")
        out["verifiedPlaintextCrc32c"] = True
    return _json(200, out)


def _decrypt(store: KeyStore, name: str, payload: dict, headers: dict | None = None) -> GcpKmsResponse:
    if not store.key_exists(name):
        return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
    denied = _require(store.get_key(name) or {}, name, headers, "cloudkms.cryptoKeyVersions.useToDecrypt")
    if denied:
        return denied
    try:
        blob = base64.b64decode(payload.get("ciphertext", "") or "")
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "ciphertext must be valid base64.")
    if payload.get("ciphertextCrc32c") not in (None, "") and str(payload["ciphertextCrc32c"]) != str(crc32c(blob)):
        return _err(400, "INVALID_ARGUMENT", "The checksum in field ciphertext_crc32c did not match the data in field ciphertext.")
    # The ciphertext self-identifies its CryptoKeyVersion; it must belong to this CryptoKey.
    embedded = store.engine.key_id_in(blob)
    if not embedded and hasattr(store, "legacy_decrypt"):
        # pre-v4 ciphertext (the appliance's retired Vault-transit handler)
        legacy = store.legacy_decrypt(name, blob)
        if legacy is not None:
            return _json(200, {"plaintext": _b64e(legacy), "plaintextCrc32c": str(crc32c(legacy)),
                               "usedPrimary": True, "protectionLevel": "SOFTWARE"})
    key_part, _, ver_part = (embedded or "").partition("/cryptoKeyVersions/")
    if embedded and key_part != name:
        return _err(400, "INVALID_ARGUMENT",
                    "Decryption failed: the ciphertext is for a different CryptoKey.")
    material = store.get_material(name)
    meta = store.get_key(name) or {}
    if ver_part:
        vstate = (meta.get("versions", {}).get(ver_part) or {}).get("state", "ENABLED")
        if vstate != "ENABLED":
            return _err(400, "FAILED_PRECONDITION",
                        f"Decryption failed: CryptoKeyVersion {name}/cryptoKeyVersions/{ver_part} is not enabled.")
        material = store.get_material(_version_name(name, ver_part)) or material
    try:
        plaintext = store.engine.decrypt(material, blob)
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Decryption failed: the ciphertext is invalid.")
    used_primary = (ver_part or str(meta.get("primary", "1"))) == str(meta.get("primary", "1"))
    return _json(200, {"plaintext": _b64e(plaintext), "plaintextCrc32c": str(crc32c(plaintext)),
                       "usedPrimary": used_primary, "protectionLevel": "SOFTWARE"})
