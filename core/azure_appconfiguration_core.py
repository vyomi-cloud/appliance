"""Azure App Configuration core (``Microsoft.AppConfiguration`` + the ``*.azconfig.io`` data plane).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

Control plane — ARM REST of the ``appconfiguration`` resource provider
(azure-rest-api-specs ``specification/appconfiguration/resource-manager``, api-version 2024-05-01), so
``azure-mgmt-appconfiguration`` / ``armappconfiguration`` / ``com.azure.resourcemanager.appconfiguration``
and ``az appconfig create|show|list|update|delete|credential`` work unchanged:

    Microsoft.AppConfiguration/configurationStores   (+ listKeys, regenerateKey, listKeyValue,
                                                        keyValues, replicas, privateLinkResources,
                                                        privateEndpointConnections)
    Microsoft.AppConfiguration/deletedConfigurationStores  (soft delete: list / get / purge / Recover)
    Microsoft.AppConfiguration/checkNameAvailability

Data plane — the ``{store}.azconfig.io`` REST API (azure-rest-api-specs
``specification/appconfiguration/data-plane``, 1.0 / 2023-11-01), so ``azure-data-appconfiguration``,
``azappconfig`` and ``az appconfig kv|feature|revision|snapshot`` work unchanged:

    /kv  /kv/{key}  /keys  /labels  /locks/{key}  /revisions  /snapshots  /snapshots/{name}  /operations

Key-values live INSIDE the store's ARM record (underscore key ``_kv``, never serialised to ARM
clients), so they are space-scoped and persisted by the same seams as the rest of ARM (offline
``azure_arm_state``; Nano ``az_arm``), and the ARM ``keyValues`` child resource and the data plane
are two views of the same data.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; ``data_dispatch`` returns
``{"status","headers","body","media"}`` (``body`` is a JSON-able object or ``None``).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

NAMESPACE = "Microsoft.AppConfiguration"
API_VERSION = "2024-05-01"
DATA_API_VERSION = "2023-11-01"
DEFAULT_LOCATION = "eastus"
SKUS = ("free", "developer", "standard", "premium")
MAX_HISTORY = 5000
PAGE_SIZE = 100
SEP = "\x1f"
KV_MEDIA = "application/vnd.microsoft.appconfig.kv+json"
KVSET_MEDIA = "application/vnd.microsoft.appconfig.kvset+json"
KEYSET_MEDIA = "application/vnd.microsoft.appconfig.keyset+json"
LABELSET_MEDIA = "application/vnd.microsoft.appconfig.labelset+json"
SNAP_MEDIA = "application/vnd.microsoft.appconfig.snapshot+json"
SNAPSET_MEDIA = "application/vnd.microsoft.appconfig.snapshotset+json"
KEY_NAMES = ("Primary", "Secondary", "Primary Read Only", "Secondary Read Only")


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _sysdata():
    n = _now()
    return {"createdBy": "vyomi@example.com", "createdByType": "User", "createdAt": n,
            "lastModifiedBy": "vyomi@example.com", "lastModifiedByType": "User", "lastModifiedAt": n}


def _to_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("true", "1", "yes", "enabled")


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


# ═══════════════════════════ control plane ═══════════════════════════════════════
def _stores(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/configurationStores".lower()]


def _find_store(state, name):
    n = (name or "").lower()
    for r in _stores(state):
        if r["name"].lower() == n:
            return r
    return None


def _name_problem(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{3,49}", name or "") or (name or "").endswith("-"):
        return ("Invalid", f"The name '{name}' is invalid. App Configuration store names must be 5-50 characters "
                           "and contain only letters, numbers and hyphens, and cannot start or end with a hyphen.")
    return None


def _endpoint(name, base=""):
    """Data-plane endpoint: the simulator's ``/azure-data/appconfig/{store}`` when the caller knows its
    own origin, else the real ``https://{store}.azconfig.io`` shape."""
    return f"{base.rstrip('/')}/azure-data/appconfig/{name}" if base else f"https://{name}.azconfig.io"


def _keys(rid, name):
    """The four access keys, deterministic per store so the same credentials work across restarts."""
    out = []
    for i, kname in enumerate(KEY_NAMES):
        kid = _h(rid, "id", i, n=4).upper() + "-l" + str(i) + "-s0:" + base64.b64encode(
            hashlib.sha256(f"{rid}|id|{i}".encode()).digest())[:20].decode().rstrip("=").replace("+", "x").replace("/", "y")
        secret = base64.b64encode(hashlib.sha256(f"{rid}|secret|{i}".encode()).digest()).decode()
        out.append({"id": kid, "name": kname, "value": secret, "lastModified": _now(), "readOnly": i >= 2,
                    "_gen": 0})
    return out


def _key_view(store, k):
    ep = store["properties"]["endpoint"]
    return {"id": k["id"], "name": k["name"], "value": k["value"],
            "connectionString": f"Endpoint={ep};Id={k['id']};Secret={k['value']}",
            "lastModified": k["lastModified"], "readOnly": k["readOnly"]}


def _store_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    return out


def _new_store(rid, name, sub, rg, payload, soft_deleted=None, base=""):
    pay = payload.get("properties") or {}
    sku = ((payload.get("sku") or {}).get("name") or "Standard")
    if str(sku).lower() not in SKUS:
        raise _E(400, "InvalidSku", f"The sku '{sku}' is not valid. Valid values are: Free, Developer, Standard, Premium.")
    loc = payload.get("location") or DEFAULT_LOCATION
    free = str(sku).lower() == "free"
    props = {
        "provisioningState": "Succeeded",
        "creationDate": _now(),
        "endpoint": _endpoint(name, base),
        "encryption": {"keyVaultProperties": pay.get("encryption", {}).get("keyVaultProperties")} if (pay.get("encryption") or {}).get("keyVaultProperties") else {},
        "privateEndpointConnections": [],
        "publicNetworkAccess": pay.get("publicNetworkAccess") or "Enabled",
        "disableLocalAuth": _to_bool(pay.get("disableLocalAuth")),
        "softDeleteRetentionInDays": 0 if free else (_to_int(pay.get("softDeleteRetentionInDays"), 7)),
        "enablePurgeProtection": False if free else _to_bool(pay.get("enablePurgeProtection")),
        "dataPlaneProxy": pay.get("dataPlaneProxy") or {"authenticationMode": "Local", "privateLinkDelegation": "Disabled"},
    }
    rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/configurationStores", "location": loc,
           "tags": dict(payload.get("tags") or {}), "sku": {"name": str(sku).capitalize()}, "properties": props,
           "systemData": _sysdata(), "_type": f"{NAMESPACE}/configurationStores", "_sub": sub, "_rg": rg,
           "_created": _now(), "_keys": _keys(rid, name),
           "_kv": {"items": {}, "history": [], "snapshots": {}, "seq": 0}, "_replicas": {}}
    if payload.get("identity"):
        ident = payload["identity"]
        t = ident.get("type") or "None"
        out = {"type": t}
        if "SystemAssigned" in t:
            out["principalId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, rid + "#p"))
            out["tenantId"] = "00000000-0000-0000-0000-000000000000"
        if "UserAssigned" in t:
            out["userAssignedIdentities"] = {k: {"principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#p")),
                                                  "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#c"))}
                                              for k in (ident.get("userAssignedIdentities") or {})}
        rec["identity"] = out
    if soft_deleted:
        rec["_kv"] = soft_deleted.get("_kv") or rec["_kv"]
        rec["_keys"] = soft_deleted.get("_keys") or rec["_keys"]
    return rec


def _apply_props(rec, payload):
    pay = payload.get("properties") or {}
    p = rec["properties"]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    if (payload.get("sku") or {}).get("name"):
        new = str(payload["sku"]["name"])
        if new.lower() not in SKUS:
            raise _E(400, "InvalidSku", f"The sku '{new}' is not valid.")
        rec["sku"]["name"] = new.capitalize()
        if new.lower() == "free":
            p["softDeleteRetentionInDays"], p["enablePurgeProtection"] = 0, False
    if "disableLocalAuth" in pay:
        p["disableLocalAuth"] = _to_bool(pay["disableLocalAuth"])
    if pay.get("publicNetworkAccess"):
        p["publicNetworkAccess"] = pay["publicNetworkAccess"]
    if "softDeleteRetentionInDays" in pay and rec["sku"]["name"].lower() != "free":
        p["softDeleteRetentionInDays"] = _to_int(pay["softDeleteRetentionInDays"], 7)
    if "enablePurgeProtection" in pay and rec["sku"]["name"].lower() != "free":
        p["enablePurgeProtection"] = _to_bool(pay["enablePurgeProtection"])
    if pay.get("encryption") is not None:
        p["encryption"] = pay["encryption"]
    if pay.get("dataPlaneProxy"):
        p["dataPlaneProxy"] = pay["dataPlaneProxy"]
    if payload.get("identity"):
        t = payload["identity"].get("type") or "None"
        ident = {"type": t}
        if "SystemAssigned" in t:
            ident["principalId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, rec["id"] + "#p"))
            ident["tenantId"] = "00000000-0000-0000-0000-000000000000"
        if "UserAssigned" in t:
            ident["userAssignedIdentities"] = {k: {"principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#p")),
                                                    "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#c"))}
                                                for k in (payload["identity"].get("userAssignedIdentities") or {})}
        if t == "None":
            rec.pop("identity", None)
        else:
            rec["identity"] = ident
    rec["systemData"]["lastModifiedAt"] = _now()


def _deleted_id(sub, loc, name):
    return f"/subscriptions/{sub}/providers/{NAMESPACE}/locations/{loc}/deletedConfigurationStores/{name}"


def _deleted_view(rec):
    return {"id": rec["id"], "name": rec["name"], "type": f"{NAMESPACE}/deletedConfigurationStores",
            "properties": dict(rec["properties"])}


def _put_store(state, sub, rg, rid, name, payload, method, base=""):
    rec = state.get(rid.lower())
    prob = _name_problem(name)
    if prob:
        raise _E(400, "InvalidParameter", prob[1])
    if rec is None and method == "PATCH":
        raise _not_found("configurationStores", name, rg)
    if rec is None:
        other = _find_store(state, name)
        if other is not None:
            raise _E(409, "Conflict",
                     f"The configuration store name '{name}' is already in use.")
        loc = payload.get("location") or DEFAULT_LOCATION
        did = _deleted_id(sub, loc, name).lower()
        gone = state.get(did)
        pay = payload.get("properties") or {}
        if gone is not None and str(pay.get("createMode", "")).lower() == "recover":
            state.pop(did)
            rec = _new_store(rid, name, sub, rg, payload, soft_deleted=gone, base=base)
        elif gone is not None:
            raise _E(409, "NameUnavailable",
                     f"The configuration store name '{name}' is soft-deleted. Purge it or create with createMode 'Recover'.")
        else:
            if not payload.get("location") and method == "PUT":
                raise _E(400, "LocationRequired", "The location property is required for this definition.")
            rec = _new_store(rid, name, sub, rg, payload, base=base)
        state[rid.lower()] = rec
        return rec, True
    _apply_props(rec, payload)
    return rec, False


def _delete_store(state, rec):
    p = rec["properties"]
    state.pop(rec["id"].lower(), None)
    if rec["sku"]["name"].lower() == "free" or not p.get("softDeleteRetentionInDays"):
        return
    did = _deleted_id(rec["_sub"], rec["location"], rec["name"])
    gone = {"id": did, "name": rec["name"], "type": f"{NAMESPACE}/deletedConfigurationStores",
            "properties": {"configurationStoreId": rec["id"], "location": rec["location"],
                           "deletionDate": _now(),
                           "scheduledPurgeDate": (datetime.now(timezone.utc) + timedelta(days=p["softDeleteRetentionInDays"]))
                           .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                           "tags": rec.get("tags") or {}, "purgeProtectionEnabled": bool(p.get("enablePurgeProtection"))},
            "_type": f"{NAMESPACE}/deletedConfigurationStores", "_sub": rec["_sub"], "_rg": None,
            "_kv": rec.get("_kv"), "_keys": rec.get("_keys"), "_loc": rec["location"]}
    state[did.lower()] = gone


def _list_stores(state, sub, rg):
    items = []
    for rec in _stores(state):
        if rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_store_view(rec))
    return _ok({"value": items})


# ── keyValues as ARM child resources ────────────────────────────────────────────
def _arm_kv_name(key, label):
    return key if label is None else f"{key}${label}"


def _split_arm_kv(name):
    name = unquote(name)
    if "$" in name:
        k, l = name.split("$", 1)
        return k, (None if l == "" else l)
    return name, None


def _arm_kv_view(store, kv):
    name = _arm_kv_name(kv["key"], kv["label"])
    return {"id": f"{store['id']}/keyValues/{name}", "name": name, "type": f"{NAMESPACE}/configurationStores/keyValues",
            "properties": {"key": kv["key"], "label": kv["label"], "value": kv["value"], "contentType": kv["content_type"],
                           "eTag": kv["etag"], "lastModified": kv["last_modified"], "locked": kv["locked"],
                           "tags": kv["tags"]}}


def _kv_ops(store, rest, method, payload):
    """keyValues sub-resource of a configuration store (ARM view over the data-plane items)."""
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_arm_kv_view(store, kv) for kv in sorted(_kv_items(store), key=lambda x: (x["key"], x["label"] or ""))]})
    key, label = _split_arm_kv(rest[0])
    if method == "GET":
        kv = _kv_get(store, key, label)
        if kv is None:
            return _err(404, "KeyValueNotFound", f"The key-value '{rest[0]}' was not found.")
        return _ok(_arm_kv_view(store, kv))
    if method == "PUT":
        pay = payload.get("properties") or {}
        kv = _kv_put(store, key, label, pay.get("value"), pay.get("contentType"), pay.get("tags"))
        return _ok(_arm_kv_view(store, kv))
    if method == "DELETE":
        _kv_delete(store, key, label)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _replica_view(store, r):
    return {"id": f"{store['id']}/replicas/{r['name']}", "name": r["name"], "type": f"{NAMESPACE}/configurationStores/replicas",
            "location": r["location"], "properties": {"endpoint": f"https://{store['name']}-{r['name']}.{r['location']}.azconfig.io",
                                                      "provisioningState": "Succeeded"},
            "systemData": r["systemData"]}


def _replica_ops(store, rest, method, payload):
    reps = store.setdefault("_replicas", {})
    if not rest:
        return _ok({"value": [_replica_view(store, r) for r in reps.values()]})
    name = rest[0]
    if method == "GET":
        if name.lower() not in reps:
            raise _E(404, "ReplicaNotFound", f"Replica '{name}' of configuration store '{store['name']}' was not found.")
        return _ok(_replica_view(store, reps[name.lower()]))
    if method == "PUT":
        if store["sku"]["name"].lower() not in ("standard", "premium"):
            raise _E(400, "ReplicaNotSupported", "Replicas require a Standard or Premium App Configuration store.")
        loc = payload.get("location") or "westus"
        if name.lower() in reps:
            return _ok(_replica_view(store, reps[name.lower()]), 200, lro=True, rid=f"{store['id']}/replicas/{name}", verb="put")
        reps[name.lower()] = {"name": name, "location": loc, "systemData": _sysdata()}
        return _ok(_replica_view(store, reps[name.lower()]), 201, lro=True, rid=f"{store['id']}/replicas/{name}", verb="put")
    if method == "DELETE":
        reps.pop(name.lower(), None)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _store_ops(state, rec, rest, method, payload, query):
    r0 = rest[0].lower()
    if r0 == "listkeys" and method == "POST":
        if rec["properties"].get("disableLocalAuth"):
            raise _E(400, "LocalAuthDisabled", "Local authentication (access keys) is disabled for this configuration store.")
        return _ok({"value": [_key_view(rec, k) for k in rec["_keys"]]})
    if r0 == "regeneratekey" and method == "POST":
        kid = payload.get("id")
        for i, k in enumerate(rec["_keys"]):
            if k["id"] == kid:
                k["_gen"] += 1
                k["value"] = base64.b64encode(hashlib.sha256(f"{rec['id']}|secret|{i}|{k['_gen']}|{uuid.uuid4()}".encode()).digest()).decode()
                k["lastModified"] = _now()
                return _ok(_key_view(rec, k))
        raise _E(400, "InvalidParameter", f"The key id '{kid}' does not belong to this configuration store.")
    if r0 == "listkeyvalue" and method == "POST":
        key = payload.get("key")
        if not key:
            raise _E(400, "InvalidParameter", "The 'key' property is required.")
        kv = _kv_get(rec, key, payload.get("label") or None)
        if kv is None:
            raise _E(404, "KeyValueNotFound", f"The key-value '{key}' was not found.")
        return _ok({"key": kv["key"], "label": kv["label"], "value": kv["value"], "contentType": kv["content_type"],
                    "eTag": kv["etag"], "lastModified": kv["last_modified"], "locked": kv["locked"], "tags": kv["tags"]})
    if r0 == "keyvalues":
        return _kv_ops(rec, rest[1:], method, payload)
    if r0 == "replicas":
        return _replica_ops(rec, rest[1:], method, payload)
    if r0 == "privatelinkresources" and method == "GET":
        pl = {"id": f"{rec['id']}/privateLinkResources/configurationStores", "name": "configurationStores",
              "type": f"{NAMESPACE}/configurationStores/privateLinkResources",
              "properties": {"groupId": "configurationStores", "requiredMembers": ["configurationStores"],
                             "requiredZoneNames": ["privatelink.azconfig.io"]}}
        if len(rest) == 1:
            return _ok({"value": [pl]})
        return _ok(pl)
    if r0 == "privateendpointconnections" and method == "GET" and len(rest) == 1:
        return _ok({"value": list(rec["properties"].get("privateEndpointConnections") or [])})
    raise _E(404, "ResourceTypeNotSupported",
             f"The resource type '{NAMESPACE}/configurationStores/{rest[0]}' is not supported.")


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.AppConfiguration`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, base)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    low = chain[0].lower()
    if low == "checknameavailability" or (low == "locations" and len(chain) >= 3 and chain[2].lower() == "checknameavailability"):
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        name = payload.get("name") or ""
        prob = _name_problem(name)
        if prob:
            return _ok({"nameAvailable": False, "reason": "Invalid", "message": prob[1]})
        if _find_store(state, name) is not None or state.get(_deleted_id(sub, DEFAULT_LOCATION, name).lower()) or any(
                str(r.get("_type", "")).lower().endswith("/deletedconfigurationstores") and r["name"].lower() == name.lower()
                for r in state.values()):
            return _ok({"nameAvailable": False, "reason": "AlreadyExists",
                        "message": f"The specified name '{name}' is already in use."})
        return _ok({"nameAvailable": True, "reason": None, "message": None})
    if low == "locations":                                  # locations/{loc}/deletedConfigurationStores[/{name}[/purge]]
        if len(chain) >= 3 and chain[2].lower() == "deletedconfigurationstores":
            return _deleted_ops(state, sub, chain, method)
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{'/'.join(chain)}' is not supported.")
    if low == "deletedconfigurationstores":
        return _deleted_ops(state, sub, ["locations", "-", "deletedConfigurationStores"] + chain[1:], method)
    if low != "configurationstores":
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0]}' is not supported.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_stores(state, sub, rg)
    name = chain[1]
    rid = _canon(sub, rg, ["configurationStores"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("configurationStores", name, rg)
        return _store_ops(state, rec, rest, method, payload, query)
    if method == "GET":
        if rec is None:
            raise _not_found("configurationStores", name, rg)
        return _ok(_store_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "App Configuration stores must be created in a resource group.")
        rec, created = _put_store(state, sub, rg, rid, name, payload, method, base)
        return _ok(_store_view(rec), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        _delete_store(state, rec)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _deleted_ops(state, sub, chain, method):
    gones = [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/deletedConfigurationStores".lower()
             and r.get("_sub") == sub]
    if len(chain) == 3:
        return _ok({"value": [_deleted_view(r) for r in gones]})
    name = chain[3]
    rec = next((r for r in gones if r["name"].lower() == name.lower()), None)
    if rec is None:
        raise _E(404, "DeletedConfigurationStoreNotFound", f"Deleted configuration store '{name}' was not found.")
    if len(chain) == 5 and chain[4].lower() == "purge" and method == "POST":
        if rec["properties"].get("purgeProtectionEnabled"):
            raise _E(409, "PurgeProtected", f"Configuration store '{name}' has purge protection enabled and cannot be purged yet.")
        state.pop(rec["id"].lower(), None)
        return _ok(None, 200, lro=True, rid=rec["id"], verb="purge")
    if len(chain) == 4 and method == "GET":
        return _ok(_deleted_view(rec))
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("configurationStores", API_VERSION)]


# ═══════════════════════════ key-value store (shared by both planes) ═══════════
def _kvs(store):
    kv = store.setdefault("_kv", {"items": {}, "history": [], "snapshots": {}, "seq": 0})
    kv.setdefault("snapshots", {})
    kv.setdefault("history", [])
    return kv


def _kv_items(store):
    return list(_kvs(store)["items"].values())


def _id(key, label):
    return key + SEP + ("" if label is None else "\u0001" + label)


def _kv_get(store, key, label):
    return _kvs(store)["items"].get(_id(key, label))


def _etag(store):
    s = _kvs(store)
    s["seq"] += 1
    return base64.urlsafe_b64encode(hashlib.sha256(f"{store['id']}|{s['seq']}|{uuid.uuid4()}".encode()).digest())[:27].decode()


def _record(store, kv, deleted=False):
    k = _kvs(store)
    h = k["history"]
    k["seq"] += 1
    h.append(dict(kv, _deleted=deleted, _at=_now(), _n=k["seq"]))
    if len(h) > MAX_HISTORY:
        del h[:len(h) - MAX_HISTORY]


def _kv_put(store, key, label, value, content_type=None, tags=None):
    old = _kv_get(store, key, label)
    if old is not None and old["locked"]:
        raise _Locked(key)
    kv = {"etag": _etag(store), "key": key, "label": label, "content_type": content_type,
          "value": value, "tags": dict(tags or {}), "locked": False, "last_modified": _now()}
    _kvs(store)["items"][_id(key, label)] = kv
    _record(store, kv)
    return kv


def _kv_delete(store, key, label):
    old = _kv_get(store, key, label)
    if old is None:
        return None
    if old["locked"]:
        raise _Locked(key)
    _kvs(store)["items"].pop(_id(key, label))
    gone = dict(old, last_modified=_now(), etag=_etag(store))
    _record(store, gone, deleted=True)
    return old


class _Locked(Exception):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


# ═══════════════════════════ data plane ══════════════════════════════════════════
class _D(Exception):
    def __init__(self, status, type_, title, detail="", name=""):
        super().__init__(title)
        self.status, self.type, self.title, self.detail, self.name = status, type_, title, detail, name


def _problem(status, type_, title, detail="", name=""):
    body = {"type": f"https://azconfig.io/errors/{type_}", "title": title, "name": name, "detail": detail, "status": status}
    return {"status": status, "headers": {}, "body": body, "media": "application/problem+json"}


def _kv_public(kv, fields=None):
    out = {"etag": kv["etag"], "key": kv["key"], "label": kv["label"], "content_type": kv["content_type"],
           "value": kv["value"], "tags": kv["tags"], "locked": kv["locked"], "last_modified": kv["last_modified"]}
    if fields:
        out = {k: v for k, v in out.items() if k in fields}
    return out


def _fields(query):
    sel = query.get("$Select") or query.get("$select") or ""
    f = {s.strip().lower() for s in sel.split(",") if s.strip()}
    return f or None


def _split_filter(expr):
    """Comma separated filter terms with ``\\`` escaping."""
    terms, cur, i = [], "", 0
    while i < len(expr):
        c = expr[i]
        if c == "\\" and i + 1 < len(expr):
            cur += "\\" + expr[i + 1]
            i += 2
            continue
        if c == ",":
            terms.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    terms.append(cur)
    return terms


def _unesc(s):
    return re.sub(r"\\(.)", r"\1", s)


def _term_match(term, value):
    if term == "\0" or term == "%00":
        return value is None
    if value is None:
        return term == "*"
    star_l = term.startswith("*")
    star_r = term.endswith("*") and not term.endswith("\\*")
    core = term[1 if star_l else 0: len(term) - 1 if star_r else len(term)]
    core = _unesc(core)
    if star_l and star_r:
        return core in value
    if star_l:
        return value.endswith(core)
    if star_r:
        return value.startswith(core)
    return value == core


def _filter_match(expr, value, null_ok_when_empty=True):
    if expr is None or expr == "":
        return True
    return any(_term_match(t, value) for t in _split_filter(expr))


def _tags_match(expr, kv):
    """``tags=name=value`` (repeatable → AND). ``value`` of ``\\0`` matches an absent value."""
    if not expr:
        return True
    for t in ([expr] if isinstance(expr, str) else expr):
        name, _, val = str(t).partition("=")
        have = (kv.get("tags") or {}).get(name)
        if val in ("\0", "%00"):
            if have is not None:
                return False
        elif have != val:
            return False
    return True


def _parse_dt(s):
    if not s:
        return None
    try:
        s = s.strip()
        for fmt in ("%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _at_time(store, when):
    """Items as they were at ``when`` (replays the revision history)."""
    cur = {}
    for rev in _kvs(store)["history"]:
        t = _parse_dt(rev["last_modified"]) or datetime.max.replace(tzinfo=timezone.utc)
        if t > when:
            continue
        i = _id(rev["key"], rev["label"])
        if rev["_deleted"]:
            cur.pop(i, None)
        else:
            cur[i] = {k: v for k, v in rev.items() if not k.startswith("_")}
    return list(cur.values())


def _http_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%a, %d %b %Y %H:%M:%S GMT")
    except ValueError:
        return iso


def _page(items, query, path, extra_q=""):
    after = query.get("after") or query.get("After") or ""
    start = 0
    if after:
        try:
            start = int(base64.urlsafe_b64decode(after + "=" * (-len(after) % 4)).decode())
        except Exception:
            start = 0
    chunk = items[start:start + PAGE_SIZE]
    body = {"items": chunk}
    if start + PAGE_SIZE < len(items):
        nxt = base64.urlsafe_b64encode(str(start + PAGE_SIZE).encode()).decode().rstrip("=")
        q = "&".join(f"{k}={quote(str(x), safe='*,=')}" for k, v in query.items() if k.lower() != "after"
                     for x in (v if isinstance(v, list) else [v]))
        body["@nextLink"] = f"{path}?{q}{'&' if q else ''}after={nxt}"
    return body


def _list_kv(store, query, headers):
    fields = _fields(query)
    snap = query.get("snapshot")
    if snap:
        s = _kvs(store)["snapshots"].get(snap)
        if s is None:
            raise _D(404, "not-found", "Resource not found", "", snap)
        items = list(s["_items"])
    else:
        dt = _parse_dt(headers.get("accept-datetime") or "")
        items = _at_time(store, dt) if dt else _kv_items(store)
    kf, lf = query.get("key"), query.get("label")
    out = [kv for kv in items if _filter_match(kf, kv["key"]) and _filter_match(lf, kv["label"]) and _tags_match(query.get("tags"), kv)]
    out.sort(key=lambda x: (x["key"], x["label"] or ""))
    return out, fields


def _snap_public(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def data_dispatch(state, store_name, method, path, query=None, headers=None, body=None, base=""):
    """One ``{store}.azconfig.io`` request. ``path`` starts at ``/kv``, ``/keys`` … ``body`` is bytes/str/dict/None."""
    method = (method or "GET").upper()
    query = {k: v for k, v in (query or {}).items()}
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    store = _find_store(state, store_name)
    if store is None:
        return _problem(404, "not-found", "The configuration store was not found.", f"No App Configuration store named '{store_name}'.", store_name)
    if str(headers.get("authorization", "")).startswith("HMAC-SHA256") and store["properties"].get("disableLocalAuth"):
        return _problem(403, "forbidden", "Access key authentication is disabled for this store.",
                        "Local authentication is disabled; use Microsoft Entra ID.", store_name)
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body) if body.strip() else {}
        except ValueError:
            return _problem(400, "invalid-argument", "Invalid request body", "The request body is not valid JSON.", "")
    body = body if isinstance(body, dict) else {}
    try:
        return _data(store, method, "/" + path.strip("/"), query, headers, body, base)
    except _D as e:
        return _problem(e.status, e.type, e.title, e.detail, e.name)
    except _Locked as e:
        return _problem(409, "key-locked", f"Modifing key '{e.key}' is not allowed", "The key is read-only. Unlock it to modify it.", e.key)


def _label_arg(query):
    lab = query.get("label")
    if lab in (None, "", "\0", "%00"):
        return None
    return lab


def _hdr(kv):
    return {"ETag": f'"{kv["etag"]}"', "Last-Modified": _http_date(kv["last_modified"])}


def _precond(headers, kv):
    """If-Match / If-None-Match against the current item (``kv`` may be None). Raises on failure."""
    im, inm = headers.get("if-match"), headers.get("if-none-match")
    if im is not None:
        if kv is None or (im.strip() != "*" and im.strip().strip('"') != kv["etag"]):
            raise _D(412, "precondition-failed", "Precondition failed", "The If-Match precondition was not met.", "")
    if inm is not None:
        if kv is not None and (inm.strip() == "*" or inm.strip().strip('"') == kv["etag"]):
            raise _D(412, "precondition-failed", "Precondition failed", "The If-None-Match precondition was not met.", "")


def _data(store, method, path, query, headers, body, base):
    s = _kvs(store)
    head = method == "HEAD"
    if head:
        method = "GET"
    parts = [unquote(p) for p in path.strip("/").split("/")]
    root = parts[0]
    ver = query.get("api-version") or DATA_API_VERSION

    def done(res):
        if head:
            res = dict(res, body=None)
        return res

    if root == "kv":
        if len(parts) == 1:
            if method != "GET":
                raise _D(405, "method-not-allowed", "Method not allowed", "", "")
            items, fields = _list_kv(store, query, headers)
            page = _page([_kv_public(kv, fields) for kv in items], query, "/kv")
            return done({"status": 200, "headers": {}, "body": page, "media": KVSET_MEDIA})
        key = "/".join(parts[1:])
        label = _label_arg(query)
        cur = _kv_get(store, key, label)
        if method == "GET":
            if cur is None:
                raise _D(404, "not-found", "Resource not found", "", key)
            inm = headers.get("if-none-match")
            if inm and inm.strip().strip('"') == cur["etag"]:
                return {"status": 304, "headers": _hdr(cur), "body": None, "media": KV_MEDIA}
            return done({"status": 200, "headers": _hdr(cur), "body": _kv_public(cur, _fields(query)), "media": KV_MEDIA})
        if method == "PUT":
            _precond(headers, cur)
            if "value" in body and body["value"] is not None and not isinstance(body["value"], str):
                raise _D(400, "invalid-argument", "Invalid request body", "'value' must be a string.", key)
            if len(key) > 10240:
                raise _D(400, "invalid-argument", "Key too long", "", key)
            kv = _kv_put(store, key, label, body.get("value"), body.get("content_type"), body.get("tags"))
            return {"status": 200, "headers": _hdr(kv), "body": _kv_public(kv), "media": KV_MEDIA}
        if method == "DELETE":
            if cur is None:
                _precond({k: v for k, v in headers.items() if k != "if-match"}, None)
                return {"status": 204, "headers": {}, "body": None, "media": KV_MEDIA}
            _precond(headers, cur)
            old = _kv_delete(store, key, label)
            return {"status": 200, "headers": _hdr(old), "body": _kv_public(old), "media": KV_MEDIA}
        raise _D(405, "method-not-allowed", "Method not allowed", "", "")

    if root in ("keys", "labels") and len(parts) == 1:
        if method != "GET":
            raise _D(405, "method-not-allowed", "Method not allowed", "", "")
        dt = _parse_dt(headers.get("accept-datetime") or "")
        items = _at_time(store, dt) if dt else _kv_items(store)
        field = "key" if root == "keys" else "label"
        names = sorted({kv[field] for kv in items if kv[field] is not None})
        flt = query.get("name")
        names = [n for n in names if _filter_match(flt, n)]
        page = _page([{"name": n} for n in names], query, "/" + root)
        return done({"status": 200, "headers": {}, "body": page, "media": KEYSET_MEDIA if root == "keys" else LABELSET_MEDIA})

    if root == "locks" and len(parts) >= 2:
        key = "/".join(parts[1:])
        label = _label_arg(query)
        cur = _kv_get(store, key, label)
        if cur is None:
            raise _D(404, "not-found", "Resource not found", "", key)
        if method not in ("PUT", "DELETE"):
            raise _D(405, "method-not-allowed", "Method not allowed", "", "")
        _precond(headers, cur)
        locked = method == "PUT"
        if cur["locked"] != locked:
            cur["locked"] = locked
            cur["etag"] = _etag(store)
            cur["last_modified"] = _now()
            _record(store, cur)
        return {"status": 200, "headers": _hdr(cur), "body": _kv_public(cur), "media": KV_MEDIA}

    if root == "revisions" and len(parts) == 1:
        if method != "GET":
            raise _D(405, "method-not-allowed", "Method not allowed", "", "")
        fields = _fields(query)
        kf, lf = query.get("key"), query.get("label")
        revs = [r for r in s["history"] if _filter_match(kf, r["key"]) and _filter_match(lf, r["label"])]
        dt = _parse_dt(headers.get("accept-datetime") or "")
        if dt:
            revs = [r for r in revs if (_parse_dt(r["last_modified"]) or dt) <= dt]
        revs = sorted(revs, key=lambda r: r.get("_n", 0), reverse=True)
        pub = [_kv_public({k: v for k, v in r.items() if not k.startswith("_")}, fields) for r in revs]
        return done({"status": 200, "headers": {}, "body": _page(pub, query, "/revisions"), "media": KVSET_MEDIA})

    if root == "snapshots":
        return _snapshots(store, method, parts, query, body, base, ver, head)

    if root == "operations" and len(parts) == 1:
        name = query.get("snapshot")
        snap = s["snapshots"].get(name or "")
        if snap is None:
            raise _D(404, "not-found", "Resource not found", "", name or "")
        return {"status": 200, "headers": {}, "body": {"id": name, "status": "Succeeded"}, "media": "application/json"}

    raise _D(404, "not-found", "Resource not found", f"Unknown path '{path}'.", "")


def _snapshots(store, method, parts, query, body, base, ver, head):
    snaps = _kvs(store)["snapshots"]
    if len(parts) == 1:
        if method != "GET":
            raise _D(405, "method-not-allowed", "Method not allowed", "", "")
        flt, st = query.get("name"), query.get("status")
        sts = {x.strip().lower() for x in st.split(",")} if st else None
        items = [_snap_public(x) for x in sorted(snaps.values(), key=lambda x: x["name"])
                 if _filter_match(flt, x["name"]) and (sts is None or x["status"] in sts)]
        return {"status": 200, "headers": {}, "body": _page(items, query, "/snapshots"), "media": SNAPSET_MEDIA}
    name = parts[1]
    cur = snaps.get(name)
    if len(parts) == 3 and parts[2] == "kv" and method == "GET":
        if cur is None:
            raise _D(404, "not-found", "Resource not found", "", name)
        return {"status": 200, "headers": {}, "body": _page(list(cur["_items"]), query, f"/snapshots/{name}/kv"), "media": KVSET_MEDIA}
    if method == "GET":
        if cur is None:
            raise _D(404, "not-found", "Resource not found", "", name)
        return {"status": 200, "headers": {"ETag": f'"{cur["etag"]}"'}, "body": _snap_public(cur), "media": SNAP_MEDIA}
    if method == "PUT":
        if cur is not None:
            raise _D(409, "already-exists", "The snapshot already exists", f"A snapshot named '{name}' already exists.", name)
        filters = body.get("filters") or []
        if not filters or len(filters) > 3:
            raise _D(400, "invalid-argument", "Invalid request body", "'filters' must contain between 1 and 3 filters.", name)
        comp = body.get("composition_type") or "key"
        if comp not in ("key", "key_label"):
            raise _D(400, "invalid-argument", "Invalid request body", "'composition_type' must be 'key' or 'key_label'.", name)
        items = {}
        for kv in _kv_items(store):
            if any(_filter_match(f.get("key"), kv["key"]) and _filter_match(f.get("label"), kv["label"]) and _tags_match(f.get("tags"), kv) for f in filters):
                ident = kv["key"] if comp == "key" else _id(kv["key"], kv["label"])
                items[ident] = dict(kv)
        if comp == "key":
            seen = {}
            for kv in sorted(items.values(), key=lambda x: x["last_modified"]):
                seen[kv["key"]] = kv
            items = seen
        frozen = sorted(items.values(), key=lambda x: (x["key"], x["label"] or ""))
        retention = _to_int(body.get("retention_period"), 7776000)
        now = datetime.now(timezone.utc)
        rec = {"etag": _etag(store), "name": name, "status": "ready", "filters": filters, "composition_type": comp,
               "created": _ts(now), "expires": None, "size": sum(len(json.dumps(i)) for i in frozen),
               "items_count": len(frozen), "tags": dict(body.get("tags") or {}), "retention_period": retention,
               "_items": frozen}
        snaps[name] = rec
        hdrs = {"ETag": f'"{rec["etag"]}"', "Operation-Location": f"{base}/operations?snapshot={quote(name)}&api-version={ver}",
                "Location": f"{base}/snapshots/{quote(name)}?api-version={ver}"}
        pub = _snap_public(rec)
        pub["status"] = "provisioning"
        return {"status": 201, "headers": hdrs, "body": pub, "media": SNAP_MEDIA}
    if method == "PATCH":
        if cur is None:
            raise _D(404, "not-found", "Resource not found", "", name)
        new = body.get("status")
        if new not in ("archived", "ready"):
            raise _D(400, "invalid-argument", "Invalid request body", "'status' must be 'archived' or 'ready'.", name)
        if new == "archived" and cur["status"] == "ready":
            cur["status"] = "archived"
            cur["expires"] = _ts(datetime.now(timezone.utc) + timedelta(seconds=cur["retention_period"]))
        elif new == "ready" and cur["status"] == "archived":
            cur["status"] = "ready"
            cur["expires"] = None
        elif new != cur["status"]:
            raise _D(409, "invalid-state", "Invalid snapshot state", f"Snapshot '{name}' is '{cur['status']}'.", name)
        cur["etag"] = _etag(store)
        return {"status": 200, "headers": {"ETag": f'"{cur["etag"]}"'}, "body": _snap_public(cur), "media": SNAP_MEDIA}
    raise _D(405, "method-not-allowed", "Method not allowed", "", "")


# ═══════════════════════════ console helpers ═════════════════════════════════════
def kv_count(store):
    return len(_kv_items(store))
