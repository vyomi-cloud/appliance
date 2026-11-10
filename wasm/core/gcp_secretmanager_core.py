# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Secret Manager core — substrate-independent, the GCP analogue of
core/secrets_core.py (AWS Secrets Manager). Speaks the native **Secret Manager
REST API v1** (`/v1/projects/{p}/secrets...`) so the native
`google-cloud-secret-manager` SDK works unchanged against it (point its
`api_endpoint` at the core's endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Persists through the SAME KvStore seam as AWS Secrets Manager
(core/kv_store.py); GCP just gets its own namespaced store instance, so secrets
are cloud-namespaced — the ADR-001 "one primitive, many clouds" model.

Wire shape recap (what google-cloud-secret-manager sends/expects):
  - create secret : POST .../secrets?secretId={id}
                    body {"replication":{"automatic":{}}}
                    -> secret resource {"name":"projects/{p}/secrets/{id}",
                                        "createTime":..., "replication":...}
  - add version   : POST .../secrets/{s}:addVersion
                    body {"payload":{"data": base64}}
                    -> version {"name":".../versions/N","state":"ENABLED"}
  - access version: GET .../secrets/{s}/versions/{v}:access  ({v} may be "latest")
                    -> {"name":".../versions/N","payload":{"data": base64}}
  - list secrets  : GET .../secrets            -> {"secrets":[...],"totalSize":N}
  - list versions : GET .../secrets/{s}/versions -> {"versions":[...]}
  - delete secret : DELETE .../secrets/{s}      -> {}
  - destroy ver.  : POST .../secrets/{s}/versions/{v}:destroy -> version DESTROYED
  - disable ver.  : POST .../secrets/{s}/versions/{v}:disable -> version DISABLED
  - enable ver.   : POST .../secrets/{s}/versions/{v}:enable  -> version ENABLED

Versions are auto-incrementing integers (1, 2, 3...) per GCP semantics; payloads
travel base64-encoded on the wire (the `data` field). All errors use the native
GCP {"error":{"code","message","status"}} body.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.kv_store import KvStore

ENABLED = "ENABLED"
DISABLED = "DISABLED"
DESTROYED = "DESTROYED"


@dataclass
class GcpResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _json(status: int, obj: dict) -> GcpResponse:
    return GcpResponse(status=status, body=json.dumps(obj).encode())


# GCP maps HTTP status -> a canonical status token in the error body.
_STATUS_TOKEN = {
    400: "INVALID_ARGUMENT",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "ALREADY_EXISTS",
    500: "INTERNAL",
}


def _err(status: int, message: str, token: str | None = None) -> GcpResponse:
    body = {"error": {"code": status, "message": message,
                      "status": token or _STATUS_TOKEN.get(status, "UNKNOWN")}}
    return GcpResponse(status=status, body=json.dumps(body).encode())


# ── storage key: namespace secrets by project inside the KvStore ───────────
def _key(project: str, secret_id: str) -> str:
    return f"{project}/{secret_id}"


def _resource_name(project: str, secret_id: str) -> str:
    return f"projects/{project}/secrets/{secret_id}"


def _version_name(project: str, secret_id: str, ver: int) -> str:
    return f"projects/{project}/secrets/{secret_id}/versions/{ver}"


# ── secret settings (secrets.patch) — shared with the offline (Vault-backed) appliance ──
PATCHABLE = ("labels", "rotation", "topics", "expireTime", "annotations", "versionAliases")


class SecretPatchError(Exception):
    def __init__(self, status: int, message: str, token: str = "INVALID_ARGUMENT"):
        super().__init__(message)
        self.status, self.message, self.token = status, message, token


def _dur_s(v) -> int:
    try:
        return int(float(str(v or "").rstrip("s")))
    except ValueError:
        raise SecretPatchError(400, "Invalid duration '%s' (seconds, e.g. 2592000s)." % v)


def replication_from_form(body: dict) -> dict:
    """The console form's replication choice → the Secret's replication policy."""
    rep = body.get("replication")
    if isinstance(rep, dict) and rep:
        return rep
    if str(rep or "automatic") == "user-managed":
        regions = [r.strip() for r in str(body.get("regions") or "").split(",") if r.strip()]
        if not regions:
            raise SecretPatchError(400, "A user-managed replication policy needs at least one location.")
        return {"userManaged": {"replicas": [{"location": r} for r in regions]}}
    return {"automatic": {}}


def validate_secret_patch(cur: dict, patch: dict, mask: str, topic_exists) -> dict:
    """secrets.patch: the fields in `mask` (comma list; empty = every patchable field in `patch`)."""
    fields = [f.strip() for f in (mask or "").split(",") if f.strip()] or [k for k in PATCHABLE if k in patch]
    out = {}
    for f in fields:
        root = f.split(".")[0]
        if root == "replication":
            raise SecretPatchError(400, "The replication policy of a secret cannot be changed after creation.")
        if root not in PATCHABLE:
            raise SecretPatchError(400, "Invalid update mask field: %s." % f)
        out[root] = patch.get(root)
    if "topics" in out:
        topics = [t for t in (out["topics"] or []) if (t or {}).get("name")]
        for t in topics:
            if not topic_exists(str(t["name"]).rsplit("/", 1)[-1]):
                raise SecretPatchError(404, "Pub/Sub topic %s not found." % t["name"], "NOT_FOUND")
        out["topics"] = [{"name": t["name"]} for t in topics]
    if "rotation" in out:
        rot = out["rotation"] or {}
        if rot:
            topics = out.get("topics", cur.get("topics")) or []
            if not topics:
                raise SecretPatchError(400, "Secret rotation requires at least one Pub/Sub topic for rotation notifications.")
            period = _dur_s(rot.get("rotationPeriod")) if rot.get("rotationPeriod") else 0
            if period and not 3600 <= period <= 3153600000:
                raise SecretPatchError(400, "rotation_period must be between 1 hour and 100 years.")
            nxt = rot.get("nextRotationTime")
            if not nxt:
                if not period:
                    raise SecretPatchError(400, "A rotation needs a next rotation time or a rotation period.")
                nxt = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + period, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                try:
                    t = datetime.strptime(str(nxt)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    raise SecretPatchError(400, "nextRotationTime must be an RFC 3339 timestamp.")
                if t.timestamp() < datetime.now(timezone.utc).timestamp() + 300:
                    raise SecretPatchError(400, "nextRotationTime must be at least 5 minutes in the future.")
            out["rotation"] = {"nextRotationTime": str(nxt), **({"rotationPeriod": "%ds" % period} if period else {})}
        else:
            out["rotation"] = None
    if "labels" in out:
        out["labels"] = {str(a): str(b) for a, b in (out["labels"] or {}).items()}
    return out


def apply_secret_patch(secret: dict, fields: dict) -> None:
    for k, v in fields.items():
        if v in (None, {}, []):
            secret.pop(k, None)
        else:
            secret[k] = v


# ── resource views ────────────────────────────────────────────────────────
def _secret_view(secret: dict) -> dict:
    return {
        "name": secret["name"],
        "createTime": secret["createTime"],
        "replication": secret.get("replication", {"automatic": {}}),
        **({"labels": secret["labels"]} if secret.get("labels") else {}),
        **{k: secret[k] for k in ("rotation", "topics", "expireTime", "annotations", "versionAliases") if secret.get(k)},
        "etag": secret.get("etag", "\"0\""),
    }


def _version_view(project: str, secret_id: str, ver: int, v: dict) -> dict:
    return {
        "name": _version_name(project, secret_id, ver),
        "createTime": v["createTime"],
        "state": v["state"],
        **({"destroyTime": v["destroyTime"]} if v.get("destroyTime") else {}),
        "replicationStatus": {"automatic": {}},
        "etag": v.get("etag", "\"0\""),
    }


# ── version resolution ─────────────────────────────────────────────────────
def _norm_versions(secret: dict) -> dict:
    """Version numbers are ints; a JSON round-trip (Nano's IndexedDB persistence, the
    file-backed store) turns them into strings — normalize them back in place."""
    vs = secret.setdefault("versions", {})
    if any(not isinstance(k, int) for k in vs):
        fixed = {int(k): v for k, v in vs.items()}
        vs.clear()
        vs.update(fixed)
        secret["version_counter"] = max([int(secret.get("version_counter") or 0)] + list(fixed))
    return vs


def _resolve_version(secret: dict, ver_ref: str) -> int | None:
    """Map a version reference ("latest" or an integer) to a concrete version
    number. "latest" = the highest-numbered version that is not DESTROYED."""
    versions: dict = _norm_versions(secret)
    if ver_ref == "latest":
        candidates = [n for n, v in versions.items() if v["state"] != DESTROYED]
        return max(candidates) if candidates else None
    try:
        n = int(ver_ref)
    except (TypeError, ValueError):
        return None
    return n if n in versions else None


# ── operations ─────────────────────────────────────────────────────────────
def _create_secret(store: KvStore, project: str, secret_id: str, body: dict) -> GcpResponse:
    if not secret_id:
        return _err(400, "secretId is required (query parameter).")
    key = _key(project, secret_id)
    if store.secret_exists(key):
        return _err(409, f"Secret [{_resource_name(project, secret_id)}] already exists.")
    secret = {
        "name": _resource_name(project, secret_id),
        "project": project,
        "secretId": secret_id,
        "createTime": _now(),
        "replication": body.get("replication") or {"automatic": {}},
        "labels": body.get("labels") or {},
        "versions": {},
        "version_counter": 0,
    }
    store.put_secret(key, secret)
    store.mirror_put(key, secret)
    store.persist()
    return _json(200, _secret_view(secret))


def _add_version(store: KvStore, project: str, secret_id: str, body: dict) -> GcpResponse:
    key = _key(project, secret_id)
    secret = store.get_secret(key)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    payload = body.get("payload") or {}
    data = payload.get("data")
    if data is None:
        return _err(400, "payload.data is required.")
    # Validate the wire-supplied base64 (google-cloud-secret-manager sends it so).
    try:
        base64.b64decode(data, validate=True)
    except Exception:
        return _err(400, "payload.data must be base64-encoded.")
    _norm_versions(secret)
    ver = int(secret["version_counter"]) + 1
    secret["version_counter"] = ver
    secret["versions"][ver] = {"data": data, "state": ENABLED, "createTime": _now()}
    store.mirror_put(key, secret)
    store.persist()
    return _json(200, _version_view(project, secret_id, ver, secret["versions"][ver]))


def _access_version(store: KvStore, project: str, secret_id: str, ver_ref: str) -> GcpResponse:
    key = _key(project, secret_id)
    secret = store.get_secret(key)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    ver = _resolve_version(secret, ver_ref)
    if ver is None:
        return _err(404, f"Secret Version [{_resource_name(project, secret_id)}/versions/{ver_ref}] not found.")
    v = secret["versions"][ver]
    if v["state"] == DESTROYED:
        return _err(400, f"Secret Version [{_version_name(project, secret_id, ver)}] is destroyed.",
                    token="FAILED_PRECONDITION")
    if v["state"] == DISABLED:
        return _err(400, f"Secret Version [{_version_name(project, secret_id, ver)}] is disabled.",
                    token="FAILED_PRECONDITION")
    return _json(200, {
        "name": _version_name(project, secret_id, ver),
        "payload": {"data": v["data"]},
    })


def _list_secrets(store: KvStore, project: str) -> GcpResponse:
    prefix = f"{project}/"
    secrets = [_secret_view(store.get_secret(k)) for k in store.names() if k.startswith(prefix)]
    return _json(200, {"secrets": secrets, "totalSize": len(secrets)})


def _list_versions(store: KvStore, project: str, secret_id: str) -> GcpResponse:
    key = _key(project, secret_id)
    secret = store.get_secret(key)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    versions = [_version_view(project, secret_id, n, secret["versions"][n])
                for n in sorted(_norm_versions(secret), reverse=True)]
    return _json(200, {"versions": versions, "totalSize": len(versions)})


def _get_secret(store: KvStore, project: str, secret_id: str) -> GcpResponse:
    key = _key(project, secret_id)
    secret = store.get_secret(key)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    return _json(200, _secret_view(secret))


def _delete_secret(store: KvStore, project: str, secret_id: str) -> GcpResponse:
    key = _key(project, secret_id)
    if not store.secret_exists(key):
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    store.drop_secret(key)
    store.mirror_delete(key)
    store.persist()
    return _json(200, {})


def _set_version_state(store: KvStore, project: str, secret_id: str, ver_ref: str,
                       new_state: str) -> GcpResponse:
    key = _key(project, secret_id)
    secret = store.get_secret(key)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    ver = _resolve_version(secret, ver_ref)
    if ver is None:
        return _err(404, f"Secret Version [{_resource_name(project, secret_id)}/versions/{ver_ref}] not found.")
    v = secret["versions"][ver]
    if v["state"] == DESTROYED and new_state != DESTROYED:
        return _err(400, f"Secret Version [{_version_name(project, secret_id, ver)}] is destroyed.",
                    token="FAILED_PRECONDITION")
    if new_state == DESTROYED:
        v["data"] = None  # payload is wiped on destroy
        v["destroyTime"] = _now()
    v["state"] = new_state
    store.mirror_put(key, secret)
    store.persist()
    return _json(200, _version_view(project, secret_id, ver, v))


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: KvStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcpResponse:
    query = query or {}
    method = method.upper()

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    # Normalise: strip a leading /v1 (or /v1beta1) prefix + trailing slash.
    p = path.split("?", 1)[0]
    for pre in ("/v1beta1", "/v1"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")

    # A trailing ":verb" custom method rides on the last path segment.
    verb = ""
    if ":" in p:
        p, verb = p.rsplit(":", 1)

    segs = [s for s in p.split("/") if s != ""]

    # Expect: projects/{p}/secrets[/{s}[/versions[/{v}]]]
    if len(segs) < 3 or segs[0] != "projects" or segs[2] != "secrets":
        return _err(404, f"Unknown path: {path}")
    project = segs[1]

    # ---- secrets collection: projects/{p}/secrets ----
    if len(segs) == 3:
        if method == "POST":
            secret_id = query.get("secretId") or query.get("secret_id") or ""
            return _create_secret(store, project, secret_id, payload)
        if method == "GET":
            return _list_secrets(store, project)
        return _err(400, f"Unsupported method {method} on secrets collection.")

    secret_id = segs[3]

    # ---- single secret: projects/{p}/secrets/{s} ----
    if len(segs) == 4:
        if verb == "addVersion":
            return _add_version(store, project, secret_id, payload)
        if method == "GET":
            return _get_secret(store, project, secret_id)
        if method == "DELETE":
            return _delete_secret(store, project, secret_id)
        if method == "PATCH":
            key = _key(project, secret_id)
            secret = store.get_secret(key)
            if secret is None:
                return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
            try:
                # topics are other services' resources: the caller checks they exist
                apply_secret_patch(secret, validate_secret_patch(secret, payload, query.get("updateMask", ""), lambda t: True))
            except SecretPatchError as e:
                return _err(e.status, e.message, token=e.token)
            store.mirror_put(key, secret)
            store.persist()
            return _json(200, _secret_view(secret))
        return _err(400, f"Unsupported operation on secret ({method} :{verb}).")

    # ---- versions collection: projects/{p}/secrets/{s}/versions ----
    if len(segs) == 5 and segs[4] == "versions":
        if method == "GET":
            return _list_versions(store, project, secret_id)
        return _err(400, f"Unsupported method {method} on versions collection.")

    # ---- single version: projects/{p}/secrets/{s}/versions/{v} ----
    if len(segs) == 6 and segs[4] == "versions":
        ver_ref = segs[5]
        if verb == "access":
            return _access_version(store, project, secret_id, ver_ref)
        if verb == "destroy":
            return _set_version_state(store, project, secret_id, ver_ref, DESTROYED)
        if verb == "disable":
            return _set_version_state(store, project, secret_id, ver_ref, DISABLED)
        if verb == "enable":
            return _set_version_state(store, project, secret_id, ver_ref, ENABLED)
        if method == "GET":
            key = _key(project, secret_id)
            secret = store.get_secret(key)
            if secret is None:
                return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
            ver = _resolve_version(secret, ver_ref)
            if ver is None:
                return _err(404, f"Secret Version [{_resource_name(project, secret_id)}/versions/{ver_ref}] not found.")
            return _json(200, _version_view(project, secret_id, ver, secret["versions"][ver]))
        return _err(400, f"Unsupported operation on version ({method} :{verb}).")

    return _err(404, f"Unknown path: {path}")
