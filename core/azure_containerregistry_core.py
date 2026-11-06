"""Azure Container Registry core (``Microsoft.ContainerRegistry``).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

ARM REST of the ``containerregistry`` resource provider (azure-rest-api-specs
``specification/containerregistry/resource-manager``, api-version 2023-07-01), so
``azure-mgmt-containerregistry`` / ``armcontainerregistry`` / ``com.azure.resourcemanager.containerregistry``
and ``az acr create|show|list|update|delete|credential|check-name|replication|webhook|token|scope-map``
work unchanged:

    Microsoft.ContainerRegistry/registries   (+ listCredentials, regenerateCredential, generateCredentials,
                                               listUsages, listPrivateLinkResources, importImage,
                                               replications, webhooks, scopeMaps, tokens)
    Microsoft.ContainerRegistry/checkNameAvailability

The image data plane (``docker push|pull`` against ``{name}.azurecr.io``) is served offline by the shared
CNCF Distribution registry container (see providers/azure_containerregistry_routes.py); this engine owns
the registry resource, its credentials and its child resources. Child resources live INSIDE the registry's
ARM record (underscore keys, never serialised to ARM clients), so they are space-scoped and persisted by the
same seams as the rest of ARM.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able object or ``None``).
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.ContainerRegistry"
API_VERSION = "2023-07-01"
DEFAULT_LOCATION = "eastus"
SKUS = ("basic", "standard", "premium")
SKU_STORAGE_GB = {"basic": 10, "standard": 100, "premium": 500}
SKU_WEBHOOKS = {"basic": 2, "standard": 10, "premium": 500}
WEBHOOK_ACTIONS = ("push", "delete", "quarantine", "chart_push", "chart_delete")
PASSWORD_NAMES = ("password", "password2")
SYSTEM_SCOPE_MAPS = {
    "_repositories_admin": ["repositories/*/metadata/read", "repositories/*/metadata/write", "repositories/*/content/read",
                            "repositories/*/content/write", "repositories/*/content/delete"],
    "_repositories_pull": ["repositories/*/content/read"],
    "_repositories_push": ["repositories/*/content/read", "repositories/*/content/write"],
    "_repositories_pull_metadata_read": ["repositories/*/content/read", "repositories/*/metadata/read"],
    "_repositories_push_metadata_write": ["repositories/*/content/read", "repositories/*/content/write",
                                          "repositories/*/metadata/read", "repositories/*/metadata/write"],
}


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _login_server(name, base=""):
    return f"{name.lower()}.azurecr.io"


def _secret(rid, idx, gen, salt=""):
    raw = hashlib.sha256(f"{rid}|pw|{idx}|{gen}|{salt}".encode()).digest()
    return base64.b64encode(raw).decode().replace("+", "x").replace("/", "y").rstrip("=")[:32]


# ═══════════════════════════ registries ═══════════════════════════════════════════
def _registries(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/registries".lower()]


def _find_registry(state, name):
    n = (name or "").lower()
    for r in _registries(state):
        if r["name"].lower() == n:
            return r
    return None


def _name_problem(name):
    if not re.fullmatch(r"[A-Za-z0-9]{5,50}", name or ""):
        return ("Invalid", f"The registry name '{name}' is invalid. Registry names must be 5-50 characters and contain "
                           "only alphanumeric characters.")
    return None


def _default_policies():
    return {
        "quarantinePolicy": {"status": "disabled"},
        "trustPolicy": {"type": "Notary", "status": "disabled"},
        "retentionPolicy": {"days": 7, "lastUpdatedTime": _now(), "status": "disabled"},
        "exportPolicy": {"status": "enabled"},
        "azureADAuthenticationAsArmPolicy": {"status": "enabled"},
        "softDeletePolicy": {"retentionDays": 7, "lastUpdatedTime": _now(), "status": "disabled"},
    }


def _new_registry(rid, name, sub, rg, payload):
    pay = payload.get("properties") or {}
    sku = ((payload.get("sku") or {}).get("name") or "")
    if not sku:
        raise _E(400, "InvalidParameter", "The sku name is required. Valid values are: Basic, Standard, Premium.")
    if str(sku).lower() not in SKUS:
        raise _E(400, "InvalidSku", f"The sku '{sku}' is not valid. Valid values are: Basic, Standard, Premium.")
    if not payload.get("location"):
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    premium = str(sku).lower() == "premium"
    props = {
        "loginServer": _login_server(name),
        "creationDate": _now(),
        "provisioningState": "Succeeded",
        "status": {"displayStatus": "Ready", "message": "The registry is ready.", "timestamp": _now()},
        "adminUserEnabled": _to_bool(pay.get("adminUserEnabled")),
        "networkRuleSet": pay.get("networkRuleSet") or {"defaultAction": "Allow", "ipRules": []},
        "policies": _default_policies(),
        "encryption": {"status": "disabled"},
        "dataEndpointEnabled": premium and _to_bool(pay.get("dataEndpointEnabled")),
        "dataEndpointHostNames": [],
        "privateEndpointConnections": [],
        "publicNetworkAccess": pay.get("publicNetworkAccess") or "Enabled",
        "networkRuleBypassOptions": pay.get("networkRuleBypassOptions") or "AzureServices",
        "zoneRedundancy": (pay.get("zoneRedundancy") or "Disabled") if premium else "Disabled",
        "anonymousPullEnabled": _to_bool(pay.get("anonymousPullEnabled")),
    }
    if props["dataEndpointEnabled"]:
        props["dataEndpointHostNames"] = [f"{name.lower()}.{payload['location']}.data.azurecr.io"]
    for pk, pv in (pay.get("policies") or {}).items():
        if isinstance(pv, dict) and pk in props["policies"]:
            props["policies"][pk].update(pv)
    rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/registries", "location": payload["location"],
           "tags": dict(payload.get("tags") or {}), "sku": {"name": str(sku).capitalize(), "tier": str(sku).capitalize()},
           "properties": props, "systemData": _sysdata(),
           "_type": f"{NAMESPACE}/registries", "_sub": sub, "_rg": rg, "_gen": [0, 0],
           "_replications": {}, "_webhooks": {}, "_scopemaps": {}, "_tokens": {}, "_imports": []}
    if payload.get("identity"):
        rec["identity"] = _identity(rid, payload["identity"])
    return rec


def _identity(rid, ident):
    t = ident.get("type") or "None"
    out = {"type": t}
    if "SystemAssigned" in t:
        out["principalId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, rid + "#p"))
        out["tenantId"] = "00000000-0000-0000-0000-000000000000"
    if "UserAssigned" in t:
        out["userAssignedIdentities"] = {k: {"principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#p")),
                                              "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#c"))}
                                          for k in (ident.get("userAssignedIdentities") or {})}
    return out


def _apply_props(rec, payload):
    pay = payload.get("properties") or {}
    p = rec["properties"]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    if (payload.get("sku") or {}).get("name"):
        new = str(payload["sku"]["name"])
        if new.lower() not in SKUS:
            raise _E(400, "InvalidSku", f"The sku '{new}' is not valid.")
        if new.lower() != "premium" and rec["_replications"]:
            raise _E(409, "Conflict", "Registries with replications must stay on the Premium SKU; delete the replications first.")
        rec["sku"] = {"name": new.capitalize(), "tier": new.capitalize()}
        if new.lower() != "premium":
            p["zoneRedundancy"], p["dataEndpointEnabled"], p["dataEndpointHostNames"] = "Disabled", False, []
    premium = rec["sku"]["name"].lower() == "premium"
    if "adminUserEnabled" in pay:
        p["adminUserEnabled"] = _to_bool(pay["adminUserEnabled"])
    if "anonymousPullEnabled" in pay:
        p["anonymousPullEnabled"] = _to_bool(pay["anonymousPullEnabled"])
    if pay.get("publicNetworkAccess"):
        p["publicNetworkAccess"] = pay["publicNetworkAccess"]
    if pay.get("networkRuleBypassOptions"):
        p["networkRuleBypassOptions"] = pay["networkRuleBypassOptions"]
    if pay.get("networkRuleSet") is not None:
        p["networkRuleSet"] = pay["networkRuleSet"]
    if "dataEndpointEnabled" in pay and premium:
        p["dataEndpointEnabled"] = _to_bool(pay["dataEndpointEnabled"])
        p["dataEndpointHostNames"] = [f"{rec['name'].lower()}.{rec['location']}.data.azurecr.io"] if p["dataEndpointEnabled"] else []
    if pay.get("zoneRedundancy") and premium:
        p["zoneRedundancy"] = pay["zoneRedundancy"]
    for pk, pv in (pay.get("policies") or {}).items():
        if isinstance(pv, dict) and pk in p["policies"]:
            p["policies"][pk].update(pv)
            if "lastUpdatedTime" in p["policies"][pk]:
                p["policies"][pk]["lastUpdatedTime"] = _now()
    if payload.get("identity"):
        t = payload["identity"].get("type") or "None"
        if t == "None":
            rec.pop("identity", None)
        else:
            rec["identity"] = _identity(rec["id"], payload["identity"])
    rec["systemData"]["lastModifiedAt"] = _now()


def _reg_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    return out


def _put_registry(state, sub, rg, rid, name, payload, method):
    rec = state.get(rid.lower())
    prob = _name_problem(name)
    if prob:
        raise _E(400, "InvalidParameter", prob[1])
    if rec is None and method == "PATCH":
        raise _not_found("registries", name, rg)
    if rec is None:
        if _find_registry(state, name) is not None:
            raise _E(409, "RegistryNameNotAvailable", f"The registry name '{name}' is already in use.")
        rec = _new_registry(rid, name, sub, rg, payload)
        state[rid.lower()] = rec
        return rec, True
    _apply_props(rec, payload)
    return rec, False


def _list_registries(state, sub, rg):
    items = []
    for rec in _registries(state):
        if rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_reg_view(rec))
    return _ok({"value": items})


def resource_types():
    return [("registries", API_VERSION)]


# ═══════════════════════════ credentials ══════════════════════════════════════════
def _credentials(rec):
    if not rec["properties"].get("adminUserEnabled"):
        raise _E(400, "InvalidParameter", f"Admin user is disabled for registry '{rec['name']}'. "
                                           "Enable it first with `az acr update --admin-enabled true`.")
    return {"username": rec["name"],
            "passwords": [{"name": n, "value": _secret(rec["id"], i, rec["_gen"][i])} for i, n in enumerate(PASSWORD_NAMES)]}


def _regenerate(rec, payload):
    name = payload.get("name")
    if name not in PASSWORD_NAMES:
        raise _E(400, "InvalidParameter", "The 'name' property must be 'password' or 'password2'.")
    rec["_gen"][PASSWORD_NAMES.index(name)] += 1
    return _credentials(rec)


def _usages(rec):
    sku = rec["sku"]["name"].lower()
    return {"value": [
        {"name": "Size", "limit": SKU_STORAGE_GB[sku] * 1024 ** 3, "currentValue": 0, "unit": "Bytes"},
        {"name": "Webhooks", "limit": SKU_WEBHOOKS[sku], "currentValue": len(rec["_webhooks"]), "unit": "Count"},
        {"name": "Geo-replications", "limit": 500 if sku == "premium" else 0, "currentValue": len(rec["_replications"]) + 1,
         "unit": "Count"},
        {"name": "ScopeMaps", "limit": 100, "currentValue": len(rec["_scopemaps"]), "unit": "Count"},
        {"name": "Tokens", "limit": 100, "currentValue": len(rec["_tokens"]), "unit": "Count"},
    ]}


# ═══════════════════════════ child resources ══════════════════════════════════════
def _child_view(rec, kind, ctype, item, loc=None):
    out = {"id": f"{rec['id']}/{kind}/{item['name']}", "name": item["name"], "type": f"{NAMESPACE}/registries/{ctype}",
           "properties": dict(item["properties"]), "systemData": item.get("systemData")}
    if loc or item.get("location"):
        out["location"] = loc or item["location"]
    if item.get("tags") is not None:
        out["tags"] = item["tags"]
    return out


def _simple_children(rec, store_key, kind, ctype, rest, method, payload, build, patch, min_sku=None, extra=None):
    store = rec[store_key]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_child_view(rec, kind, ctype, i) for i in store.values()]})
    name = rest[0]
    key = name.lower()
    sub_op = rest[1].lower() if len(rest) > 1 else None
    if sub_op and extra:
        return extra(rec, store, name, sub_op, method, payload)
    if method == "GET":
        if key not in store:
            raise _E(404, "ResourceNotFound", f"The Resource '{NAMESPACE}/registries/{kind}/{name}' under resource group "
                                              f"'{rec['_rg']}' was not found.")
        return _ok(_child_view(rec, kind, ctype, store[key]))
    if method in ("PUT", "PATCH"):
        if min_sku and rec["sku"]["name"].lower() not in min_sku and key not in store:
            raise _E(400, "InvalidSku", f"{ctype} require the {' or '.join(s.capitalize() for s in min_sku)} registry SKU.")
        if key in store:
            patch(rec, store[key], payload)
            store[key]["systemData"]["lastModifiedAt"] = _now()
            return _ok(_child_view(rec, kind, ctype, store[key]), 200, lro=True, rid=f"{rec['id']}/{kind}/{name}", verb="put")
        if method == "PATCH":
            raise _E(404, "ResourceNotFound", f"The Resource '{NAMESPACE}/registries/{kind}/{name}' was not found.")
        store[key] = build(rec, name, payload)
        return _ok(_child_view(rec, kind, ctype, store[key]), 201, lro=True, rid=f"{rec['id']}/{kind}/{name}", verb="put")
    if method == "DELETE":
        if key not in store:
            return _ok(None, 204)
        gone = store.pop(key)
        if kind == "scopeMaps":                         # a token can't outlive its scope map
            for t in list(rec["_tokens"].values()):
                if (t["properties"].get("scopeMapId") or "").lower() == f"{rec['id']}/scopeMaps/{gone['name']}".lower():
                    raise _E(409, "Conflict", f"Scope map '{gone['name']}' is in use by token '{t['name']}'.")
        return _ok(None, 200, lro=True, rid=f"{rec['id']}/{kind}/{name}", verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _build_replication(rec, name, payload):
    loc = payload.get("location")
    if not loc:
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    if loc.lower().replace(" ", "") == rec["location"].lower().replace(" ", ""):
        raise _E(409, "Conflict", f"The registry already has a home region replica in '{loc}'.")
    pay = payload.get("properties") or {}
    return {"name": name, "location": loc, "tags": dict(payload.get("tags") or {}), "systemData": _sysdata(),
            "properties": {"provisioningState": "Succeeded",
                           "status": {"displayStatus": "Ready", "message": "The replication is ready.", "timestamp": _now()},
                           "regionEndpointEnabled": _to_bool(pay.get("regionEndpointEnabled"), True),
                           "zoneRedundancy": pay.get("zoneRedundancy") or "Disabled"}}


def _patch_replication(rec, item, payload):
    pay = payload.get("properties") or {}
    if "regionEndpointEnabled" in pay:
        item["properties"]["regionEndpointEnabled"] = _to_bool(pay["regionEndpointEnabled"])
    if isinstance(payload.get("tags"), dict):
        item["tags"] = payload["tags"]


def _build_webhook(rec, name, payload):
    if not re.fullmatch(r"[A-Za-z0-9]{5,50}", name):
        raise _E(400, "InvalidParameter", f"The webhook name '{name}' is invalid. Webhook names must be 5-50 alphanumeric characters.")
    pay = payload.get("properties") or {}
    if not pay.get("serviceUri"):
        raise _E(400, "InvalidParameter", "The 'serviceUri' property is required.")
    actions = pay.get("actions") or []
    bad = [a for a in actions if a not in WEBHOOK_ACTIONS]
    if not actions or bad:
        raise _E(400, "InvalidParameter", "The 'actions' property must be a non-empty list of: " + ", ".join(WEBHOOK_ACTIONS) + ".")
    if len(rec["_webhooks"]) >= SKU_WEBHOOKS[rec["sku"]["name"].lower()]:
        raise _E(409, "Conflict", f"The {rec['sku']['name']} SKU allows at most {SKU_WEBHOOKS[rec['sku']['name'].lower()]} webhooks.")
    return {"name": name, "location": payload.get("location") or rec["location"], "tags": dict(payload.get("tags") or {}),
            "systemData": _sysdata(), "_events": [],
            "properties": {"status": pay.get("status") or "enabled", "scope": pay.get("scope") or "", "actions": list(actions),
                           "provisioningState": "Succeeded", "serviceUri": pay["serviceUri"],
                           "customHeaders": dict(pay.get("customHeaders") or {})}}


def _patch_webhook(rec, item, payload):
    pay = payload.get("properties") or {}
    p = item["properties"]
    for k in ("status", "scope", "serviceUri"):
        if pay.get(k) is not None:
            p[k] = pay[k]
    if pay.get("actions"):
        p["actions"] = list(pay["actions"])
    if pay.get("customHeaders") is not None:
        p["customHeaders"] = pay["customHeaders"]
    if isinstance(payload.get("tags"), dict):
        item["tags"] = payload["tags"]


def _webhook_extra(rec, store, name, sub_op, method, payload):
    item = store.get(name.lower())
    if item is None:
        raise _E(404, "ResourceNotFound", f"The Resource '{NAMESPACE}/registries/webhooks/{name}' was not found.")
    if sub_op == "ping" and method == "POST":
        eid = str(uuid.uuid4())
        item["_events"].append({"id": eid, "eventRequestMessage": {"content": {"id": eid, "action": "ping"}, "method": "POST",
                                                                   "requestUri": item["properties"]["serviceUri"], "version": "1.1"},
                                "eventResponseMessage": {"statusCode": "200", "reasonPhrase": "OK", "version": "1.1"}})
        return _ok({"id": eid})
    if sub_op == "getcallbackconfig" and method == "POST":
        return _ok({"serviceUri": item["properties"]["serviceUri"], "customHeaders": item["properties"]["customHeaders"]})
    if sub_op == "listevents" and method == "POST":
        return _ok({"value": item["_events"]})
    raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/registries/webhooks/{sub_op}' is not supported.")


def _build_scopemap(rec, name, payload):
    if name.startswith("_"):
        raise _E(400, "InvalidParameter", "Scope map names starting with '_' are reserved for system scope maps.")
    pay = payload.get("properties") or {}
    actions = pay.get("actions") or []
    if not actions:
        raise _E(400, "InvalidParameter", "The 'actions' property is required.")
    return {"name": name, "systemData": _sysdata(),
            "properties": {"description": pay.get("description") or "", "type": "UserDefined", "creationDate": _now(),
                           "provisioningState": "Succeeded", "actions": list(actions)}}


def _patch_scopemap(rec, item, payload):
    pay = payload.get("properties") or {}
    if pay.get("description") is not None:
        item["properties"]["description"] = pay["description"]
    if pay.get("actions"):
        item["properties"]["actions"] = list(pay["actions"])


def _scopemap_store(rec):
    out = dict(rec["_scopemaps"])
    for n, acts in SYSTEM_SCOPE_MAPS.items():
        out.setdefault(n.lower(), {"name": n, "systemData": rec["systemData"],
                                   "properties": {"description": f"Can perform all {n.strip('_').replace('_', ' ')} actions",
                                                  "type": "SystemDefined", "creationDate": rec["properties"]["creationDate"],
                                                  "provisioningState": "Succeeded", "actions": list(acts)}})
    return out


def _build_token(rec, name, payload):
    pay = payload.get("properties") or {}
    smid = pay.get("scopeMapId")
    if not smid:
        raise _E(400, "InvalidParameter", "The 'scopeMapId' property is required.")
    sm_name = smid.rsplit("/", 1)[-1]
    if sm_name.lower() not in _scopemap_store(rec):
        raise _E(400, "InvalidParameter", f"The scope map '{sm_name}' does not exist in registry '{rec['name']}'.")
    return {"name": name, "systemData": _sysdata(),
            "properties": {"creationDate": _now(), "provisioningState": "Succeeded", "scopeMapId": smid,
                           "status": pay.get("status") or "enabled", "credentials": {"certificates": [], "passwords": []}}}


def _patch_token(rec, item, payload):
    pay = payload.get("properties") or {}
    if pay.get("status"):
        item["properties"]["status"] = pay["status"]
    if pay.get("scopeMapId"):
        item["properties"]["scopeMapId"] = pay["scopeMapId"]


def _generate_credentials(rec, payload):
    tid = payload.get("tokenId") or ""
    tok = rec["_tokens"].get(tid.rsplit("/", 1)[-1].lower())
    if tok is None:
        raise _E(400, "InvalidParameter", f"The token '{tid}' does not exist in registry '{rec['name']}'.")
    n = len(tok["properties"]["credentials"]["passwords"])
    if n >= 2:
        raise _E(409, "Conflict", "A token can have at most two passwords.")
    pname = f"password{n + 1}"
    val = _secret(rec["id"], tok["name"], n, uuid.uuid4().hex)
    pw = {"creationTime": _now(), "expiry": payload.get("expiry"), "name": pname}
    tok["properties"]["credentials"]["passwords"].append(pw)
    return {"username": tok["name"], "passwords": [dict(pw, value=val)]}


def _import_image(rec, payload):
    src = payload.get("source") or {}
    if not (src.get("sourceImage") and (src.get("registryUri") or src.get("resourceId"))):
        raise _E(400, "InvalidParameter", "The 'source.sourceImage' and a source registry (registryUri or resourceId) are required.")
    rec["_imports"].append({"source": src, "targetTags": list(payload.get("targetTags") or []), "at": _now()})


# ═══════════════════════════ dispatch ═════════════════════════════════════════════
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.ContainerRegistry`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, base)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    low = chain[0].lower()
    if low == "checknameavailability":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        name = payload.get("name") or ""
        if (payload.get("type") or "Microsoft.ContainerRegistry/registries").lower() != f"{NAMESPACE}/registries".lower():
            return _err(400, "InvalidParameter", "The 'type' must be 'Microsoft.ContainerRegistry/registries'.")
        prob = _name_problem(name)
        if prob:
            return _ok({"nameAvailable": False, "reason": "Invalid", "message": prob[1]})
        if _find_registry(state, name) is not None:
            return _ok({"nameAvailable": False, "reason": "AlreadyExists",
                        "message": f"The registry {name} is already in use."})
        return _ok({"nameAvailable": True})
    if low != "registries":
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0]}' is not supported.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_registries(state, sub, rg)
    name = chain[1]
    rid = _canon(sub, rg, ["registries"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("registries", name, rg)
        return _registry_ops(rec, rest, method, payload)
    if method == "GET":
        if rec is None:
            raise _not_found("registries", name, rg)
        return _ok(_reg_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Container registries must be created in a resource group.")
        rec, created = _put_registry(state, sub, rg, rid, name, payload, method)
        return _ok(_reg_view(rec), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rec["id"].lower(), None)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _registry_ops(rec, rest, method, payload):
    r0 = rest[0].lower()
    if r0 == "listcredentials" and method == "POST":
        return _ok(_credentials(rec))
    if r0 == "regeneratecredential" and method == "POST":
        return _ok(_regenerate(rec, payload))
    if r0 == "generatecredentials" and method == "POST":
        return _ok(_generate_credentials(rec, payload), lro=True, rid=rec["id"], verb="post")
    if r0 == "listusages" and method == "GET":
        return _ok(_usages(rec))
    if r0 == "importimage" and method == "POST":
        _import_image(rec, payload)
        return _ok(None, 200, lro=True, rid=rec["id"], verb="post")
    if r0 == "listprivatelinkresources" or r0 == "privatelinkresources":
        pl = {"id": f"{rec['id']}/privateLinkResources/registry", "name": "registry",
              "type": f"{NAMESPACE}/registries/privateLinkResources",
              "properties": {"groupId": "registry", "requiredMembers": ["registry", "registry_data_" + rec["location"]],
                             "requiredZoneNames": ["privatelink.azurecr.io"]}}
        if len(rest) > 1:
            return _ok(pl)
        return _ok({"value": [pl]})
    if r0 == "privateendpointconnections" and method == "GET" and len(rest) == 1:
        return _ok({"value": list(rec["properties"].get("privateEndpointConnections") or [])})
    sub_rest = rest[1:]
    if r0 == "replications":
        return _simple_children(rec, "_replications", "replications", "replications", sub_rest, method, payload,
                                _build_replication, _patch_replication, min_sku=("premium",))
    if r0 == "webhooks":
        return _simple_children(rec, "_webhooks", "webhooks", "webhooks", sub_rest, method, payload,
                                _build_webhook, _patch_webhook, extra=_webhook_extra)
    if r0 == "scopemaps":
        if method == "GET":                              # system scope maps are listed read-only next to user ones
            tmp = dict(rec)
            tmp["_scopemaps"] = _scopemap_store(rec)
            return _simple_children(tmp, "_scopemaps", "scopeMaps", "scopeMaps", sub_rest, method, payload,
                                    _build_scopemap, _patch_scopemap)
        return _simple_children(rec, "_scopemaps", "scopeMaps", "scopeMaps", sub_rest, method, payload,
                                _build_scopemap, _patch_scopemap)
    if r0 == "tokens":
        return _simple_children(rec, "_tokens", "tokens", "tokens", sub_rest, method, payload,
                                _build_token, _patch_token)
    raise _E(404, "ResourceTypeNotSupported",
             f"The resource type '{NAMESPACE}/registries/{rest[0]}' is not supported.")
