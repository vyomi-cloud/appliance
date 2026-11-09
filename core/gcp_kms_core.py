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

v4 GAP SWEEP (wave 5b) — Autokey: automatic per-resource key ring/key provisioning.
The real AutokeyAdmin API configures a singleton AutokeyConfig on a FOLDER (state +
a dedicated keyProject) and derives each project's "effective" config from its
ancestry; Vyomi's Resource Manager core models projects only (no folders/orgs —
see gcp_resourcemanager_core.py), so AutokeyConfig collapses to one singleton per
PROJECT at `projects/{p}/autokeyConfig` (GET/PATCH) — same fields (keyProject,
state), same enforcement, one less level of indirection. Once a project's config
is ACTIVE, POSTing a KeyHandle (`projects/{p}/locations/{l}/keyHandles`) really
provisions: it creates (or reuses) an `autokey-{location}` key ring in the
configured key project and mints a brand-new CryptoKey in it with its own key
material, through the SAME create-key path :encrypt/:decrypt/rotation already
exercise — not bookkeeping. Creating a KeyHandle before Autokey is ACTIVE is
refused (FAILED_PRECONDITION), matching the real API.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

try:
    from core.kms_keystore import KeyStore
    from core import gcp_kms_import as _imp
except ImportError:  # pragma: no cover - Pyodide flat layout
    from kms_keystore import KeyStore  # type: ignore
    import gcp_kms_import as _imp  # type: ignore


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


# ── Autokey bookkeeping (same seam as _rings: attached to the store instance) ─
def _autokey_configs(store: KeyStore) -> dict:
    cfgs = getattr(store, "gcp_autokey_configs", None)
    if cfgs is None:
        cfgs = store.__dict__.setdefault("gcp_autokey_configs", {})
    return cfgs


def _key_handles(store: KeyStore) -> dict:
    handles = getattr(store, "gcp_key_handles", None)
    if handles is None:
        handles = store.__dict__.setdefault("gcp_key_handles", {})
    return handles


_PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_RESOURCE_TYPE_SELECTOR_RE = re.compile(r"^[a-z][a-z0-9.-]*\.googleapis\.com/[A-Za-z][A-Za-z0-9]*$")


def _autokey_config_view(name: str, cfg: dict) -> dict:
    return {"name": name, "keyProject": cfg.get("keyProject", ""), "state": cfg.get("state", "DISABLED")}


def _key_handle_view(name: str, h: dict) -> dict:
    view = {"name": name, "resourceTypeSelector": h.get("resourceTypeSelector", ""), "createTime": h.get("createTime", _now())}
    if h.get("kmsKey"):
        view["kmsKey"] = h["kmsKey"]
    return view


def _autokey_provision(store: KeyStore, key_project: str, location: str) -> str:
    """Real provisioning: ensure the project's Autokey key ring exists, then mint a
    brand-new CryptoKey with its OWN key material in it — the exact same steps
    CreateCryptoKey takes over the wire, just invoked internally so a KeyHandle's
    kmsKey is backed by a genuine, immediately usable key (not a stored reference)."""
    rings = _rings(store)
    ring_name = f"projects/{key_project}/locations/{location}/keyRings/autokey-{location}"
    if ring_name not in rings:
        rings[ring_name] = {"createTime": _now()}
    key_name = f"{ring_name}/cryptoKeys/autokey-{uuid.uuid4().hex[:16]}"
    now = _now()
    meta = {
        "purpose": "ENCRYPT_DECRYPT",
        "algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION",
        "createTime": now,
        "primary": "1",
        "versions": {"1": {"state": "ENABLED", "createTime": now}},
    }
    material = store.engine.new_key_material()
    store.put_key(key_name, meta, material)
    store.material[_version_name(key_name, "1")] = material
    return key_name


def _autokey_config_dispatch(store: KeyStore, project: str, method: str, payload: dict, query: dict) -> GcpKmsResponse:
    name = f"projects/{project}/autokeyConfig"
    cfgs = _autokey_configs(store)
    cfg = cfgs.setdefault(name, {"keyProject": "", "state": "DISABLED"})
    if method == "GET":
        return _json(200, _autokey_config_view(name, cfg))
    if method == "PATCH":
        mask = [m for m in str(query.get("updateMask") or query.get("update_mask") or "").split(",") if m]
        fields = mask or [f for f in ("keyProject", "state") if f in payload]
        if "keyProject" in fields:
            kp = str(payload.get("keyProject") or "").strip()
            kp = kp.rsplit("/", 1)[-1] if kp else kp
            if kp and not _PROJECT_ID_RE.match(kp):
                return _err(400, "INVALID_ARGUMENT", "keyProject must be a valid project ID.")
            cfg["keyProject"] = kp
        if "state" in fields:
            state = str(payload.get("state") or "").upper()
            if state not in ("ACTIVE", "DISABLED"):
                return _err(400, "INVALID_ARGUMENT", "state must be ACTIVE or DISABLED.")
            if state == "ACTIVE" and not cfg.get("keyProject"):
                return _err(400, "FAILED_PRECONDITION", "Autokey requires a keyProject before it can be set to ACTIVE.")
            cfg["state"] = state
        store.persist()
        return _json(200, _autokey_config_view(name, cfg))
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on autokeyConfig")


def _key_handles_dispatch(store: KeyStore, segs: list, verb: str | None, method: str, payload: dict, query: dict) -> GcpKmsResponse:
    project, location = segs[1], segs[3]
    handles = _key_handles(store)
    if len(segs) == 5:   # .../keyHandles collection
        if method == "POST":
            cfg = _autokey_configs(store).get(f"projects/{project}/autokeyConfig") or {}
            if cfg.get("state") != "ACTIVE":
                return _err(400, "FAILED_PRECONDITION",
                            f"Autokey is not enabled for project {project}. Set up Autokey before creating a key handle.")
            selector = str(payload.get("resourceTypeSelector") or "").strip()
            if not _RESOURCE_TYPE_SELECTOR_RE.match(selector):
                return _err(400, "INVALID_ARGUMENT",
                            "resourceTypeSelector must look like '<service>.googleapis.com/<Type>'.")
            hid = str(query.get("keyHandleId") or payload.get("keyHandleId") or "").strip() or f"autokey-{uuid.uuid4().hex[:16]}"
            name = f"projects/{project}/locations/{location}/keyHandles/{hid}"
            if name in handles:
                return _err(409, "ALREADY_EXISTS", f"KeyHandle {name} already exists.")
            kms_key = _autokey_provision(store, cfg["keyProject"], location)
            handles[name] = {"resourceTypeSelector": selector, "createTime": _now(), "kmsKey": kms_key}
            store.persist()
            opname = f"projects/{project}/locations/{location}/operations/autokey-{uuid.uuid4().hex[:12]}"
            return _json(200, {"name": opname, "done": True,
                                "response": {"@type": "type.googleapis.com/google.cloud.kms.v1.KeyHandle",
                                             **_key_handle_view(name, handles[name])}})
        if method == "GET":
            items = [_key_handle_view(n, h) for n, h in sorted(handles.items())
                     if n.startswith(f"projects/{project}/locations/") and (location == "-" or n.split("/")[3] == location)]
            return _json(200, {"keyHandles": items})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on keyHandles")
    if len(segs) == 6 and method == "GET" and not verb:   # single keyHandle
        name = "/".join(segs)
        if name not in handles:
            return _err(404, "NOT_FOUND", f"KeyHandle {name} not found.")
        return _json(200, _key_handle_view(name, handles[name]))
    return _err(400, "INVALID_ARGUMENT", "Unsupported request on keyHandles")


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
        **{k: entry[k] for k in ("destroyTime", "destroyEventTime") if entry.get(k)},
    }
    if entry.get("importJob"):
        view["importJob"] = entry["importJob"]
        view["importTime"] = entry.get("importTime", entry.get("createTime"))
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
        "purpose": _enum(meta.get("purpose"), _PURPOSES, "ENCRYPT_DECRYPT"),
        "createTime": meta.get("createTime", _now()),
        "versionTemplate": {
            "protectionLevel": "SOFTWARE",
            "algorithm": _enum(meta.get("algorithm"), _ALGORITHMS, "GOOGLE_SYMMETRIC_ENCRYPTION"),
        },
    }
    if primary in versions or not meta.get("importOnly"):
        view["primary"] = _version_view(name, primary, versions.get(primary, {}))
    if meta.get("importOnly"):
        view["importOnly"] = True
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


# ── key versions, rotation, primary, import jobs (shared with the offline appliance) ──
# Version 1's material is the key's own (ciphertexts embed the CryptoKey name, as
# before); a version N > 1 gets fresh material and its ciphertexts embed the version
# name, so decrypt finds the version — and refuses one that isn't ENABLED.
DESTROY_SCHEDULED_SECONDS = 30 * 86400   # Cloud KMS default destroy_scheduled_duration


class KmsTabError(Exception):
    def __init__(self, status: int, gcp_status: str, message: str):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _parse_ts(s: str) -> float:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _dur(v) -> int:
    try:
        return int(float(str(v or "").rstrip("s")))
    except ValueError:
        raise KmsTabError(400, "INVALID_ARGUMENT", "Invalid duration '%s' (seconds, e.g. 7776000s)." % v)


def validate_rotation(period, next_time) -> dict:
    """CryptoKey rotation_period / next_rotation_time rules (symmetric keys)."""
    out = {}
    if period not in (None, ""):
        secs = _dur(period)
        if secs < 86400:
            raise KmsTabError(400, "INVALID_ARGUMENT", "rotation_period must be at least 24 hours.")
        if secs > 876000 * 3600:
            raise KmsTabError(400, "INVALID_ARGUMENT", "rotation_period must be at most 100 years.")
        out["rotationPeriod"] = "%ds" % secs
    if next_time not in (None, ""):
        t = _parse_ts(next_time)
        if not t:
            raise KmsTabError(400, "INVALID_ARGUMENT", "next_rotation_time must be an RFC 3339 timestamp.")
        out["nextRotationTime"] = str(next_time)   # echoed as given (validated above)
    elif "rotationPeriod" in out:
        out["nextRotationTime"] = _ts(datetime.now(timezone.utc).timestamp() + _dur(out["rotationPeriod"]))
    return out


def _vmat_key(name: str, ver: str) -> str:
    return f"{name}/cryptoKeyVersions/{ver}"


def _version_material(store: KeyStore, name: str, ver: str):
    return store.get_material(name) if str(ver) == "1" else store.material.get(_vmat_key(name, ver))


def _new_version(store: KeyStore, name: str, meta: dict) -> str:
    versions = meta.setdefault("versions", {})
    ver = str(max([int(v) for v in versions] + [0]) + 1)
    versions[ver] = {"state": "ENABLED", "createTime": _now()}
    store.material[_vmat_key(name, ver)] = store.engine.new_key_material()
    return ver


def _maybe_rotate(store: KeyStore, name: str) -> None:
    """Automatic rotation: once next_rotation_time passes a new primary version is made."""
    meta = store.get_key(name) or {}
    nxt, period = meta.get("nextRotationTime"), meta.get("rotationPeriod")
    if not nxt or not period:
        return
    now = datetime.now(timezone.utc).timestamp()
    t, rotated = _parse_ts(nxt), False
    while t and t <= now:
        meta["primary"] = _new_version(store, name, meta)
        t += _dur(period)
        rotated = True
    if rotated:
        meta["nextRotationTime"] = _ts(t)
        store.persist()


def rotation_due(meta: dict) -> int:
    """How many automatic rotations are due (next_rotation_time passed), and move
    next_rotation_time past now — for backends that rotate their own key material."""
    nxt, period = meta.get("nextRotationTime"), meta.get("rotationPeriod")
    if not nxt or not period:
        return 0
    now, t, n = datetime.now(timezone.utc).timestamp(), _parse_ts(nxt), 0
    while t and t <= now:
        t += _dur(period)
        n += 1
    if n:
        meta["nextRotationTime"] = _ts(t)
    return n


def _purge_destroyed(store: KeyStore, name: str) -> None:
    """DESTROY_SCHEDULED versions whose destroy time passed lose their material."""
    meta = store.get_key(name) or {}
    now = datetime.now(timezone.utc).timestamp()
    for ver, v in (meta.get("versions") or {}).items():
        if v.get("state") == "DESTROY_SCHEDULED" and _parse_ts(v.get("destroyTime", "")) <= now:
            v["state"], v["destroyEventTime"] = "DESTROYED", _now()
            if str(ver) != "1":
                store.material.pop(_vmat_key(name, ver), None)


def set_version_state(meta: dict, ver: str, action: str) -> dict:
    """enable / disable / destroy / restore one version per Cloud KMS's state machine."""
    v = (meta.get("versions") or {}).get(str(ver))
    if v is None:
        raise KmsTabError(404, "NOT_FOUND", "CryptoKeyVersion %s not found." % ver)
    st = v.get("state", "ENABLED")
    if action in ("enable", "disable"):
        if st not in ("ENABLED", "DISABLED"):
            raise KmsTabError(400, "FAILED_PRECONDITION", "CryptoKeyVersion %s is %s; only ENABLED or DISABLED versions can change state." % (ver, st))
        # (disabling the primary is allowed: encrypt then fails until a new primary is set)
        v["state"] = "ENABLED" if action == "enable" else "DISABLED"
    elif action == "destroy":
        if st not in ("ENABLED", "DISABLED"):
            raise KmsTabError(400, "FAILED_PRECONDITION", "CryptoKeyVersion %s is already %s." % (ver, st))
        v["state"] = "DESTROY_SCHEDULED"
        v["destroyTime"] = _ts(datetime.now(timezone.utc).timestamp() + DESTROY_SCHEDULED_SECONDS)
    elif action == "restore":
        if st != "DESTROY_SCHEDULED":
            raise KmsTabError(400, "FAILED_PRECONDITION", "Only a version scheduled for destruction can be restored (it is %s)." % st)
        v["state"] = "DISABLED"
        v.pop("destroyTime", None)
    else:
        raise KmsTabError(400, "INVALID_ARGUMENT", "Unknown version action %s." % action)
    return v


def set_primary(meta: dict, ver: str) -> None:
    v = (meta.get("versions") or {}).get(str(ver))
    if v is None:
        raise KmsTabError(404, "NOT_FOUND", "CryptoKeyVersion %s not found." % ver)
    if v.get("state") != "ENABLED":
        raise KmsTabError(400, "FAILED_PRECONDITION", "The primary version must be ENABLED (version %s is %s)." % (ver, v.get("state")))
    meta["primary"] = str(ver)


# Import jobs: a real RSA wrapping key (OAEP) per job. With `cryptography` (the offline
# appliance) the key is generated at once; under Pyodide a pure-Python generator searches
# for the primes a slice of time per request, so the job stays PENDING_GENERATION until the
# key really exists — then ACTIVE, with its public key.
IMPORT_METHODS = {"RSA_OAEP_3072_SHA1_AES_256": 3072, "RSA_OAEP_4096_SHA1_AES_256": 4096,
                  "RSA_OAEP_3072_SHA256_AES_256": 3072, "RSA_OAEP_4096_SHA256_AES_256": 4096,
                  "RSA_OAEP_3072_SHA256": 3072, "RSA_OAEP_4096_SHA256": 4096}
_SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]


def _probable_prime(n: int, rounds: int = 24) -> bool:
    import random
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    rnd = random.SystemRandom()
    for _ in range(rounds):
        a = rnd.randrange(2, n - 2)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(body)) + body


def _der_int(v: int) -> bytes:
    b = v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big")
    return _der(0x02, b)


def rsa_public_pem(n: int, e: int) -> str:
    """SubjectPublicKeyInfo PEM for an RSA public key."""
    algo = _der(0x30, _der(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    spki = _der(0x30, algo + _der(0x03, b"\x00" + _der(0x30, _der_int(n) + _der_int(e))))
    b64 = base64.b64encode(spki).decode()
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64)) + "\n-----END PUBLIC KEY-----\n"


def rsa_generate(bits: int) -> dict:
    """A real RSA key pair {n, e, d, p, q} (`cryptography` when available, else pure Python)."""
    import os
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        nums = _rsa.generate_private_key(public_exponent=65537, key_size=bits).private_numbers()
        return {"n": nums.public_numbers.n, "e": 65537, "d": nums.d, "p": nums.p, "q": nums.q}
    except Exception:
        pass
    primes = []
    while len(primes) < 2:
        c = int.from_bytes(os.urandom(bits // 16), "big") | (3 << (bits // 2 - 2)) | 1
        if (c - 1) % 65537 and _probable_prime(c) and c not in primes:
            primes.append(c)
    p, q = primes
    return {"n": p * q, "e": 65537, "d": pow(65537, -1, (p - 1) * (q - 1)), "p": p, "q": q}


def rsa_private_pem(k: dict) -> str:
    """PKCS#8 PEM ('BEGIN PRIVATE KEY', what Google key files carry) of an RSA key."""
    n, e, d, p, q = (int(k[x]) for x in ("n", "e", "d", "p", "q"))
    rsa_der = _der(0x30, b"".join(_der_int(v) for v in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
    algo = _der(0x30, _der(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    pk8 = _der(0x30, _der_int(0) + algo + _der(0x04, rsa_der))
    b64 = base64.b64encode(pk8).decode()
    return "-----BEGIN PRIVATE KEY-----\n" + "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64)) + "\n-----END PRIVATE KEY-----\n"


def _advance_keygen(job: dict, budget_s: float) -> None:
    """Grow the job's RSA key: (cryptography) at once, else prime search within the budget."""
    import os
    import time as _time
    if job.get("state") != "PENDING_GENERATION":
        return
    bits = IMPORT_METHODS[job["importMethod"]]
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
        k = _rsa.generate_private_key(public_exponent=65537, key_size=bits)
        nums = k.private_numbers()
        job["_rsa"] = {"n": str(nums.public_numbers.n), "e": "65537", "p": str(nums.p), "q": str(nums.q)}
    except Exception:
        primes = [int(x) for x in job.setdefault("_primes", [])]
        stop = _time.time() + budget_s
        while len(primes) < 2 and _time.time() < stop:
            c = int.from_bytes(os.urandom(bits // 16), "big") | (3 << (bits // 2 - 2)) | 1
            if (c - 1) % 65537 and _probable_prime(c):
                primes.append(c)
        job["_primes"] = [str(p) for p in primes]
        if len(primes) < 2:
            return
        p, q = primes
        job["_rsa"] = {"n": str(p * q), "e": "65537", "p": str(p), "q": str(q)}
        job.pop("_primes", None)
    job["state"] = "ACTIVE"
    job["generateTime"] = _now()
    job["publicKey"] = {"pem": rsa_public_pem(int(job["_rsa"]["n"]), 65537)}


def import_job_view(name: str, job: dict) -> dict:
    return {"name": name, **{k: v for k, v in job.items() if not k.startswith("_")}}


def _import_jobs(store: KeyStore) -> dict:
    return store.__dict__.setdefault("gcp_import_jobs", {})


def import_job_create(jobs: dict, ring: str, jid: str, payload: dict, budget_s: float) -> dict:
    """importJobs.create into `jobs` ({job name: job}); returns the job view."""
    import re as _re
    if not _re.match(r"^[a-zA-Z0-9_-]{1,63}$", jid or ""):
        raise KmsTabError(400, "INVALID_ARGUMENT", "importJobId must be 1-63 letters, digits, '-' or '_'.")
    name = f"{ring}/importJobs/{jid}"
    if name in jobs:
        raise KmsTabError(409, "ALREADY_EXISTS", f"ImportJob {name} already exists.")
    meth = str(payload.get("importMethod") or "")
    if meth not in IMPORT_METHODS:
        raise KmsTabError(400, "INVALID_ARGUMENT", "import_method must be one of " + ", ".join(IMPORT_METHODS) + ".")
    lvl = str(payload.get("protectionLevel") or "SOFTWARE")
    if lvl not in ("SOFTWARE", "HSM"):
        raise KmsTabError(400, "INVALID_ARGUMENT", "protection_level must be SOFTWARE or HSM for import jobs.")
    now = datetime.now(timezone.utc).timestamp()
    jobs[name] = {"importMethod": meth, "protectionLevel": lvl, "createTime": _ts(now),
                  "expireTime": _ts(now + 3 * 86400), "state": "PENDING_GENERATION"}
    _advance_keygen(jobs[name], budget_s)
    return import_job_view(name, jobs[name])


def import_job_list(jobs: dict, ring: str, budget_s: float) -> list:
    out = []
    for n, j in sorted(jobs.items()):
        if n.startswith(ring + "/importJobs/"):
            _advance_keygen(j, budget_s)
            if j.get("state") == "ACTIVE" and _parse_ts(j.get("expireTime", "")) <= datetime.now(timezone.utc).timestamp():
                j["state"] = "EXPIRED"
            out.append(import_job_view(n, j))
    return out


def _import_job_route(store, method, segs, query, payload, budget_s):
    ring = "/".join(segs[:6])
    jobs = _import_jobs(store)
    if ring not in _rings(store):
        return _err(404, "NOT_FOUND", f"KeyRing {ring} not found.")
    if len(segs) == 7:
        if method == "POST":
            try:
                view = import_job_create(jobs, ring, str(query.get("importJobId") or payload.get("importJobId") or ""), payload, budget_s)
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
            store.persist()
            return _json(200, view)
        if method == "GET":
            out = import_job_list(jobs, ring, budget_s)
            store.persist()
            return _json(200, {"importJobs": out} if out else {})
    if len(segs) == 8 and method == "GET":
        name = "/".join(segs)
        if name not in jobs:
            return _err(404, "NOT_FOUND", f"ImportJob {name} not found.")
        _advance_keygen(jobs[name], budget_s)
        store.persist()
        return _json(200, import_job_view(name, jobs[name]))
    return _err(400, "INVALID_ARGUMENT", "Unsupported request on importJobs")


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

    # ── Autokey: projects/{p}/autokeyConfig and projects/{p}/locations/{l}/keyHandles[/{id}] ──
    if len(segs) == 3 and segs[0] == "projects" and segs[2] == "autokeyConfig" and not verb:
        return _autokey_config_dispatch(store, segs[1], method, payload, query)
    if len(segs) >= 5 and segs[0] == "projects" and segs[2] == "locations" and segs[4] == "keyHandles":
        return _key_handles_dispatch(store, segs, verb, method, payload, query)

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

    if segs[6] == "importJobs":
        return _import_jobs_dispatch(store, segs, verb, method, payload, query)

    # From here on the 7th segment must be cryptoKeys.
    if segs[6] != "cryptoKeys":
        return _err(404, "NOT_FOUND", f"Unknown resource path: {path}")
    if len(segs) >= 8 and store.key_exists("/".join(segs[:8])):
        _maybe_rotate(store, "/".join(segs[:8]))
        _purge_destroyed(store, "/".join(segs[:8]))

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
            skip = str(query.get("skipInitialVersionCreation", "")).lower() == "true"
            if payload.get("importOnly") or skip:
                meta["versions"] = {}          # import-only: versions arrive via cryptoKeyVersions:import
                meta["importOnly"] = bool(payload.get("importOnly"))
            _apply_settings(meta, payload, [])
            material = store.engine.new_key_material()
            store.put_key(name, meta, material)
            if meta["versions"]:
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
        if verb in ("updateCryptoKeyPrimaryVersion", "updatePrimaryVersion"):
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
        if method in ("GET", "PATCH") and not store.key_exists(name):
            return _err(404, "NOT_FOUND", f"CryptoKey {name} not found.")
        meta = store.get_key(name) if store.key_exists(name) else {}
        if method == "GET":
            return _json(200, _crypto_key_view(store, name))
        if method == "PATCH":                       # cryptoKeys.patch (rotation, labels)
            mask = [m.strip() for m in str(query.get("updateMask") or "").split(",") if m.strip()] or list(payload)
            try:
                for m in mask:
                    if m not in ("rotationPeriod", "nextRotationTime", "labels", "rotation_period", "next_rotation_time"):
                        raise KmsTabError(400, "INVALID_ARGUMENT", "Field %s can't be updated." % m)
                if any(m in mask for m in ("rotationPeriod", "nextRotationTime", "rotation_period", "next_rotation_time")):
                    _pm = any(m in mask for m in ("rotationPeriod", "rotation_period"))
                    period = payload.get("rotationPeriod") if _pm else meta.get("rotationPeriod")   # not in the mask: untouched
                    if _pm and period in (None, "") and "nextRotationTime" not in payload:
                        meta.pop("rotationPeriod", None)
                        meta.pop("nextRotationTime", None)
                    else:
                        meta.pop("rotationPeriod", None)
                        meta.update(validate_rotation(period, payload.get("nextRotationTime")))
                if "labels" in mask:
                    meta["labels"] = {str(a): str(b) for a, b in (payload.get("labels") or {}).items()}
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
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

        if len(segs) == 9 and verb == "import" and method == "POST":
            return _import_version(store, key_name, meta, versions, payload)
        if len(segs) == 9 and method == "GET":       # list versions
            items = [_version_view(key_name, v, versions[v]) for v in sorted(versions, key=int)]
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
            try:
                if verb in ("destroy", "restore") and method == "POST":
                    set_version_state(meta, ver, verb)
                elif method == "PATCH" and not verb:     # updateMask=state {state: ENABLED|DISABLED}
                    want = str(payload.get("state") or "")
                    if want not in ("ENABLED", "DISABLED"):
                        raise KmsTabError(400, "INVALID_ARGUMENT", "state can only be set to ENABLED or DISABLED.")
                    set_version_state(meta, ver, "enable" if want == "ENABLED" else "disable")
                elif method == "GET" and not verb:
                    return _json(200, _version_view(key_name, ver, versions[ver]))
                else:
                    return _err(400, "INVALID_ARGUMENT", f"Unsupported request on cryptoKeyVersions")
            except KmsTabError as e:
                return _err(e.status, e.gcp_status, e.message)
            store.persist()
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


# ── ImportJobs + wrapped key import ─────────────────────────────────────────
_IMPORT_JOB_TTL = 3 * 24 * 3600          # real jobs expire 3 days after creation


def _import_view(name: str, j: dict) -> dict:
    now = datetime.now(timezone.utc)
    exp = datetime.strptime(j["expireTime"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    state = j["state"]
    if state == "ACTIVE" and exp <= now:
        state = "EXPIRED"
    view = {"name": name, "importMethod": j["importMethod"],
            "protectionLevel": "SOFTWARE", "createTime": j["createTime"],
            "generateTime": j.get("generateTime", j["createTime"]),
            "expireTime": j["expireTime"], "state": state}
    if state == "EXPIRED":
        view["expireEventTime"] = j["expireTime"]
    else:
        view["publicKey"] = {"pem": j["publicKeyPem"],
                             "algorithm": "RSA_DECRYPT_OAEP_%d_%s" % (
                                 _imp.IMPORT_METHODS[j["importMethod"]][0],
                                 _imp.IMPORT_METHODS[j["importMethod"]][1])}
    return view


def _import_jobs_dispatch(store, segs, verb, method, payload, query) -> GcpKmsResponse:
    rings = _rings(store)
    ring = "/".join(segs[:6])
    if ring not in rings:
        return _err(404, "NOT_FOUND", f"KeyRing {ring} not found.")
    jobs = rings[ring].setdefault("importJobs", {})
    if len(segs) == 7:
        if method == "POST":
            jid = query.get("importJobId") or payload.get("importJobId")
            if not jid:
                return _err(400, "INVALID_ARGUMENT", "importJobId is required.")
            if not re.match(r"^[a-zA-Z0-9_-]{1,63}$", str(jid)):
                return _err(400, "INVALID_ARGUMENT", "importJobId must match [a-zA-Z0-9_-]{1,63}.")
            method_name = _enum(payload.get("importMethod"), {}, "")
            if method_name not in _imp.IMPORT_METHODS:
                return _err(400, "INVALID_ARGUMENT",
                            "importMethod must be one of: " + ", ".join(sorted(_imp.IMPORT_METHODS)) + ".")
            if payload.get("protectionLevel") not in (None, "", "SOFTWARE"):
                return _err(400, "INVALID_ARGUMENT", "Only protectionLevel SOFTWARE is supported by Vyomi.")
            name = f"{ring}/importJobs/{jid}"
            if name in jobs:
                return _err(409, "ALREADY_EXISTS", f"ImportJob {name} already exists.")
            kp = _imp.rsa_generate(_imp.IMPORT_METHODS[method_name][0])
            now = _now()
            jobs[name] = {"importMethod": method_name, "state": "ACTIVE", "createTime": now,
                          "generateTime": now, "expireTime": _future(_IMPORT_JOB_TTL),
                          "publicKeyPem": _imp.rsa_public_pem(kp["n"], kp["e"]),
                          "n": str(kp["n"]), "e": kp["e"], "d": str(kp["d"])}
            store.persist()
            return _json(200, _import_view(name, jobs[name]))
        if method == "GET":
            return _json(200, {"importJobs": [_import_view(n, j) for n, j in sorted(jobs.items())]})
    elif len(segs) == 8 and method == "GET" and not verb:
        name = "/".join(segs)
        if name not in jobs:
            return _err(404, "NOT_FOUND", f"ImportJob {name} not found.")
        return _json(200, _import_view(name, jobs[name]))
    return _err(400, "INVALID_ARGUMENT", f"Unsupported request on importJobs ({method}).")


def _import_version(store, key_name: str, meta: dict, versions: dict, payload: dict) -> GcpKmsResponse:
    job_name = str(payload.get("importJob") or "")
    ring = key_name.rsplit("/cryptoKeys/", 1)[0]
    job = (_rings(store).get(ring, {}).get("importJobs") or {}).get(job_name)
    if not job:
        return _err(404, "NOT_FOUND", f"ImportJob {job_name or '(unset)'} not found in key ring {ring}.")
    view = _import_view(job_name, job)
    if view["state"] != "ACTIVE":
        return _err(400, "FAILED_PRECONDITION", f"ImportJob {job_name} is {view['state']}; create a new import job.")
    algo = _enum(payload.get("algorithm"), {}, "")
    if algo != "GOOGLE_SYMMETRIC_ENCRYPTION":
        return _err(400, "INVALID_ARGUMENT",
                    "Vyomi imports symmetric key material only: algorithm must be GOOGLE_SYMMETRIC_ENCRYPTION.")
    if meta.get("purpose", "ENCRYPT_DECRYPT") != "ENCRYPT_DECRYPT":
        return _err(400, "INVALID_ARGUMENT", "Import is only supported into ENCRYPT_DECRYPT keys.")
    b64 = payload.get("rsaAesWrappedKey") or payload.get("wrappedKey")
    if not b64:
        return _err(400, "INVALID_ARGUMENT", "rsaAesWrappedKey (or wrappedKey) is required.")
    imp_method = job["importMethod"]
    with_aes = _imp.IMPORT_METHODS[imp_method][2]
    if with_aes and not payload.get("rsaAesWrappedKey"):
        return _err(400, "INVALID_ARGUMENT", f"Import method {imp_method} requires rsaAesWrappedKey.")
    if not with_aes and not payload.get("wrappedKey"):
        return _err(400, "INVALID_ARGUMENT", f"Import method {imp_method} requires wrappedKey.")
    try:
        wrapped = base64.b64decode(b64)
        raw = _imp.unwrap_import(imp_method, int(job["n"]), int(job["d"]), wrapped)
    except Exception:
        return _err(400, "INVALID_ARGUMENT",
                    "Unable to unwrap the key material: it was not wrapped for this import job's public key "
                    "with the job's import method (RSA-OAEP / AES-KWP).")
    if len(raw) != 32:
        return _err(400, "INVALID_ARGUMENT",
                    "GOOGLE_SYMMETRIC_ENCRYPTION requires a 256-bit (32-byte) key; the unwrapped key is %d bytes." % len(raw))
    next_id = str(max((int(v) for v in versions), default=0) + 1)
    now = _now()
    versions[next_id] = {"state": "ENABLED", "createTime": now, "importJob": job_name, "importTime": now}
    store.material[_version_name(key_name, next_id)] = raw
    if not meta.get("primary") or str(meta.get("primary")) not in versions:
        meta["primary"] = next_id
    elif len(versions) == 1:
        meta["primary"] = next_id
    meta["versions"] = versions
    store.put_key(key_name, meta, store.get_material(key_name))
    store.persist()
    return _json(200, _version_view(key_name, next_id, versions[next_id]))


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
    if primary not in meta.get("versions", {primary: {}}):
        return _err(400, "FAILED_PRECONDITION", f"CryptoKey {name} has no primary version; import key material first.")
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
