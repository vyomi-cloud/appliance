"""Azure Cache for Redis core (``Microsoft.Cache/redis`` — caches, access keys, firewall rules,
patch schedules, linked servers, import / export, reboot).

Substrate-free (no fastapi / sockets / subprocess) so the SAME file runs offline and in Nano.

ARM REST of the ``redis`` resource provider (azure-rest-api-specs ``specification/redis/resource-manager``,
api-version 2024-03-01), so ``azure-mgmt-redis`` / ``armredis`` / ``com.azure.resourcemanager.redis`` and
``az redis …`` work unchanged:

    Microsoft.Cache/redis                                  (Create / Update / Delete / Get / ListBy*)
    Microsoft.Cache/redis/{name}/listKeys | regenerateKey | forceReboot | import | export   (POST)
    Microsoft.Cache/redis/{name}/firewallRules/{rule}      (CreateOrUpdate / Get / Delete / List)
    Microsoft.Cache/redis/{name}/patchSchedules/default    (CreateOrUpdate / Get / Delete / List)
    Microsoft.Cache/redis/{name}/linkedServers/{linked}    (Create / Get / Delete / List)
    Microsoft.Cache/CheckNameAvailability                  (POST, subscription scope)

Child resources live INSIDE the cache's ARM record (underscore keys, never serialised to ARM
clients), so they are space-scoped and persisted by the same seams as the rest of ARM.

Data plane: offline, the appliance points ``configure_data_plane`` at the shared Valkey container
(BSD-3, Redis-protocol compatible); ``connection_info`` tells the console how to reach it. Nano and
the Free tier run the control plane only.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}`` (``body`` is a JSON-able
object or ``None``).
"""
from __future__ import annotations

import base64
import ipaddress
import re
import secrets
import uuid

NAMESPACE = "Microsoft.Cache"
TYPE = "Redis"
RESOURCE_TYPE = f"{NAMESPACE}/{TYPE}"
API_VERSION = "2024-03-01"
DEFAULT_LOCATION = "eastus"
PORT = 6379
SSL_PORT = 6380
TIERS = ("Basic", "Standard", "Premium")
REDIS_VERSIONS = ("4", "6")
DEFAULT_VERSION = "6.0"
TLS_VERSIONS = ("1.0", "1.1", "1.2")
MAX_PREMIUM_SHARDS = 10
# cache size (MB) and maxclients by SKU family + capacity
SIZES_MB = {"C": [250, 1024, 2560, 6144, 13312, 26624, 53248], "P": [6144, 13312, 26624, 53248, 122880]}
MAX_CLIENTS = {"C": [256, 1000, 2000, 5000, 10000, 15000, 20000], "P": [7500, 15000, 30000, 40000, 40000]}
EVICTION = ("volatile-lru", "allkeys-lru", "volatile-lfu", "allkeys-lfu", "volatile-random", "allkeys-random",
            "volatile-ttl", "noeviction")
# settable redisConfiguration keys → allowed values (None = any); the rest are computed / read-only
CONFIG_KEYS = {
    "maxmemory-policy": EVICTION, "maxmemory-reserved": None, "maxfragmentationmemory-reserved": None,
    "maxmemory-delta": None, "notify-keyspace-events": None, "preferred-data-archive-auth-method": None,
    "preferred-data-persistence-auth-method": None, "authnotrequired": ("true", "false"),
    "aof-backup-enabled": ("true", "false"), "aof-storage-connection-string-0": None,
    "aof-storage-connection-string-1": None, "rdb-backup-enabled": ("true", "false"),
    "rdb-backup-frequency": ("15", "30", "60", "360", "720", "1440"), "rdb-backup-max-snapshot-count": None,
    "rdb-storage-connection-string": None, "zonal-configuration": None, "aad-enabled": ("true", "false"),
}
PREMIUM_CONFIG = ("aof-backup-enabled", "aof-storage-connection-string-0", "aof-storage-connection-string-1",
                  "rdb-backup-enabled", "rdb-backup-frequency", "rdb-backup-max-snapshot-count", "rdb-storage-connection-string")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Everyday", "Weekend")
REBOOT_TYPES = ("PrimaryNode", "SecondaryNode", "AllNodes")
EXPORT_FORMATS = ("RDB", "AOF")

# Offline data plane (the shared Valkey container); None → control plane only.
DATA_PLANE: dict = {"host": None, "port": PORT}


def configure_data_plane(host, port=PORT):
    DATA_PLANE["host"], DATA_PLANE["port"] = (host or None), int(port or PORT)


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_bool(v, default=None):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return default


def _rid(sub, rg, name):
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{NAMESPACE}/{TYPE}/{name}"


def _caches(state):
    return [r for r in state.values() if str(r.get("_type", "")).lower() == RESOURCE_TYPE.lower()]


def _not_found(name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{RESOURCE_TYPE}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _view(rec, keys=False):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    out["properties"] = dict(rec["properties"])
    if keys:
        out["properties"]["accessKeys"] = _keys_view(rec)
    return out


def _keys_view(rec):
    k = rec["_keys"]
    return {"primaryKey": k["primary"], "secondaryKey": k["secondary"]}


def _new_key():
    return base64.b64encode(secrets.token_bytes(32)).decode()


# ═══════════════════════════ validation ══════════════════════════════════════════
def name_problem(name):
    n = name or ""
    if not 1 <= len(n) <= 63:
        return "The name must be between 1 and 63 characters long."
    if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?", n):
        return ("The name can contain only letters, numbers and hyphens, and must start and end with a letter or number.")
    if "--" in n:
        return "The name cannot contain consecutive hyphens."
    return None


def _norm_sku(raw, current=None):
    if not isinstance(raw, dict):
        raise _E(400, "BadRequest", "Required property 'sku' not found in JSON.")
    name = str(raw.get("name") or "").strip().capitalize()
    if name not in TIERS:
        raise _E(400, "BadRequest", f"The sku name '{raw.get('name') or ''}' is not valid. Valid values are Basic, Standard and Premium.")
    fam = str(raw.get("family") or ("P" if name == "Premium" else "C")).upper()
    if fam not in ("C", "P") or (fam == "P") != (name == "Premium"):
        raise _E(400, "BadRequest", f"The sku family '{fam}' does not match the {name} tier (Basic and Standard use C, Premium uses P).")
    cap = _to_int(raw.get("capacity"))
    lo, hi = (1, 5) if fam == "P" else (0, 6)
    if cap is None or not lo <= cap <= hi:
        raise _E(400, "BadRequest", f"The capacity {raw.get('capacity')!r} is not valid for the {name} tier: it must be between {lo} and {hi}.")
    sku = {"name": name, "family": fam, "capacity": cap}
    if current:
        if TIERS.index(name) < TIERS.index(current["name"]):
            raise _E(400, "BadRequest", f"Scaling down from the {current['name']} tier to the {name} tier is not supported.")
        if name == current["name"] and SIZES_MB[fam][cap - (1 if fam == "P" else 0)] < SIZES_MB[fam][current["capacity"] - (1 if fam == "P" else 0)]:
            raise _E(400, "BadRequest", "Scaling down to a smaller cache size is not supported; the size can only be increased.")
    return sku


def size_mb(sku):
    return SIZES_MB[sku["family"]][sku["capacity"] - (1 if sku["family"] == "P" else 0)]


def size_label(sku):
    mb = size_mb(sku)
    return f"{mb} MB" if mb < 1024 else f"{mb / 1024:g} GB"


def _computed_config(sku, cfg):
    mb = size_mb(sku)
    idx = sku["capacity"] - (1 if sku["family"] == "P" else 0)
    reserved = str(max(2, mb // 10))
    out = {"maxclients": str(MAX_CLIENTS[sku["family"]][idx]), "maxmemory-reserved": reserved,
           "maxfragmentationmemory-reserved": reserved, "maxmemory-delta": reserved, "maxmemory-policy": "volatile-lru"}
    out.update(cfg)
    return out


def _norm_config(raw, sku):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _E(400, "BadRequest", "redisConfiguration must be an object of string settings.")
    out = {}
    for k, v in raw.items():
        if k == "maxclients":
            continue                                           # read-only
        if k not in CONFIG_KEYS:
            raise _E(400, "BadRequest", f"The redis configuration '{k}' is not supported.")
        if k in PREMIUM_CONFIG and sku["name"] != "Premium":
            raise _E(400, "BadRequest", f"The redis configuration '{k}' is only supported on the Premium tier.")
        sv = str(v).lower() if isinstance(v, bool) else str(v)
        allowed = CONFIG_KEYS[k]
        if allowed and sv not in allowed:
            raise _E(400, "BadRequest", f"'{sv}' is not a valid value for '{k}'. Valid values: {', '.join(allowed)}.")
        out[k] = sv
    return out


def _enum(v, allowed, what):
    if v not in allowed:
        raise _E(400, "BadRequest", f"'{v}' is not a valid {what}. Valid values: {', '.join(allowed)}.")
    return v


def _instances(rec):
    p = rec["properties"]
    shards = _to_int(p.get("shardCount")) or 1
    if rec["properties"]["sku"]["name"] != "Premium":
        return []
    return [{"sslPort": 15000 + i, "nonSslPort": 13000 + i, "shardId": i, "isMaster": True, "isPrimary": True} for i in range(shards)]


def _hostname(name):
    return f"{name.lower()}.redis.cache.windows.net"


# ═══════════════════════════ caches ══════════════════════════════════════════════
def _create(state, sub, rg, rid, name, payload):
    prob = name_problem(name)
    if prob:
        raise _E(400, "BadRequest", prob)
    if not payload.get("location"):
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    pay = payload.get("properties") or {}
    sku = _norm_sku(pay.get("sku"))
    for c in _caches(state):
        if c["name"].lower() == name.lower():
            raise _E(409, "Conflict", f"The name '{name}' is already in use. Cache names are globally unique.")
    version = str(pay.get("redisVersion") or DEFAULT_VERSION)
    if version.split(".")[0] not in REDIS_VERSIONS and version.lower() != "latest":
        raise _E(400, "BadRequest", f"The redis version '{version}' is not supported. Supported versions: 4, 6.")
    if version.lower() == "latest":
        version = DEFAULT_VERSION
    tls = str(pay.get("minimumTlsVersion") or "1.2")
    _enum(tls, TLS_VERSIONS, "minimumTlsVersion")
    pna = str(pay.get("publicNetworkAccess") or "Enabled")
    _enum(pna, ("Enabled", "Disabled"), "publicNetworkAccess")
    props = {
        "provisioningState": "Succeeded", "redisVersion": version, "sku": sku,
        "enableNonSslPort": _to_bool(pay.get("enableNonSslPort"), False),
        "publicNetworkAccess": pna, "minimumTlsVersion": tls,
        "redisConfiguration": {}, "hostName": _hostname(name), "port": PORT, "sslPort": SSL_PORT,
        "linkedServers": [], "instances": [], "privateEndpointConnections": [],
        "updateChannel": str(pay.get("updateChannel") or "Stable"),
        "disableAccessKeyAuthentication": _to_bool(pay.get("disableAccessKeyAuthentication"), False),
    }
    props["redisConfiguration"] = _computed_config(sku, _norm_config(pay.get("redisConfiguration"), sku))
    _premium_props(props, pay, sku)
    rec = {"id": rid, "name": name, "type": RESOURCE_TYPE, "location": payload["location"],
           "tags": dict(payload.get("tags") or {}), "properties": props,
           "_type": RESOURCE_TYPE, "_sub": sub, "_rg": rg,
           "_keys": {"primary": _new_key(), "secondary": _new_key()}, "_fw": {}, "_patch": {}, "_linked": {}}
    if payload.get("zones"):
        rec["zones"] = [str(z) for z in payload["zones"]]
    if isinstance(payload.get("identity"), dict) and payload["identity"].get("type"):
        rec["identity"] = {"type": payload["identity"]["type"], "principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, rid)),
                           "tenantId": "00000000-0000-0000-0000-000000000000"}
    props["instances"] = _instances(rec)
    state[rid.lower()] = rec
    return rec


def _premium_props(props, pay, sku):
    """Premium-only knobs (shards, replicas, vnet)."""
    for f in ("shardCount", "replicasPerMaster", "replicasPerPrimary", "subnetId", "staticIP"):
        if pay.get(f) in (None, ""):
            continue
        if sku["name"] != "Premium":
            raise _E(400, "BadRequest", f"'{f}' is only supported on the Premium tier.")
        if f in ("shardCount", "replicasPerMaster", "replicasPerPrimary"):
            n = _to_int(pay[f])
            hi = MAX_PREMIUM_SHARDS if f == "shardCount" else 3
            if n is None or not (0 if f == "shardCount" else 1) <= n <= hi:
                raise _E(400, "BadRequest", f"'{f}' must be between {0 if f == 'shardCount' else 1} and {hi}.")
            props[f] = n
        elif f == "staticIP":
            try:
                props[f] = str(ipaddress.IPv4Address(str(pay[f]).strip()))
            except ValueError:
                raise _E(400, "BadRequest", f"'{pay[f]}' is not a valid IPv4 address.") from None
        else:
            props[f] = str(pay[f])
    if "replicasPerMaster" in props and "replicasPerPrimary" not in props:
        props["replicasPerPrimary"] = props["replicasPerMaster"]
    if "replicasPerPrimary" in props and "replicasPerMaster" not in props:
        props["replicasPerMaster"] = props["replicasPerPrimary"]


def _update(rec, payload, method):
    pay = payload.get("properties") or {}
    props = rec["properties"]
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = dict(payload["tags"])
    sku = props["sku"]
    if pay.get("sku") is not None:
        sku = _norm_sku(pay["sku"], current=props["sku"])
        props["sku"] = sku
    if "enableNonSslPort" in pay:
        props["enableNonSslPort"] = _to_bool(pay["enableNonSslPort"], props["enableNonSslPort"])
    if pay.get("minimumTlsVersion") is not None:
        props["minimumTlsVersion"] = _enum(str(pay["minimumTlsVersion"]), TLS_VERSIONS, "minimumTlsVersion")
    if pay.get("publicNetworkAccess") is not None:
        props["publicNetworkAccess"] = _enum(str(pay["publicNetworkAccess"]), ("Enabled", "Disabled"), "publicNetworkAccess")
    if pay.get("updateChannel") is not None:
        props["updateChannel"] = _enum(str(pay["updateChannel"]), ("Stable", "Preview"), "updateChannel")
    if "disableAccessKeyAuthentication" in pay:
        props["disableAccessKeyAuthentication"] = _to_bool(pay["disableAccessKeyAuthentication"], False)
    if pay.get("redisVersion") is not None:
        v = str(pay["redisVersion"])
        if v.lower() != "latest" and v.split(".")[0] not in REDIS_VERSIONS:
            raise _E(400, "BadRequest", f"The redis version '{v}' is not supported. Supported versions: 4, 6.")
        if v.split(".")[0] < props["redisVersion"].split(".")[0]:
            raise _E(400, "BadRequest", "Downgrading the redis version is not supported.")
        props["redisVersion"] = DEFAULT_VERSION if v.lower() == "latest" else v
    cur_cfg = {k: v for k, v in props["redisConfiguration"].items() if k in CONFIG_KEYS}
    if pay.get("redisConfiguration") is not None:
        cur_cfg.update(_norm_config(pay["redisConfiguration"], sku))
    props["redisConfiguration"] = _computed_config(sku, cur_cfg)
    _premium_props(props, pay, sku)
    props["instances"] = _instances(rec)
    props["provisioningState"] = "Succeeded"


def _list(state, sub, rg, query, base):
    cs = [r for r in _caches(state) if r.get("_sub") == sub and (rg is None or (r.get("_rg") or "").lower() == rg.lower())]
    cs.sort(key=lambda r: (r["name"].lower(), r["id"].lower()))
    items = [_view(r) for r in cs]
    return _ok({"value": items})


def connection_info(rec):
    """What the console's Connect blade shows (not part of the Azure API)."""
    p = rec["properties"]
    live = bool(DATA_PLANE["host"])
    host, port = (DATA_PLANE["host"], DATA_PLANE["port"]) if live else (p["hostName"], p["port"])
    return {
        "hostName": p["hostName"], "port": p["port"], "sslPort": p["sslPort"],
        "primaryConnectionString": f"{p['hostName']}:{p['sslPort']},password={rec['_keys']['primary']},ssl=True,abortConnect=False",
        "secondaryConnectionString": f"{p['hostName']}:{p['sslPort']},password={rec['_keys']['secondary']},ssl=True,abortConnect=False",
        "redisCli": f"redis-cli -h {host} -p {port}" + ("" if live else f" -a <access key> --tls (port {p['sslPort']})"),
        "dataPlane": (f"Valkey data plane (Redis protocol, no TLS) at {host}:{port}" if live
                      else "Control plane only (the Valkey data plane runs on the offline appliance, Lite tier and up)"),
        "dataPlaneHost": host if live else None, "dataPlanePort": port if live else None,
        "size": size_label(p["sku"]), "maxClients": p["redisConfiguration"].get("maxclients"),
    }


# ═══════════════════════════ child resources ═════════════════════════════════════
def _child_id(rec, kind, name):
    return f"{rec['id']}/{kind}/{name}"


def _ip(v, what):
    try:
        return str(ipaddress.IPv4Address(str(v).strip()))
    except ValueError:
        raise _E(400, "BadRequest", f"'{v}' is not a valid IPv4 address for {what}.") from None


def _fw_view(rec, r):
    return {"id": _child_id(rec, "firewallRules", r["name"]), "name": r["name"], "type": f"{RESOURCE_TYPE}/firewallRules",
            "properties": {"startIP": r["startIP"], "endIP": r["endIP"]}}


def _patch_view(rec, r):
    return {"id": _child_id(rec, "patchSchedules", r["name"]), "name": r["name"], "type": f"{RESOURCE_TYPE}/patchSchedules",
            "location": rec["location"], "properties": {"scheduleEntries": r["entries"]}}


def _linked_view(rec, r):
    return {"id": _child_id(rec, "linkedServers", r["name"]), "name": r["name"], "type": f"{RESOURCE_TYPE}/linkedServers",
            "properties": {"linkedRedisCacheId": r["linkedRedisCacheId"], "linkedRedisCacheLocation": r["linkedRedisCacheLocation"],
                           "serverRole": r["serverRole"], "provisioningState": "Succeeded",
                           "geoReplicatedPrimaryHostName": r["geoPrimary"], "primaryHostName": r["primaryHost"]}}


def _sync_linked(rec):
    rec["properties"]["linkedServers"] = [{"id": r["linkedRedisCacheId"]} for r in rec["_linked"].values()]


def _firewall(rec, rest, method, payload):
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_fw_view(rec, r) for _, r in sorted(rec["_fw"].items())]})
    key = rest[1].lower()
    cur = rec["_fw"].get(key)
    if method == "GET":
        if cur is None:
            raise _E(404, "NotFound", f"The firewall rule '{rest[1]}' was not found.")
        return _ok(_fw_view(rec, cur))
    if method == "PUT":
        if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", rest[1]):
            raise _E(400, "BadRequest", "The firewall rule name can contain only letters, numbers and underscores (1-128 characters).")
        p = payload.get("properties") or {}
        for f in ("startIP", "endIP"):
            if not p.get(f):
                raise _E(400, "BadRequest", f"Required property '{f}' not found in JSON.")
        s, e = _ip(p["startIP"], "startIP"), _ip(p["endIP"], "endIP")
        if int(ipaddress.IPv4Address(s)) > int(ipaddress.IPv4Address(e)):
            raise _E(400, "BadRequest", "startIP must not be greater than endIP.")
        rec["_fw"][key] = {"name": rest[1], "startIP": s, "endIP": e}
        return _ok(_fw_view(rec, rec["_fw"][key]), 200 if cur else 201)
    if method == "DELETE":
        rec["_fw"].pop(key, None)
        return _ok(None, 200 if cur else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _norm_entries(raw):
    if not isinstance(raw, list) or not raw:
        raise _E(400, "BadRequest", "Required property 'scheduleEntries' must be a non-empty array.")
    out = []
    for e in raw:
        e = e or {}
        day = str(e.get("dayOfWeek") or "")
        day = next((d for d in DAYS if d.lower() == day.lower()), None)
        if day is None:
            raise _E(400, "BadRequest", f"dayOfWeek must be one of {', '.join(DAYS)}.")
        hr = _to_int(e.get("startHourUtc"))
        if hr is None or not 0 <= hr <= 23:
            raise _E(400, "BadRequest", "startHourUtc must be an integer between 0 and 23.")
        entry = {"dayOfWeek": day, "startHourUtc": hr}
        if e.get("maintenanceWindow"):
            if not re.fullmatch(r"P(T\d+H)?(\d+D)?", str(e["maintenanceWindow"])) and not str(e["maintenanceWindow"]).startswith("PT"):
                raise _E(400, "BadRequest", "maintenanceWindow must be an ISO 8601 duration such as PT5H.")
            entry["maintenanceWindow"] = str(e["maintenanceWindow"])
        out.append(entry)
    return out


def _patch_schedules(rec, rest, method, payload):
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_patch_view(rec, r) for r in rec["_patch"].values()]})
    if rest[1].lower() != "default":
        raise _E(400, "BadRequest", "The patch schedule name must be 'default'.")
    cur = rec["_patch"].get("default")
    if method == "GET":
        if cur is None:
            raise _E(404, "NotFound", f"There are no patch schedules found for Redis cache '{rec['name']}'.")
        return _ok(_patch_view(rec, cur))
    if method == "PUT":
        if rec["properties"]["sku"]["name"] != "Premium":
            raise _E(400, "BadRequest", "Patch schedules are only supported on the Premium tier.")
        entries = _norm_entries((payload.get("properties") or {}).get("scheduleEntries"))
        rec["_patch"]["default"] = {"name": "default", "entries": entries}
        return _ok(_patch_view(rec, rec["_patch"]["default"]), 200 if cur else 201)
    if method == "DELETE":
        if cur is None:
            raise _E(404, "NotFound", f"There are no patch schedules found for Redis cache '{rec['name']}'.")
        rec["_patch"].pop("default")
        return _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _linked_servers(state, rec, rest, method, payload):
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_linked_view(rec, r) for r in rec["_linked"].values()]})
    key = rest[1].lower()
    cur = rec["_linked"].get(key)
    if method == "GET":
        if cur is None:
            raise _E(404, "NotFound", f"The linked server '{rest[1]}' was not found.")
        return _ok(_linked_view(rec, cur))
    if method == "PUT":
        p = payload.get("properties") or {}
        lid = p.get("linkedRedisCacheId")
        if not lid or not p.get("linkedRedisCacheLocation"):
            raise _E(400, "BadRequest", "linkedRedisCacheId and linkedRedisCacheLocation are required.")
        role = _enum(str(p.get("serverRole") or ""), ("Primary", "Secondary"), "serverRole")
        other = state.get(str(lid).lower())
        if other is None or str(other.get("_type", "")).lower() != RESOURCE_TYPE.lower():
            raise _E(404, "ResourceNotFound", f"The linked cache '{lid}' was not found.")
        if other["name"].lower() != rest[1].lower():
            raise _E(400, "BadRequest", "The linked server name must be the name of the linked cache.")
        if other["id"].lower() == rec["id"].lower():
            raise _E(400, "BadRequest", "A cache cannot be linked to itself.")
        if "Premium" != rec["properties"]["sku"]["name"] or other["properties"]["sku"]["name"] != "Premium":
            raise _E(400, "BadRequest", "Geo-replication requires both caches to be on the Premium tier.")
        prim = rec if role == "Secondary" else other
        rec["_linked"][key] = {"name": other["name"], "linkedRedisCacheId": other["id"],
                               "linkedRedisCacheLocation": p["linkedRedisCacheLocation"], "serverRole": role,
                               "geoPrimary": prim["properties"]["hostName"], "primaryHost": rec["properties"]["hostName"]}
        _sync_linked(rec)
        return _ok(_linked_view(rec, rec["_linked"][key]), 200 if cur else 201, lro=True, rid=rec["id"], verb="put")
    if method == "DELETE":
        if cur is None:
            return _ok(None, 204)
        rec["_linked"].pop(key)
        _sync_linked(rec)
        return _ok(None, 200, lro=True, rid=rec["id"], verb="put")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ═══════════════════════════ actions ═════════════════════════════════════════════
def _action(state, rec, act, method, payload):
    if method != "POST":
        return _err(405, "MethodNotAllowed", "POST required.")
    if act == "listkeys":
        return _ok(_keys_view(rec))
    if act == "regeneratekey":
        kt = str(payload.get("keyType") or "")
        kt = next((k for k in ("Primary", "Secondary") if k.lower() == kt.lower()), None)
        if kt is None:
            raise _E(400, "BadRequest", "keyType must be Primary or Secondary.")
        rec["_keys"][kt.lower()] = _new_key()
        return _ok(_keys_view(rec))
    if act == "forcereboot":
        rt = str(payload.get("rebootType") or "")
        rt = next((k for k in REBOOT_TYPES if k.lower() == rt.lower()), None)
        if rt is None:
            raise _E(400, "BadRequest", f"rebootType must be one of {', '.join(REBOOT_TYPES)}.")
        sku = rec["properties"]["sku"]
        if rt == "SecondaryNode" and sku["name"] == "Basic":
            raise _E(400, "BadRequest", "A Basic cache has no secondary node to reboot.")
        shard = payload.get("shardId")
        if shard is not None and (sku["name"] != "Premium" or not 0 <= (_to_int(shard, -1)) < (rec["properties"].get("shardCount") or 1)):
            raise _E(400, "BadRequest", "shardId is only valid for a Premium cache and must name an existing shard.")
        return _ok({"message": "Reboot of " + {"PrimaryNode": "the primary node", "SecondaryNode": "the secondary node",
                                               "AllNodes": "all nodes"}[rt] + " has completed."})
    if act in ("import", "export"):
        if rec["properties"]["sku"]["name"] != "Premium":
            raise _E(400, "BadRequest", f"Data {act} is only supported on the Premium tier.")
        if act == "import":
            files = payload.get("files")
            if not isinstance(files, list) or not files or not all(isinstance(f, str) and f for f in files):
                raise _E(400, "BadRequest", "Required property 'files' must be a non-empty array of blob URIs.")
        else:
            for f in ("prefix", "container"):
                if not payload.get(f):
                    raise _E(400, "BadRequest", f"Required property '{f}' not found in JSON.")
        if payload.get("format") is not None:
            _enum(str(payload["format"]).upper(), EXPORT_FORMATS, "format")
        return _ok(None, 202, lro=True, rid=rec["id"], verb="put")
    if act == "flush":
        return _ok({"message": "Flush has completed."})
    return _err(404, "ResourceTypeNotSupported", f"The action '{act}' is not supported on {RESOURCE_TYPE}.")


# ═══════════════════════════ dispatch ════════════════════════════════════════════
def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.Cache`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {}, base)
    except _E as e:
        return _err(e.status, e.code, e.message)


def handles(chain):
    return bool(chain) and chain[0].lower() in (TYPE.lower(), "checknameavailability")


def _dispatch(state, method, sub, rg, chain, payload, query, base=""):
    low = chain[0].lower()
    if low == "checknameavailability":
        if method != "POST" or len(chain) != 1:
            return _err(405, "MethodNotAllowed", "POST required.")
        if str(payload.get("type") or "").lower() != RESOURCE_TYPE.lower():
            raise _E(400, "BadRequest", f"The type must be '{RESOURCE_TYPE}'.")
        n = str(payload.get("name") or "")
        prob = name_problem(n)
        if prob:
            raise _E(400, "BadRequest", prob)
        if any(c["name"].lower() == n.lower() for c in _caches(state)):
            raise _E(409, "Conflict", f"The name '{n}' is already in use.")
        return _ok(None, 200)
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(state, sub, rg, query, base)
    name = chain[1]
    if rg is None:
        return _err(400, "InvalidResourceId", "Redis caches must be addressed within a resource group.")
    rid = _rid(sub, rg, name)
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found(name, rg)
        sub_low = rest[0].lower()
        if len(rest) == 1 and sub_low in ("listkeys", "regeneratekey", "forcereboot", "import", "export", "flush"):
            return _action(state, rec, sub_low, method, payload)
        if sub_low == "connectioninfo" and len(rest) == 1:                 # console Connect blade (not an Azure API)
            return _ok(connection_info(rec))
        if sub_low == "firewallrules" and len(rest) <= 2:
            return _firewall(rec, rest, method, payload)
        if sub_low == "patchschedules" and len(rest) <= 2:
            return _patch_schedules(rec, rest, method, payload)
        if sub_low == "linkedservers" and len(rest) <= 2:
            return _linked_servers(state, rec, rest, method, payload)
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{RESOURCE_TYPE}/{'/'.join(rest)}' is not supported.")
    if method == "GET":
        if rec is None:
            raise _not_found(name, rg)
        return _ok(_view(rec))
    if method in ("PUT", "PATCH"):
        created = rec is None
        if created:
            if method == "PATCH":
                raise _not_found(name, rg)
            rec = _create(state, sub, rg, rid, name, payload)
        else:
            _update(rec, payload, method)
        return _ok(_view(rec, keys=True), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        state.pop(rid.lower(), None)
        for other in _caches(state):                       # unlink geo-replication partners
            if rec["id"].lower() in other["_linked"] or rec["name"].lower() in other["_linked"]:
                other["_linked"].pop(rec["name"].lower(), None)
                _sync_linked(other)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [(TYPE, API_VERSION)]
