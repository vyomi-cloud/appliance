# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Compute Engine core — substrate-independent. Speaks the native **Compute Engine
REST API v1** (`compute.googleapis.com/v1`) so `google-cloud-compute` / `googleapis-common`
clients and `gcloud compute ...` work unchanged against it (point them at the relay).

NO fastapi / docker / subprocess / socket imports → loads under Pyodide, so the SAME file
runs offline and in Nano, like every other core. This models the Compute Engine *control
plane* only: instance/disk/image/template/group/health-check lifecycle, state and metadata.
No guest OS boots behind an instance — there is nothing to SSH into (that data plane is not
modeled at any tier, exactly like Kubernetes Engine's cluster endpoint in gcp_container_core);
the console says so via the "Connect" column / SSH action.

Resources (v1 discovery doc, subset the v4 console needs):
    projects/{p}/zones/{z}/instances/{i}            projects/{p}/zones/{z}/disks/{d}
    projects/{p}/global/images/{i}                  projects/{p}/global/snapshots/{s}
    projects/{p}/global/machineImages/{m}           projects/{p}/global/instanceTemplates/{t}
    projects/{p}/zones/{z}/instanceGroups/{g}        projects/{p}/global/healthChecks/{h}
    projects/{p}/zones/{z}/instanceGroupManagers/{g} projects/{p}/zones/{z}/operations/{o}
    projects/{p}/global/operations/{o}
    projects/{p}/zones, projects/{p}/regions, projects/{p}/zones/{z}/machineTypes (catalog)
    projects/{p} (project resource incl. commonInstanceMetadata)
Methods: insert/get/list/delete/aggregatedList per collection, instances.start/stop/suspend/
resume/reset/setLabels/setMetadata/setDeletionProtection/setMachineType, disks.createSnapshot,
instanceGroups.addInstances/removeInstances/listInstances, instanceGroupManagers.resize/
listManagedInstances/patch (member instances are really created/deleted from the instance
template; resize always uses it, and patch(updatePolicy.type=PROACTIVE) rolling-replaces
every existing member honoring maxSurge/maxUnavailable — the OPPORTUNISTIC default only
changes the template for members created afterwards, like the real API. Autoscaling policies
are not modeled — there's no real load for one to react to), projects.setCommonInstanceMetadata.
Every mutation returns a completed `Operation` (status DONE) like a very fast real cloud;
errors use the Google JSON shape `{"error":{"code","message","status"}}` (the same
simplification gcp_cloudsql_core and gcp_container_core use for these older-style APIs).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.instance_catalog import GCP as MACHINE_SHAPES

RUNNING, PROVISIONING, STAGING, STOPPING, TERMINATED, SUSPENDING, SUSPENDED, REPAIRING = (
    "RUNNING", "PROVISIONING", "STAGING", "STOPPING", "TERMINATED", "SUSPENDING", "SUSPENDED", "REPAIRING")
DISK_READY, DISK_CREATING, DISK_FAILED = "READY", "CREATING", "FAILED"

ZONES = [
    ("us-central1-a", "us-central1"), ("us-central1-b", "us-central1"), ("us-central1-c", "us-central1"),
    ("us-east1-b", "us-east1"), ("us-east1-c", "us-east1"), ("us-east1-d", "us-east1"),
    ("us-east4-a", "us-east4"), ("us-east4-b", "us-east4"), ("us-east4-c", "us-east4"),
    ("us-west1-a", "us-west1"), ("us-west1-b", "us-west1"), ("us-west1-c", "us-west1"),
    ("europe-west1-b", "europe-west1"), ("europe-west1-c", "europe-west1"), ("europe-west1-d", "europe-west1"),
    ("europe-west4-a", "europe-west4"), ("europe-west4-b", "europe-west4"), ("europe-west4-c", "europe-west4"),
    ("asia-east1-a", "asia-east1"), ("asia-east1-b", "asia-east1"), ("asia-east1-c", "asia-east1"),
    ("asia-southeast1-a", "asia-southeast1"), ("asia-southeast1-b", "asia-southeast1"), ("asia-southeast1-c", "asia-southeast1"),
    ("asia-northeast1-a", "asia-northeast1"), ("asia-northeast1-b", "asia-northeast1"), ("asia-northeast1-c", "asia-northeast1"),
]
ZONE_NAMES = [z for z, _ in ZONES]
REGIONS = sorted({r for _, r in ZONES})
ZONE_REGION = dict(ZONES)
DEFAULT_ZONE, DEFAULT_REGION = "us-central1-a", "us-central1"
CPU_PLATFORMS = ["Intel Broadwell", "Intel Skylake", "Intel Cascade Lake", "Intel Ice Lake", "AMD Rome", "AMD Milan"]
DISK_TYPES = ["pd-balanced", "pd-extreme", "pd-ssd", "pd-standard", "hyperdisk-balanced", "hyperdisk-throughput", "hyperdisk-extreme"]
DEFAULT_DISK_TYPE, DEFAULT_DISK_GB = "pd-balanced", 10
HEALTH_CHECK_TYPES = ("TCP", "HTTP", "HTTPS", "SSL", "HTTP2", "GRPC")

_NAME = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")


# ── store ────────────────────────────────────────────────────────────────────
class ComputeStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.instances: dict = {}          # "projects/p/zones/z/instances/n" -> resource
        self.disks: dict = {}              # "projects/p/zones/z/disks/n" -> resource
        self.images: dict = {}             # "projects/p/global/images/n" -> resource
        self.snapshots: dict = {}          # "projects/p/global/snapshots/n" -> resource
        self.machine_images: dict = {}     # "projects/p/global/machineImages/n" -> resource
        self.instance_templates: dict = {}  # "projects/p/global/instanceTemplates/n" -> resource
        self.instance_groups: dict = {}    # "projects/p/zones/z/instanceGroups/n" -> resource
        self.instance_group_managers: dict = {}  # "projects/p/zones/z/instanceGroupManagers/n" -> resource
        self.health_checks: dict = {}      # "projects/p/global/healthChecks/n" -> resource
        self.operations: dict = {}         # "projects/p/(zones/z|global)/operations/n" -> resource
        self.project_metadata: dict = {}   # project -> commonInstanceMetadata
        self.seq = {"op": 0, "id": 1000}


_SHARED: ComputeStore | None = None


def shared_store() -> ComputeStore:
    global _SHARED
    if _SHARED is None:
        _SHARED = ComputeStore()
    return _SHARED


@dataclass
class ComputeResponse:
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
    return ComputeResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return ComputeResponse(status=status, body=json.dumps(obj).encode())


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _copy(x):
    return json.loads(json.dumps(x))


def _next_id(store):
    store.seq["id"] += 1
    return str(store.seq["id"])


def _selflink(tail):
    return "https://compute.googleapis.com/compute/v1/%s" % tail


def _last(url_or_name):
    return str(url_or_name or "").rstrip("/").rsplit("/", 1)[-1]


def _region_of(zone):
    return ZONE_REGION.get(zone, zone.rsplit("-", 1)[0] if zone else zone)


def _check_name(name, what="name"):
    if not name or not _NAME.match(name):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field '%s': %r. Must be 1-63 characters, start with a "
                                           "lowercase letter, and contain only lowercase letters, numbers and hyphens." % (what, name))


def _fingerprint(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def _synthetic_ip(prefix, name):
    h = hashlib.sha256(name.encode()).digest()
    need = 3 - prefix.count(".")           # fill the address out to four octets
    return ".".join([prefix] + [str(h[i] % 254 + 1) for i in range(need)])


# ── operations ───────────────────────────────────────────────────────────────
def _operation(store, project, scope, op_type, target_name, target_link, user="vyomi-console-ui@vyomi.local"):
    """`scope` is a zone name, a region name, or None (global)."""
    store.seq["op"] += 1
    oid = "operation-%d-%s" % (store.seq["op"], hashlib.sha1(("%s%d" % (target_link, store.seq["op"])).encode()).hexdigest()[:10])
    loc = "zones/%s" % scope if scope in ZONE_REGION else ("regions/%s" % scope if scope else "global")
    full = "projects/%s/%s/operations/%s" % (project, loc, oid)
    now = _ts()
    op = {
        "id": _next_id(store), "name": oid, "operationType": op_type, "status": "DONE", "progress": 100,
        "user": user, "targetId": _next_id(store), "targetLink": target_link,
        "selfLink": _selflink(full), "insertTime": now, "startTime": now, "endTime": now,
        "kind": "compute#operation",
    }
    if scope in ZONE_REGION:
        op["zone"] = _selflink("projects/%s/zones/%s" % (project, scope))
    elif scope:
        op["region"] = _selflink("projects/%s/regions/%s" % (project, scope))
    store.operations[full] = op
    return op


# ── zones / regions / machine types ─────────────────────────────────────────
def zone_view(project, zone, instance_count):
    return {
        # Zone.id is a uint64 (strict clients — gcloud's apitools — reject a name here)
        "id": str(int(hashlib.sha1(zone.encode()).hexdigest()[:12], 16)), "kind": "compute#zone",
        "name": zone, "description": zone,
        "status": "UP", "region": _selflink("projects/%s/regions/%s" % (project, ZONE_REGION[zone])),
        "region_name": ZONE_REGION[zone], "availableCpuPlatforms": list(CPU_PLATFORMS),
        "selfLink": _selflink("projects/%s/zones/%s" % (project, zone)),
        "instance_count": instance_count,
    }


def list_zones(store, project):
    counts = {}
    for n, i in store.instances.items():
        if n.startswith("projects/%s/zones/" % project):
            counts[i["_zone"]] = counts.get(i["_zone"], 0) + 1
    return [zone_view(project, z, counts.get(z, 0)) for z in ZONE_NAMES]


def list_regions(project):
    return [{"id": str(int(hashlib.sha1(r.encode()).hexdigest()[:12], 16)), "kind": "compute#region", "name": r, "description": r, "status": "UP",
              "zones": [_selflink("projects/%s/zones/%s" % (project, z)) for z, rr in ZONES if rr == r],
              "selfLink": _selflink("projects/%s/regions/%s" % (project, r))} for r in REGIONS]


def machine_type_view(project, zone, name):
    shape = MACHINE_SHAPES.get(name)
    if not shape:
        return None
    family = name.split("-")[0].upper()
    return {
        "id": str(int(hashlib.sha1(name.encode()).hexdigest()[:6], 16)), "kind": "compute#machineType", "name": name,
        "description": "%s machine type with %d vCPUs and %s GB of memory" % (family, shape["vcpu"], round(shape["ram_mb"] / 1024, 2)),
        "guestCpus": shape["vcpu"], "memoryMb": shape["ram_mb"], "zone": zone, "isSharedCpu": shape["family"] == "burstable",
        "selfLink": _selflink("projects/%s/zones/%s/machineTypes/%s" % (project, zone, name)),
    }


def list_machine_types(project, zone):
    return [v for v in (machine_type_view(project, zone, n) for n in MACHINE_SHAPES) if v]


# ── views ────────────────────────────────────────────────────────────────────
def instance_view(store, project, full):
    i = store.instances[full]
    v = _copy({k: x for k, x in i.items() if not k.startswith("_")})
    disks_in = v.get("disks", [])
    boot = next((d for d in disks_in if d.get("boot")), None)
    v["_display"] = {
        "project": project, "zone": i["_zone"], "resourceName": _last(full),
        "internalIp": i.get("_internalIp"), "externalIp": i.get("_externalIp"),
        "bootDiskName": _last(boot["source"]) if boot else None,
        "machineTypeName": _last(i.get("machineType")),
    }
    return v


def disk_view(store, project, full):
    d = store.disks[full]
    v = _copy({k: x for k, x in d.items() if not k.startswith("_")})
    users = [_last(u) for u in v.get("users", [])]
    v["_display"] = {"project": project, "zone": d["_zone"], "inUseBy": ", ".join(users) if users else None}
    return v


def _attached_users(store, project, disk_name, zone):
    full_disk = "projects/%s/zones/%s/disks/%s" % (project, zone, disk_name)
    out = []
    for n, i in store.instances.items():
        if i["_zone"] != zone:
            continue
        for d in i.get("disks", []):
            if _last(d.get("source", "")) == disk_name:
                out.append(n)
    return out


def list_all(d: dict, prefix: str):
    return [n for n in sorted(d) if n.startswith(prefix)]


# ── name validation / lookups ────────────────────────────────────────────────
def _get(store, bucket: dict, full, kind):
    r = bucket.get(full)
    if not r:
        raise _E(404, "NOT_FOUND", "The resource '%s' was not found." % full)
    return r


def _mt_full(project, zone, machine_type):
    name = _last(machine_type)
    return name, _selflink("projects/%s/zones/%s/machineTypes/%s" % (project, zone, name))


# ── instances ────────────────────────────────────────────────────────────────
def insert_instance(store, project, zone, payload):
    if zone not in ZONE_REGION:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'zone': %r." % zone)
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/zones/%s/instances/%s" % (project, zone, name)
    if full in store.instances:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    mt_name, mt_link = _mt_full(project, zone, payload.get("machineType") or "e2-medium")
    if mt_name not in MACHINE_SHAPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'machineType': %r." % mt_name)
    now = _ts()
    disks_in = payload.get("disks") or []
    disks_out = []
    for idx, d in enumerate(disks_in):
        boot = bool(d.get("boot")) or idx == 0
        if d.get("source"):
            dname = _last(d["source"])
            dfull = "projects/%s/zones/%s/disks/%s" % (project, zone, dname)
            if dfull not in store.disks:
                raise _E(400, "INVALID_ARGUMENT", "The disk resource '%s' was not found." % dfull)
        else:
            ip = d.get("initializeParams") or {}
            dname = ip.get("diskName") or "%s" % name
            dfull = "projects/%s/zones/%s/disks/%s" % (project, zone, dname)
            if dfull not in store.disks:
                _insert_disk_record(store, project, zone, dname, {
                    "sizeGb": str(ip.get("diskSizeGb") or DEFAULT_DISK_GB),
                    "type": ip.get("diskType") or DEFAULT_DISK_TYPE,
                    "sourceImage": ip.get("sourceImage"),
                }, source_detail="From instance %s" % name)
        source_link = _selflink(dfull)
        disks_out.append({
            "boot": boot, "autoDelete": d.get("autoDelete", True), "source": source_link,
            "deviceName": d.get("deviceName") or dname, "mode": d.get("mode") or "READ_WRITE",
            "type": "PERSISTENT", "diskSizeGb": store.disks[dfull]["sizeGb"], "index": idx,
            "interface": d.get("interface") or "SCSI",
        })
        store.disks[dfull]["users"] = store.disks[dfull].get("users", []) + [_selflink(full)]
    if not disks_out:
        raise _E(400, "INVALID_ARGUMENT", "At least one disk is required (boot disk).")
    nis_in = payload.get("networkInterfaces") or [{}]
    nis_out = []
    internal_ip = external_ip = None
    for ni in nis_in:
        internal_ip = ni.get("networkIP") or _synthetic_ip("10.128", full)
        net = ni.get("network") or _selflink("projects/%s/global/networks/default" % project)
        sub = ni.get("subnetwork") or _selflink("projects/%s/regions/%s/subnetworks/default" % (project, _region_of(zone)))
        access = ni.get("accessConfigs")
        out_ni = {"name": "nic0", "network": net, "subnetwork": sub, "networkIP": internal_ip,
                  "stackType": "IPV4_ONLY", "fingerprint": _fingerprint(ni)}
        if access is None:
            external_ip = _synthetic_ip("34.72", full + "x")
            out_ni["accessConfigs"] = [{"type": "ONE_TO_ONE_NAT", "name": "External NAT", "natIP": external_ip, "networkTier": "PREMIUM"}]
        elif access:
            external_ip = _synthetic_ip("34.72", full + "x")
            out_ni["accessConfigs"] = [{**a, "natIP": a.get("natIP") or external_ip} for a in access]
        nis_out.append(out_ni)
    labels = payload.get("labels") or {}
    tags = payload.get("tags") or {}
    scheduling = dict({"automaticRestart": True, "onHostMaintenance": "MIGRATE", "provisioningModel": "STANDARD"}, **(payload.get("scheduling") or {}))
    inst = {
        "id": _next_id(store), "name": name, "description": payload.get("description", ""),
        "kind": "compute#instance", "zone": _selflink("projects/%s/zones/%s" % (project, zone)),
        "machineType": mt_link, "status": RUNNING, "statusMessage": "",
        "creationTimestamp": now, "lastStartTimestamp": now,
        "disks": disks_out, "networkInterfaces": nis_out,
        "labels": labels, "labelFingerprint": _fingerprint(labels),
        "tags": {"items": tags.get("items", []), "fingerprint": _fingerprint(tags)},
        "metadata": {"items": (payload.get("metadata") or {}).get("items", []), "fingerprint": _fingerprint(payload.get("metadata") or {})},
        "serviceAccounts": payload.get("serviceAccounts") or [{"email": "default", "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}],
        "scheduling": scheduling,
        "deletionProtection": bool(payload.get("deletionProtection", False)),
        "shieldedInstanceConfig": dict({"enableSecureBoot": False, "enableVtpm": True, "enableIntegrityMonitoring": True}, **(payload.get("shieldedInstanceConfig") or {})),
        "cpuPlatform": "Intel Broadwell", "startRestricted": False, "hostname": payload.get("hostname") or None,
        "canIpForward": bool(payload.get("canIpForward", False)),
        "selfLink": _selflink(full), "_zone": zone, "_internalIp": internal_ip, "_externalIp": external_ip,
    }
    store.instances[full] = inst
    return _operation(store, project, zone, "insert", name, _selflink(full))


def _instance(store, project, zone, name):
    full = "projects/%s/zones/%s/instances/%s" % (project, zone, name)
    return full, _get(store, store.instances, full, "instance")


def get_instance(store, project, zone, name):
    full, _ = _instance(store, project, zone, name)
    return _json(200, instance_view(store, project, full))


def list_instances(store, project, zone, filter_project=True):
    prefix = "projects/%s/zones/%s/instances/" % (project, zone)
    return [instance_view(store, project, n) for n in list_all(store.instances, prefix)]


def aggregated_instances(store, project):
    out = {}
    for zone in ZONE_NAMES:
        items = list_instances(store, project, zone)
        key = "zones/%s" % zone
        out[key] = {"instances": items} if items else {"warning": {"code": "NO_RESULTS_ON_PAGE", "message": "There are no results for scope '%s' on this page." % key}}
    return {"kind": "compute#instanceAggregatedList", "items": out, "id": "projects/%s/aggregated/instances" % project}


def _require_state(inst, allowed, action):
    if inst["status"] not in allowed:
        raise _E(400, "CONDITION_NOT_MET", "The instance is in state %s, which does not permit '%s' (requires %s)." % (inst["status"], action, "/".join(allowed)))


def set_instance_status(store, project, zone, name, action):
    full, inst = _instance(store, project, zone, name)
    table = {
        "start": ((TERMINATED,), RUNNING), "resume": ((SUSPENDED,), RUNNING),
        "stop": ((RUNNING, STAGING, PROVISIONING, REPAIRING), TERMINATED),
        "suspend": ((RUNNING,), SUSPENDED), "reset": ((RUNNING,), RUNNING),
    }
    allowed, new_status = table[action]
    _require_state(inst, allowed, action)
    inst["status"] = new_status
    if action == "start" or action == "resume":
        inst["lastStartTimestamp"] = _ts()
    if action in ("stop", "suspend"):
        inst["lastStopTimestamp"] = _ts()
    return _operation(store, project, zone, action, name, _selflink(full))


def delete_instance(store, project, zone, name):
    full, inst = _instance(store, project, zone, name)
    if inst.get("deletionProtection"):
        raise _E(400, "FAILED_PRECONDITION", "The instance '%s' has deletionProtection enabled; disable it before deleting." % name)
    for d in inst.get("disks", []):
        dfull = "projects/%s/zones/%s/disks/%s" % (project, zone, _last(d["source"]))
        disk = store.disks.get(dfull)
        if disk:
            disk["users"] = [u for u in disk.get("users", []) if _last(u) != name]
            if d.get("autoDelete") and not disk["users"]:
                del store.disks[dfull]
    del store.instances[full]
    return _operation(store, project, zone, "delete", name, _selflink(full))


def set_instance_field(store, project, zone, name, verb, payload):
    full, inst = _instance(store, project, zone, name)
    if verb == "setLabels":
        inst["labels"] = payload.get("labels") or {}
        inst["labelFingerprint"] = _fingerprint(inst["labels"])
    elif verb == "setMetadata":
        inst["metadata"] = {"items": payload.get("items") or [], "fingerprint": _fingerprint(payload)}
    elif verb == "setDeletionProtection":
        inst["deletionProtection"] = bool(payload.get("deletionProtection", True))
    elif verb == "setMachineType":
        _require_state(inst, (TERMINATED,), "setMachineType")
        mt_name, mt_link = _mt_full(project, zone, (payload.get("machineType") or ""))
        if mt_name not in MACHINE_SHAPES:
            raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'machineType': %r." % mt_name)
        inst["machineType"] = mt_link
    elif verb == "setTags":
        inst["tags"] = {"items": payload.get("items") or [], "fingerprint": _fingerprint(payload)}
    else:
        raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)
    return _operation(store, project, zone, verb, name, _selflink(full))


# ── disks ────────────────────────────────────────────────────────────────────
def _insert_disk_record(store, project, zone, name, spec, source_detail=None):
    full = "projects/%s/zones/%s/disks/%s" % (project, zone, name)
    now = _ts()
    disk = {
        "id": _next_id(store), "name": name, "kind": "compute#disk", "status": DISK_READY,
        "zone": _selflink("projects/%s/zones/%s" % (project, zone)), "sizeGb": str(spec.get("sizeGb") or DEFAULT_DISK_GB),
        "type": _selflink("projects/%s/zones/%s/diskTypes/%s" % (project, zone, spec.get("type") or DEFAULT_DISK_TYPE)),
        "sourceImage": spec.get("sourceImage"), "sourceSnapshot": spec.get("sourceSnapshot"),
        "architecture": "X86_64", "creationTimestamp": now, "labels": spec.get("labels") or {},
        "users": [], "physicalBlockSizeBytes": "4096", "_zone": zone, "_sourceDetail": source_detail,
        "selfLink": _selflink(full),
    }
    store.disks[full] = disk
    return full, disk


def insert_disk(store, project, zone, payload):
    if zone not in ZONE_REGION:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'zone': %r." % zone)
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/zones/%s/disks/%s" % (project, zone, name)
    if full in store.disks:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    dtype = _last(payload.get("type") or DEFAULT_DISK_TYPE)
    if dtype not in DISK_TYPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'type': %r." % dtype)
    _insert_disk_record(store, project, zone, name, {
        "sizeGb": payload.get("sizeGb") or DEFAULT_DISK_GB, "type": dtype,
        "sourceImage": payload.get("sourceImage"), "sourceSnapshot": payload.get("sourceSnapshot"),
        "labels": payload.get("labels"),
    })
    return _operation(store, project, zone, "insert", name, _selflink(full))


def _disk(store, project, zone, name):
    full = "projects/%s/zones/%s/disks/%s" % (project, zone, name)
    return full, _get(store, store.disks, full, "disk")


def get_disk(store, project, zone, name):
    full, _ = _disk(store, project, zone, name)
    return _json(200, disk_view(store, project, full))


def list_disks(store, project, zone):
    prefix = "projects/%s/zones/%s/disks/" % (project, zone)
    return [disk_view(store, project, n) for n in list_all(store.disks, prefix)]


def aggregated_disks(store, project):
    out = {}
    for zone in ZONE_NAMES:
        items = list_disks(store, project, zone)
        key = "zones/%s" % zone
        out[key] = {"disks": items} if items else {"warning": {"code": "NO_RESULTS_ON_PAGE", "message": "no results"}}
    return {"kind": "compute#diskAggregatedList", "items": out, "id": "projects/%s/aggregated/disks" % project}


def delete_disk(store, project, zone, name):
    full, disk = _disk(store, project, zone, name)
    if disk.get("users"):
        raise _E(400, "RESOURCE_IN_USE_BY_ANOTHER_RESOURCE", "The disk resource '%s' is already being used by '%s'." % (name, disk["users"][0]))
    del store.disks[full]
    return _operation(store, project, zone, "delete", name, _selflink(full))


def create_snapshot(store, project, zone, disk_name, payload):
    _, disk = _disk(store, project, zone, disk_name)
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/global/snapshots/%s" % (project, name)
    if full in store.snapshots:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    now = _ts()
    snap = {
        "id": _next_id(store), "name": name, "kind": "compute#snapshot", "status": "READY",
        "sourceDisk": _selflink("projects/%s/zones/%s/disks/%s" % (project, zone, disk_name)),
        "diskSizeGb": disk["sizeGb"], "storageBytes": str(int(disk["sizeGb"]) * 1024 * 1024 * 50),
        "snapshotType": "STANDARD", "creationTimestamp": now, "labels": payload.get("labels") or {},
        "selfLink": _selflink(full), "storageLocations": [ZONE_REGION[zone]],
    }
    store.snapshots[full] = snap
    return _operation(store, project, None, "insert", name, _selflink(full))


def snapshot_view(store, full):
    s = store.snapshots[full]
    v = _copy(s)
    v["_display"] = {"location": v.get("storageLocations", [None])[0], "sourceDiskName": _last(v.get("sourceDisk", ""))}
    return v


def list_snapshots(store, project):
    return [snapshot_view(store, n) for n in list_all(store.snapshots, "projects/%s/global/snapshots/" % project)]


def get_snapshot(store, project, name):
    full = "projects/%s/global/snapshots/%s" % (project, name)
    _get(store, store.snapshots, full, "snapshot")
    return _json(200, snapshot_view(store, full))


def delete_snapshot(store, project, name):
    full = "projects/%s/global/snapshots/%s" % (project, name)
    _get(store, store.snapshots, full, "snapshot")
    del store.snapshots[full]
    return _operation(store, project, None, "delete", name, _selflink(full))


# ── images ───────────────────────────────────────────────────────────────────
def insert_image(store, project, payload):
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/global/images/%s" % (project, name)
    if full in store.images:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    src_disk = payload.get("sourceDisk")
    src_image = payload.get("sourceImage")
    disk_size = 10
    if src_disk:
        d = store.disks.get("projects/%s/zones/%s/disks/%s" % (project, _last(payload.get("sourceDiskZone") or ""), _last(src_disk))
                             if payload.get("sourceDiskZone") else None)
        if not d:
            for full_d, dd in store.disks.items():
                if full_d.endswith("/disks/%s" % _last(src_disk)):
                    d = dd
                    break
        if d:
            disk_size = int(d["sizeGb"])
    now = _ts()
    img = {
        "id": _next_id(store), "name": name, "kind": "compute#image", "status": "READY",
        "sourceDisk": src_disk, "sourceImage": src_image, "diskSizeGb": str(payload.get("diskSizeGb") or disk_size),
        "archiveSizeBytes": str(int(payload.get("diskSizeGb") or disk_size) * 1024 * 1024 * 40),
        "family": payload.get("family", ""), "description": payload.get("description", ""),
        "creationTimestamp": now, "labels": payload.get("labels") or {},
        "selfLink": _selflink(full), "storageLocations": [ZONE_REGION.get(DEFAULT_ZONE, "us")],
    }
    store.images[full] = img
    return _operation(store, project, None, "insert", name, _selflink(full))


def image_view(store, full):
    v = _copy(store.images[full])
    v["_display"] = {"location": v.get("storageLocations", [None])[0], "createdBy": "you"}
    return v


def list_images(store, project):
    return [image_view(store, n) for n in list_all(store.images, "projects/%s/global/images/" % project)]


def get_image(store, project, name):
    full = "projects/%s/global/images/%s" % (project, name)
    _get(store, store.images, full, "image")
    return _json(200, image_view(store, full))


def delete_image(store, project, name):
    full = "projects/%s/global/images/%s" % (project, name)
    _get(store, store.images, full, "image")
    del store.images[full]
    return _operation(store, project, None, "delete", name, _selflink(full))


# ── machine images ───────────────────────────────────────────────────────────
def insert_machine_image(store, project, payload):
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/global/machineImages/%s" % (project, name)
    if full in store.machine_images:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    src = payload.get("sourceInstance") or ""
    src_name, src_zone = _last(src), None
    total_bytes = 0
    for zone, _ in ZONES:
        f = "projects/%s/zones/%s/instances/%s" % (project, zone, src_name)
        if f in store.instances:
            src_zone = zone
            for d in store.instances[f].get("disks", []):
                total_bytes += int(d.get("diskSizeGb") or 10) * 1024 * 1024 * 1024
            break
    if not src_zone:
        raise _E(400, "INVALID_ARGUMENT", "Source instance '%s' was not found." % src_name)
    now = _ts()
    mi = {
        "id": _next_id(store), "name": name, "kind": "compute#machineImage", "status": "READY",
        "sourceInstance": _selflink("projects/%s/zones/%s/instances/%s" % (project, src_zone, src_name)),
        "totalStorageBytes": str(total_bytes), "creationTimestamp": now,
        "description": payload.get("description", ""), "selfLink": _selflink(full),
        "storageLocations": [ZONE_REGION[src_zone]],
    }
    store.machine_images[full] = mi
    return _operation(store, project, None, "insert", name, _selflink(full))


def list_machine_images(store, project):
    out = []
    for n in list_all(store.machine_images, "projects/%s/global/machineImages/" % project):
        v = _copy(store.machine_images[n])
        v["_display"] = {"location": v.get("storageLocations", [None])[0], "sourceInstanceName": _last(v.get("sourceInstance", ""))}
        out.append(v)
    return out


def get_machine_image(store, project, name):
    full = "projects/%s/global/machineImages/%s" % (project, name)
    v = _get(store, store.machine_images, full, "machineImage")
    return _json(200, v)


def delete_machine_image(store, project, name):
    full = "projects/%s/global/machineImages/%s" % (project, name)
    _get(store, store.machine_images, full, "machineImage")
    del store.machine_images[full]
    return _operation(store, project, None, "delete", name, _selflink(full))


# ── instance templates ───────────────────────────────────────────────────────
def insert_instance_template(store, project, payload):
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/global/instanceTemplates/%s" % (project, name)
    if full in store.instance_templates:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    props = payload.get("properties") or {}
    mt_name = _last(props.get("machineType") or "e2-medium")
    if mt_name not in MACHINE_SHAPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'machineType': %r." % mt_name)
    now = _ts()
    tpl = {
        "id": _next_id(store), "name": name, "kind": "compute#instanceTemplate",
        "properties": {
            "machineType": mt_name, "disks": props.get("disks") or [], "networkInterfaces": props.get("networkInterfaces") or [],
            "labels": props.get("labels") or {}, "description": props.get("description", ""),
        },
        "description": payload.get("description", ""), "creationTimestamp": now, "selfLink": _selflink(full),
    }
    store.instance_templates[full] = tpl
    return _operation(store, project, None, "insert", name, _selflink(full))


def list_instance_templates(store, project):
    out = []
    for n in list_all(store.instance_templates, "projects/%s/global/instanceTemplates/" % project):
        v = _copy(store.instance_templates[n])
        disks = v["properties"].get("disks") or []
        boot = next((d for d in disks if d.get("boot")), None)
        ip = (boot or {}).get("initializeParams") or {}
        v["_display"] = {"machineType": v["properties"]["machineType"], "imageName": _last(ip.get("sourceImage", "")) or "—",
                          "diskType": _last(ip.get("diskType", "")) or DEFAULT_DISK_TYPE}
        out.append(v)
    return out


def get_instance_template(store, project, name):
    full = "projects/%s/global/instanceTemplates/%s" % (project, name)
    v = _get(store, store.instance_templates, full, "instanceTemplate")
    return _json(200, v)


def delete_instance_template(store, project, name):
    full = "projects/%s/global/instanceTemplates/%s" % (project, name)
    _get(store, store.instance_templates, full, "instanceTemplate")
    del store.instance_templates[full]
    return _operation(store, project, None, "delete", name, _selflink(full))


# ── instance groups (unmanaged) ──────────────────────────────────────────────
def insert_instance_group(store, project, zone, payload):
    if zone not in ZONE_REGION:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'zone': %r." % zone)
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/zones/%s/instanceGroups/%s" % (project, zone, name)
    if full in store.instance_groups:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    now = _ts()
    grp = {
        "id": _next_id(store), "name": name, "kind": "compute#instanceGroup", "zone": _selflink("projects/%s/zones/%s" % (project, zone)),
        "description": payload.get("description", ""), "network": payload.get("network") or _selflink("projects/%s/global/networks/default" % project),
        "size": 0, "creationTimestamp": now, "selfLink": _selflink(full), "members": [], "_zone": zone,
    }
    store.instance_groups[full] = grp
    return _operation(store, project, zone, "insert", name, _selflink(full))


def _group(store, project, zone, name):
    full = "projects/%s/zones/%s/instanceGroups/%s" % (project, zone, name)
    return full, _get(store, store.instance_groups, full, "instanceGroup")


def group_members(store, project, zone, name):
    _, g = _group(store, project, zone, name)
    links = []
    for m in g["members"]:
        f = "projects/%s/zones/%s/instances/%s" % (project, zone, m)
        if f in store.instances:
            links.append({"instance": _selflink(f), "status": store.instances[f]["status"]})
    return links


def add_group_instances(store, project, zone, name, payload):
    full, g = _group(store, project, zone, name)
    added = 0
    for ref in payload.get("instances") or []:
        iname = _last(ref.get("instance", ""))
        if "projects/%s/zones/%s/instances/%s" % (project, zone, iname) not in store.instances:
            raise _E(400, "INVALID_ARGUMENT", "Instance '%s' was not found." % iname)
        if iname not in g["members"]:
            g["members"].append(iname)
            added += 1
    g["size"] = len(g["members"])
    return _operation(store, project, zone, "addInstances", name, _selflink(full))


def remove_group_instances(store, project, zone, name, payload):
    full, g = _group(store, project, zone, name)
    for ref in payload.get("instances") or []:
        iname = _last(ref.get("instance", ""))
        if iname in g["members"]:
            g["members"].remove(iname)
    g["size"] = len(g["members"])
    return _operation(store, project, zone, "removeInstances", name, _selflink(full))


def list_instance_groups(store, project, zone):
    out = []
    for n in list_all(store.instance_groups, "projects/%s/zones/%s/instanceGroups/" % (project, zone)):
        g = store.instance_groups[n]
        if g.get("_managed"):   # the backing group of a managed instance group — not in the unmanaged list
            continue
        v = _copy({k: x for k, x in g.items() if not k.startswith("_")})
        out.append(v)
    return out


def aggregated_instance_groups(store, project):
    out = {}
    for zone in ZONE_NAMES:
        items = list_instance_groups(store, project, zone)
        key = "zones/%s" % zone
        out[key] = {"instanceGroups": items} if items else {"warning": {"code": "NO_RESULTS_ON_PAGE", "message": "no results"}}
    return {"kind": "compute#instanceGroupAggregatedList", "items": out, "id": "projects/%s/aggregated/instanceGroups" % project}


def delete_instance_group(store, project, zone, name):
    full, g = _group(store, project, zone, name)
    del store.instance_groups[full]
    return _operation(store, project, zone, "delete", name, _selflink(full))


# ── instance groups (managed) ─────────────────────────────────────────────────
# A managed instance group holds a fixed-size pool of instances stamped out of an instance
# template; resize() creates/deletes real instances to match targetSize, and patch() can
# rolling-replace every member onto a new template (see _rolling_replace_members). Autoscaling
# policies are not modeled — there's no real load for one to react to, exactly like
# gcp.compute.instance_groups.crud declares.
def _mig(store, project, zone, name):
    full = "projects/%s/zones/%s/instanceGroupManagers/%s" % (project, zone, name)
    return full, _get(store, store.instance_group_managers, full, "instanceGroupManager")


def _mig_view(mgr):
    return {k: x for k, x in mgr.items() if not k.startswith("_")}


def _resolve_mig_template(store, project, tpl_ref):
    tpl_name = _last(tpl_ref or "")
    tpl_full = "projects/%s/global/instanceTemplates/%s" % (project, tpl_name)
    tpl = store.instance_templates.get(tpl_full)
    if not tpl:
        raise _E(400, "INVALID_ARGUMENT", "The instance template '%s' was not found." % tpl_name)
    if not any(d.get("initializeParams") or d.get("source") for d in (tpl["properties"].get("disks") or [])):
        raise _E(400, "INVALID_ARGUMENT", "Instance template '%s' has no boot disk configured." % tpl_name)
    return tpl_full


def insert_instance_group_manager(store, project, zone, payload):
    if zone not in ZONE_REGION:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'zone': %r." % zone)
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/zones/%s/instanceGroupManagers/%s" % (project, zone, name)
    if full in store.instance_group_managers:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    base_name = payload.get("baseInstanceName") or name
    _check_name(base_name, "baseInstanceName")
    tpl_full = _resolve_mig_template(store, project, payload.get("instanceTemplate"))
    now = _ts()
    grp_full = "projects/%s/zones/%s/instanceGroups/%s" % (project, zone, name)
    members: list = []
    mgr = {
        "id": _next_id(store), "name": name, "kind": "compute#instanceGroupManager",
        "zone": _selflink("projects/%s/zones/%s" % (project, zone)),
        "baseInstanceName": base_name, "instanceTemplate": _selflink(tpl_full),
        "instanceGroup": _selflink(grp_full), "targetSize": 0,
        "description": payload.get("description", ""), "creationTimestamp": now, "selfLink": _selflink(full),
        "currentActions": {"none": 0, "creating": 0, "deleting": 0, "recreating": 0, "restarting": 0, "refreshing": 0, "abandoning": 0, "creatingWithoutRetries": 0, "verifying": 0},
        "status": {"isStable": True}, "members": members, "_zone": zone, "_seq": 0,
        "updatePolicy": payload.get("updatePolicy") or {"type": "OPPORTUNISTIC", "minimalAction": "REPLACE", "maxSurge": {"fixed": 1}, "maxUnavailable": {"fixed": 0}},
    }
    store.instance_group_managers[full] = mgr
    store.instance_groups[grp_full] = {
        "id": _next_id(store), "name": name, "kind": "compute#instanceGroup",
        "zone": _selflink("projects/%s/zones/%s" % (project, zone)),
        "description": payload.get("description", ""), "network": _selflink("projects/%s/global/networks/default" % project),
        "size": 0, "creationTimestamp": now, "selfLink": _selflink(grp_full), "members": members, "_zone": zone, "_managed": True,
    }
    op = _operation(store, project, zone, "insert", name, _selflink(full))
    target = int(payload.get("targetSize") or 0)
    if target:
        resize_instance_group_manager(store, project, zone, name, target)
    return op


def _create_mig_instance(store, project, zone, mgr):
    tpl_full = "projects/%s/global/instanceTemplates/%s" % (project, _last(mgr["instanceTemplate"]))
    tpl = store.instance_templates.get(tpl_full)
    if not tpl:
        raise _E(400, "INVALID_ARGUMENT", "The instance template '%s' was not found." % _last(mgr["instanceTemplate"]))
    props = tpl["properties"]
    mgr["_seq"] += 1
    suffix = hashlib.sha1(("%s:%d" % (mgr["selfLink"], mgr["_seq"])).encode()).hexdigest()[:4]
    iname = "%s-%s" % (mgr["baseInstanceName"], suffix)
    insert_instance(store, project, zone, {
        "name": iname, "machineType": props.get("machineType"),
        "disks": props.get("disks") or [], "networkInterfaces": props.get("networkInterfaces") or [{}],
        "labels": props.get("labels") or {},
    })
    mgr["members"].append(iname)


def resize_instance_group_manager(store, project, zone, name, new_size):
    full, mgr = _mig(store, project, zone, name)
    new_size = int(new_size or 0)
    if new_size < 0:
        raise _E(400, "INVALID_ARGUMENT", "targetSize must be >= 0.")
    current = len(mgr["members"])
    if new_size > current:
        for _ in range(current, new_size):
            _create_mig_instance(store, project, zone, mgr)
    elif new_size < current:
        for _ in range(new_size, current):
            iname = mgr["members"].pop()
            ifull = "projects/%s/zones/%s/instances/%s" % (project, zone, iname)
            if ifull in store.instances:
                delete_instance(store, project, zone, iname)
    mgr["targetSize"] = new_size
    grp = store.instance_groups.get("projects/%s/zones/%s/instanceGroups/%s" % (project, zone, name))
    if grp:
        grp["size"] = len(mgr["members"])
    return _operation(store, project, zone, "resize", name, _selflink(full))


def _rolling_replace_members(store, project, zone, mgr):
    """Replace every current member with a fresh instance stamped from the manager's
    CURRENT instance template, batching the create-then-retire sequence by
    updatePolicy.maxSurge/maxUnavailable — what instanceGroupManagers.patch(updatePolicy.
    type=PROACTIVE) drives on the real API (gcloud's `rolling-action start-update` /
    the console's "Apply to all instances now"). OPPORTUNISTIC patches never call this —
    only new members (created by a later resize) pick up the new template, exactly like
    the real default."""
    policy = mgr.get("updatePolicy") or {}
    surge = int((policy.get("maxSurge") or {}).get("fixed", 1) or 0)
    unavailable = int((policy.get("maxUnavailable") or {}).get("fixed", 0) or 0)
    batch_size = max(surge, unavailable, 1)
    stale = list(mgr["members"])
    i = 0
    while i < len(stale):
        batch = stale[i:i + batch_size]
        for _ in range(min(surge, len(batch))):
            _create_mig_instance(store, project, zone, mgr)
        for old_name in batch:
            if old_name in mgr["members"]:
                mgr["members"].remove(old_name)
                ifull = "projects/%s/zones/%s/instances/%s" % (project, zone, old_name)
                if ifull in store.instances:
                    delete_instance(store, project, zone, old_name)
            if not surge:
                _create_mig_instance(store, project, zone, mgr)
        i += len(batch)
    mgr["targetSize"] = len(mgr["members"])
    grp = store.instance_groups.get("projects/%s/zones/%s/instanceGroups/%s" % (project, zone, mgr["name"]))
    if grp:
        grp["size"] = len(mgr["members"])


def patch_instance_group_manager(store, project, zone, name, payload):
    full, mgr = _mig(store, project, zone, name)
    if "instanceTemplate" in payload:
        mgr["instanceTemplate"] = _selflink(_resolve_mig_template(store, project, payload["instanceTemplate"]))
    if "updatePolicy" in payload:
        mgr["updatePolicy"] = payload["updatePolicy"]
    if (mgr.get("updatePolicy") or {}).get("type") == "PROACTIVE":
        _rolling_replace_members(store, project, zone, mgr)
    return _operation(store, project, zone, "patch", name, _selflink(full))


def delete_instance_group_manager(store, project, zone, name):
    full, mgr = _mig(store, project, zone, name)
    for iname in list(mgr["members"]):
        ifull = "projects/%s/zones/%s/instances/%s" % (project, zone, iname)
        if ifull in store.instances:
            delete_instance(store, project, zone, iname)
    store.instance_groups.pop("projects/%s/zones/%s/instanceGroups/%s" % (project, zone, name), None)
    del store.instance_group_managers[full]
    return _operation(store, project, zone, "delete", name, _selflink(full))


def list_instance_group_managers(store, project, zone):
    prefix = "projects/%s/zones/%s/instanceGroupManagers/" % (project, zone)
    return [_mig_view(store.instance_group_managers[n]) for n in list_all(store.instance_group_managers, prefix)]


def aggregated_instance_group_managers(store, project):
    out = {}
    for zone in ZONE_NAMES:
        items = list_instance_group_managers(store, project, zone)
        key = "zones/%s" % zone
        out[key] = {"instanceGroupManagers": items} if items else {"warning": {"code": "NO_RESULTS_ON_PAGE", "message": "no results"}}
    return {"kind": "compute#instanceGroupManagerAggregatedList", "items": out, "id": "projects/%s/aggregated/instanceGroupManagers" % project}


def list_managed_instances(store, project, zone, name):
    _, mgr = _mig(store, project, zone, name)
    out = []
    for iname in mgr["members"]:
        ifull = "projects/%s/zones/%s/instances/%s" % (project, zone, iname)
        inst = store.instances.get(ifull)
        out.append({"instance": _selflink(ifull), "instanceStatus": inst["status"] if inst else "DELETING", "currentAction": "NONE"})
    return out


# ── health checks (global) ───────────────────────────────────────────────────
def insert_health_check(store, project, payload):
    name = payload.get("name") or ""
    _check_name(name, "resource.name")
    full = "projects/%s/global/healthChecks/%s" % (project, name)
    if full in store.health_checks:
        raise _E(409, "ALREADY_EXISTS", "The resource '%s' already exists." % full)
    hctype = (payload.get("type") or "TCP").upper()
    if hctype not in HEALTH_CHECK_TYPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value for field 'type': %r." % hctype)
    now = _ts()
    hc = {
        "id": _next_id(store), "name": name, "kind": "compute#healthCheck", "type": hctype,
        "checkIntervalSec": payload.get("checkIntervalSec", 5), "timeoutSec": payload.get("timeoutSec", 5),
        "healthyThreshold": payload.get("healthyThreshold", 2), "unhealthyThreshold": payload.get("unhealthyThreshold", 2),
        "description": payload.get("description", ""), "creationTimestamp": now, "selfLink": _selflink(full),
    }
    key = "%sHealthCheck" % hctype.lower().replace("ssl", "ssl").replace("grpc", "grpc").replace("http2", "http2")
    detail = payload.get(key) or {}
    hc[key] = {"port": detail.get("port", 80 if "HTTP" in hctype and hctype != "HTTPS" else 443 if hctype in ("HTTPS", "SSL") else 80),
               "requestPath": detail.get("requestPath", "/") if "HTTP" in hctype else None,
               "host": detail.get("host")}
    store.health_checks[full] = hc
    return _operation(store, project, None, "insert", name, _selflink(full))


def list_health_checks(store, project):
    out = []
    for n in list_all(store.health_checks, "projects/%s/global/healthChecks/" % project):
        v = _copy(store.health_checks[n])
        key = "%sHealthCheck" % v["type"].lower()
        detail = v.get(key) or {}
        v["_display"] = {"scope": "Global", "host": detail.get("host") or "—", "path": detail.get("requestPath") or "—", "port": detail.get("port")}
        out.append(v)
    return out


def get_health_check(store, project, name):
    full = "projects/%s/global/healthChecks/%s" % (project, name)
    v = _get(store, store.health_checks, full, "healthCheck")
    return _json(200, v)


def delete_health_check(store, project, name):
    full = "projects/%s/global/healthChecks/%s" % (project, name)
    _get(store, store.health_checks, full, "healthCheck")
    del store.health_checks[full]
    return _operation(store, project, None, "delete", name, _selflink(full))


# ── operations ───────────────────────────────────────────────────────────────
def list_operations(store, project, scope=None):
    if scope:
        prefix = "projects/%s/zones/%s/operations/" % (project, scope) if scope in ZONE_REGION else "projects/%s/regions/%s/operations/" % (project, scope)
    else:
        prefix = "projects/%s/global/operations/" % project
    out = [op for n, op in store.operations.items() if n.startswith(prefix)]
    out.sort(key=lambda o: -int(o["id"]))
    return out


def list_all_operations(store, project):
    """Every operation for a project, any scope — for the console's combined Operations page."""
    out = [op for n, op in store.operations.items() if n.startswith("projects/%s/" % project)]
    out.sort(key=lambda o: -int(o["id"]))
    return out


def get_operation(store, project, scope, name):
    loc = "zones/%s" % scope if scope in ZONE_REGION else ("regions/%s" % scope if scope else "global")
    full = "projects/%s/%s/operations/%s" % (project, loc, name)
    if full not in store.operations and name.startswith("operation-"):
        # every operation completes synchronously; the VPC core's (networks, subnetworks,
        # firewalls, routes, addresses) are not kept here — report those DONE as well
        return {"kind": "compute#operation", "id": "0", "name": name, "status": "DONE", "progress": 100,
                "selfLink": _selflink(full)}
    return _get(store, store.operations, full, "operation")


# ── project / metadata ───────────────────────────────────────────────────────
def _proj(store, project):
    if project not in store.project_metadata:
        store.project_metadata[project] = {"items": [], "fingerprint": _fingerprint([])}
    return store.project_metadata[project]


def get_project(store, project):
    meta = _proj(store, project)
    return {"kind": "compute#project", "name": project, "id": str(int(hashlib.sha1(project.encode()).hexdigest()[:12], 16)),
            "commonInstanceMetadata": {"kind": "compute#metadata", "items": meta["items"], "fingerprint": meta["fingerprint"]},
            "defaultServiceAccount": "%s-compute@developer.gserviceaccount.com" % hashlib.sha1(project.encode()).hexdigest()[:12],
            "selfLink": _selflink("projects/%s" % project)}


def set_common_instance_metadata(store, project, payload):
    items = payload.get("items") or []
    store.project_metadata[project] = {"items": items, "fingerprint": _fingerprint(items)}
    return _operation(store, project, None, "setMetadata", project, _selflink("projects/%s" % project))


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    query, headers = query or {}, headers or {}
    try:
        r = _dispatch(store, method.upper(), path, query, headers, body)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    if method.upper() != "GET" and r.status < 300 and hasattr(store, "persist"):
        store.persist()          # durable substrates save here (the in-memory store has no persist)
    return r


def _body(body):
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        raise _E(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    return payload if isinstance(payload, dict) else {}


def _dispatch(store, method, path, query, headers, body):
    p = path.split("?", 1)[0]
    for pre in ("/compute/beta", "/compute/v1"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p.rsplit("/", 1)[-1]:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if len(segs) < 2 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project = segs[1]
    rest = segs[2:]
    payload = _body(body)

    if not rest:
        if method == "GET":
            return _json(200, get_project(store, project))
        return _err(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
    if rest == ["setCommonInstanceMetadata"] and method == "POST":
        return _json(200, set_common_instance_metadata(store, project, payload))
    if rest[0] == "zones" and len(rest) == 1 and method == "GET":
        return _json(200, {"kind": "compute#zoneList", "items": list_zones(store, project)})
    if rest[0] == "zones" and len(rest) == 2 and method == "GET":
        zv = next((z for z in list_zones(store, project) if z["name"] == rest[1]), None)
        if not zv:
            return _err(404, "NOT_FOUND", "The resource 'projects/%s/zones/%s' was not found." % (project, rest[1]))
        return _json(200, zv)
    if rest[0] == "regions" and len(rest) == 1 and method == "GET":
        return _json(200, {"kind": "compute#regionList", "items": list_regions(project)})
    if rest[0] == "aggregated" and len(rest) == 2 and method == "GET":
        fn = {"instances": aggregated_instances, "disks": aggregated_disks, "instanceGroups": aggregated_instance_groups,
              "instanceGroupManagers": aggregated_instance_group_managers}.get(rest[1])
        if fn:
            return _json(200, fn(store, project))
        if rest[1] == "operations":
            return _json(200, {"kind": "compute#operationAggregatedList", "items": {"global": {"operations": list_all_operations(store, project)}}})
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)

    if len(rest) >= 3 and rest[-1] == "wait" and rest[-3] == "operations" and method == "POST":
        rest, method = rest[:-1], "GET"     # operations.wait — every operation is already DONE
    if rest[0] == "regions" and len(rest) in (3, 4) and rest[2] == "operations" and method == "GET":
        if len(rest) == 3:
            return _json(200, {"kind": "compute#operationList", "items": list_operations(store, project, rest[1])})
        return _json(200, get_operation(store, project, rest[1], rest[3]))
    if rest[0] == "global":
        return _global(store, method, project, rest[1:], verb, payload)
    if rest[0] == "zones" and len(rest) >= 2:
        rest2 = rest[2:]
        if not verb and len(rest2) == 3 and rest2[0] in ("instances", "disks", "instanceGroups", "instanceGroupManagers"):
            # The real Compute v1 REST spells custom methods as a trailing path segment
            # (`instances/{i}/start`, `disks/{d}/createSnapshot`) — what google-cloud-compute
            # and gcloud send; `instances/{i}:start` (the console's form) is accepted too.
            rest2, verb = rest2[:2], rest2[2]
        return _zonal(store, method, project, rest[1], rest2, verb, payload, query)
    return _err(404, "NOT_FOUND", "Unknown path: %s" % path)


def _global(store, method, project, rest, verb, payload):
    if not rest:
        return _err(404, "NOT_FOUND", "Unknown path.")
    coll, rest2 = rest[0], rest[1:]
    if coll == "images":
        if not rest2:
            if method == "POST":
                return _json(200, insert_image(store, project, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#imageList", "items": list_images(store, project)})
        elif len(rest2) == 1:
            if method == "GET":
                return get_image(store, project, rest2[0])
            if method == "DELETE":
                return _json(200, delete_image(store, project, rest2[0]))
    elif coll == "snapshots":
        if not rest2:
            if method == "GET":
                return _json(200, {"kind": "compute#snapshotList", "items": list_snapshots(store, project)})
        elif len(rest2) == 1:
            if method == "GET":
                return get_snapshot(store, project, rest2[0])
            if method == "DELETE":
                return _json(200, delete_snapshot(store, project, rest2[0]))
    elif coll == "machineImages":
        if not rest2:
            if method == "POST":
                return _json(200, insert_machine_image(store, project, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#machineImageList", "items": list_machine_images(store, project)})
        elif len(rest2) == 1:
            if method == "GET":
                return get_machine_image(store, project, rest2[0])
            if method == "DELETE":
                return _json(200, delete_machine_image(store, project, rest2[0]))
    elif coll == "instanceTemplates":
        if not rest2:
            if method == "POST":
                return _json(200, insert_instance_template(store, project, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#instanceTemplateList", "items": list_instance_templates(store, project)})
        elif len(rest2) == 1:
            if method == "GET":
                return get_instance_template(store, project, rest2[0])
            if method == "DELETE":
                return _json(200, delete_instance_template(store, project, rest2[0]))
    elif coll == "healthChecks":
        if not rest2:
            if method == "POST":
                return _json(200, insert_health_check(store, project, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#healthCheckList", "items": list_health_checks(store, project)})
        elif len(rest2) == 1:
            if method == "GET":
                return get_health_check(store, project, rest2[0])
            if method == "DELETE":
                return _json(200, delete_health_check(store, project, rest2[0]))
    elif coll == "operations":
        if not rest2 and method == "GET":
            return _json(200, {"kind": "compute#operationList", "items": list_operations(store, project)})
        if len(rest2) == 1 and method == "GET":
            return _json(200, get_operation(store, project, None, rest2[0]))
    return _err(404, "NOT_FOUND", "Unknown path or method %s." % method)


def _zonal(store, method, project, zone, rest, verb, payload, query=None):
    if not rest:
        return _err(404, "NOT_FOUND", "Unknown path.")
    coll, rest2 = rest[0], rest[1:]
    if coll == "machineTypes":
        if not rest2 and method == "GET":
            return _json(200, {"kind": "compute#machineTypeList", "items": list_machine_types(project, zone)})
        if len(rest2) == 1 and method == "GET":
            v = machine_type_view(project, zone, rest2[0])
            if not v:
                return _err(404, "NOT_FOUND", "Machine type '%s' was not found." % rest2[0])
            return _json(200, v)
    elif coll == "operations":
        if not rest2 and method == "GET":
            return _json(200, {"kind": "compute#operationList", "items": list_operations(store, project, zone)})
        if len(rest2) == 1 and method == "GET":
            return _json(200, get_operation(store, project, zone, rest2[0]))
    elif coll == "instances":
        if not rest2:
            if method == "POST":
                return _json(200, insert_instance(store, project, zone, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#instanceList", "items": list_instances(store, project, zone)})
        elif len(rest2) == 1 and not verb:
            name = rest2[0]
            if method == "GET":
                return get_instance(store, project, zone, name)
            if method == "DELETE":
                return _json(200, delete_instance(store, project, zone, name))
        elif len(rest2) == 1 and verb:
            name = rest2[0]
            if verb in ("start", "stop", "suspend", "resume", "reset") and method == "POST":
                return _json(200, set_instance_status(store, project, zone, name, verb))
            if verb in ("setLabels", "setMetadata", "setDeletionProtection", "setMachineType", "setTags") and method == "POST":
                if verb == "setDeletionProtection":   # a query parameter on the real API (default true)
                    flag = str((query or {}).get("deletionProtection", "true")).lower()
                    payload = dict(payload, deletionProtection=flag not in ("false", "0"))
                return _json(200, set_instance_field(store, project, zone, name, verb, payload))
    elif coll == "disks":
        if not rest2:
            if method == "POST":
                return _json(200, insert_disk(store, project, zone, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#diskList", "items": list_disks(store, project, zone)})
        elif len(rest2) == 1 and not verb:
            name = rest2[0]
            if method == "GET":
                return get_disk(store, project, zone, name)
            if method == "DELETE":
                return _json(200, delete_disk(store, project, zone, name))
        elif len(rest2) == 1 and verb == "createSnapshot" and method == "POST":
            return _json(200, create_snapshot(store, project, zone, rest2[0], payload))
    elif coll == "instanceGroups":
        if not rest2:
            if method == "POST":
                return _json(200, insert_instance_group(store, project, zone, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#instanceGroupList", "items": list_instance_groups(store, project, zone)})
        elif len(rest2) == 1 and not verb:
            name = rest2[0]
            if method == "GET":
                full, g = _group(store, project, zone, name)
                return _json(200, {k: x for k, x in g.items() if not k.startswith("_")})
            if method == "DELETE":
                return _json(200, delete_instance_group(store, project, zone, name))
        elif len(rest2) == 1 and verb:
            name = rest2[0]
            if verb == "addInstances" and method == "POST":
                return _json(200, add_group_instances(store, project, zone, name, payload))
            if verb == "removeInstances" and method == "POST":
                return _json(200, remove_group_instances(store, project, zone, name, payload))
            if verb == "listInstances" and method == "POST":
                return _json(200, {"items": group_members(store, project, zone, name)})
    elif coll == "instanceGroupManagers":
        if not rest2:
            if method == "POST":
                return _json(200, insert_instance_group_manager(store, project, zone, payload))
            if method == "GET":
                return _json(200, {"kind": "compute#instanceGroupManagerList", "items": list_instance_group_managers(store, project, zone)})
        elif len(rest2) == 1 and not verb:
            name = rest2[0]
            if method == "GET":
                _, mgr = _mig(store, project, zone, name)
                return _json(200, _mig_view(mgr))
            if method == "DELETE":
                return _json(200, delete_instance_group_manager(store, project, zone, name))
            if method == "PATCH":
                return _json(200, patch_instance_group_manager(store, project, zone, name, payload))
        elif len(rest2) == 1 and verb:
            name = rest2[0]
            if verb == "resize" and method == "POST":
                size = (query or {}).get("size", payload.get("targetSize"))
                return _json(200, resize_instance_group_manager(store, project, zone, name, size))
            if verb == "listManagedInstances" and method == "POST":
                return _json(200, {"items": list_managed_instances(store, project, zone, name)})
    return _err(404, "NOT_FOUND", "Unknown path or method %s." % method)
