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
  - access version: GET .../secrets/{s}/versions/{v}:access  ({v} may be "latest"
                    or a configured version alias)
  - list secrets  : GET .../secrets            -> {"secrets":[...],"totalSize":N}
  - list versions : GET .../secrets/{s}/versions -> {"versions":[...]}
  - delete secret : DELETE .../secrets/{s}      -> {}
  - destroy ver.  : POST .../secrets/{s}/versions/{v}:destroy -> version DESTROYED
  - disable ver.  : POST .../secrets/{s}/versions/{v}:disable -> version DISABLED
  - enable ver.   : POST .../secrets/{s}/versions/{v}:enable  -> version ENABLED
  - update secret : PATCH .../secrets/{s}?updateMask=... body merges into the secret
                    (labels, annotations, rotation, expireTime, ttl, topics,
                    versionAliases) -> updated secret resource. replication is
                    immutable after creation, matching the real API.
  - IAM on a secret: .../secrets/{s}:getIamPolicy / :setIamPolicy / :testIamPermissions

v4 C0b — the offline appliance serves Secret Manager through THIS core (over
core/appliance_stores.py) instead of the retired Vault-KV handlers in
core/vault_routes.py. Legacy behaviours ported (tests/conformance/
test_c0b_legacy_parity_core.py): `secretId` accepted from the JSON body as well as
the query string, version numbers that survive a JSON round-trip of the store
(persisted stores write int keys as strings). (Pre-v4 Vault secrets are imported
by the appliance's store on first use — core/appliance_stores.py.)

Versions are auto-incrementing integers (1, 2, 3...) per GCP semantics; payloads
travel base64-encoded on the wire (the `data` field). All errors use the native
GCP {"error":{"code","message","status"}} body.

v4 DEPTH — cross-service/behavioural enforcement added on top of the base CRUD:
  - replication: structural validation (automatic xor userManaged, CMEK key name
    shape + location match) and immutability after create (real API behaviour).
  - rotation: real pre-condition (needs >=1 topic), minimum period, future
    nextRotationTime — the same checks google-cloud-secret-manager itself raises.
  - expiration: a secret whose expireTime has passed is ACTUALLY deleted on next
    read (list/get/access/patch), not just returned-and-ignored.
  - version aliases: access/enable/disable/destroy/get accept a configured alias
    wherever a version number or "latest" is accepted.
  - permissions: a real per-secret IAM policy (getIamPolicy/setIamPolicy/
    testIamPermissions) that is actually enforced against the
    X-Cloudlearn-Principal header on versions.access/add/enable/disable/destroy,
    secrets.delete and secrets.update — unlike GCP KMS/Pub/Sub's policy-store-only
    IAM, the simulator's caller holds every permission it asks about.
  - notifications/logging: optional `notifier`/`logger` callbacks (unused unless
    the router wires them — see core/aws_wire_router.py `_secrets_notify` /
    `_secrets_log`) fire a real Pub/Sub publish on each configured topic and a
    real Cloud Logging entry for every lifecycle event.
"""
from __future__ import annotations

import base64
import json
import re
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


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_rfc3339(ts) -> float | None:
    if not ts:
        return None
    s = str(ts).strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _parse_duration_secs(d) -> float | None:
    try:
        return float(str(d).rstrip("s"))
    except (TypeError, ValueError):
        return None


def _ttl_to_expire_time(ttl: str) -> str | None:
    """Google Duration string ("2592000s") -> an absolute Timestamp, the same
    conversion the real API performs for a create/patch request that sends `ttl`."""
    secs = _parse_duration_secs(ttl)
    if secs is None:
        return None
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


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


# ── resource views ────────────────────────────────────────────────────────
_OPTIONAL_SECRET_FIELDS = ("labels", "annotations", "rotation", "expireTime", "topics", "versionAliases")


def _secret_view(secret: dict) -> dict:
    return {
        "name": secret["name"],
        "createTime": secret["createTime"],
        "replication": secret.get("replication", {"automatic": {}}),
        **{k: secret[k] for k in _OPTIONAL_SECRET_FIELDS if secret.get(k)},
        "etag": secret.get("etag", "\"0\""),
    }


def _version_view(project: str, secret_id: str, ver: int, v: dict) -> dict:
    return {
        "name": _version_name(project, secret_id, ver),
        "createTime": v["createTime"],
        "state": v["state"],
        "replicationStatus": {"automatic": {}},
        "etag": v.get("etag", "\"0\""),
    }


def _norm(secret: dict | None) -> dict | None:
    """Version keys are ints; a JSON-persisted store hands them back as strings."""
    if isinstance(secret, dict):
        vers = secret.get("versions")
        if isinstance(vers, dict) and any(not isinstance(k, int) for k in vers):
            fixed = {int(k): v for k, v in vers.items()}
            vers.clear()
            vers.update(fixed)
        if "version_counter" in secret:
            secret["version_counter"] = int(secret["version_counter"] or 0)
    return secret


def _raw_get(store: KvStore, key: str) -> dict | None:
    return _norm(store.get_secret(key))


# ── lifecycle callbacks: notifier (Pub/Sub) + logger (Cloud Logging) ───────
def _notify(notifier, secret: dict, event_type: str) -> None:
    if not notifier:
        return
    for t in secret.get("topics") or []:
        name = (t or {}).get("name") if isinstance(t, dict) else None
        if not name:
            continue
        try:
            notifier(name, event_type, secret["name"])
        except Exception:
            pass   # a topic that doesn't exist (or a wiring gap) is silently skipped


def _log(logger, secret_name: str, event_type: str, message: str) -> None:
    if not logger:
        return
    try:
        logger(secret_name, event_type, message)
    except Exception:
        pass


def _get(store: KvStore, key: str, logger=None) -> dict | None:
    """Fetch a secret, auto-deleting it first if its expireTime has passed — the
    real service deletes the Secret resource itself once expireTime arrives;
    Vyomi mirrors that the next time anyone reads it."""
    secret = _raw_get(store, key)
    if secret is None:
        return None
    exp = _parse_rfc3339(secret.get("expireTime"))
    if exp is not None and exp <= _now_epoch():
        store.drop_secret(key)
        store.mirror_delete(key)
        store.persist()
        _log(logger, secret["name"], "SECRET_EXPIRE", f"Secret [{secret['name']}] expired and was deleted.")
        return None
    return secret


# ── IAM on a secret: a real, enforced policy (unlike GCP KMS/Pub/Sub's store-
# only policy, the simulator's caller only holds what a binding actually grants
# it) ───────────────────────────────────────────────────────────────────────
_OWNER_PRINCIPALS = {"", "root", "owner", "admin"}

_ROLE_PERMS: dict[str, list[str]] = {
    "roles/secretmanager.admin": ["*"],
    "roles/secretmanager.secretAccessor": [
        "secretmanager.versions.access", "secretmanager.versions.get", "secretmanager.secrets.get",
    ],
    "roles/secretmanager.secretVersionAdder": [
        "secretmanager.versions.add", "secretmanager.secrets.get",
    ],
    "roles/secretmanager.secretVersionManager": [
        "secretmanager.versions.access", "secretmanager.versions.get", "secretmanager.versions.add",
        "secretmanager.versions.enable", "secretmanager.versions.disable", "secretmanager.versions.destroy",
        "secretmanager.secrets.get",
    ],
    "roles/secretmanager.viewer": ["secretmanager.secrets.get", "secretmanager.secrets.list"],
}


def _header(headers: dict | None, name: str) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return str(v)
    return ""


def _principal(headers: dict | None) -> str:
    return _header(headers, "x-cloudlearn-principal").strip().lower()


def _granted(secret: dict, principal: str) -> set[str]:
    perms: set[str] = set()
    for b in (secret.get("iamPolicy") or {}).get("bindings") or []:
        role = str(b.get("role") or "")
        for m in b.get("members") or []:
            ms = str(m)
            if ms in ("allUsers", "allAuthenticatedUsers") or ms.split(":", 1)[-1].lower() == principal:
                perms.update(_ROLE_PERMS.get(role, []))
                break
    return perms


def _authorized(secret: dict, principal: str, permission: str) -> bool:
    if not principal or principal in _OWNER_PRINCIPALS:
        return True
    bindings = (secret.get("iamPolicy") or {}).get("bindings") or []
    if not bindings:
        return True   # no policy configured yet: nothing to deny against
    granted = _granted(secret, principal)
    return permission in granted or "*" in granted


def _require(secret: dict, headers, permission: str) -> GcpResponse | None:
    principal = _principal(headers)
    if _authorized(secret, principal, permission):
        return None
    return _err(403, f"Permission '{permission}' denied on resource '{secret.get('name')}' "
                     f"for principal '{principal}' (or it may not exist).")


def _default_policy() -> dict:
    return {"bindings": [], "etag": "AA=="}


# ── validation: replication, rotation, version aliases ─────────────────────
_CMEK_RE = re.compile(r"^projects/[^/]+/locations/([^/]+)/keyRings/[^/]+/cryptoKeys/[^/]+$")


def _validate_replication(replication) -> str | None:
    if not isinstance(replication, dict) or not replication:
        return None
    has_auto, has_um = "automatic" in replication, "userManaged" in replication
    if has_auto and has_um:
        return "replication must set exactly one of automatic or userManaged, not both."
    if has_um:
        um = replication.get("userManaged") or {}
        replicas = um.get("replicas")
        if not isinstance(replicas, list) or not replicas:
            return "replication.userManaged.replicas must be a non-empty list."
        seen = set()
        for r in replicas:
            if not isinstance(r, dict) or not str(r.get("location") or "").strip():
                return "Each replication.userManaged.replicas[] entry requires a non-empty location."
            loc = r["location"]
            if loc in seen:
                return f"replication.userManaged.replicas[] has a duplicate location '{loc}'."
            seen.add(loc)
            cmek = r.get("customerManagedEncryption")
            if cmek:
                name = cmek.get("kmsKeyName") or ""
                m = _CMEK_RE.match(name)
                if not m:
                    return f"customerManagedEncryption.kmsKeyName '{name}' is not a valid CryptoKey resource name."
                if m.group(1) != loc:
                    return (f"customerManagedEncryption.kmsKeyName location '{m.group(1)}' must match "
                            f"the replica location '{loc}'.")
    elif has_auto:
        cmek = (replication.get("automatic") or {}).get("customerManagedEncryption")
        if cmek:
            name = cmek.get("kmsKeyName") or ""
            if not _CMEK_RE.match(name):
                return f"customerManagedEncryption.kmsKeyName '{name}' is not a valid CryptoKey resource name."
    return None


def _validate_rotation(rotation, topics) -> str | None:
    if not rotation:
        return None
    period, next_rot = rotation.get("rotationPeriod"), rotation.get("nextRotationTime")
    if not period and not next_rot:
        return None
    if not topics:
        return ("A pre-condition for scheduling a rotation is the existence of at least one "
                "Pub/Sub topic configured to be notified.")
    if period is not None:
        secs = _parse_duration_secs(period)
        if secs is None or secs < 3600:
            return "rotation.rotationPeriod must be a duration of at least 3600s (1 hour)."
    if next_rot is not None:
        t = _parse_rfc3339(next_rot)
        if t is None or t <= _now_epoch():
            return "rotation.nextRotationTime must be a valid RFC 3339 timestamp in the future."
    return None


_ALIAS_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,62}$")


def _validate_aliases(aliases) -> str | None:
    if not aliases:
        return None
    for k in aliases:
        if k == "latest" or not _ALIAS_RE.match(str(k)):
            return (f"versionAliases key '{k}' is invalid (must match [a-zA-Z][a-zA-Z0-9_-]{{0,62}} "
                     "and may not be \"latest\").")
    return None


# ── version resolution ─────────────────────────────────────────────────────
def _resolve_version(secret: dict, ver_ref: str) -> int | None:
    """Map a version reference to a concrete version number: "latest" (the
    highest-numbered version that is not DESTROYED), an integer, or a
    configured version alias."""
    versions: dict = secret["versions"]
    if ver_ref == "latest":
        candidates = [n for n, v in versions.items() if v["state"] != DESTROYED]
        return max(candidates) if candidates else None
    try:
        n = int(ver_ref)
    except (TypeError, ValueError):
        alias_target = (secret.get("versionAliases") or {}).get(ver_ref)
        if alias_target is None:
            return None
        try:
            n = int(alias_target)
        except (TypeError, ValueError):
            return None
    return n if n in versions else None


# ── operations ─────────────────────────────────────────────────────────────
def _create_secret(store: KvStore, project: str, secret_id: str, body: dict,
                   notifier=None, logger=None) -> GcpResponse:
    if not secret_id:
        return _err(400, "secretId is required (query parameter).")
    key = _key(project, secret_id)
    if store.secret_exists(key):
        return _err(409, f"Secret [{_resource_name(project, secret_id)}] already exists.")
    replication = body.get("replication") or {"automatic": {}}
    rep_err = _validate_replication(replication)
    if rep_err:
        return _err(400, rep_err)
    topics = body.get("topics") or []
    rotation = body.get("rotation") or {}
    rot_err = _validate_rotation(rotation, topics)
    if rot_err:
        return _err(400, rot_err)
    aliases = body.get("versionAliases") or {}
    alias_err = _validate_aliases(aliases)
    if alias_err:
        return _err(400, alias_err)
    expire_time = body.get("expireTime") or (_ttl_to_expire_time(body["ttl"]) if body.get("ttl") else None)
    secret = {
        "name": _resource_name(project, secret_id),
        "project": project,
        "secretId": secret_id,
        "createTime": _now(),
        "replication": replication,
        "labels": body.get("labels") or {},
        "annotations": body.get("annotations") or {},
        "rotation": rotation,
        "topics": topics,
        "versionAliases": aliases,
        "iamPolicy": _default_policy(),
        **({"expireTime": expire_time} if expire_time else {}),
        "versions": {},
        "version_counter": 0,
    }
    store.put_secret(key, secret)
    store.mirror_put(key, secret)
    store.persist()
    _log(logger, secret["name"], "SECRET_CREATE", f"Secret [{secret['name']}] created.")
    return _json(200, _secret_view(secret))


def _add_version(store: KvStore, project: str, secret_id: str, body: dict,
                 headers=None, notifier=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    denied = _require(secret, headers, "secretmanager.versions.add")
    if denied:
        return denied
    payload = body.get("payload") or {}
    data = payload.get("data")
    if data is None:
        return _err(400, "payload.data is required.")
    # Validate the wire-supplied base64 (google-cloud-secret-manager sends it so).
    try:
        base64.b64decode(data, validate=True)
    except Exception:
        return _err(400, "payload.data must be base64-encoded.")
    ver = secret["version_counter"] + 1
    secret["version_counter"] = ver
    secret["versions"][ver] = {"data": data, "state": ENABLED, "createTime": _now()}
    store.mirror_put(key, secret)
    store.persist()
    _notify(notifier, secret, "SECRET_VERSION_ADD")
    _log(logger, secret["name"], "SECRET_VERSION_ADD", f"Version {ver} added to [{secret['name']}].")
    return _json(200, _version_view(project, secret_id, ver, secret["versions"][ver]))


def _access_version(store: KvStore, project: str, secret_id: str, ver_ref: str,
                    headers=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    denied = _require(secret, headers, "secretmanager.versions.access")
    if denied:
        return denied
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


def _list_secrets(store: KvStore, project: str, logger=None) -> GcpResponse:
    prefix = f"{project}/"
    secrets = []
    for k in list(store.names()):
        if not k.startswith(prefix):
            continue
        s = _get(store, k, logger)
        if s is not None:
            secrets.append(_secret_view(s))
    return _json(200, {"secrets": secrets, "totalSize": len(secrets)})


def _list_versions(store: KvStore, project: str, secret_id: str, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    versions = [_version_view(project, secret_id, n, secret["versions"][n])
                for n in sorted(secret["versions"], reverse=True)]
    return _json(200, {"versions": versions, "totalSize": len(versions)})


def _get_secret(store: KvStore, project: str, secret_id: str, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    return _json(200, _secret_view(secret))


_PATCHABLE_FIELDS = ("labels", "annotations", "rotation", "expireTime", "ttl", "topics", "versionAliases")


def _update_secret(store: KvStore, project: str, secret_id: str, body: dict, update_mask: str,
                   headers=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    denied = _require(secret, headers, "secretmanager.secrets.update")
    if denied:
        return denied
    fields = [f.strip() for f in update_mask.split(",") if f.strip()] if update_mask else list(body.keys())
    if "replication" in fields:
        return _err(400, "The replication policy for a secret cannot be changed after it is created.")
    new_rotation = body["rotation"] if "rotation" in fields and "rotation" in body else secret.get("rotation", {})
    new_topics = body["topics"] if "topics" in fields and "topics" in body else secret.get("topics", [])
    rot_err = _validate_rotation(new_rotation, new_topics)
    if rot_err:
        return _err(400, rot_err)
    if "versionAliases" in fields and "versionAliases" in body:
        alias_err = _validate_aliases(body["versionAliases"])
        if alias_err:
            return _err(400, alias_err)
    for f in fields:
        if f not in _PATCHABLE_FIELDS or f not in body:
            continue
        if f == "ttl":
            expire_time = _ttl_to_expire_time(body["ttl"])
            if expire_time:
                secret["expireTime"] = expire_time
        else:
            secret[f] = body[f]
    store.mirror_put(key, secret)
    store.persist()
    _log(logger, secret["name"], "SECRET_UPDATE", f"Secret [{secret['name']}] updated ({', '.join(fields)}).")
    return _json(200, _secret_view(secret))


def _delete_secret(store: KvStore, project: str, secret_id: str, headers=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    denied = _require(secret, headers, "secretmanager.secrets.delete")
    if denied:
        return denied
    store.drop_secret(key)
    store.mirror_delete(key)
    store.persist()
    _log(logger, secret["name"], "SECRET_DELETE", f"Secret [{secret['name']}] deleted.")
    return _json(200, {})


_STATE_PERM = {
    ENABLED: "secretmanager.versions.enable",
    DISABLED: "secretmanager.versions.disable",
    DESTROYED: "secretmanager.versions.destroy",
}
_STATE_EVENT = {
    ENABLED: "SECRET_VERSION_ENABLE",
    DISABLED: "SECRET_VERSION_DISABLE",
    DESTROYED: "SECRET_VERSION_DESTROY",
}


def _set_version_state(store: KvStore, project: str, secret_id: str, ver_ref: str, new_state: str,
                       headers=None, notifier=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    denied = _require(secret, headers, _STATE_PERM[new_state])
    if denied:
        return denied
    ver = _resolve_version(secret, ver_ref)
    if ver is None:
        return _err(404, f"Secret Version [{_resource_name(project, secret_id)}/versions/{ver_ref}] not found.")
    v = secret["versions"][ver]
    if v["state"] == DESTROYED and new_state != DESTROYED:
        return _err(400, f"Secret Version [{_version_name(project, secret_id, ver)}] is destroyed.",
                    token="FAILED_PRECONDITION")
    if new_state == DESTROYED:
        v["data"] = None  # payload is wiped on destroy
    v["state"] = new_state
    store.mirror_put(key, secret)
    store.persist()
    _notify(notifier, secret, _STATE_EVENT[new_state])
    _log(logger, secret["name"], _STATE_EVENT[new_state], f"Version {ver} of [{secret['name']}] set to {new_state}.")
    return _json(200, _version_view(project, secret_id, ver, v))


# ── IAM on a secret ──────────────────────────────────────────────────────────
def _get_iam_policy(store: KvStore, project: str, secret_id: str, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    return _json(200, secret.get("iamPolicy") or _default_policy())


def _set_iam_policy(store: KvStore, project: str, secret_id: str, body: dict,
                    headers=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    denied = _require(secret, headers, "secretmanager.secrets.setIamPolicy")
    if denied:
        return denied
    policy = dict(body.get("policy") or {})
    for b in policy.get("bindings") or []:
        if not str(b.get("role") or "") or not isinstance(b.get("members"), list) or not b["members"]:
            return _err(400, "Each policy.bindings[] entry requires a role and a non-empty members list.")
    policy.setdefault("bindings", [])
    policy["etag"] = base64.b64encode(f"{len(policy['bindings'])}-{_now()}".encode()).decode()
    secret["iamPolicy"] = policy
    store.mirror_put(key, secret)
    store.persist()
    _log(logger, secret["name"], "SECRET_SET_IAM_POLICY", f"IAM policy updated on [{secret['name']}].")
    return _json(200, policy)


def _test_iam_permissions(store: KvStore, project: str, secret_id: str, body: dict,
                          headers=None, logger=None) -> GcpResponse:
    key = _key(project, secret_id)
    secret = _get(store, key, logger)
    if secret is None:
        return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
    requested = [p for p in (body.get("permissions") or []) if isinstance(p, str)]
    principal = _principal(headers)
    bindings = (secret.get("iamPolicy") or {}).get("bindings") or []
    if not principal or principal in _OWNER_PRINCIPALS or not bindings:
        allowed = requested   # no policy configured / owner principal: nothing to deny against
    else:
        granted = _granted(secret, principal)
        allowed = [p for p in requested if p in granted or "*" in granted]
    return _json(200, {"permissions": allowed} if allowed else {})


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: KvStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", notifier=None, logger=None) -> GcpResponse:
    query = query or {}
    headers = headers or {}
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
            secret_id = (query.get("secretId") or query.get("secret_id")
                         or payload.get("secretId") or "")
            return _create_secret(store, project, secret_id, payload, notifier=notifier, logger=logger)
        if method == "GET":
            return _list_secrets(store, project, logger=logger)
        return _err(400, f"Unsupported method {method} on secrets collection.")

    secret_id = segs[3]

    # ---- single secret + custom methods: projects/{p}/secrets/{s}[:verb] ----
    if len(segs) == 4:
        if verb == "addVersion":
            return _add_version(store, project, secret_id, payload, headers=headers, notifier=notifier, logger=logger)
        if verb == "getIamPolicy":
            return _get_iam_policy(store, project, secret_id, logger=logger)
        if verb == "setIamPolicy":
            return _set_iam_policy(store, project, secret_id, payload, headers=headers, logger=logger)
        if verb == "testIamPermissions":
            return _test_iam_permissions(store, project, secret_id, payload, headers=headers, logger=logger)
        if method == "GET":
            return _get_secret(store, project, secret_id, logger=logger)
        if method == "PATCH":
            return _update_secret(store, project, secret_id, payload, query.get("updateMask") or "",
                                  headers=headers, logger=logger)
        if method == "DELETE":
            return _delete_secret(store, project, secret_id, headers=headers, logger=logger)
        return _err(400, f"Unsupported operation on secret ({method} :{verb}).")

    # ---- versions collection: projects/{p}/secrets/{s}/versions ----
    if len(segs) == 5 and segs[4] == "versions":
        if method == "GET":
            return _list_versions(store, project, secret_id, logger=logger)
        return _err(400, f"Unsupported method {method} on versions collection.")

    # ---- single version: projects/{p}/secrets/{s}/versions/{v} ----
    if len(segs) == 6 and segs[4] == "versions":
        ver_ref = segs[5]
        if verb == "access":
            return _access_version(store, project, secret_id, ver_ref, headers=headers, logger=logger)
        if verb == "destroy":
            return _set_version_state(store, project, secret_id, ver_ref, DESTROYED,
                                      headers=headers, notifier=notifier, logger=logger)
        if verb == "disable":
            return _set_version_state(store, project, secret_id, ver_ref, DISABLED,
                                      headers=headers, notifier=notifier, logger=logger)
        if verb == "enable":
            return _set_version_state(store, project, secret_id, ver_ref, ENABLED,
                                      headers=headers, notifier=notifier, logger=logger)
        if method == "GET":
            key = _key(project, secret_id)
            secret = _get(store, key, logger)
            if secret is None:
                return _err(404, f"Secret [{_resource_name(project, secret_id)}] not found.")
            ver = _resolve_version(secret, ver_ref)
            if ver is None:
                return _err(404, f"Secret Version [{_resource_name(project, secret_id)}/versions/{ver_ref}] not found.")
            return _json(200, _version_view(project, secret_id, ver, secret["versions"][ver]))
        return _err(400, f"Unsupported operation on version ({method} :{verb}).")

    return _err(404, f"Unknown path: {path}")
