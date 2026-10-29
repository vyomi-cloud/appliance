"""GCP console resource-detail tabs — the shared engine for the parts of a resource the
service backends don't model on their own (Compute Engine instance settings in Nano,
per-resource child collections such as snapshots, Cloud SQL users and flags, Pub/Sub
schemas, Firestore rules, …) plus the validation every tab write goes through.

One engine for both runtimes (never forked): the offline appliance calls it from
providers/gcp_tabs_console.py (`/api/gcp/sub/{service}/{op}/{name}`), Nano calls it from
wasm/providers/gcp_core_adapter.py (the SW maps the same URL onto `_resource` ops) and gets
this file through wasm/build_cores.py.

Pure stdlib (runs under Pyodide). State is a plain JSON-safe dict the caller owns and
persists (offline: a space-scoped service state; Nano: a public dict on a registry store, so
nano_persist captures it):

    root = {"<service>/<parent>/<kind>": {"<child name>": {...record...}}}

Every write raises TabError(status, code, message) with the message the real API returns
for the same mistake, so the console shows the same error offline and in Nano.
"""
from __future__ import annotations

import hashlib
import re
import time


class TabError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def short(v) -> str:
    """Last path segment of a GCP resource name / self link."""
    return str(v or "").rstrip("/").rsplit("/", 1)[-1]


def numeric_id(seed: str) -> str:
    """Stable 19-digit resource id, the way GCE ids look."""
    return str(int(hashlib.sha256(seed.encode()).hexdigest()[:15], 16))


# ---------------------------------------------------------------------------
# child collections (records the backends don't hold themselves)
# ---------------------------------------------------------------------------
def children(root: dict, service: str, parent: str, kind: str, create: bool = False) -> dict:
    key = "%s/%s/%s" % (service, parent, kind)
    coll = root.get(key)
    if coll is None:
        coll = {}
        if create:
            root[key] = coll
    return coll


def list_children(root: dict, service: str, parent: str, kind: str) -> list:
    return list(children(root, service, parent, kind).values())


def put_child(root: dict, service: str, parent: str, kind: str, rec: dict, replace: bool = False) -> dict:
    coll = children(root, service, parent, kind, create=True)
    name = str(rec.get("name") or "").strip()
    if not name:
        raise TabError(400, "INVALID_ARGUMENT", "A name is required.")
    if name in coll and not replace:
        raise TabError(409, "ALREADY_EXISTS", "'%s' already exists." % name)
    coll[name] = rec
    return rec


def delete_child(root: dict, service: str, parent: str, kind: str, name: str) -> dict:
    coll = children(root, service, parent, kind, create=True)
    rec = coll.pop(str(name), None)
    if rec is None:
        raise TabError(404, "NOT_FOUND", "'%s' was not found." % name)
    return rec


def drop_parent(root: dict, service: str, parent: str) -> None:
    """A deleted resource takes its child collections with it."""
    pre = "%s/%s/" % (service, parent)
    for k in [k for k in root if k.startswith(pre)]:
        root.pop(k, None)


def get_settings(root: dict, service: str, parent: str, kind: str, defaults: dict) -> dict:
    """A per-resource settings record (e.g. a bucket's retention policy) with defaults."""
    coll = children(root, service, parent, "_settings")
    out = dict(defaults)
    out.update(coll.get(kind) or {})
    return out


def put_settings(root: dict, service: str, parent: str, kind: str, values: dict) -> dict:
    coll = children(root, service, parent, "_settings", create=True)
    cur = dict(coll.get(kind) or {})
    cur.update(values)
    coll[kind] = cur
    return cur


# ---------------------------------------------------------------------------
# per-tab partial reads — `get<View>` returns only the fields that tab shows (the
# `fields=` partial response every Google API supports), from the resource's GET view
# ---------------------------------------------------------------------------
VIEWS = {
    "compute": {
        "networking": ["name", "zone", "networkInterfaces", "tags", "canIpForward"],
        "machine": ["name", "zone", "machineType", "cpuPlatform", "status"],
        "metadata": ["name", "metadata"],
        "startup": ["name", "metadata"],
        "connect": ["name", "zone", "status", "networkInterfaces"],
        "scheduling": ["name", "status", "scheduling"],
        "labels": ["name", "labels", "labelFingerprint"],
    },
    "cloudsql": {
        "connectivity": ["name", "connectionName", "ipAddresses", "settings", "region", "gceZone", "connection",
                         "connect_help", "databaseVersion", "state"],
        "flags": ["name", "databaseVersion", "settings"],
        "backupconfig": ["name", "settings"],
        "insights": ["name", "databaseVersion", "settings"],
        "logging": ["name", "databaseVersion", "settings"],
    },
    "pubsub": {
        "encryption": ["name", "kmsKeyName"],
        "schema": ["name", "schemaSettings", "schema"],
        "labels": ["name", "labels"],
    },
    "storage": {
        "configuration": ["name", "location", "locationType", "storageClass", "iamConfiguration", "versioning",
                          "timeCreated", "updated", "metageneration", "projectNumber", "labels"],
        "lifecycle": ["name", "lifecycle"],
        "encryption": ["name", "encryption"],
        "retention": ["name", "retentionPolicy", "softDeletePolicy", "versioning"],
    },
}


_PUBSUB_ID = re.compile(r"^[A-Za-z][A-Za-z0-9\-_.~+%]{2,254}$")


def validate_pubsub_id(v, what="subscription") -> str:
    v = str(v or "").strip()
    if not _PUBSUB_ID.match(v) or v.lower().startswith("goog"):
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid %s ID '%s': 3-255 characters, start with a letter, letters/digits/-_.~+%% only, "
                       "and not starting with 'goog'." % (what, v))
    return v


def pubsub_topic_patch(op: str, body: dict):
    """Topic tab write → the topics.patch `topic` body (validated by the Pub/Sub engine)."""
    op = op[0].lower() + op[1:]
    if op == "setEncryption":
        return {"kmsKeyName": str(body.get("kmsKeyName") or "")}
    if op == "setSchema":
        sch = str(body.get("schema") or "")
        return {"schemaSettings": {"schema": sch, "encoding": body.get("encoding") or "JSON"} if sch else {}}
    if op == "setRetention":
        return {"messageRetentionDuration": body.get("messageRetentionDuration") or ""}
    if op == "setLabels":
        return {"labels": validate_labels(body.get("labels", {}))}
    return None


def storage_patch(op: str, body: dict):
    """Bucket tab write → the buckets.patch body it amounts to (validated by the GCS engine)."""
    op = op[0].lower() + op[1:]
    if op == "setLifecycle":
        return {"lifecycle": {"rule": list(body.get("rule") or [])}}
    if op == "setEncryption":
        return {"encryption": {"defaultKmsKeyName": str(body.get("defaultKmsKeyName") or "")}}
    if op == "setRetention":
        p = body.get("retentionPeriod")
        return {"retentionPolicy": {"retentionPeriod": p} if p not in (None, "", 0, "0") else None}
    if op == "setVersioning":
        return {"versioning": {"enabled": bool(body.get("enabled"))}}
    if op == "setSoftDelete":
        return {"softDeletePolicy": {"retentionDurationSeconds": body.get("retentionDurationSeconds", 0)}}
    if op == "setStorageClass":
        return {"storageClass": body.get("storageClass")}
    if op == "setLabels":
        return {"labels": validate_labels(body.get("labels", {}))}
    return None


def view_op(service: str, op: str):
    """'getNetworking' (offline) / 'GetNetworking' (Nano) → 'networking' when it is a
    registered view of `service`."""
    if not op[:3].lower() == "get":
        return None
    v = op[3:].lower()
    return v if v in VIEWS.get(service, {}) or v == "labels" else None


def view(service: str, v: str, full: dict) -> dict:
    fields = VIEWS.get(service, {}).get(v) or ["name", "labels"]
    out = {k: full[k] for k in fields if k in full}
    if service == "cloudsql" and v == "labels":   # Cloud SQL labels live in settings.userLabels
        out["labels"] = dict((full.get("settings") or {}).get("userLabels") or full.get("labels") or {})
    return out


def sql_settings_patch(op: str, body: dict, settings: dict):
    """Cloud SQL tab write → the instances.patch `settings` body it amounts to."""
    op = op[0].lower() + op[1:]
    ip = dict(settings.get("ipConfiguration") or {})
    if op == "setFlags":
        return {"databaseFlags": list(body.get("flags") or [])}
    if op == "setIpConfig":
        return {"ipConfiguration": {k: body[k] for k in ("ipv4Enabled", "sslMode", "privateNetwork") if k in body}}
    if op == "addAuthorizedNetwork":
        nets = list(ip.get("authorizedNetworks") or [])
        nets.append({"name": str(body.get("name") or ""), "value": str(body.get("value") or "")})
        return {"ipConfiguration": {"authorizedNetworks": nets}}
    if op == "removeAuthorizedNetwork":
        nets = [n for n in (ip.get("authorizedNetworks") or []) if n.get("value") != body.get("value")]
        if len(nets) == len(ip.get("authorizedNetworks") or []):
            raise TabError(404, "NOT_FOUND", "Authorized network %s is not set on this instance." % body.get("value"))
        return {"ipConfiguration": {"authorizedNetworks": nets}}
    if op == "setBackupConfig":
        return {"backupConfiguration": {k: body[k] for k in ("enabled", "startTime", "pointInTimeRecoveryEnabled",
                                                            "retainedBackups", "transactionLogRetentionDays") if k in body}}
    if op == "setInsights":
        return {"insightsConfig": {k: body[k] for k in ("queryInsightsEnabled", "recordApplicationTags",
                                                        "recordClientAddress", "queryStringLength") if k in body}}
    if op == "setLabels":
        return {"userLabels": validate_labels(body.get("labels", {}))}
    return None


# ---------------------------------------------------------------------------
# labels (every service) — GCP label rules
# ---------------------------------------------------------------------------
_LABEL_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_LABEL_VAL = re.compile(r"^[a-z0-9_-]{0,63}$")


def validate_labels(labels) -> dict:
    if not isinstance(labels, dict):
        raise TabError(400, "INVALID_ARGUMENT", "labels must be a map of key/value strings.")
    if len(labels) > 64:
        raise TabError(400, "INVALID_ARGUMENT", "A resource can have at most 64 labels.")
    out = {}
    for k, v in labels.items():
        k, v = str(k), "" if v is None else str(v)
        if not _LABEL_KEY.match(k):
            raise TabError(400, "INVALID_ARGUMENT",
                           "Invalid label key '%s': keys start with a lowercase letter and contain only "
                           "lowercase letters, digits, underscores and dashes (max 63)." % k)
        if not _LABEL_VAL.match(v):
            raise TabError(400, "INVALID_ARGUMENT",
                           "Invalid label value '%s' for key '%s': lowercase letters, digits, underscores "
                           "and dashes only (max 63)." % (v, k))
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# IAM bindings (Permissions tab) — add/remove one member on a policy
# ---------------------------------------------------------------------------
_MEMBER = re.compile(r"^(user|serviceAccount|group|domain|principal|principalSet):.+|^(allUsers|allAuthenticatedUsers)$")


def policy_grant(policy: dict, role: str, member: str) -> dict:
    role, member = str(role or "").strip(), str(member or "").strip()
    if not role.startswith(("roles/", "projects/", "organizations/")):
        raise TabError(400, "INVALID_ARGUMENT", "Role '%s' is not a valid role name (e.g. roles/viewer)." % role)
    if not _MEMBER.match(member):
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid member '%s': use user:, serviceAccount:, group: or domain: prefixes." % member)
    pol = {"version": policy.get("version", 1), "etag": policy.get("etag", ""),
           "bindings": [dict(b, members=list(b.get("members") or [])) for b in (policy.get("bindings") or [])]}
    for b in pol["bindings"]:
        if b.get("role") == role:
            if member not in b["members"]:
                b["members"].append(member)
            break
    else:
        pol["bindings"].append({"role": role, "members": [member]})
    return pol


def policy_revoke(policy: dict, role: str, member: str) -> dict:
    pol = {"version": policy.get("version", 1), "etag": policy.get("etag", ""), "bindings": []}
    found = False
    for b in policy.get("bindings") or []:
        ms = [m for m in (b.get("members") or []) if not (b.get("role") == role and m == member)]
        found = found or len(ms) != len(b.get("members") or [])
        if ms:
            pol["bindings"].append(dict(b, members=ms))
    if not found:
        raise TabError(404, "NOT_FOUND", "%s has no %s binding." % (member, role))
    return pol


# ---------------------------------------------------------------------------
# Compute Engine — instance settings
# ---------------------------------------------------------------------------
_RFC1035 = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
_META_KEY = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
DISK_TYPES = ("pd-balanced", "pd-ssd", "pd-standard", "pd-extreme", "hyperdisk-balanced")


def validate_name(name: str, what: str) -> str:
    name = str(name or "").strip()
    if not _RFC1035.match(name):
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid value for field '%s': '%s'. Must be a match of regex "
                       "'(?:[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?)'" % (what, name))
    return name


def validate_metadata(items) -> list:
    """`items` = [{key, value}] (or a {key: value} map) → normalized item list."""
    if isinstance(items, dict):
        items = [{"key": k, "value": v} for k, v in items.items()]
    if not isinstance(items, list):
        raise TabError(400, "INVALID_ARGUMENT", "metadata.items must be a list of {key, value}.")
    out, seen, total = [], set(), 0
    for it in items:
        if not isinstance(it, dict):
            continue
        k, v = str(it.get("key") or "").strip(), "" if it.get("value") is None else str(it.get("value"))
        if not k:
            continue
        if not _META_KEY.match(k):
            raise TabError(400, "INVALID_ARGUMENT",
                           "Invalid value for field 'resource.items[].key': '%s'. Keys are 1-128 letters, "
                           "digits, '-' or '_'." % k)
        if k in seen:
            raise TabError(400, "INVALID_ARGUMENT", "Duplicate metadata key '%s'." % k)
        seen.add(k)
        total += len(k) + len(v)
        if len(v) > 256 * 1024:
            raise TabError(400, "INVALID_ARGUMENT", "Metadata value for '%s' exceeds 256 KB." % k)
        out.append({"key": k, "value": v})
    if total > 512 * 1024:
        raise TabError(400, "INVALID_ARGUMENT", "Total metadata size exceeds 512 KB.")
    return out


def validate_scheduling(body: dict, current: dict | None = None) -> dict:
    cur = dict(current or {})
    for k in ("onHostMaintenance", "automaticRestart", "preemptible", "provisioningModel",
              "instanceTerminationAction"):
        if k in body and body[k] is not None and body[k] != "":
            cur[k] = body[k]
    ohm = str(cur.get("onHostMaintenance") or "MIGRATE").upper()
    if ohm not in ("MIGRATE", "TERMINATE"):
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid value for field 'resource.onHostMaintenance': '%s'. Must be MIGRATE or TERMINATE." % ohm)
    model = str(cur.get("provisioningModel") or "STANDARD").upper()
    if model not in ("STANDARD", "SPOT"):
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid value for field 'resource.provisioningModel': '%s'. Must be STANDARD or SPOT." % model)
    auto = cur.get("automaticRestart", True)
    auto = auto if isinstance(auto, bool) else str(auto).lower() in ("true", "1", "on", "yes")
    pre = cur.get("preemptible", False)
    pre = pre if isinstance(pre, bool) else str(pre).lower() in ("true", "1", "on", "yes")
    if model == "SPOT" or pre:
        if ohm != "TERMINATE":
            raise TabError(400, "INVALID_ARGUMENT",
                           "Invalid value for field 'resource.onHostMaintenance': 'MIGRATE'. Scheduling must have "
                           "preemptible be false when OnHostMaintenance isn't TERMINATE.")
        if auto:
            raise TabError(400, "INVALID_ARGUMENT",
                           "Invalid value for field 'resource.automaticRestart': 'true'. Preemptible and Spot "
                           "instances cannot be automatically restarted.")
    out = {"onHostMaintenance": ohm, "automaticRestart": auto, "preemptible": pre, "provisioningModel": model}
    if model == "SPOT":
        out["instanceTerminationAction"] = str(cur.get("instanceTerminationAction") or "STOP").upper()
    return out


def check_stopped(status: str, what: str) -> None:
    if str(status or "").upper() not in ("TERMINATED", "STOPPED", "SUSPENDED"):
        raise TabError(400, "FAILED_PRECONDITION",
                       "The instance must be stopped before %s (current status: %s)." % (what, str(status or "RUNNING").upper()))


def validate_machine_type(mt: str, known: list | None) -> str:
    mt = short(mt)
    if not mt:
        raise TabError(400, "INVALID_ARGUMENT", "machineType is required.")
    if known and mt not in known:
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid value for field 'resource.machineType': '%s'. Machine type with name '%s' "
                       "does not exist in zone." % (mt, mt))
    return mt


def disk_spec(body: dict, instance: str, existing: list) -> dict:
    """A new persistent disk to create + attach to `instance`."""
    name = validate_name(body.get("name") or "%s-disk-%d" % (instance, len(existing) + 1), "resource.name")
    if name in existing:
        raise TabError(409, "ALREADY_EXISTS", "The resource 'disks/%s' already exists" % name)
    try:
        size = int(body.get("sizeGb") or 10)
    except (TypeError, ValueError):
        raise TabError(400, "INVALID_ARGUMENT", "sizeGb must be a whole number of GB.")
    if size < 10 or size > 65536:
        raise TabError(400, "INVALID_ARGUMENT",
                       "Invalid value for field 'resource.sizeGb': '%s'. Disk size must be between 10 and 65536 GB." % size)
    dtype = short(body.get("type") or "pd-balanced")
    if dtype not in DISK_TYPES:
        raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.type': '%s'." % dtype)
    return {"name": name, "sizeGb": size, "type": dtype, "mode": "READ_WRITE", "autoDelete": bool(body.get("autoDelete", False))}


def snapshot_spec(body: dict, disk_names: list, existing: list) -> dict:
    name = validate_name(body.get("name") or "", "resource.name")
    if name in existing:
        raise TabError(409, "ALREADY_EXISTS", "The resource 'snapshots/%s' already exists" % name)
    disk = short(body.get("sourceDisk") or (disk_names[0] if disk_names else ""))
    if disk not in disk_names:
        raise TabError(400, "INVALID_ARGUMENT", "Disk '%s' is not attached to this instance." % disk)
    return {"name": name, "sourceDisk": disk, "description": str(body.get("description") or "")}


def describe_instance(rec: dict, project: str, zone: str) -> dict:
    """Nano: a created instance comes back described the way instances.get describes it.
    Filled once at insert time (ids/IPs derived from the instance name, so they're stable)."""
    out = dict(rec)
    name = str(out.get("name") or "")
    zone = short(out.get("zone") or zone) or "us-central1-a"
    region = zone.rsplit("-", 1)[0]
    h = hashlib.sha256(("%s/%s/%s" % (project, zone, name)).encode()).digest()
    mt = short(out.get("machineType") or "e2-medium")
    disk_gb = out.get("bootDiskSizeGb") or 10
    out.setdefault("id", numeric_id("%s:%s:%s" % (project, zone, name)))
    out["zone"] = zone
    out["machineType"] = mt
    out.setdefault("status", "RUNNING")
    out.setdefault("cpuPlatform", "Intel Broadwell")
    out.setdefault("creationTimestamp", now_iso())
    out.setdefault("networkInterfaces", [{
        "name": "nic0", "network": "default", "subnetwork": "default",
        # the default network's auto-mode subnet for the region (10.128.0.0/20 in us-central1)
        "networkIP": "10.%d.0.%d" % (auto_subnet_second_octet(region), 2 + h[0] % 250),
        "accessConfigs": [{"name": "External NAT", "type": "ONE_TO_ONE_NAT",
                           "natIP": "34.%d.%d.%d" % (100 + h[1] % 100, h[2], 1 + h[3] % 254),
                           "networkTier": "PREMIUM"}],
        "stackType": "IPV4_ONLY",
    }])
    out.setdefault("disks", [{
        "deviceName": name, "source": name, "boot": True, "autoDelete": True, "mode": "READ_WRITE",
        "type": "PERSISTENT", "diskSizeGb": str(disk_gb), "diskType": "pd-balanced",
        "sourceImage": "projects/debian-cloud/global/images/family/debian-12",
    }])
    out.setdefault("metadata", {"items": []})
    out.setdefault("scheduling", {"onHostMaintenance": "MIGRATE", "automaticRestart": True,
                                  "preemptible": False, "provisioningModel": "STANDARD"})
    out.setdefault("serviceAccounts", [{"email": "%s-compute@developer.gserviceaccount.com" % numeric_id(project)[:12],
                                        "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}])
    out.setdefault("tags", {"items": []})
    out.setdefault("labels", {})
    return out


# Auto-mode VPC subnet ranges (the fixed per-region /20s Google assigns to auto-mode networks).
AUTO_SUBNETS = [
    ("us-central1", "10.128.0.0/20"), ("europe-west1", "10.132.0.0/20"), ("us-west1", "10.138.0.0/20"),
    ("asia-east1", "10.140.0.0/20"), ("us-east1", "10.142.0.0/20"), ("asia-northeast1", "10.146.0.0/20"),
    ("asia-southeast1", "10.148.0.0/20"), ("us-east4", "10.150.0.0/20"), ("australia-southeast1", "10.152.0.0/20"),
    ("europe-west2", "10.154.0.0/20"), ("europe-west3", "10.156.0.0/20"), ("southamerica-east1", "10.158.0.0/20"),
    ("asia-south1", "10.160.0.0/20"), ("northamerica-northeast1", "10.162.0.0/20"), ("europe-west4", "10.164.0.0/20"),
    ("europe-north1", "10.166.0.0/20"), ("us-west2", "10.168.0.0/20"), ("asia-east2", "10.170.0.0/20"),
    ("europe-west6", "10.172.0.0/20"), ("asia-northeast2", "10.174.0.0/20"),
]


def auto_subnet_second_octet(region: str) -> int:
    for r, cidr in AUTO_SUBNETS:
        if r == region:
            return int(cidr.split(".")[1])
    return 128
