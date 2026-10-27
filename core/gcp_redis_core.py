"""GCP Memorystore for Redis core — substrate-independent. Speaks the native
**Memorystore for Redis REST API v1** (`redis.googleapis.com/v1`) so the native
`google-cloud-redis` SDKs and `gcloud redis instances ...` work unchanged against it
(point them at the endpoint via api_endpoint / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano. This is the Memorystore *control plane*: instances,
long-running operations, auth strings, failover/upgrade/import/export. The data plane is
the shared Valkey container (BSD-3, Redis-protocol compatible) when the appliance has one
(`configure_data_plane(host, port)` is called by the server from the compose env);
otherwise (Nano, Free tier) an instance's `host` is a deterministic private address and
the console says the data plane is not served.

Resources (Discovery doc `redis/v1`):
    projects/{p}/locations/{l}/instances/{i}
    projects/{p}/locations/{l}/operations/{op}
Methods: instances.create/get/list/patch/delete/failover/upgrade/import/export/
rescheduleMaintenance/getAuthString, operations.get/list/delete/cancel. Every mutation
returns a completed `google.longrunning.Operation` (done=true) like a very fast real cloud;
errors use the Google shape `{"error":{"code","message","status"}}`.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

REGIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1", "europe-west2",
           "europe-west3", "europe-west4", "asia-east1", "asia-northeast1", "asia-south1",
           "asia-southeast1", "australia-southeast1", "southamerica-east1"]
VERSIONS = ["REDIS_3_2", "REDIS_4_0", "REDIS_5_0", "REDIS_6_X", "REDIS_7_0", "REDIS_7_2"]
DEFAULT_VERSION = "REDIS_7_0"
TIERS = ("BASIC", "STANDARD_HA")
CONNECT_MODES = ("DIRECT_PEERING", "PRIVATE_SERVICE_ACCESS")
TRANSIT_MODES = ("DISABLED", "SERVER_AUTHENTICATION")
READ_REPLICAS = ("READ_REPLICAS_DISABLED", "READ_REPLICAS_ENABLED")
PERSISTENCE_MODES = ("DISABLED", "RDB")
SNAPSHOT_PERIODS = ("ONE_HOUR", "SIX_HOURS", "TWELVE_HOURS", "TWENTY_FOUR_HOURS")
MAX_MEMORY_GB = 300
DEFAULT_PORT = 6379
# redis.conf parameters the service lets you set (Instance.redisConfigs)
REDIS_CONFIGS = {
    "maxmemory-policy": ("volatile-lru", "allkeys-lru", "volatile-lfu", "allkeys-lfu", "volatile-random",
                         "allkeys-random", "volatile-ttl", "noeviction"),
    "notify-keyspace-events": None, "activedefrag": ("yes", "no"), "lfu-log-factor": None,
    "lfu-decay-time": None, "stream-node-max-bytes": None, "stream-node-max-entries": None,
    "maxmemory-gb": None, "timeout": None, "slowlog-log-slower-than": None, "slowlog-max-len": None,
}
DEFAULT_CONFIGS = {"maxmemory-policy": "volatile-lru"}

# Offline data plane (the shared Valkey container); None → control plane only.
DATA_PLANE: dict = {"host": None, "port": DEFAULT_PORT}


def configure_data_plane(host, port=DEFAULT_PORT):
    DATA_PLANE["host"], DATA_PLANE["port"] = (host or None), int(port or DEFAULT_PORT)


# ── store ──────────────────────────────────────────────────────────────────
class RedisStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.instances: dict = {}    # full instance name -> Instance resource
        self.operations: dict = {}   # full operation name -> Operation resource
        self.seq: dict = {"op": 0}


_SHARED: RedisStore | None = None


def shared_store() -> RedisStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = RedisStore()
    return _SHARED


@dataclass
class RedisResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _err(status, gcp_status, message):
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return RedisResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return RedisResponse(status=status, body=json.dumps(obj).encode())


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _copy(x):
    return json.loads(json.dumps(x))


# ── names / validation ─────────────────────────────────────────────────────
_NAME = re.compile(r"^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$")
_LABEL = re.compile(r"^[a-z][-_a-z0-9]{0,62}$")
_NET = re.compile(r"^projects/[^/]+/global/networks/[^/]+$")
_RANGE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$")


def instance_name(project, location, iid):
    return "projects/%s/locations/%s/instances/%s" % (project, location, iid)


def _valid_region(location):
    return location in REGIONS


def _zone_ok(zone, region):
    return bool(re.match(r"^%s-[a-z]$" % re.escape(region), zone or ""))


def _private_ip(name):
    h = hashlib.sha256(name.encode()).digest()
    return "10.%d.%d.%d" % (h[0] % 200 + 10, h[1], h[2] % 250 + 2)


def _check_labels(labels):
    if not isinstance(labels, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid labels.")
    if len(labels) > 64:
        raise _E(400, "INVALID_ARGUMENT", "An instance may have at most 64 labels.")
    for k, v in labels.items():
        if not _LABEL.match(str(k)) or len(str(v)) > 63:
            raise _E(400, "INVALID_ARGUMENT", "Invalid label %r: keys must match [a-z][-_a-z0-9]{0,62} and values be at most 63 characters." % k)


def _check_configs(cfg):
    if not isinstance(cfg, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid redisConfigs.")
    for k, v in cfg.items():
        if k not in REDIS_CONFIGS:
            raise _E(400, "INVALID_ARGUMENT", "Unsupported redis config %r; supported: %s." % (k, ", ".join(sorted(REDIS_CONFIGS))))
        allowed = REDIS_CONFIGS[k]
        if allowed is not None and v not in allowed:
            raise _E(400, "INVALID_ARGUMENT", "Invalid value %r for redis config %s; allowed: %s." % (v, k, ", ".join(allowed)))
    return {k: str(v) for k, v in cfg.items()}


def _check_persistence(p):
    p = dict(p or {})
    mode = p.get("persistenceMode") or "DISABLED"
    if mode not in PERSISTENCE_MODES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid persistenceMode %r." % mode)
    out = {"persistenceMode": mode}
    if mode == "RDB":
        period = p.get("rdbSnapshotPeriod") or "TWENTY_FOUR_HOURS"
        if period not in SNAPSHOT_PERIODS:
            raise _E(400, "INVALID_ARGUMENT", "Invalid rdbSnapshotPeriod %r." % period)
        out["rdbSnapshotPeriod"] = period
        out["rdbNextSnapshotTime"] = _ts()
    return out


def _check_maintenance(mp):
    mp = dict(mp or {})
    for w in mp.get("weeklyMaintenanceWindow") or []:
        if w.get("day") not in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"):
            raise _E(400, "INVALID_ARGUMENT", "Invalid maintenance window day %r." % w.get("day"))
        if not isinstance(w.get("startTime"), dict):
            raise _E(400, "INVALID_ARGUMENT", "weeklyMaintenanceWindow.startTime is required.")
        w.setdefault("duration", "3600s")
    mp.setdefault("createTime", _ts())
    mp["updateTime"] = _ts()
    return mp


def _check_memory(n):
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > MAX_MEMORY_GB:
        raise _E(400, "INVALID_ARGUMENT", "memorySizeGb must be an integer between 1 and %d." % MAX_MEMORY_GB)
    return n


def _check_replicas(tier, n, mode):
    if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > 5:
        raise _E(400, "INVALID_ARGUMENT", "replicaCount must be between 0 and 5.")
    if tier == "BASIC" and n != 0:
        raise _E(400, "INVALID_ARGUMENT", "replicaCount can only be set for the STANDARD_HA tier.")
    if tier == "STANDARD_HA" and n < 1:
        raise _E(400, "INVALID_ARGUMENT", "STANDARD_HA instances need at least 1 replica.")
    if mode == "READ_REPLICAS_ENABLED" and tier == "BASIC":
        raise _E(400, "INVALID_ARGUMENT", "Read replicas require the STANDARD_HA tier.")


def _nodes(inst):
    zones = [inst["currentLocationId"]]
    if inst["tier"] == "STANDARD_HA":
        zones.append(inst["alternativeLocationId"])
    n = 1 + inst.get("replicaCount", 0) if inst["tier"] == "STANDARD_HA" else 1
    return [{"id": "node-%d" % i, "zone": zones[i % len(zones)]} for i in range(n)]


def _endpoints(inst, name):
    host = DATA_PLANE["host"] or _private_ip(name)
    inst["host"], inst["port"] = host, DATA_PLANE["port"] if DATA_PLANE["host"] else DEFAULT_PORT
    if inst.get("readReplicasMode") == "READ_REPLICAS_ENABLED":
        inst["readEndpoint"], inst["readEndpointPort"] = host, inst["port"]
    else:
        inst.pop("readEndpoint", None)
        inst.pop("readEndpointPort", None)


# ── operations ─────────────────────────────────────────────────────────────
def _operation(store, project, location, verb, target, response=None, response_type="google.cloud.redis.v1.Instance"):
    store.seq["op"] += 1
    oid = "operation-%d-%s" % (store.seq["op"], hashlib.sha1(("%s%d" % (target, store.seq["op"])).encode()).hexdigest()[:10])
    name = "projects/%s/locations/%s/operations/%s" % (project, location, oid)
    now = _ts()
    op = {"name": name,
          "metadata": {"@type": "type.googleapis.com/google.cloud.redis.v1.OperationMetadata", "createTime": now,
                       "endTime": now, "target": target, "verb": verb, "statusDetail": "",
                       "cancelRequested": False, "apiVersion": "v1"},
          "done": True}
    resp = {"@type": "type.googleapis.com/" + response_type}
    if response_type == "google.protobuf.Empty":
        resp["value"] = {}   # Empty has a special JSON form inside Any: the payload sits under "value"
    else:
        resp.update(response if response is not None else {})
    op["response"] = resp
    store.operations[name] = op
    return _copy(op)


def _get_op(store, project, location, oid):
    name = "projects/%s/locations/%s/operations/%s" % (project, location, oid)
    op = store.operations.get(name)
    if not op:
        raise _E(404, "NOT_FOUND", "Not found: %s." % name)
    return name, op


# ── instance views ─────────────────────────────────────────────────────────
def _get(store, project, location, iid):
    full = instance_name(project, location, iid)
    i = store.instances.get(full)
    if not i:
        raise _E(404, "NOT_FOUND", "Instance %s not found." % full)
    return i


def instance_view(i):
    v = _copy(i)
    v.pop("authString", None)   # only served by getAuthString
    v["nodes"] = _nodes(i)
    return v


def console_view(i):
    """Flat row for the console grid / detail: every column filled."""
    seg = i["name"].split("/")
    v = instance_view(i)
    ha = i["tier"] == "STANDARD_HA"
    live = bool(DATA_PLANE["host"])
    cfg = i.get("redisConfigs") or {}
    pers = i.get("persistenceConfig") or {}
    mw = ((i.get("maintenancePolicy") or {}).get("weeklyMaintenanceWindow") or [])
    v.update({
        "id": seg[5], "name": seg[5], "resourceName": i["name"], "project": seg[1], "region": seg[3],
        "status": i["state"],
        "tier_label": "Standard (HA)" if ha else "Basic",
        "version": i["redisVersion"].replace("REDIS_", "Redis ").replace("_X", ".x").replace("_", "."),
        "capacity": "%d GB" % i["memorySizeGb"],
        "endpoint": "%s:%d" % (i["host"], i["port"]),
        "replicas": i.get("replicaCount", 0),
        "network": i["authorizedNetwork"].rsplit("/", 1)[-1],
        "auth": "Enabled" if i.get("authEnabled") else "Disabled",
        "encryption": "Server authentication (TLS)" if i.get("transitEncryptionMode") == "SERVER_AUTHENTICATION" else "Disabled",
        "zone": i["currentLocationId"],
        "alt_zone": i.get("alternativeLocationId") or "None (Basic tier)",
        "read_endpoint": ("%s:%d" % (i["readEndpoint"], i["readEndpointPort"])) if i.get("readEndpoint") else "Read replicas disabled",
        "read_replicas": "Enabled" if i.get("readReplicasMode") == "READ_REPLICAS_ENABLED" else "Disabled",
        "node_summary": ", ".join("%s (%s)" % (n["id"], n["zone"]) for n in v["nodes"]),
        "redis_configs_text": ", ".join("%s=%s" % kv for kv in sorted(cfg.items())) or "Defaults",
        "persistence": pers.get("persistenceMode", "DISABLED") + (
            " every %s" % pers["rdbSnapshotPeriod"].lower().replace("_", " ") if pers.get("rdbSnapshotPeriod") else ""),
        "maintenance_window": ", ".join("%s %02d:%02d" % (w["day"].title(), w["startTime"].get("hours", 0), w["startTime"].get("minutes", 0))
                                        for w in mw) or "Any time (no preference)",
        "labels_text": ", ".join("%s=%s" % kv for kv in sorted((i.get("labels") or {}).items())) or "None",
        "display_name": i.get("displayName") or seg[5],
        "connect_cmd": "redis-cli -h %s -p %d%s" % (i["host"], i["port"], " -a <AUTH string>" if i.get("authEnabled") else ""),
        "data_plane": ("Valkey data plane (Redis protocol) at %s:%d" % (DATA_PLANE["host"], DATA_PLANE["port"])) if live
        else "Control plane only (the Valkey data plane runs on the offline appliance, Lite tier and up)",
        "created": i.get("createTime", ""),
    })
    return v


def view_by_name(store, full):
    return console_view(store.instances[full])


def list_all(store, project=None):
    """Console grid: every instance (optionally for one project)."""
    return [console_view(i) for n, i in sorted(store.instances.items())
            if project is None or n.startswith("projects/%s/" % project)]


# ── instance operations ────────────────────────────────────────────────────
def create_instance(store, project, location, iid, payload):
    if not _valid_region(location):
        raise _E(400, "INVALID_ARGUMENT", "Location %r does not exist." % location)
    if not iid:
        raise _E(400, "INVALID_ARGUMENT", "instanceId is required.")
    if not _NAME.match(iid):
        raise _E(400, "INVALID_ARGUMENT", "Invalid instance id %r: must match %s (at most 40 characters)." % (iid, _NAME.pattern))
    spec = dict(payload or {})
    if not spec:
        raise _E(400, "INVALID_ARGUMENT", "Instance must be specified.")
    full = instance_name(project, location, iid)
    if full in store.instances:
        raise _E(409, "ALREADY_EXISTS", "Instance %s already exists." % full)
    tier = spec.get("tier") or "BASIC"
    if tier not in TIERS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid tier %r; valid: %s." % (tier, ", ".join(TIERS)))
    mem = _check_memory(spec.get("memorySizeGb"))
    ver = spec.get("redisVersion") or DEFAULT_VERSION
    if ver not in VERSIONS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid redisVersion %r; valid: %s." % (ver, ", ".join(VERSIONS)))
    mode = spec.get("connectMode") or "DIRECT_PEERING"
    if mode not in CONNECT_MODES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid connectMode %r." % mode)
    net = spec.get("authorizedNetwork") or "projects/%s/global/networks/default" % project
    if "/" not in net:
        net = "projects/%s/global/networks/%s" % (project, net)
    if not _NET.match(net):
        raise _E(400, "INVALID_ARGUMENT", "Invalid authorizedNetwork %r: expected projects/{project}/global/networks/{network}." % net)
    zone = spec.get("locationId") or location + "-a"
    if not _zone_ok(zone, location):
        raise _E(400, "INVALID_ARGUMENT", "locationId %r is not a zone of region %s." % (zone, location))
    alt = spec.get("alternativeLocationId")
    if tier == "STANDARD_HA":
        alt = alt or location + ("-b" if zone.endswith("-a") else "-a")
        if not _zone_ok(alt, location):
            raise _E(400, "INVALID_ARGUMENT", "alternativeLocationId %r is not a zone of region %s." % (alt, location))
        if alt == zone:
            raise _E(400, "INVALID_ARGUMENT", "alternativeLocationId must differ from locationId.")
    elif alt:
        raise _E(400, "INVALID_ARGUMENT", "alternativeLocationId can only be set for the STANDARD_HA tier.")
    if spec.get("reservedIpRange") and mode == "DIRECT_PEERING" and not _RANGE.match(spec["reservedIpRange"]):
        raise _E(400, "INVALID_ARGUMENT", "reservedIpRange must be a CIDR block such as 10.0.0.0/29.")
    rmode = spec.get("readReplicasMode") or "READ_REPLICAS_DISABLED"
    if rmode not in READ_REPLICAS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid readReplicasMode %r." % rmode)
    replicas = spec.get("replicaCount", 1 if tier == "STANDARD_HA" else 0)
    _check_replicas(tier, replicas, rmode)
    tmode = spec.get("transitEncryptionMode") or "DISABLED"
    if tmode not in TRANSIT_MODES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid transitEncryptionMode %r." % tmode)
    if "labels" in spec:
        _check_labels(spec["labels"])
    cfg = dict(DEFAULT_CONFIGS)
    cfg.update(_check_configs(spec.get("redisConfigs") or {}))
    inst = {
        "name": full, "displayName": spec.get("displayName") or iid, "labels": spec.get("labels") or {},
        "locationId": zone, "alternativeLocationId": alt or "", "redisVersion": ver,
        "reservedIpRange": spec.get("reservedIpRange") or "10.%d.0.0/29" % (int(hashlib.sha1(full.encode()).hexdigest()[:2], 16) % 200 + 10),
        "currentLocationId": zone, "createTime": _ts(), "state": "READY", "statusMessage": "",
        "redisConfigs": cfg, "tier": tier, "memorySizeGb": mem, "authorizedNetwork": net,
        "persistenceIamIdentity": "serviceAccount:service-%s@cloud-redis.iam.gserviceaccount.com" % (
            str(int(hashlib.sha1(project.encode()).hexdigest()[:8], 16))),
        "connectMode": mode, "authEnabled": bool(spec.get("authEnabled", False)),
        "serverCaCerts": [], "transitEncryptionMode": tmode, "replicaCount": replicas,
        "readReplicasMode": rmode, "persistenceConfig": _check_persistence(spec.get("persistenceConfig")),
        "suspensionReasons": [],
    }
    if not inst["alternativeLocationId"]:
        inst.pop("alternativeLocationId")
    if spec.get("maintenancePolicy"):
        inst["maintenancePolicy"] = _check_maintenance(spec["maintenancePolicy"])
    if tmode == "SERVER_AUTHENTICATION":
        inst["serverCaCerts"] = [_ca_cert(full)]
    inst["authString"] = "auth-" + hashlib.sha256(("auth" + full).encode()).hexdigest()[:32]
    _endpoints(inst, full)
    store.instances[full] = inst
    return _operation(store, project, location, "create", full, _public(inst))


def _ca_cert(full):
    sha = hashlib.sha1(full.encode()).hexdigest()
    return {"serialNumber": "0", "cert": "-----BEGIN CERTIFICATE-----\n%s\n-----END CERTIFICATE-----" % hashlib.sha256(full.encode()).hexdigest(),
            "createTime": _ts(), "expireTime": "2036-01-01T00:00:00Z", "sha1Fingerprint": sha}


def _public(i):
    """Instance as the API returns it."""
    return instance_view(i)


_UPDATABLE = {"displayName", "labels", "memorySizeGb", "redisConfigs", "replicaCount", "maintenancePolicy",
              "persistenceConfig", "authEnabled", "readReplicasMode", "transitEncryptionMode"}


def _camel(s):
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), s)


def patch_instance(store, project, location, iid, payload, mask):
    i = _get(store, project, location, iid)
    paths = [_camel(p.strip()) for p in (mask or "").split(",") if p.strip()]
    if not paths:
        raise _E(400, "INVALID_ARGUMENT", "updateMask is required.")
    patch = dict(payload or {})
    full = i["name"]
    new = _copy(i)
    for p in paths:
        top = p.split(".")[0]
        if top == "redisConfig":
            top = "redisConfigs"
        if top not in _UPDATABLE:
            raise _E(400, "INVALID_ARGUMENT", "Field %r is not updatable (updatable: %s)." % (p, ", ".join(sorted(_UPDATABLE))))
        val = patch.get(top)
        if top == "displayName":
            new["displayName"] = val or ""
        elif top == "labels":
            _check_labels(val or {})
            new["labels"] = dict(val or {})
        elif top == "memorySizeGb":
            new["memorySizeGb"] = _check_memory(val)
        elif top == "redisConfigs":
            if "." in p:
                key = p.split(".", 1)[1]
                cfg = dict(new["redisConfigs"])
                if key in (val or {}):
                    cfg.update(_check_configs({key: val[key]}))
                else:
                    cfg.pop(key, None)
                new["redisConfigs"] = cfg
            else:
                new["redisConfigs"] = dict(DEFAULT_CONFIGS, **_check_configs(val or {}))
        elif top == "replicaCount":
            _check_replicas(new["tier"], val, new["readReplicasMode"])
            new["replicaCount"] = val
        elif top == "maintenancePolicy":
            if val:
                new["maintenancePolicy"] = _check_maintenance(val)
            else:
                new.pop("maintenancePolicy", None)
                new.pop("maintenanceSchedule", None)
        elif top == "persistenceConfig":
            new["persistenceConfig"] = _check_persistence(val)
        elif top == "authEnabled":
            new["authEnabled"] = bool(val)
        elif top == "readReplicasMode":
            if val not in READ_REPLICAS:
                raise _E(400, "INVALID_ARGUMENT", "Invalid readReplicasMode %r." % val)
            _check_replicas(new["tier"], new["replicaCount"], val)
            new["readReplicasMode"] = val
        elif top == "transitEncryptionMode":
            if val not in TRANSIT_MODES:
                raise _E(400, "INVALID_ARGUMENT", "Invalid transitEncryptionMode %r." % val)
            new["transitEncryptionMode"] = val
            new["serverCaCerts"] = [_ca_cert(full)] if val == "SERVER_AUTHENTICATION" else []
    _endpoints(new, full)
    store.instances[full] = new
    return _operation(store, project, location, "update", full, _public(new))


def delete_instance(store, project, location, iid):
    i = _get(store, project, location, iid)
    del store.instances[i["name"]]
    return _operation(store, project, location, "delete", i["name"], {}, "google.protobuf.Empty")


def failover_instance(store, project, location, iid, payload):
    i = _get(store, project, location, iid)
    if i["tier"] != "STANDARD_HA":
        raise _E(400, "FAILED_PRECONDITION", "Failover is only supported for STANDARD_HA instances.")
    mode = payload.get("dataProtectionMode") or "LIMITED_DATA_LOSS"
    if mode not in ("LIMITED_DATA_LOSS", "FORCE_DATA_LOSS"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid dataProtectionMode %r." % mode)
    cur, alt = i["currentLocationId"], i["alternativeLocationId"]
    i["currentLocationId"], i["alternativeLocationId"] = alt, cur
    return _operation(store, project, location, "failover", i["name"], _public(i))


def upgrade_instance(store, project, location, iid, payload):
    i = _get(store, project, location, iid)
    ver = payload.get("redisVersion")
    if ver not in VERSIONS:
        raise _E(400, "INVALID_ARGUMENT", "Invalid redisVersion %r; valid: %s." % (ver, ", ".join(VERSIONS)))
    if VERSIONS.index(ver) <= VERSIONS.index(i["redisVersion"]):
        raise _E(400, "FAILED_PRECONDITION", "Cannot upgrade from %s to %s: the target must be a newer version." % (i["redisVersion"], ver))
    i["redisVersion"] = ver
    return _operation(store, project, location, "upgrade", i["name"], _public(i))


def _gcs_uri(uri, what):
    if not isinstance(uri, str) or not re.match(r"^gs://[a-z0-9][-a-z0-9_.]{1,220}/.+$", uri):
        raise _E(400, "INVALID_ARGUMENT", "%s must be a Cloud Storage object URI such as gs://bucket/dump.rdb." % what)


def export_instance(store, project, location, iid, payload):
    i = _get(store, project, location, iid)
    _gcs_uri(((payload.get("outputConfig") or {}).get("gcsDestination") or {}).get("uri"), "outputConfig.gcsDestination.uri")
    return _operation(store, project, location, "export", i["name"], _public(i))


def import_instance(store, project, location, iid, payload):
    i = _get(store, project, location, iid)
    _gcs_uri(((payload.get("inputConfig") or {}).get("gcsSource") or {}).get("uri"), "inputConfig.gcsSource.uri")
    return _operation(store, project, location, "import", i["name"], _public(i))


def reschedule_maintenance(store, project, location, iid, payload):
    i = _get(store, project, location, iid)
    rt = payload.get("rescheduleType")
    if rt not in ("IMMEDIATE", "NEXT_AVAILABLE_WINDOW", "SPECIFIC_TIME"):
        raise _E(400, "INVALID_ARGUMENT", "Invalid rescheduleType %r." % rt)
    if rt == "SPECIFIC_TIME" and not payload.get("scheduleTime"):
        raise _E(400, "INVALID_ARGUMENT", "scheduleTime is required for SPECIFIC_TIME.")
    start = payload.get("scheduleTime") if rt == "SPECIFIC_TIME" else _ts()
    i["maintenanceSchedule"] = {"startTime": start, "endTime": start, "canReschedule": True}
    return _operation(store, project, location, "rescheduleMaintenance", i["name"], _public(i))


def get_auth_string(store, project, location, iid):
    i = _get(store, project, location, iid)
    if not i.get("authEnabled"):
        raise _E(400, "FAILED_PRECONDITION", "Instance %s does not have AUTH enabled." % i["name"])
    return {"authString": i["authString"]}


# ── console form ───────────────────────────────────────────────────────────
def job_from_form(b, project="demo"):
    """Console create form (catalog createFields) → (location, instanceId, Instance body), shared by
    the offline console REST and the Nano adapter so both consoles create identical instances."""
    location = str(b.get("region") or b.get("location") or "us-central1")
    tier = str(b.get("tier") or "BASIC").upper().replace(" ", "_")
    try:
        mem = int(b.get("memorySizeGb") if b.get("memorySizeGb") not in (None, "") else 1)
    except (TypeError, ValueError):
        mem = -1
    inst = {"tier": tier, "memorySizeGb": mem,
            "redisVersion": str(b.get("redisVersion") or DEFAULT_VERSION).upper(),
            "authorizedNetwork": str(b.get("network") or "default").strip() or "default"}
    if b.get("displayName"):
        inst["displayName"] = str(b["displayName"])
    if str(b.get("authEnabled", "")).lower() in ("true", "yes", "enabled", "1"):
        inst["authEnabled"] = True
    if str(b.get("transitEncryptionMode") or "").upper() == "SERVER_AUTHENTICATION":
        inst["transitEncryptionMode"] = "SERVER_AUTHENTICATION"
    if isinstance(b.get("labels"), dict) and b["labels"]:
        inst["labels"] = b["labels"]
    return {"parent": "projects/%s/locations/%s" % (project, location), "location": location,
            "instanceId": str(b.get("name") or "").strip(), "instance": inst}


# ── enum encoding ──────────────────────────────────────────────────────────
# Proto enums are strings on the wire by default, but the Java / Go-gapic REST clients send
# `$alt=json;enum-encoding=int` and expect integers back (and send integers in bodies).
_ENUMS = {
    "state": {"STATE_UNSPECIFIED": 0, "CREATING": 1, "READY": 2, "UPDATING": 3, "DELETING": 4, "REPAIRING": 5,
              "MAINTENANCE": 6, "IMPORTING": 8, "FAILING_OVER": 9},
    "tier": {"TIER_UNSPECIFIED": 0, "BASIC": 1, "STANDARD_HA": 3},
    "connectMode": {"CONNECT_MODE_UNSPECIFIED": 0, "DIRECT_PEERING": 1, "PRIVATE_SERVICE_ACCESS": 2},
    "transitEncryptionMode": {"TRANSIT_ENCRYPTION_MODE_UNSPECIFIED": 0, "SERVER_AUTHENTICATION": 1, "DISABLED": 2},
    "readReplicasMode": {"READ_REPLICAS_MODE_UNSPECIFIED": 0, "READ_REPLICAS_DISABLED": 1, "READ_REPLICAS_ENABLED": 2},
    "persistenceMode": {"PERSISTENCE_MODE_UNSPECIFIED": 0, "DISABLED": 1, "RDB": 2},
    "rdbSnapshotPeriod": {"SNAPSHOT_PERIOD_UNSPECIFIED": 0, "ONE_HOUR": 3, "SIX_HOURS": 4, "TWELVE_HOURS": 5,
                          "TWENTY_FOUR_HOURS": 6},
    "dataProtectionMode": {"DATA_PROTECTION_MODE_UNSPECIFIED": 0, "LIMITED_DATA_LOSS": 1, "FORCE_DATA_LOSS": 2},
    "rescheduleType": {"RESCHEDULE_TYPE_UNSPECIFIED": 0, "IMMEDIATE": 1, "NEXT_AVAILABLE_WINDOW": 2, "SPECIFIC_TIME": 3},
    "day": {"DAY_OF_WEEK_UNSPECIFIED": 0, "MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3, "THURSDAY": 4, "FRIDAY": 5,
            "SATURDAY": 6, "SUNDAY": 7},
}
_FREE_FORM = ("labels", "redisConfigs", "metadata")   # maps whose keys/values are user data, never enums


def _enum_walk(o, to_int):
    if isinstance(o, list):
        return [_enum_walk(x, to_int) for x in o]
    if not isinstance(o, dict):
        return o
    out = {}
    for k, v in o.items():
        if k in _FREE_FORM:
            out[k] = v
        elif k in _ENUMS and not isinstance(v, (dict, list)):
            table = _ENUMS[k]
            if not to_int:
                table = {n: s for s, n in table.items()}
            out[k] = table.get(v, v)
        else:
            out[k] = _enum_walk(v, to_int)
    return out


def _wants_int_enums(query):
    return "enum-encoding=int" in (query.get("$alt") or query.get("alt") or "").replace("%3D", "=")


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    query = query or {}
    r = _dispatch(store, method, path, query, headers or {}, body)
    if r.status == 200 and _wants_int_enums(query):
        try:
            r.body = json.dumps(_enum_walk(json.loads(r.body), True)).encode()
        except Exception:
            pass
    return r


def _dispatch(store, method, path, query, headers, body):
    method = method.upper()
    for k, v in headers.items():   # REST clients without PATCH/PUT tunnel them over POST
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    payload = _enum_walk(payload, False)
    p = path.split("?", 1)[0]
    for pre in ("/v1beta1", "/v1"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if len(segs) < 5 or segs[0] != "projects" or segs[2] != "locations":
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project, location, kind, rest = segs[1], segs[3], segs[4], segs[5:]
    try:
        if kind == "instances":
            return _instances(store, method, project, location, rest, verb, payload, query)
        if kind == "operations":
            return _operations(store, method, project, location, rest, verb)
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)


def _instances(store, method, project, location, rest, verb, payload, query):
    if not rest:
        if method == "POST":
            return _json(200, create_instance(store, project, location, query.get("instanceId") or "", payload))
        if method == "GET":
            if location != "-" and not _valid_region(location):
                raise _E(400, "INVALID_ARGUMENT", "Location %r does not exist." % location)
            names = [n for n in sorted(store.instances)
                     if n.startswith("projects/%s/locations/" % project) and (location == "-" or n.split("/")[3] == location)]
            try:
                size = int(query.get("pageSize") or 0)
                start = int(query.get("pageToken") or 0)
            except ValueError:
                raise _E(400, "INVALID_ARGUMENT", "Invalid pageToken or pageSize.")
            page = names[start:start + size] if size > 0 else names[start:]
            out = {"instances": [_public(store.instances[n]) for n in page]}
            if size > 0 and start + size < len(names):
                out["nextPageToken"] = str(start + size)
            if not out["instances"]:
                out = {}
            return _json(200, out)
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on instances collection." % method)
    iid = rest[0]
    if len(rest) == 2 and rest[1] == "authString" and method == "GET":
        return _json(200, get_auth_string(store, project, location, iid))
    if len(rest) != 1:
        raise _E(404, "NOT_FOUND", "Unknown path.")
    if verb:
        if method != "POST":
            raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
        fn = {"failover": failover_instance, "upgrade": upgrade_instance, "export": export_instance,
              "import": import_instance, "rescheduleMaintenance": reschedule_maintenance}.get(verb)
        if not fn:
            raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
        return _json(200, fn(store, project, location, iid, payload))
    if method == "GET":
        return _json(200, _public(_get(store, project, location, iid)))
    if method in ("PATCH", "PUT"):
        return _json(200, patch_instance(store, project, location, iid, payload, query.get("updateMask") or ""))
    if method == "DELETE":
        return _json(200, delete_instance(store, project, location, iid))
    raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on instance." % method)


def _operations(store, method, project, location, rest, verb):
    if not rest:
        if method == "GET":
            pre = "projects/%s/locations/%s/operations/" % (project, location)
            ops = [o for n, o in sorted(store.operations.items())
                   if n.startswith(pre) or (location == "-" and n.startswith("projects/%s/locations/" % project))]
            return _json(200, {"operations": _copy(ops)} if ops else {})
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
    name, op = _get_op(store, project, location, rest[0])
    if verb == "cancel" and method == "POST":
        raise _E(400, "FAILED_PRECONDITION", "Operation %s is already done and cannot be cancelled." % name)
    if verb:
        raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
    if method == "GET":
        return _json(200, _copy(op))
    if method == "DELETE":
        del store.operations[name]
        return _json(200, {})
    raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)


def dispatch_shared_operations(store, other, method, path, query=None, headers=None, body=b""):
    """`projects/*/locations/*/operations` is one URL family shared with Kubernetes Engine (and the
    Functions stub). `other` is that service's dispatch callable; a collection GET merges both
    services' operations, a single-operation request goes to whoever owns the id."""
    query = query or {}
    r1 = other(method, path, query, headers or {}, body)
    p = path.split("?", 1)[0].rstrip("/")
    is_collection = p.endswith("/operations")
    if method.upper() == "GET" and is_collection:
        r2 = dispatch(store, method, path, query, headers or {}, body)
        ops = []
        for r in (r1, r2):
            if r.status == 200:
                ops += json.loads(r.body or b"{}").get("operations", [])
        out = {"operations": ops} if ops else {}
        return RedisResponse(status=200, body=json.dumps(out).encode())
    if r1.status == 404:
        return dispatch(store, method, path, query, headers or {}, body)
    return r1
