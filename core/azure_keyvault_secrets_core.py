"""Azure Key Vault — secrets data-plane core — substrate-independent, the Azure
analogue of core/gcp_storage_core.py / core/secrets_core.py. Speaks the native
**Key Vault Secrets REST API** (`/secrets/...?api-version=7.x`) so the native
`azure-keyvault-secrets` SDK works unchanged against it (point its
`SecretClient(vault_url=...)` at the endpoint).

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide.
Persists through the SAME KvStore seam as AWS Secrets Manager
(core/kv_store.py); Azure just gets its own namespaced store instance.

Scope (data plane): set secret (PUT, new 32-hex version each call), get current,
get specific version, list secrets, list versions, delete (soft-delete bundle
with recoveryId). Errors are the Key Vault JSON shape
`{"error":{"code":"SecretNotFound","message":...}}` matching the HTTP status.

The secret `id` is ALWAYS a full https URL including the version, exactly as the
service returns it — the SDK parses vault/name/version back out of it.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

from core.kv_store import InMemoryKvStore

# Default vault host baked into returned identifiers. The azure-keyvault-secrets
# SDK reads the vault_url from the id it gets back, so this just needs to be a
# well-formed KV host; the SDK's own vault_url is what the client sends to.
VAULT_HOST = "https://vault.vault.azure.net"
_RECOVERY_LEVEL = "Recoverable+Purgeable"


@dataclass
class KvResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ────────────────────────────────────────────────────────────
def _now() -> int:
    # Key Vault attributes carry POSIX seconds (unix epoch integers).
    return int(time.time())


def _new_version() -> str:
    return uuid.uuid4().hex  # 32 hex chars, matches KV version format


def _secret_id(name: str, version: str = "") -> str:
    if version:
        return f"{VAULT_HOST}/secrets/{name}/{version}"
    return f"{VAULT_HOST}/secrets/{name}"


def _json(status: int, obj: dict) -> KvResponse:
    return KvResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> KvResponse:
    body = {"error": {"code": code, "message": message}}
    return KvResponse(status=status, body=json.dumps(body).encode())


# ── record shape (owned by this core, stored through the KvStore seam) ─────
# store.secrets[name] = {
#   "name": name,
#   "current": version,          # latest set version
#   "deleted": bool,
#   "deletedDate": int | None,
#   "versions": { version: {"value","contentType","tags","attributes":{...}} },
# }
def _version_bundle(name: str, version: str, ver: dict) -> dict:
    out = {
        "value": ver.get("value"),
        "id": _secret_id(name, version),
        "attributes": ver.get("attributes", {}),
    }
    if ver.get("contentType") is not None:
        out["contentType"] = ver["contentType"]
    if ver.get("tags") is not None:
        out["tags"] = ver["tags"]
    return out


def _secret_item(name: str, rec: dict) -> dict:
    """List-secrets item: base id (no version) + current version attributes."""
    cur = rec["versions"][rec["current"]]
    item = {"id": _secret_id(name), "attributes": cur.get("attributes", {})}
    if cur.get("contentType") is not None:
        item["contentType"] = cur["contentType"]
    if cur.get("tags") is not None:
        item["tags"] = cur["tags"]
    return item


def _version_item(name: str, version: str, ver: dict) -> dict:
    """List-versions item: full versioned id + attributes (no value)."""
    item = {"id": _secret_id(name, version), "attributes": ver.get("attributes", {})}
    if ver.get("contentType") is not None:
        item["contentType"] = ver["contentType"]
    if ver.get("tags") is not None:
        item["tags"] = ver["tags"]
    return item


# ── soft delete: Manage deleted secrets (list / get / recover / purge) ────
def _deleted_item(name: str, rec: dict) -> dict:
    cur = rec["versions"][rec["current"]]
    out = {"id": _secret_id(name), "attributes": cur.get("attributes", {}),
           "recoveryId": f"{VAULT_HOST}/deletedsecrets/{name}", "deletedDate": rec.get("deletedDate"),
           "scheduledPurgeDate": (rec.get("deletedDate") or 0) + 90 * 24 * 3600}
    if cur.get("contentType") is not None:
        out["contentType"] = cur["contentType"]
    if cur.get("tags") is not None:
        out["tags"] = cur["tags"]
    return out


def _deleted_secrets(store, method: str, segs: list) -> KvResponse:
    if len(segs) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", f"Unsupported method {method} on /deletedsecrets")
        items = []
        for n in store.names():
            r = store.get_secret(n)
            if r and r.get("deleted") and r.get("versions"):
                items.append(_deleted_item(n, r))
        return _json(200, {"value": items, "nextLink": None})
    name = segs[1]
    rec = store.get_secret(name)
    if not rec or not rec.get("deleted") or not rec.get("versions"):
        return _err(404, "SecretNotFound", f"Deleted Secret not found: {name}")
    if len(segs) == 2 and method == "GET":
        out = _version_bundle(name, rec["current"], rec["versions"][rec["current"]])
        out.update(_deleted_item(name, rec))
        return _json(200, out)
    if len(segs) == 2 and method == "DELETE":      # purge
        store.drop_secret(name)
        store.persist()
        store.mirror_delete(name)
        return KvResponse(status=204, body=b"")
    if len(segs) == 3 and segs[2] == "recover" and method == "POST":
        rec["deleted"], rec["deletedDate"] = False, None
        store.put_secret(name, rec)
        store.persist()
        store.mirror_put(name, rec)
        return _json(200, _version_bundle(name, rec["current"], rec["versions"][rec["current"]]))
    return _err(405, "MethodNotAllowed", f"Unsupported method {method} on /deletedsecrets/{name}")


# ── per-vault scoping (secrets + certificates) ───────────────────────────
# Real Key Vault: secrets belong to ONE vault; a missing/deleted vault is 404 VaultNotFound.
# The simulator serves every vault from one relay, so the vault is read from the request
# (`/azure-data/keyvault/{vault}/...`, the console's `x-vyomi-vault` header, or a
# `<vault>.vault.azure.net` Host) and the store is wrapped in a view whose `secrets` map is
# namespaced `<vault>/<name>`. No vault in the request -> the legacy shared namespace (old
# state keeps working). Keys stay per-space (customer-managed-key envelopes resolve them by
# name from the unscoped store).
_VAULT_SEP = "/"


def vault_of(path: str = "", headers: dict | None = None) -> str:
    segs = [x for x in (path or "").split("?", 1)[0].split("/") if x]
    if len(segs) >= 3 and segs[0] == "azure-data" and segs[1] == "keyvault":
        return unquote(segs[2]).lower()
    lh = {str(k).lower(): v for k, v in (headers or {}).items()}
    v = str(lh.get("x-vyomi-vault") or "").strip()
    if v:
        return v.lower()
    host = str(lh.get("x-forwarded-host") or lh.get("host") or "").split(":")[0].lower()
    if host.endswith(".vault.azure.net") and host.count(".") >= 3:
        return host.split(".")[0]
    return ""


def vault_exists(arm_state, vault: str) -> bool:
    want = f"/vaults/{vault}".lower()
    for rec in (arm_state or {}).values():
        if isinstance(rec, dict) and str(rec.get("_type", "")).lower() == "microsoft.keyvault/vaults" \
                and str(rec.get("id", "")).lower().endswith(want):
            return True
    return False


def vault_not_found(vault: str) -> KvResponse:
    return _err(404, "VaultNotFound", f"A vault with name '{vault}' was not found in this subscription.")


class _PrefixDict:
    """Mapping view over `getter()` restricted to keys `<prefix>name`, exposed as `name`."""

    def __init__(self, getter, prefix: str):
        self._g, self._p = getter, prefix

    def __getitem__(self, k): return self._g()[self._p + k]
    def __setitem__(self, k, v): self._g()[self._p + k] = v
    def __delitem__(self, k): del self._g()[self._p + k]
    def __contains__(self, k): return (self._p + str(k)) in self._g()
    def __iter__(self): return iter([k[len(self._p):] for k in list(self._g()) if str(k).startswith(self._p)])
    def __len__(self): return sum(1 for _ in self)
    def get(self, k, d=None): return self._g().get(self._p + k, d)
    def pop(self, k, *d): return self._g().pop(self._p + k, *d)
    def keys(self): return list(iter(self))
    def values(self): return [self._g()[self._p + k] for k in self]
    def items(self): return [(k, self._g()[self._p + k]) for k in self]
    def setdefault(self, k, d=None): return self._g().setdefault(self._p + k, d)
    def update(self, o=(), **kw): [self.__setitem__(k, v) for k, v in dict(o, **kw).items()]
    def clear(self): [self.pop(k, None) for k in list(self)]


_VIEW_CLASSES: dict = {}


def scoped(store, vault: str):
    """`store` itself without a vault; else a view over `<vault>/`-namespaced secrets."""
    if not vault or store is None:
        return store
    base_cls = type(store)
    cls = _VIEW_CLASSES.get(base_cls)
    if cls is None:
        cls = type("VaultScoped" + base_cls.__name__, (base_cls,), {
            "secrets": property(lambda self: self.__dict__["_pd"]),
            "__getattr__": lambda self, n: getattr(self.__dict__["_base"], n),
        })
        _VIEW_CLASSES[base_cls] = cls
    v = cls.__new__(cls)
    v.__dict__["_base"] = store
    v.__dict__["_pd"] = _PrefixDict(lambda: store.secrets, vault.lower() + _VAULT_SEP)
    return v


def purge_vault(store, vault: str) -> int:
    """Drop every secret/cert a deleted vault owned. Returns how many were removed."""
    if store is None or not vault:
        return 0
    pre = vault.lower() + _VAULT_SEP
    d = store.secrets
    gone = [k for k in list(d) if str(k).startswith(pre)]
    for k in gone:
        d.pop(k, None)
    if gone:
        try:
            store.persist()
        except Exception:
            pass
    return len(gone)


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: InMemoryKvStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> KvResponse:
    query = query or {}
    method = method.upper()
    lheaders = {(k or "").lower(): v for k, v in (headers or {}).items()}

    # Key Vault auth challenge: the SDK sends an unauthenticated probe first and
    # expects a 401 + WWW-Authenticate, then retries with the bearer token (and
    # the real body). We never verify the token — the challenge just drives the
    # SDK's handshake so `azure-keyvault-secrets` works unchanged. Gated on an SDK
    # marker so substrate tests (which send no headers) are unaffected.
    _sdk = ("x-ms-client-request-id" in lheaders
            or "azsdk" in lheaders.get("user-agent", "").lower())
    if _sdk and "authorization" not in lheaders:
        return KvResponse(status=401, headers={
            "www-authenticate": ('Bearer authorization="https://login.microsoftonline.com/common", '
                                 'resource="https://vault.azure.net"')},
            body=b"", media_type=None)

    if not query.get("api-version"):
        return _err(400, "BadParameter", "The api-version query parameter is required.")

    p = path.split("?", 1)[0].rstrip("/")
    segs = [unquote(s) for s in p.split("/") if s != ""]

    if segs and segs[0] == "deletedsecrets":
        return _deleted_secrets(store, method, segs)
    if not segs or segs[0] != "secrets":
        return _err(404, "NotFound", f"Unknown path: {path}")

    # ---- /secrets  (collection) ----
    if len(segs) == 1:
        if method == "GET":                 # list secrets
            items = []
            for name in store.names():
                rec = store.get_secret(name)
                if rec and not rec.get("deleted") and rec.get("versions"):
                    items.append(_secret_item(name, rec))
            return _json(200, {"value": items, "nextLink": None})
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on /secrets")

    if len(segs) == 2 and segs[1] == "restore" and method == "POST":
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return _err(400, "BadParameter", "Request body is not valid JSON.")
        from core import azure_keyvault_keys_core as _k
        doc, bad = _k.backup_unpack("secret", payload.get("value") or "")
        if bad:
            return _err(400, "BadParameter", bad)
        existing = store.get_secret(doc["name"])
        if existing and not existing.get("deleted") and existing.get("versions"):
            return _err(409, "Conflict", f"A secret with name {doc['name']} already exists in this key vault; delete (and purge) it before restoring a backup.")
        rec = doc["record"]
        rec["deleted"], rec["deletedDate"] = False, None
        store.put_secret(doc["name"], rec)
        store.persist()
        store.mirror_put(doc["name"], rec)
        return _json(200, _version_bundle(doc["name"], rec["current"], rec["versions"][rec["current"]]))

    name = segs[1]

    if len(segs) == 3 and segs[2] == "backup" and method == "POST":
        rec = store.get_secret(name)
        if not rec or rec.get("deleted") or not rec.get("versions"):
            return _err(404, "SecretNotFound", f"A secret with (name/id) {name} was not found in this key vault.")
        from core import azure_keyvault_keys_core as _k
        return _json(200, {"value": _k._backup_pack("secret", {"name": name, "record": rec})})

    # ---- /secrets/{name}  ----
    if len(segs) == 2:
        if method == "PUT":                 # set secret (new version)
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return _err(400, "BadParameter", "Request body is not valid JSON.")
            if "value" not in payload:
                return _err(400, "BadParameter", "The secret value is required.")
            version = _new_version()
            now = _now()
            req_attrs = payload.get("attributes") or {}
            attributes = {
                "enabled": req_attrs.get("enabled", True),
                "created": now,
                "updated": now,
                "recoveryLevel": _RECOVERY_LEVEL,
            }
            ver = {
                "value": payload["value"],
                "contentType": payload.get("contentType"),
                "tags": payload.get("tags"),
                "attributes": attributes,
            }
            rec = store.get_secret(name)
            if not rec or rec.get("deleted"):
                rec = {"name": name, "versions": {}, "deleted": False, "deletedDate": None}
            rec["versions"][version] = ver
            rec["current"] = version
            rec["deleted"] = False
            store.put_secret(name, rec)
            store.persist()
            store.mirror_put(name, rec)
            return _json(200, _version_bundle(name, version, ver))

        if method == "GET":                 # get current secret
            rec = store.get_secret(name)
            if not rec or rec.get("deleted") or not rec.get("versions"):
                return _err(404, "SecretNotFound",
                            f"A secret with (name/id) {name} was not found in this key vault.")
            version = rec["current"]
            return _json(200, _version_bundle(name, version, rec["versions"][version]))

        if method == "DELETE":              # soft-delete secret
            rec = store.get_secret(name)
            if not rec or rec.get("deleted") or not rec.get("versions"):
                return _err(404, "SecretNotFound",
                            f"A secret with (name/id) {name} was not found in this key vault.")
            version = rec["current"]
            ver = rec["versions"][version]
            now = _now()
            rec["deleted"] = True
            rec["deletedDate"] = now
            store.put_secret(name, rec)
            store.persist()
            store.mirror_delete(name)
            bundle = _version_bundle(name, version, ver)
            bundle.update({
                "recoveryId": f"{VAULT_HOST}/deletedsecrets/{name}",
                "deletedDate": now,
                "scheduledPurgeDate": now + 90 * 24 * 3600,
            })
            return _json(200, bundle)

        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on secret")

    # ---- /secrets/{name}/versions  ----
    if len(segs) == 3 and segs[2] == "versions":
        if method == "GET":
            rec = store.get_secret(name)
            if not rec or rec.get("deleted") or not rec.get("versions"):
                return _err(404, "SecretNotFound",
                            f"A secret with (name/id) {name} was not found in this key vault.")
            items = [_version_item(name, v, ver) for v, ver in rec["versions"].items()]
            return _json(200, {"value": items, "nextLink": None})
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on versions")

    # ---- /secrets/{name}/{version}  ----
    if len(segs) == 3:
        version = segs[2]
        if method == "GET":
            rec = store.get_secret(name)
            if not rec or rec.get("deleted") or version not in rec.get("versions", {}):
                return _err(404, "SecretNotFound",
                            f"A secret with (name/id) {name}/{version} was not found in this key vault.")
            return _json(200, _version_bundle(name, version, rec["versions"][version]))
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on secret version")

    return _err(404, "NotFound", f"Unknown path: {path}")
