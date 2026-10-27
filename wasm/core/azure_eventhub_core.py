"""Azure Event Hubs core (``Microsoft.EventHub`` ARM control plane + the REST send / console read data plane).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

Control plane — ARM REST of the ``eventhub`` resource provider (azure-rest-api-specs
``specification/eventhub/resource-manager``, api-version 2024-01-01), so ``azure-mgmt-eventhub`` /
``armeventhub`` / ``com.azure.resourcemanager.eventhubs`` and ``az eventhubs namespace|eventhub|…`` work
unchanged:

    Microsoft.EventHub/namespaces   (+ authorizationRules[/listKeys|regenerateKeys], networkRuleSets,
                                       eventhubs[/consumergroups, /authorizationRules[/listKeys|regenerateKeys]],
                                       disasterRecoveryConfigs[/breakPairing|failOver|checkNameAvailability],
                                       privateLinkResources, privateEndpointConnections)
    Microsoft.EventHub/checkNameAvailability

Data plane — each event hub keeps a partitioned, ordered event log (sequence number / offset per partition,
partition-key hashing, retention window). Sending works through the Event Hubs REST API
(``POST /{hub}/messages``, ``/{hub}/partitions/{id}/messages``, ``/{hub}/publishers/{p}/messages`` incl. the batch media
type ``application/vnd.microsoft.servicebus.json``). Reading back is a Vyomi console extension (the real service only
offers AMQP / Kafka for receive): ``GET …/eventhubs/{hub}/events`` on the ARM path (see ``_events_ops``).

Everything lives inside the namespace's ARM record (underscore keys, never serialised to ARM clients), so it is
space-scoped and persisted by the same seams as the rest of ARM (offline ``azure_arm_state``; Nano ``az_arm``).

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; ``data_dispatch`` returns
``{"status","headers","body","media"}`` (``body`` is a JSON-able object or ``None``).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.EventHub"
API_VERSION = "2024-01-01"
DEFAULT_LOCATION = "eastus"
SKUS = ("basic", "standard", "premium")
RIGHTS = ("Listen", "Send", "Manage")
ROOT_RULE = "RootManageSharedAccessKey"
MAX_EVENTS_PER_PARTITION = 1000
BATCH_MEDIA = "application/vnd.microsoft.servicebus.json"
MAX_EVENT_BYTES = 1024 * 1024


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


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


# ═══════════════════════════ namespaces ══════════════════════════════════════════
def _namespaces(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/namespaces".lower()]


def _find_ns(state, name):
    n = (name or "").lower()
    for r in _namespaces(state):
        if r["name"].lower() == n:
            return r
    return None


def _ns_name_problem(name):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{4,49}", name or "") or name.endswith("-"):
        return (f"The specified namespace name '{name}' is invalid. Namespace names must be 6-50 characters, "
                "contain only letters, numbers and hyphens, start with a letter and end with a letter or number.")
    return None


def _endpoint(name, base=""):
    return f"{base.rstrip('/')}/azure-data/eventhub/{name}" if base else f"https://{name}.servicebus.windows.net:443/"


def _secret(*parts):
    return base64.b64encode(hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()).decode()


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


def _sku_for(payload):
    sku = payload.get("sku") or {}
    name = str(sku.get("name") or sku.get("tier") or "Standard")
    if name.lower() not in SKUS:
        raise _E(400, "BadRequest", f"The sku '{name}' is not valid. Valid values are: Basic, Standard, Premium.")
    name = name.capitalize()
    cap = _to_int(sku.get("capacity"), 1)
    if cap is None or cap < 1 or cap > (16 if name == "Premium" else 40):
        raise _E(400, "BadRequest", f"Invalid sku capacity {cap}.")
    return {"name": name, "tier": name, "capacity": cap}


def _new_rule(rid, name, rights):
    return {"name": name, "rights": list(rights), "_gp": 0, "_gs": 0, "_rid": rid, "systemData": _sysdata()}


def _new_ns(rid, name, sub, rg, payload, base=""):
    pay = payload.get("properties") or {}
    sku = _sku_for(payload)
    basic = sku["name"] == "Basic"
    max_tu = _to_int(pay.get("maximumThroughputUnits"), 0)
    auto = _to_bool(pay.get("isAutoInflateEnabled"))
    if auto and (basic or max_tu < 1 or max_tu > 40):
        raise _E(400, "BadRequest", "Auto-inflate requires a Standard namespace and maximumThroughputUnits between 1 and 40.")
    if pay.get("kafkaEnabled") is not None and not _to_bool(pay.get("kafkaEnabled")) and not basic:
        kafka = False
    else:
        kafka = not basic
    props = {
        "minimumTlsVersion": pay.get("minimumTlsVersion") or "1.2",
        "provisioningState": "Succeeded", "status": "Active",
        "createdAt": _now(), "updatedAt": _now(),
        "serviceBusEndpoint": _endpoint(name, base),
        "metricId": f"{sub}:{name.lower()}",
        "isAutoInflateEnabled": auto, "maximumThroughputUnits": max_tu if auto else 0,
        "kafkaEnabled": kafka, "zoneRedundant": _to_bool(pay.get("zoneRedundant"), True),
        "disableLocalAuth": _to_bool(pay.get("disableLocalAuth")),
        "publicNetworkAccess": pay.get("publicNetworkAccess") or "Enabled",
        "privateEndpointConnections": [],
    }
    if pay.get("encryption"):
        props["encryption"] = pay["encryption"]
    rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/namespaces", "location": payload.get("location") or DEFAULT_LOCATION,
           "tags": dict(payload.get("tags") or {}), "sku": sku, "properties": props, "systemData": _sysdata(),
           "_type": f"{NAMESPACE}/namespaces", "_sub": sub, "_rg": rg, "_created": _now(),
           "_rules": {ROOT_RULE.lower(): _new_rule(rid + "/authorizationRules/" + ROOT_RULE, ROOT_RULE, RIGHTS)},
           "_hubs": {}, "_dr": {},
           "_netrules": {"defaultAction": "Allow", "publicNetworkAccess": "Enabled", "trustedServiceAccessEnabled": False,
                         "virtualNetworkRules": [], "ipRules": []}}
    if payload.get("identity"):
        rec["identity"] = _identity(rid, payload["identity"])
    return rec


def _apply_ns(rec, payload):
    pay = payload.get("properties") or {}
    p = rec["properties"]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    if payload.get("sku"):
        new = _sku_for(dict(payload, sku=dict(rec["sku"], **payload["sku"])))
        if rec["sku"]["name"] == "Premium" and new["name"] != "Premium":
            raise _E(400, "BadRequest", "A Premium namespace cannot be changed to another tier.")
        if new["name"] == "Basic" and any(len(h["_cgs"]) > 1 for h in rec["_hubs"].values()):
            raise _E(400, "BadRequest", "Basic namespaces support only the $Default consumer group; remove the others first.")
        rec["sku"] = new
        p["kafkaEnabled"] = new["name"] != "Basic" and p.get("kafkaEnabled", True)
    for k in ("minimumTlsVersion", "publicNetworkAccess"):
        if pay.get(k):
            p[k] = pay[k]
    for k in ("disableLocalAuth", "zoneRedundant"):
        if k in pay:
            p[k] = _to_bool(pay[k])
    if "isAutoInflateEnabled" in pay or "maximumThroughputUnits" in pay:
        auto = _to_bool(pay.get("isAutoInflateEnabled"), p["isAutoInflateEnabled"])
        tu = _to_int(pay.get("maximumThroughputUnits"), p["maximumThroughputUnits"])
        if auto and (rec["sku"]["name"] == "Basic" or not tu or tu < 1 or tu > 40):
            raise _E(400, "BadRequest", "Auto-inflate requires a Standard namespace and maximumThroughputUnits between 1 and 40.")
        p["isAutoInflateEnabled"], p["maximumThroughputUnits"] = auto, tu if auto else 0
    if "kafkaEnabled" in pay and rec["sku"]["name"] != "Basic":
        p["kafkaEnabled"] = _to_bool(pay["kafkaEnabled"], True)
    if payload.get("identity"):
        ident = _identity(rec["id"], payload["identity"])
        if ident["type"] == "None":
            rec.pop("identity", None)
        else:
            rec["identity"] = ident
    p["updatedAt"] = rec["systemData"]["lastModifiedAt"] = _now()


def _put_ns(state, sub, rg, rid, name, payload, method, base=""):
    rec = state.get(rid.lower())
    prob = _ns_name_problem(name)
    if prob and rec is None:
        raise _E(400, "BadRequest", prob)
    if rec is None and method == "PATCH":
        raise _not_found("namespaces", name, rg)
    if rec is None:
        if _find_ns(state, name) is not None:
            raise _E(409, "Conflict", f"The specified namespace name '{name}' is already in use.")
        if not payload.get("location"):
            raise _E(400, "LocationRequired", "The location property is required for this definition.")
        rec = _new_ns(rid, name, sub, rg, payload, base)
        state[rid.lower()] = rec
        return rec, True
    _apply_ns(rec, payload)
    return rec, False


def _ns_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    return out


def _list_ns(state, sub, rg):
    items = []
    for rec in _namespaces(state):
        if rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_ns_view(rec))
    return _ok({"value": items})


# ═══════════════════════════ authorization rules ═════════════════════════════════
def _rule_view(owner_id, r):
    return {"id": f"{owner_id}/authorizationRules/{r['name']}", "name": r["name"],
            "type": f"{NAMESPACE}/{'namespaces' if '/eventhubs/' not in owner_id else 'namespaces/eventhubs'}/authorizationRules",
            "properties": {"rights": list(r["rights"])}, "systemData": r["systemData"]}


def _check_rights(rights):
    rights = list(rights or [])
    if not rights or any(x not in RIGHTS for x in rights) or len(set(rights)) != len(rights):
        raise _E(400, "BadRequest", "Authorization rule rights must be a non-empty subset of Listen, Send, Manage.")
    if "Manage" in rights and not {"Listen", "Send"} <= set(rights):
        raise _E(400, "BadRequest", "The Manage right requires Listen and Send as well.")
    return rights


def _keys_view(ns, hub, r):
    pk, sk = _secret(r["_rid"], "primary", r["_gp"]), _secret(r["_rid"], "secondary", r["_gs"])
    ep = f"sb://{ns['name']}.servicebus.windows.net/"
    tail = f";EntityPath={hub['name']}" if hub else ""
    return {"primaryConnectionString": f"Endpoint={ep};SharedAccessKeyName={r['name']};SharedAccessKey={pk}{tail}",
            "secondaryConnectionString": f"Endpoint={ep};SharedAccessKeyName={r['name']};SharedAccessKey={sk}{tail}",
            "aliasPrimaryConnectionString": None, "aliasSecondaryConnectionString": None,
            "primaryKey": pk, "secondaryKey": sk, "keyName": r["name"]}


def _rule_ops(ns, hub, rules, owner_id, rest, method, payload):
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_rule_view(owner_id, r) for r in rules.values()]})
    name = rest[0]
    key = name.lower()
    if len(rest) == 2:
        act = rest[1].lower()
        r = rules.get(key)
        if r is None:
            raise _E(404, "ResourceNotFound", f"Authorization rule '{name}' was not found.")
        if ns["properties"].get("disableLocalAuth"):
            raise _E(400, "BadRequest", "Local authentication (SAS keys) is disabled for this namespace.")
        if act == "listkeys" and method == "POST":
            return _ok(_keys_view(ns, hub, r))
        if act == "regeneratekeys" and method == "POST":
            kt = payload.get("keyType")
            if kt not in ("PrimaryKey", "SecondaryKey"):
                raise _E(400, "BadRequest", "keyType must be PrimaryKey or SecondaryKey.")
            r["_gp" if kt == "PrimaryKey" else "_gs"] += 1
            return _ok(_keys_view(ns, hub, r))
        raise _E(404, "ResourceTypeNotSupported", f"Unsupported authorization rule action '{rest[1]}'.")
    if method == "GET":
        if key not in rules:
            raise _E(404, "ResourceNotFound", f"Authorization rule '{name}' was not found.")
        return _ok(_rule_view(owner_id, rules[key]))
    if method == "PUT":
        rights = _check_rights((payload.get("properties") or {}).get("rights"))
        if key in rules:
            rules[key]["rights"] = rights
            return _ok(_rule_view(owner_id, rules[key]))
        rules[key] = _new_rule(f"{owner_id}/authorizationRules/{name}", name, rights)
        return _ok(_rule_view(owner_id, rules[key]))
    if method == "DELETE":
        if key == ROOT_RULE.lower() and hub is None:
            raise _E(400, "BadRequest", f"The {ROOT_RULE} rule cannot be deleted.")
        rules.pop(key, None)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ event hubs / consumer groups ════════════════════════
def _max_partitions(ns):
    return 100 if ns["sku"]["name"] == "Premium" else 32


def _max_retention(ns):
    return {"Basic": 1, "Standard": 7, "Premium": 90}[ns["sku"]["name"]]


def _hub_name_problem(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}", name or ""):
        return (f"The event hub name '{name}' is invalid. Names must be 1-256 characters, start with a letter or number "
                "and contain only letters, numbers, periods, hyphens and underscores.")
    return None


def _hub_view(ns, h):
    return {"id": f"{ns['id']}/eventhubs/{h['name']}", "name": h["name"], "type": f"{NAMESPACE}/namespaces/eventhubs",
            "location": ns["location"], "properties": dict(h["properties"]), "systemData": h["systemData"]}


def _retention(ns, pay, current=None):
    days = _to_int(pay.get("messageRetentionInDays"), None)
    desc = pay.get("retentionDescription") or {}
    if days is None and desc.get("retentionTimeInHours"):
        days = max(1, int(desc["retentionTimeInHours"]) // 24)
    if days is None:
        days = current if current is not None else _max_retention(ns)
    if days < 1 or days > _max_retention(ns):
        raise _E(400, "BadRequest", f"messageRetentionInDays must be between 1 and {_max_retention(ns)} for the "
                                    f"{ns['sku']['name']} tier.")
    return days


def _put_hub(ns, name, payload):
    prob = _hub_name_problem(name)
    if prob:
        raise _E(400, "BadRequest", prob)
    pay = payload.get("properties") or {}
    hubs = ns["_hubs"]
    h = hubs.get(name.lower())
    count = _to_int(pay.get("partitionCount"), None)
    if count is not None and (count < 1 or count > _max_partitions(ns)):
        raise _E(400, "BadRequest", f"partitionCount must be between 1 and {_max_partitions(ns)} for the {ns['sku']['name']} tier.")
    if ns["sku"]["name"] == "Basic" and count is not None and count > 32:
        raise _E(400, "BadRequest", "Basic tier supports at most 32 partitions.")
    status = pay.get("status")
    if status is not None and status not in ("Active", "Disabled", "SendDisabled"):
        raise _E(400, "BadRequest", f"Invalid event hub status '{status}'.")
    cap = pay.get("captureDescription")
    if cap and ns["sku"]["name"] == "Basic":
        raise _E(400, "BadRequest", "Capture is not available in the Basic tier.")
    if h is None:
        count = count or 4
        days = _retention(ns, pay)
        if _to_int(pay.get("messageRetentionInDays"), None) is None and not pay.get("retentionDescription"):
            days = 1 if ns["sku"]["name"] == "Basic" else 7 if ns["sku"]["name"] == "Standard" else 7
        props = {"partitionIds": [str(i) for i in range(count)], "createdAt": _now(), "updatedAt": _now(),
                 "messageRetentionInDays": days, "partitionCount": count, "status": status or "Active",
                 "retentionDescription": {"cleanupPolicy": "Delete", "retentionTimeInHours": days * 24}}
        if cap:
            props["captureDescription"] = _capture(cap)
        h = {"name": name, "properties": props, "systemData": _sysdata(), "_cgs": {}, "_rules": {}, "_events": {},
             "_next": 0}
        h["_cgs"]["$default"] = _new_cg("$Default")
        hubs[name.lower()] = h
        return h, True
    p = h["properties"]
    if count is not None and count != p["partitionCount"]:
        if ns["sku"]["name"] != "Premium" or count < p["partitionCount"]:
            raise _E(400, "BadRequest", "The partition count of an existing event hub can only be increased on the "
                                        "Premium and Dedicated tiers.")
        for i in range(p["partitionCount"], count):
            p["partitionIds"].append(str(i))
        p["partitionCount"] = count
    if pay.get("messageRetentionInDays") is not None or pay.get("retentionDescription"):
        p["messageRetentionInDays"] = _retention(ns, pay, p["messageRetentionInDays"])
        p["retentionDescription"]["retentionTimeInHours"] = p["messageRetentionInDays"] * 24
    if status:
        p["status"] = status
    if "captureDescription" in pay:
        p["captureDescription"] = _capture(cap) if cap else None
        if not cap:
            p.pop("captureDescription")
    p["updatedAt"] = _now()
    return h, False


def _capture(cap):
    dest = cap.get("destination") or {}
    return {"enabled": _to_bool(cap.get("enabled"), True), "encoding": cap.get("encoding") or "Avro",
            "intervalInSeconds": _to_int(cap.get("intervalInSeconds"), 300),
            "sizeLimitInBytes": _to_int(cap.get("sizeLimitInBytes"), 314572800),
            "skipEmptyArchives": _to_bool(cap.get("skipEmptyArchives")),
            "destination": {"name": dest.get("name") or "EventHubArchive.AzureBlockBlob",
                            "properties": dest.get("properties") or {}}}


def _new_cg(name, meta=None):
    return {"name": name, "userMetadata": meta, "createdAt": _now(), "updatedAt": _now(), "systemData": _sysdata()}


def _cg_view(ns, h, cg):
    return {"id": f"{ns['id']}/eventhubs/{h['name']}/consumergroups/{cg['name']}", "name": cg["name"],
            "type": f"{NAMESPACE}/namespaces/eventhubs/consumergroups", "location": ns["location"],
            "properties": {"createdAt": cg["createdAt"], "updatedAt": cg["updatedAt"], "userMetadata": cg["userMetadata"]},
            "systemData": cg["systemData"]}


def _cg_ops(ns, h, rest, method, payload):
    cgs = h["_cgs"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_cg_view(ns, h, c) for c in cgs.values()]})
    name = rest[0]
    key = name.lower()
    if method == "GET":
        if key not in cgs:
            raise _E(404, "ResourceNotFound", f"Consumer group '{name}' was not found in event hub '{h['name']}'.")
        return _ok(_cg_view(ns, h, cgs[key]))
    if method == "PUT":
        if not re.fullmatch(r"[A-Za-z0-9$][A-Za-z0-9._-]{0,49}", name):
            raise _E(400, "BadRequest", f"The consumer group name '{name}' is invalid.")
        meta = (payload.get("properties") or {}).get("userMetadata")
        if key in cgs:
            cgs[key]["userMetadata"], cgs[key]["updatedAt"] = meta, _now()
            return _ok(_cg_view(ns, h, cgs[key]))
        if ns["sku"]["name"] == "Basic":
            raise _E(400, "BadRequest", "Basic namespaces support only the $Default consumer group.")
        if len(cgs) >= (100 if ns["sku"]["name"] == "Premium" else 20):
            raise _E(409, "QuotaExceeded", "The maximum number of consumer groups for this event hub has been reached.")
        cgs[key] = _new_cg(name, meta)
        return _ok(_cg_view(ns, h, cgs[key]))
    if method == "DELETE":
        if key == "$default":
            raise _E(400, "BadRequest", "The $Default consumer group cannot be deleted.")
        cgs.pop(key, None)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _hub_ops(ns, rest, method, payload, query):
    hubs = ns["_hubs"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        items = [_hub_view(ns, h) for h in hubs.values()]
        skip, top = _to_int(query.get("$skip"), 0) or 0, _to_int(query.get("$top"), None)
        items = items[skip:] if top is None else items[skip:skip + top]
        return _ok({"value": items})
    name = rest[0]
    key = name.lower()
    sub = rest[1:]
    if sub:
        h = hubs.get(key)
        if h is None:
            raise _E(404, "ResourceNotFound", f"The event hub '{name}' was not found in namespace '{ns['name']}'.")
        t = sub[0].lower()
        if t == "consumergroups":
            return _cg_ops(ns, h, sub[1:], method, payload)
        if t == "authorizationrules":
            return _rule_ops(ns, h, h["_rules"], f"{ns['id']}/eventhubs/{h['name']}", sub[1:], method, payload)
        if t == "events":
            return _events_ops(ns, h, sub[1:], method, payload, query)
        raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/namespaces/eventhubs/{sub[0]}' is not supported.")
    if method == "GET":
        if key not in hubs:
            raise _E(404, "ResourceNotFound", f"The event hub '{name}' was not found in namespace '{ns['name']}'.")
        return _ok(_hub_view(ns, hubs[key]))
    if method == "PUT":
        h, created = _put_hub(ns, name, payload)
        return _ok(_hub_view(ns, h), 201 if created else 200)
    if method == "DELETE":
        hubs.pop(key, None)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ event log (data plane core) ═════════════════════════
def _partition_for(h, pid=None, key=None):
    n = h["properties"]["partitionCount"]
    if pid is not None:
        p = str(pid)
        if p not in h["properties"]["partitionIds"]:
            raise _E(400, "BadRequest", f"Partition '{p}' does not exist in event hub '{h['name']}'.")
        return p
    if key not in (None, ""):
        return str(int.from_bytes(hashlib.md5(str(key).encode()).digest()[:4], "big") % n)
    p = h["_next"] % n
    h["_next"] = (h["_next"] + 1) % n
    return str(p)


def _plog(h, pid):
    return h["_events"].setdefault(str(pid), {"items": [], "seq": -1, "offset": 0})


def send_events(ns, h, events, partition_id=None, partition_key=None):
    """Append events to the hub's log. ``events`` = [{"body": str|json, "properties": {…}, "partitionKey": …}].
    Returns the list of stored records."""
    if h["properties"]["status"] in ("Disabled", "SendDisabled"):
        raise _E(403, "Forbidden", f"The event hub '{h['name']}' is {h['properties']['status']}; sending is not allowed.")
    out = []
    for ev in events:
        body = ev.get("body")
        raw = body if isinstance(body, str) else json.dumps(body, separators=(",", ":"))
        if len(raw.encode()) > MAX_EVENT_BYTES:
            raise _E(413, "MessageSizeExceeded", "The event exceeds the maximum size of 1 MB.")
        pid = _partition_for(h, partition_id, ev.get("partitionKey") or partition_key)
        log = _plog(h, pid)
        log["seq"] += 1
        log["offset"] += len(raw.encode()) + 64
        rec = {"sequenceNumber": log["seq"], "offset": str(log["offset"]), "partitionId": pid, "enqueuedTime": _now(),
               "partitionKey": ev.get("partitionKey") or partition_key, "body": raw, "properties": ev.get("properties") or {}}
        log["items"].append(rec)
        if len(log["items"]) > MAX_EVENTS_PER_PARTITION:
            del log["items"][: len(log["items"]) - MAX_EVENTS_PER_PARTITION]
        out.append(rec)
    return out


def _events_ops(ns, h, rest, method, payload, query):
    """Vyomi console extension on the ARM path: GET …/eventhubs/{hub}/events[?partitionId&fromSequence&maxCount],
    POST …/events {events:[{body,partitionKey,properties}], partitionId?}, GET …/events/partitions."""
    if rest and rest[0].lower() == "partitions" and method == "GET":
        return _ok({"value": [_partition_props(h, p) for p in h["properties"]["partitionIds"]]})
    if method == "POST":
        evs = payload.get("events")
        if evs is None and "body" in payload:
            evs = [payload]
        if not isinstance(evs, list) or not evs:
            raise _E(400, "BadRequest", "Provide an 'events' array with at least one event.")
        evs = [e if isinstance(e, dict) else {"body": e} for e in evs]
        stored = send_events(ns, h, evs, payload.get("partitionId"), payload.get("partitionKey"))
        return _ok({"sent": len(stored), "value": stored}, 201)
    if method == "GET":
        pids = [str(query["partitionId"])] if query.get("partitionId") not in (None, "") else h["properties"]["partitionIds"]
        for p in pids:
            if p not in h["properties"]["partitionIds"]:
                raise _E(400, "BadRequest", f"Partition '{p}' does not exist in event hub '{h['name']}'.")
        frm = _to_int(query.get("fromSequence"), 0) or 0
        limit = min(_to_int(query.get("maxCount"), 100) or 100, 500)
        items = []
        for p in pids:
            items += [e for e in _plog(h, p)["items"] if e["sequenceNumber"] >= frm]
        items.sort(key=lambda e: (e["enqueuedTime"], e["partitionId"], e["sequenceNumber"]))
        return _ok({"value": items[:limit], "count": len(items)})
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _partition_props(h, pid):
    log = _plog(h, pid)
    first = log["items"][0] if log["items"] else None
    last = log["items"][-1] if log["items"] else None
    return {"partitionId": str(pid), "eventHubName": h["name"],
            "beginningSequenceNumber": first["sequenceNumber"] if first else log["seq"] + 1,
            "lastEnqueuedSequenceNumber": log["seq"],
            "lastEnqueuedOffset": last["offset"] if last else "-1",
            "lastEnqueuedTimeUtc": last["enqueuedTime"] if last else None,
            "isEmpty": not log["items"]}


def hub_event_count(h):
    return sum(len(v["items"]) for v in h["_events"].values())


# ═══════════════════════════ namespace-level sub resources ═══════════════════════
def _netrules_view(ns):
    n = ns["_netrules"]
    return {"id": f"{ns['id']}/networkRuleSets/default", "name": "default", "type": f"{NAMESPACE}/namespaces/networkRuleSets",
            "properties": {"defaultAction": n["defaultAction"], "publicNetworkAccess": ns["properties"]["publicNetworkAccess"],
                           "trustedServiceAccessEnabled": n["trustedServiceAccessEnabled"],
                           "virtualNetworkRules": n["virtualNetworkRules"], "ipRules": n["ipRules"]}}


def _dr_view(ns, d):
    return {"id": f"{ns['id']}/disasterRecoveryConfigs/{d['name']}", "name": d["name"],
            "type": f"{NAMESPACE}/namespaces/disasterrecoveryconfigs",
            "properties": {"provisioningState": d["state"], "partnerNamespace": d["partner"], "alternateName": d["alternate"],
                           "role": d["role"], "pendingReplicationOperationsCount": 0},
            "systemData": d["systemData"]}


def _dr_ops(state, ns, rest, method, payload):
    drs = ns["_dr"]
    if not rest:
        return _ok({"value": [_dr_view(ns, d) for d in drs.values()]})
    if rest[0].lower() == "checknameavailability" and method == "POST":
        name = payload.get("name") or ""
        taken = name.lower() in drs
        return _ok({"nameAvailable": not taken, "reason": "NameInUse" if taken else None,
                    "message": "The alias is already in use." if taken else None})
    name = rest[0]
    key = name.lower()
    if len(rest) == 2 and method == "POST":
        d = drs.get(key)
        if d is None:
            raise _E(404, "ResourceNotFound", f"Disaster recovery config '{name}' was not found.")
        act = rest[1].lower()
        if act == "breakpairing":
            d["state"], d["role"], d["partner"] = "Succeeded", "PrimaryNotReplicating", ""
            return _ok(None, 200)
        if act == "failover":
            d["role"] = "Secondary" if d["role"] == "Primary" else "Primary"
            return _ok(None, 200)
        raise _E(404, "ResourceTypeNotSupported", f"Unsupported action '{rest[1]}'.")
    if method == "GET":
        if key not in drs:
            raise _E(404, "ResourceNotFound", f"Disaster recovery config '{name}' was not found.")
        return _ok(_dr_view(ns, drs[key]))
    if method == "PUT":
        if ns["sku"]["name"] == "Basic":
            raise _E(400, "BadRequest", "Geo-disaster recovery is not available in the Basic tier.")
        partner = (payload.get("properties") or {}).get("partnerNamespace") or ""
        pname = partner.rstrip("/").rsplit("/", 1)[-1]
        if not pname or (_find_ns(state, pname) is None):
            raise _E(400, "BadRequest", "partnerNamespace must be the ARM id of an existing namespace.")
        if pname.lower() == ns["name"].lower():
            raise _E(400, "BadRequest", "A namespace cannot be paired with itself.")
        drs[key] = {"name": name, "state": "Succeeded", "partner": partner,
                    "alternate": (payload.get("properties") or {}).get("alternateName") or "", "role": "Primary",
                    "systemData": _sysdata()}
        return _ok(_dr_view(ns, drs[key]))
    if method == "DELETE":
        drs.pop(key, None)
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _ns_ops(state, ns, rest, method, payload, query):
    r0 = rest[0].lower()
    if r0 == "eventhubs":
        return _hub_ops(ns, rest[1:], method, payload, query)
    if r0 == "authorizationrules":
        return _rule_ops(ns, None, ns["_rules"], ns["id"], rest[1:], method, payload)
    if r0 == "disasterrecoveryconfigs":
        return _dr_ops(state, ns, rest[1:], method, payload)
    if r0 == "networkrulesets":
        if len(rest) == 1:
            return _ok({"value": [_netrules_view(ns)]})
        if rest[1].lower() != "default":
            raise _E(404, "ResourceNotFound", f"Network rule set '{rest[1]}' was not found.")
        if method == "PUT":
            pay = payload.get("properties") or {}
            n = ns["_netrules"]
            if pay.get("defaultAction") in ("Allow", "Deny"):
                n["defaultAction"] = pay["defaultAction"]
            if pay.get("publicNetworkAccess"):
                ns["properties"]["publicNetworkAccess"] = pay["publicNetworkAccess"]
            for k in ("virtualNetworkRules", "ipRules"):
                if isinstance(pay.get(k), list):
                    n[k] = pay[k]
            if "trustedServiceAccessEnabled" in pay:
                n["trustedServiceAccessEnabled"] = _to_bool(pay["trustedServiceAccessEnabled"])
        return _ok(_netrules_view(ns))
    if r0 == "privatelinkresources" and method == "GET":
        pl = {"id": f"{ns['id']}/privateLinkResources/namespace", "name": "namespace",
              "type": f"{NAMESPACE}/namespaces/privateLinkResources",
              "properties": {"groupId": "namespace", "requiredMembers": ["namespace"],
                             "requiredZoneNames": ["privatelink.servicebus.windows.net"]}}
        return _ok({"value": [pl]})
    if r0 == "privateendpointconnections" and method == "GET" and len(rest) == 1:
        return _ok({"value": list(ns["properties"].get("privateEndpointConnections") or [])})
    raise _E(404, "ResourceTypeNotSupported",
             f"The resource type '{NAMESPACE}/namespaces/{rest[0]}' is not supported.")


# ═══════════════════════════ ARM dispatch ════════════════════════════════════════
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.EventHub`` ARM request (``chain`` = tokens after the namespace)."""
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
        prob = _ns_name_problem(name)
        if prob:
            return _ok({"nameAvailable": False, "reason": "InvalidName", "message": prob})
        if _find_ns(state, name) is not None:
            return _ok({"nameAvailable": False, "reason": "NameInUse",
                        "message": f"The specified name '{name}' is already in use."})
        return _ok({"nameAvailable": True, "reason": "None", "message": None})
    if low != "namespaces":
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0]}' is not supported.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_ns(state, sub, rg)
    name = chain[1]
    rid = _canon(sub, rg, ["namespaces"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("namespaces", name, rg)
        return _ns_ops(state, rec, rest, method, payload, query)
    if method == "GET":
        if rec is None:
            raise _not_found("namespaces", name, rg)
        return _ok(_ns_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Event Hubs namespaces must be created in a resource group.")
        rec, created = _put_ns(state, sub, rg, rid, name, payload, method, base)
        return _ok(_ns_view(rec), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rec["id"].lower(), None)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("namespaces", API_VERSION)]


def event_count(ns):
    return sum(hub_event_count(h) for h in ns.get("_hubs", {}).values())


# ═══════════════════════════ data plane (REST send) ══════════════════════════════
def data_dispatch(state, ns_name, method, path, query=None, headers=None, body=None, base=""):
    """``{ns}.servicebus.windows.net`` REST: POST /{hub}/messages · /{hub}/partitions/{id}/messages ·
    /{hub}/publishers/{publisher}/messages (single event or ``application/vnd.microsoft.servicebus.json`` batch);
    GET /{hub}/partitions/{id} (partition properties)."""
    query = query or {}
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}
    try:
        ns = _find_ns(state, ns_name)
        if ns is None:
            raise _E(404, "NamespaceNotFound", f"The Event Hubs namespace '{ns_name}' was not found.")
        parts = [p for p in (path or "").split("/") if p]
        if not parts:
            raise _E(404, "NotFound", "Specify an event hub.")
        h = ns["_hubs"].get(parts[0].lower())
        if h is None:
            raise _E(404, "EntityNotFound", f"The messaging entity '{ns_name}:eventhub:{parts[0]}' could not be found.")
        rest = [p.lower() for p in parts[1:]]
        if method == "GET" and len(parts) == 3 and rest[0] == "partitions":
            if parts[2] not in h["properties"]["partitionIds"]:
                raise _E(400, "BadRequest", f"Partition '{parts[2]}' does not exist.")
            return {"status": 200, "headers": {}, "body": _partition_props(h, parts[2]), "media": "application/json"}
        if method == "GET" and len(parts) == 1:
            return {"status": 200, "headers": {}, "media": "application/json",
                    "body": {"name": h["name"], "partitionIds": h["properties"]["partitionIds"],
                             "createdAt": h["properties"]["createdAt"]}}
        pid = pkey = None
        if len(parts) == 2 and rest[0] == "messages":
            pass
        elif len(parts) == 4 and rest[0] == "partitions" and rest[2] == "messages":
            pid = parts[2]
        elif len(parts) == 4 and rest[0] == "publishers" and rest[2] == "messages":
            pkey = parts[2]
        else:
            raise _E(404, "NotFound", f"Unsupported path '/{'/'.join(parts)}'.")
        if method != "POST":
            raise _E(405, "MethodNotAllowed", "Use POST to send events.")
        raw = body if isinstance(body, (bytes, bytearray)) else (body or "").encode() if isinstance(body, str) else b""
        ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype == BATCH_MEDIA:
            try:
                arr = json.loads(raw.decode() or "[]")
            except ValueError:
                raise _E(400, "BadRequest", "The batch body is not valid JSON.")
            if not isinstance(arr, list) or not arr:
                raise _E(400, "BadRequest", "The batch body must be a non-empty JSON array.")
            evs = []
            for it in arr:
                bp = it.get("BrokerProperties") or {}
                evs.append({"body": it.get("Body"), "properties": it.get("UserProperties") or {},
                            "partitionKey": bp.get("PartitionKey")})
        else:
            bp = {}
            if headers.get("brokerproperties"):
                try:
                    bp = json.loads(headers["brokerproperties"])
                except ValueError:
                    raise _E(400, "BadRequest", "The BrokerProperties header is not valid JSON.")
            props = {k: v for k, v in headers.items() if k.startswith("x-ms-prop-")}
            evs = [{"body": raw.decode("utf-8", "replace"), "partitionKey": bp.get("PartitionKey"),
                    "properties": {**props, **({"content-type": ctype} if ctype else {})}}]
        send_events(ns, h, evs, pid, pkey)
        return {"status": 201, "headers": {}, "body": None, "media": "application/json"}
    except _E as e:
        return {"status": e.status, "headers": {}, "media": "application/json",
                "body": {"error": {"code": e.code, "message": e.message}}}
