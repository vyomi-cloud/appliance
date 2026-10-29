# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
    "functions": {
        "source": ["name", "runtime", "entryPoint", "code", "buildConfig", "updateTime", "versionId"],
        "trigger": ["name", "eventTrigger", "httpsTrigger", "serviceConfig", "permissions"],
        "variables": ["name", "environmentVariables"],
        "networking": ["name", "serviceConfig", "vpcConnector"],
        "testing": ["name", "runtime", "entryPoint", "serviceConfig", "state"],
        "labels": ["name", "labels"],
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


# ---------------------------------------------------------------------------
# VPC networks — subnets, firewall rules, routes, peering, flow logs
# ---------------------------------------------------------------------------
def _net(cidr: str, what: str):
    import ipaddress
    try:
        return ipaddress.ip_network(str(cidr).strip(), strict=True)
    except ValueError as e:
        raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field '%s': '%s'. %s" % (what, cidr, e))


def auto_subnets(network: str) -> list:
    """networks.insert(autoCreateSubnetworks=true): one /20 per region, named like the network."""
    out = []
    for region, cidr in AUTO_SUBNETS:
        base = cidr.split("/")[0].rsplit(".", 1)[0]
        out.append({"name": network, "network": network, "region": region, "ipCidrRange": cidr,
                    "gatewayAddress": base + ".1", "privateIpGoogleAccess": False, "secondaryIpRanges": [],
                    "stackType": "IPV4_ONLY", "purpose": "PRIVATE", "state": "READY", "autoCreated": True,
                    "logConfig": {"enable": False}})
    return out


def default_route(network: str) -> dict:
    h = hashlib.sha256(network.encode()).hexdigest()[:16]
    return {"name": "default-route-" + h, "network": network, "destRange": "0.0.0.0/0", "priority": 1000,
            "nextHopGateway": "default-internet-gateway", "description": "Default route to the Internet."}


def validate_subnet(body: dict, network: str, existing: list) -> dict:
    """subnetworks.insert: name, region and a primary range that doesn't overlap the network's other subnets."""
    name = validate_name(body.get("name"), "resource.name")
    region = str(body.get("region") or "").strip()
    if region not in [r for r, _ in AUTO_SUBNETS]:
        raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'region': '%s'. Unknown region." % region)
    net = _net(body.get("ipCidrRange") or "", "resource.ipCidrRange")
    if net.version != 4 or not (8 <= net.prefixlen <= 29):
        raise TabError(400, "INVALID_ARGUMENT", "Invalid IPCidrRange: %s. Primary ranges are IPv4 /8 to /29." % net)
    for s in existing:
        if s.get("region") == region and s.get("name") == name:
            raise TabError(409, "ALREADY_EXISTS", "The resource 'projects/regions/%s/subnetworks/%s' already exists" % (region, name))
        if net.overlaps(_net(s.get("ipCidrRange"), "ipCidrRange")):
            raise TabError(400, "INVALID_ARGUMENT", "Invalid IPCidrRange: %s conflicts with existing subnetwork '%s' in region '%s'."
                           % (net, s.get("name"), s.get("region")))
    sec = []
    for r in body.get("secondaryIpRanges") or []:
        sn = _net(r.get("ipCidrRange"), "secondaryIpRanges.ipCidrRange")
        if sn.overlaps(net):
            raise TabError(400, "INVALID_ARGUMENT", "Secondary range %s overlaps the primary range %s." % (sn, net))
        sec.append({"rangeName": validate_name(r.get("rangeName"), "secondaryIpRanges.rangeName"), "ipCidrRange": str(sn)})
    return {"name": name, "network": network, "region": region, "ipCidrRange": str(net),
            "gatewayAddress": str(next(net.hosts())), "privateIpGoogleAccess": bool(body.get("privateIpGoogleAccess")),
            "secondaryIpRanges": sec, "stackType": "IPV4_ONLY", "purpose": "PRIVATE", "state": "READY",
            "logConfig": {"enable": False}, "description": str(body.get("description") or "")}


def validate_flow_logs(body: dict) -> dict:
    enable = bool(body.get("enable"))
    out = {"enable": enable}
    if enable:
        iv = str(body.get("aggregationInterval") or "INTERVAL_5_SEC")
        if iv not in ("INTERVAL_5_SEC", "INTERVAL_30_SEC", "INTERVAL_1_MIN", "INTERVAL_5_MIN", "INTERVAL_10_MIN", "INTERVAL_15_MIN"):
            raise TabError(400, "INVALID_ARGUMENT", "Invalid aggregationInterval %s." % iv)
        try:
            fs = float(body.get("flowSampling", 0.5))
        except (TypeError, ValueError):
            fs = -1
        if not 0 <= fs <= 1:
            raise TabError(400, "INVALID_ARGUMENT", "flowSampling must be between 0 and 1.")
        md = str(body.get("metadata") or "INCLUDE_ALL_METADATA")
        if md not in ("INCLUDE_ALL_METADATA", "EXCLUDE_ALL_METADATA"):
            raise TabError(400, "INVALID_ARGUMENT", "Invalid metadata option %s." % md)
        out.update({"aggregationInterval": iv, "flowSampling": fs, "metadata": md})
    return out


def _rules(spec):
    """'tcp:22,80;udp:53;icmp' (or a list of {IPProtocol, ports}) → firewall allowed/denied entries."""
    if isinstance(spec, list):
        items = [(str(x.get("IPProtocol") or ""), [str(p) for p in (x.get("ports") or [])]) for x in spec if isinstance(x, dict)]
    else:
        items = []
        for part in [p.strip() for p in str(spec or "").split(";") if p.strip()]:
            proto, _, ports = part.partition(":")
            items.append((proto.strip().lower(), [p.strip() for p in ports.split(",") if p.strip()]))
    out = []
    for proto, ports in items:
        if proto not in ("tcp", "udp", "icmp", "esp", "ah", "sctp", "ipip", "all"):
            raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.allowed[].IPProtocol': '%s'." % proto)
        for p in ports:
            lo, _, hi = p.partition("-")
            if not (lo.isdigit() and (not hi or hi.isdigit()) and 0 <= int(lo) <= 65535 and int(hi or lo) <= 65535):
                raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.allowed[].ports[]': '%s'." % p)
            if proto not in ("tcp", "udp", "sctp"):
                raise TabError(400, "INVALID_ARGUMENT", "Ports can only be specified for tcp, udp or sctp, not %s." % proto)
        out.append({"IPProtocol": proto, **({"ports": ports} if ports else {})})
    if not out:
        raise TabError(400, "INVALID_ARGUMENT", "A firewall rule needs at least one protocol (e.g. tcp:22).")
    return out


def validate_firewall(body: dict, network: str, existing_names: list) -> dict:
    name = validate_name(body.get("name"), "resource.name")
    if name in existing_names:
        raise TabError(409, "ALREADY_EXISTS", "The resource 'projects/global/firewalls/%s' already exists" % name)
    direction = str(body.get("direction") or "INGRESS").upper()
    if direction not in ("INGRESS", "EGRESS"):
        raise TabError(400, "INVALID_ARGUMENT", "direction must be INGRESS or EGRESS.")
    try:
        prio = int(body.get("priority", 1000))
    except (TypeError, ValueError):
        prio = -1
    if not 0 <= prio <= 65535:
        raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.priority': must be 0-65535.")
    action = str(body.get("action") or "allow").lower()
    rules = _rules(body.get("rules") or body.get("allowed") or body.get("denied"))
    ranges = body.get("ranges")
    if isinstance(ranges, str):
        ranges = [r.strip() for r in ranges.split(",") if r.strip()]
    ranges = [str(_net(r, "sourceRanges" if direction == "INGRESS" else "destinationRanges")) for r in (ranges or [])] or ["0.0.0.0/0"]
    tags = body.get("targetTags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    rec = {"name": name, "network": network, "direction": direction, "priority": prio,
           "allowed": rules if action == "allow" else [], "denied": rules if action == "deny" else [],
           "sourceRanges": ranges if direction == "INGRESS" else [], "destinationRanges": ranges if direction == "EGRESS" else [],
           "targetTags": [validate_name(t, "targetTags[]") for t in (tags or [])], "disabled": bool(body.get("disabled")),
           "logConfig": {"enable": bool(body.get("logging"))}, "description": str(body.get("description") or "")}
    return rec


def validate_route(body: dict, network: str, existing_names: list) -> dict:
    name = validate_name(body.get("name"), "resource.name")
    if name in existing_names:
        raise TabError(409, "ALREADY_EXISTS", "The resource 'projects/global/routes/%s' already exists" % name)
    dest = str(_net(body.get("destRange") or "", "resource.destRange"))
    try:
        prio = int(body.get("priority", 1000))
    except (TypeError, ValueError):
        prio = -1
    if not 0 <= prio <= 65535:
        raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.priority': must be 0-65535.")
    kind = str(body.get("nextHopType") or "gateway")
    hop = str(body.get("nextHop") or "").strip()
    rec = {"name": name, "network": network, "destRange": dest, "priority": prio, "description": str(body.get("description") or ""),
           "tags": [t.strip() for t in str(body.get("tags") or "").split(",") if t.strip()]}
    if kind == "gateway":
        rec["nextHopGateway"] = "default-internet-gateway"
    elif kind == "ip":
        import ipaddress
        try:
            rec["nextHopIp"] = str(ipaddress.ip_address(hop))
        except ValueError:
            raise TabError(400, "INVALID_ARGUMENT", "Invalid value for field 'resource.nextHopIp': '%s'." % hop)
    elif kind == "instance":
        rec["nextHopInstance"] = validate_name(hop, "resource.nextHopInstance")
    else:
        raise TabError(400, "INVALID_ARGUMENT", "Unknown next hop type %s." % kind)
    return rec


def subnet_routes(network: str, subnets: list) -> list:
    """The system-generated subnet routes every VPC has (one per subnet range)."""
    out = []
    for s in subnets:
        out.append({"name": "default-subnet-route-%s" % hashlib.sha256(("%s/%s/%s" % (network, s.get("region"), s.get("name"))).encode()).hexdigest()[:12],
                    "network": network, "destRange": s.get("ipCidrRange"), "priority": 0, "nextHop": "Virtual network " + network,
                    "type": "Subnet route", "region": s.get("region")})
    return out


def validate_peering(body: dict, network: str, peer_exists: bool, my_subnets: list, peer_subnets: list, existing: list) -> dict:
    name = validate_name(body.get("name"), "networkPeering.name")
    peer = short(body.get("peerNetwork"))
    if not peer_exists:
        raise TabError(404, "NOT_FOUND", "The resource 'projects/global/networks/%s' was not found" % peer)
    if peer == network:
        raise TabError(400, "INVALID_ARGUMENT", "A network cannot be peered with itself.")
    if any(p.get("name") == name for p in existing):
        raise TabError(409, "ALREADY_EXISTS", "A peering named %s already exists on %s." % (name, network))
    if any(short(p.get("network")) == peer for p in existing):
        raise TabError(400, "INVALID_ARGUMENT", "%s is already peered with %s." % (network, peer))
    for a in my_subnets:
        for b in peer_subnets:
            if _net(a["ipCidrRange"], "ipCidrRange").overlaps(_net(b["ipCidrRange"], "ipCidrRange")):
                raise TabError(400, "INVALID_ARGUMENT",
                               "Cannot peer %s with %s: subnet %s (%s) overlaps %s (%s)."
                               % (network, peer, a["name"], a["ipCidrRange"], b["name"], b["ipCidrRange"]))
    return {"name": name, "network": peer, "exchangeSubnetRoutes": True,
            "exportCustomRoutes": bool(body.get("exportCustomRoutes")), "importCustomRoutes": bool(body.get("importCustomRoutes")),
            "stackType": "IPV4_ONLY"}


def peering_state(network: str, peering: dict, peer_peerings: list) -> dict:
    """ACTIVE once the peer network has the matching peering back; INACTIVE until then."""
    back = any(short(p.get("network")) == network for p in peer_peerings or [])
    return {**peering, "state": "ACTIVE" if back else "INACTIVE",
            "stateDetails": "[%s]: Connected." % now_iso() if back else
            "[%s]: Waiting for peer network to connect." % now_iso()}


def vpc_op(be, network: str, op: str, body: dict):
    """One VPC network's detail-tab op over a storage backend `be` (offline: server.py's
    gcp_vpc_state; Nano: the ResourceStore record + child collections). `be` provides:
    network(name)->dict|None, update_network(name, field, value), subnets(network), put_subnet(rec),
    delete_subnet(region, name), firewalls(network), firewall_names(), put_firewall(rec),
    update_firewall(name, patch), delete_firewall(name), routes(network), route_names(),
    put_route(rec), delete_route(name)."""
    op = op[0].lower() + op[1:]
    net = be.network(network)
    if net is None:
        raise TabError(404, "NOT_FOUND", "The resource 'projects/global/networks/%s' was not found" % network)
    if not net.get("defaultsCreated"):
        # networks.insert side effects for a network created before they were modelled:
        # an auto-mode network's per-region subnets and every network's default route.
        have = be.subnets(network)
        if net.get("autoCreateSubnetworks", True) and not any(s.get("autoCreated") for s in have):
            for s in auto_subnets(network):
                if not any(x.get("region") == s["region"] and x.get("name") == s["name"] for x in have):
                    be.put_subnet(s)
        dr = default_route(network)
        if dr["name"] not in be.route_names():
            be.put_route(dr)
        be.update_network(network, "defaultsCreated", True)
        net = be.network(network)
    subs = be.subnets(network)
    if op == "listSubnets":
        return {"ok": True, "items": sorted(subs, key=lambda s: (s.get("region") or "", s.get("name") or ""))}
    if op == "createSubnet":
        rec = validate_subnet(body, network, subs)
        be.put_subnet(rec)
        return {"ok": True, "name": rec["name"], "region": rec["region"]}
    if op in ("deleteSubnet", "setPrivateGoogleAccess", "setFlowLogs"):
        s = next((x for x in subs if x.get("name") == body.get("name") and x.get("region") == body.get("region")), None)
        if s is None:
            raise TabError(404, "NOT_FOUND", "The resource 'projects/regions/%s/subnetworks/%s' was not found" % (body.get("region"), body.get("name")))
        if op == "deleteSubnet":
            if s.get("autoCreated") and net.get("autoCreateSubnetworks", True):
                raise TabError(400, "INVALID_ARGUMENT", "Subnetwork %s in %s was auto-created by an auto-mode network and cannot be deleted; "
                               "convert the network to custom mode first." % (s["name"], s["region"]))
            be.delete_subnet(s["region"], s["name"])
            return {"ok": True}
        patch = {"privateIpGoogleAccess": bool(body.get("enabled"))} if op == "setPrivateGoogleAccess" else {"logConfig": validate_flow_logs(body)}
        be.put_subnet({**s, **patch})
        return {"ok": True}
    if op == "listFlowLogs":
        return {"ok": True, "items": [{"name": s["name"], "region": s["region"], "ipCidrRange": s["ipCidrRange"],
                                       **{"enable": False, **(s.get("logConfig") or {})}} for s in subs]}
    if op == "listFirewalls":
        return {"ok": True, "items": sorted(be.firewalls(network), key=lambda f: (f.get("priority", 1000), f.get("name")))}
    if op == "createFirewall":
        rec = validate_firewall(body, network, be.firewall_names())
        be.put_firewall(rec)
        return {"ok": True, "name": rec["name"]}
    if op in ("deleteFirewall", "setFirewallDisabled"):
        name = str(body.get("name") or "")
        if name not in [f.get("name") for f in be.firewalls(network)]:
            raise TabError(404, "NOT_FOUND", "The resource 'projects/global/firewalls/%s' was not found" % name)
        if op == "deleteFirewall":
            be.delete_firewall(name)
        else:
            be.update_firewall(name, {"disabled": bool(body.get("disabled"))})
        return {"ok": True, "name": name}
    if op == "listRoutes":
        custom = [{**r, "type": "Static route" if not str(r.get("name", "")).startswith("default-route-") else "Default route",
                   "nextHop": r.get("nextHopGateway") or r.get("nextHopIp") or r.get("nextHopInstance") or r.get("nextHopNetwork") or "default-internet-gateway"}
                  for r in be.routes(network)]
        peers = [{"name": "peering-route-%s" % p.get("name"), "network": network, "destRange": s["ipCidrRange"], "priority": 0,
                  "nextHop": "Peering " + p.get("name"), "type": "Peering subnet route"}
                 for p in (net.get("peerings") or []) if p.get("state") == "ACTIVE"
                 for s in be.subnets(short(p.get("network")))]
        return {"ok": True, "items": subnet_routes(network, subs) + custom + peers}
    if op == "createRoute":
        rec = validate_route(body, network, be.route_names())
        be.put_route(rec)
        return {"ok": True, "name": rec["name"]}
    if op == "deleteRoute":
        name = str(body.get("name") or "")
        if name.startswith("default-subnet-route-"):
            raise TabError(400, "INVALID_ARGUMENT", "Subnet routes are managed by the VPC and cannot be deleted.")
        if name not in [r.get("name") for r in be.routes(network)]:
            raise TabError(404, "NOT_FOUND", "The resource 'projects/global/routes/%s' was not found" % name)
        be.delete_route(name)
        return {"ok": True, "name": name}
    if op == "listPeerings":
        out = []
        for p in net.get("peerings") or []:
            other = be.network(short(p.get("network"))) or {}
            out.append(peering_state(network, p, other.get("peerings")))
        be.update_network(network, "peerings", out)   # keep the stored state current (routes read it)
        return {"ok": True, "items": out}
    if op == "addPeering":
        peer = short(body.get("peerNetwork"))
        rec = validate_peering(body, network, be.network(peer) is not None, subs, be.subnets(peer) if be.network(peer) else [],
                               net.get("peerings") or [])
        other = be.network(peer) or {}
        rec = peering_state(network, rec, other.get("peerings"))
        be.update_network(network, "peerings", list(net.get("peerings") or []) + [rec])
        if rec["state"] == "ACTIVE":   # the peer's side becomes ACTIVE too
            be.update_network(peer, "peerings", [peering_state(peer, p, [rec]) if short(p.get("network")) == network else p
                                   for p in other.get("peerings") or []])
        return {"ok": True, "name": rec["name"], "state": rec["state"]}
    if op == "removePeering":
        name = str(body.get("name") or "")
        p = next((x for x in net.get("peerings") or [] if x.get("name") == name), None)
        if p is None:
            raise TabError(404, "NOT_FOUND", "No peering named %s on %s." % (name, network))
        be.update_network(network, "peerings", [x for x in net.get("peerings") or [] if x.get("name") != name])
        other = be.network(short(p.get("network")))
        if other is not None:   # the peer's side drops back to INACTIVE
            be.update_network(short(p.get("network")), "peerings", [peering_state(short(p.get("network")), x, []) if short(x.get("network")) == network else x
                                                       for x in other.get("peerings") or []])
        return {"ok": True, "name": name}
    return None


# ---------------------------------------------------------------------------
# Cloud Functions — source, trigger, variables, networking, test runs
# ---------------------------------------------------------------------------
FUNCTION_RUNTIMES = ("python313", "python312", "python311", "python310", "python39", "nodejs22", "nodejs20", "nodejs18",
                     "go123", "go122", "java21", "java17", "ruby33", "php83", "dotnet8")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENV = ("X_GOOGLE_", "FIREBASE_CONFIG", "FUNCTION_TARGET", "FUNCTION_SIGNATURE_TYPE", "K_SERVICE", "K_REVISION",
                 "K_CONFIGURATION", "PORT")


def validate_source(runtime: str, code: str, entry: str) -> dict:
    runtime = str(runtime or "").strip()
    if runtime not in FUNCTION_RUNTIMES:
        raise TabError(400, "INVALID_ARGUMENT", "Invalid runtime '%s'. Supported: %s." % (runtime, ", ".join(FUNCTION_RUNTIMES)))
    entry = str(entry or "").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", entry):
        raise TabError(400, "INVALID_ARGUMENT", "Invalid entry point '%s'." % entry)
    code = str(code or "")
    if runtime.startswith("python") and code.strip():
        import ast
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise TabError(400, "FAILED_PRECONDITION",
                           "Build failed: main.py line %s: %s" % (e.lineno, e.msg))
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if entry not in names:
            raise TabError(400, "FAILED_PRECONDITION",
                           "Function failed on loading user code: entry point '%s' is not defined in main.py." % entry)
    if runtime.startswith("nodejs") and code.strip() and entry not in code:
        raise TabError(400, "FAILED_PRECONDITION",
                       "Function failed on loading user code: entry point '%s' is not exported by index.js." % entry)
    return {"runtime": runtime, "entryPoint": entry, "code": code}


def validate_env(env) -> dict:
    if not isinstance(env, dict):
        raise TabError(400, "INVALID_ARGUMENT", "environmentVariables must be a map.")
    out = {}
    for k, v in env.items():
        k = str(k)
        if not _ENV_KEY.match(k):
            raise TabError(400, "INVALID_ARGUMENT", "Invalid environment variable name '%s'." % k)
        if k.startswith(_RESERVED_ENV) or k in _RESERVED_ENV:
            raise TabError(400, "INVALID_ARGUMENT", "Environment variable '%s' is reserved by Cloud Functions." % k)
        out[k] = str(v)
    return out


def validate_trigger(body: dict, topic_exists) -> dict:
    kind = str(body.get("type") or "http")
    if kind == "http":
        return {"eventTrigger": None}
    if kind == "pubsub":
        topic = str(body.get("topic") or "")
        if not topic_exists(short(topic)):
            raise TabError(404, "NOT_FOUND", "Topic %s not found." % topic)
        return {"eventTrigger": {"eventType": "google.cloud.pubsub.topic.v1.messagePublished", "pubsubTopic": topic,
                                 "retryPolicy": "RETRY_POLICY_RETRY" if body.get("retry") else "RETRY_POLICY_DO_NOT_RETRY",
                                 "triggerRegion": str(body.get("region") or "us-central1")}}
    if kind == "storage":
        bucket = str(body.get("bucket") or "").strip()
        if not bucket:
            raise TabError(400, "INVALID_ARGUMENT", "A Cloud Storage trigger needs a bucket.")
        ev = str(body.get("event") or "google.cloud.storage.object.v1.finalized")
        return {"eventTrigger": {"eventType": ev, "eventFilters": [{"attribute": "bucket", "value": bucket}],
                                 "retryPolicy": "RETRY_POLICY_RETRY" if body.get("retry") else "RETRY_POLICY_DO_NOT_RETRY",
                                 "triggerRegion": str(body.get("region") or "us-central1")}}
    raise TabError(400, "INVALID_ARGUMENT", "Unknown trigger type %s." % kind)


def validate_fn_networking(body: dict) -> dict:
    ing = str(body.get("ingressSettings") or "ALLOW_ALL")
    if ing not in ("ALLOW_ALL", "ALLOW_INTERNAL_ONLY", "ALLOW_INTERNAL_AND_GCLB"):
        raise TabError(400, "INVALID_ARGUMENT", "Invalid ingressSettings %s." % ing)
    egress = str(body.get("vpcConnectorEgressSettings") or "PRIVATE_RANGES_ONLY")
    if egress not in ("PRIVATE_RANGES_ONLY", "ALL_TRAFFIC"):
        raise TabError(400, "INVALID_ARGUMENT", "Invalid vpcConnectorEgressSettings %s." % egress)
    conn = str(body.get("vpcConnector") or "").strip()
    if conn and not re.match(r"^projects/[^/]+/locations/[^/]+/connectors/[a-z][-a-z0-9]{0,23}$", conn):
        raise TabError(400, "INVALID_ARGUMENT", "vpcConnector must be projects/PROJECT/locations/REGION/connectors/NAME.")
    out = {"ingressSettings": ing, "vpcConnector": conn, "vpcConnectorEgressSettings": egress}
    for k, lo, hi in (("minInstanceCount", 0, 1000), ("maxInstanceCount", 1, 3000)):
        if body.get(k) not in (None, ""):
            n = int(body[k])
            if not lo <= n <= hi:
                raise TabError(400, "INVALID_ARGUMENT", "%s must be between %d and %d." % (k, lo, hi))
            out[k] = n
    if out.get("minInstanceCount", 0) > out.get("maxInstanceCount", 3000):
        raise TabError(400, "INVALID_ARGUMENT", "minInstanceCount cannot exceed maxInstanceCount.")
    return out


_FN_SAFE_MODULES = {"json", "math", "datetime", "base64", "re", "random", "uuid", "hashlib", "hmac", "itertools",
                    "functools", "collections", "string", "decimal", "statistics", "textwrap", "time"}


def run_python_function(code: str, entry: str, event, env: dict | None = None) -> dict:
    """Run a Python function's source in-process (Nano: Pyodide) with a restricted sandbox:
    computational stdlib only, `os.environ` = the function's runtime variables, print → logs.
    Same contract as core/gcp_function_runtime.execute: {status, result, logs[, error]}."""
    import builtins as _b
    import importlib
    import json as _json
    import traceback
    logs = []

    class _Os:
        environ = dict(env or {})

        @staticmethod
        def getenv(k, d=None):
            return _Os.environ.get(k, d)

    def _imp(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root == "os":
            return _Os
        if root not in _FN_SAFE_MODULES:
            raise ImportError("module '%s' is not available in the function sandbox" % name)
        return importlib.import_module(name)

    def _print(*a, **k):
        logs.append(" ".join(str(x) for x in a))

    safe = {n: getattr(_b, n) for n in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "len",
                                         "list", "map", "max", "min", "range", "reversed", "round", "set", "sorted", "str",
                                         "sum", "tuple", "zip", "isinstance", "hasattr", "getattr", "repr", "type", "chr",
                                         "ord", "Exception", "ValueError", "KeyError", "TypeError", "IndexError",
                                         "RuntimeError", "object", "staticmethod", "classmethod", "property", "super",
                                         "bytes", "format", "divmod", "pow", "hash", "iter", "next", "slice", "frozenset")}
    safe.update({"__import__": _imp, "print": _print, "__build_class__": _b.__build_class__, "__name__": "main"})
    g = {"__builtins__": safe}
    started = time.time()
    try:
        exec(compile(code, "main.py", "exec"), g)
        fn = g.get(entry)
        if not callable(fn):
            raise RuntimeError("Entry point %r not found in function source" % entry)
        result = fn(event)
        try:
            _json.dumps(result)
        except TypeError:
            result = str(result)
        return {"status": "SUCCESS", "result": result, "logs": "\n".join(logs)[:4000],
                "durationMs": int((time.time() - started) * 1000)}
    except Exception as e:
        tb = traceback.format_exception_only(type(e), e)[-1].strip()
        return {"status": "ERROR", "result": None, "error": tb[:2000], "logs": "\n".join(logs)[:4000],
                "durationMs": int((time.time() - started) * 1000)}


def functions_op(be, op: str, body: dict):
    """One function's detail-tab op over `be`: rec() (the stored function), update(patch),
    view() (functions.get shape), execute(code, entry, runtime, event, env, timeout) and
    topic_exists(topic_id). Offline executes in core/gcp_function_runtime's subprocess
    sandbox; Nano in run_python_function."""
    op = op[0].lower() + op[1:]
    rec = be.rec()
    v = view_op("functions", op)
    if v:
        return {"ok": True, "item": view("functions", v, be.view())}
    if op == "setSource":
        src = validate_source(body.get("runtime") or rec.get("runtime"), body.get("code", rec.get("code", "")),
                              body.get("entryPoint") or rec.get("entryPoint"))
        versions = [x for x in rec.get("versions") or [] if isinstance(x, dict)]
        for x in versions:
            x["is_latest"] = False
        versions.append({"version": str(len(versions) + 1), "state": "ACTIVE", "created": now_iso(), "is_latest": True,
                         "runtime": src["runtime"], "entryPoint": src["entryPoint"],
                         "sha256": hashlib.sha256(src["code"].encode()).hexdigest()[:16]})
        be.update({**src, "versions": versions, "versionId": str(len(versions)),
                   "buildConfig": {**(rec.get("buildConfig") or {}), "runtime": src["runtime"], "entryPoint": src["entryPoint"]},
                   "updateTime": now_iso()})
        return {"ok": True, "versionId": str(len(versions))}
    if op == "setTrigger":
        be.update({**validate_trigger(body, be.topic_exists), "updateTime": now_iso()})
        return {"ok": True}
    if op == "setPublicAccess":
        perms = [b for b in rec.get("permissions") or [] if not (b.get("role") == "roles/cloudfunctions.invoker" and "allUsers" in (b.get("members") or []))]
        if body.get("public"):
            perms.append({"role": "roles/cloudfunctions.invoker", "members": ["allUsers"]})
        be.update({"permissions": perms})
        return {"ok": True}
    if op == "setEnvVars":
        be.update({"environmentVariables": validate_env(body.get("environmentVariables") or {}), "updateTime": now_iso()})
        return {"ok": True}
    if op == "setNetworking":
        net = validate_fn_networking(body)
        sc = {**(rec.get("serviceConfig") or {}), **{k: net[k] for k in net if k != "vpcConnector"}}
        if net["vpcConnector"]:
            sc["vpcConnector"] = net["vpcConnector"]
        else:
            sc.pop("vpcConnector", None)
        be.update({"serviceConfig": sc, "vpcConnector": net["vpcConnector"], "updateTime": now_iso()})
        return {"ok": True}
    if op == "setLabels":
        be.update({"labels": validate_labels(body.get("labels", {}))})
        return {"ok": True}
    if op == "testFunction":
        data = body.get("data")
        if isinstance(data, str):
            import json as _json
            try:
                data = _json.loads(data) if data.strip() else {}
            except ValueError:
                raise TabError(400, "INVALID_ARGUMENT", "The triggering event must be valid JSON.")
        code, entry, runtime = rec.get("code") or "", rec.get("entryPoint") or "handler", rec.get("runtime") or "python312"
        if not code.strip():   # no source deployed: the default echo handler both runtimes run
            code = ("exports.%s = (event) => ({ message: 'default handler (no source deployed)', echo: event });\n" % entry
                    if runtime.startswith("nodejs") else
                    "def %s(event):\n    return {'message': 'default handler (no source deployed)', 'echo': event}\n" % entry)
        timeout = int((rec.get("serviceConfig") or {}).get("timeoutSeconds") or 60)
        out = be.execute(code, entry, runtime, data, rec.get("environmentVariables") or {}, min(max(timeout, 1), 120))
        inv = {"id": "exec-" + hashlib.sha256(("%s%s" % (now_iso(), time.time())).encode()).hexdigest()[:12],
               "timestamp": now_iso(), "request": data, "response": out.get("result"), "status": out.get("status", "SUCCESS"),
               "error": out.get("error", ""), "logs": out.get("logs", "")}
        be.update({"invocations": (list(rec.get("invocations") or []) + [inv])[-100:]})
        return {"ok": True, **{k: inv[k] for k in ("id", "status", "response", "error", "logs")}}
    if op in ("listInvocations", "listLogs"):
        out = []
        for inv in reversed(rec.get("invocations") or []):
            if op == "listInvocations":
                out.append({k: inv.get(k) for k in ("id", "timestamp", "status", "error")})
                continue
            base = {"timestamp": inv.get("timestamp"), "executionId": inv.get("id")}
            for line in (inv.get("logs") or "").splitlines():
                out.append({**base, "severity": "INFO", "textPayload": line})
            out.append({**base, "severity": "ERROR" if inv.get("status") == "ERROR" else "DEBUG",
                        "textPayload": ("Function execution took %s, finished with status: '%s'" % ("under a second", "error" if inv.get("status") == "ERROR" else "ok"))
                                       + (" — " + inv["error"] if inv.get("error") else "")})
        return {"ok": True, "items": out[:300]}
    return None


def describe_function(rec: dict, project: str, region: str) -> dict:
    """Nano: a deployed function described like functions.get (v2): build/service config + URL."""
    out = dict(rec)
    name = short(out.get("name") or "")
    out.setdefault("runtime", "python312")
    out.setdefault("entryPoint", "handler")
    out.setdefault("code", "")
    out.setdefault("environmentVariables", {})
    out.setdefault("eventTrigger", None)
    out.setdefault("invocations", [])
    sc = dict(out.get("serviceConfig") or {})
    sc.setdefault("availableMemory", str(out.get("memory") or "256M"))
    sc.setdefault("timeoutSeconds", int(out.get("timeoutSeconds") or 60))
    sc.setdefault("ingressSettings", "ALLOW_ALL")
    sc.setdefault("vpcConnectorEgressSettings", "PRIVATE_RANGES_ONLY")
    sc.setdefault("maxInstanceCount", 100)
    sc.setdefault("minInstanceCount", 0)
    sc["uri"] = "https://%s-%s.cloudfunctions.net/%s" % (region, project, name)
    out["serviceConfig"] = sc
    out["httpsTrigger"] = {"url": sc["uri"]}
    return out


# ---------------------------------------------------------------------------
# Firestore — data, query builder, indexes, security rules, import/export
# ---------------------------------------------------------------------------
def fs_to_typed(val):
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, list):
        return {"arrayValue": {"values": [fs_to_typed(x) for x in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: fs_to_typed(x) for k, x in val.items()}}}
    return {"stringValue": str(val)}


def fs_from_typed(v):
    if not isinstance(v, dict) or not v:
        return None
    k, x = next(iter(v.items()))
    if k == "integerValue":
        try:
            return int(x)
        except (TypeError, ValueError):
            return x
    if k == "doubleValue":
        return float(x)
    if k == "arrayValue":
        return [fs_from_typed(i) for i in (x or {}).get("values") or []]
    if k == "mapValue":
        return {a: fs_from_typed(b) for a, b in ((x or {}).get("fields") or {}).items()}
    if k == "nullValue":
        return None
    return x


def _fs_data(data) -> dict:
    import json as _json
    if isinstance(data, str):
        try:
            data = _json.loads(data) if data.strip() else {}
        except ValueError as e:
            raise TabError(400, "INVALID_ARGUMENT", "Document data must be a JSON object: %s" % e)
    if not isinstance(data, dict):
        raise TabError(400, "INVALID_ARGUMENT", "Document data must be a JSON object.")
    return {k: fs_to_typed(v) for k, v in data.items()}


_FS_ID = re.compile(r"^(?!__.*__$)[^/]{1,1500}$")
_FS_OPS = {"==": "EQUAL", "!=": "NOT_EQUAL", "<": "LESS_THAN", "<=": "LESS_THAN_OR_EQUAL", ">": "GREATER_THAN",
           ">=": "GREATER_THAN_OR_EQUAL", "array-contains": "ARRAY_CONTAINS", "in": "IN", "not-in": "NOT_IN",
           "array-contains-any": "ARRAY_CONTAINS_ANY"}
DEFAULT_RULES = ("rules_version = '2';\n\nservice cloud.firestore {\n  match /databases/{database}/documents {\n"
                 "    match /{document=**} {\n      allow read, write: if false;\n    }\n  }\n}\n")


def validate_rules(source: str) -> str:
    src = str(source or "")
    if "service cloud.firestore" not in src:
        raise TabError(400, "INVALID_ARGUMENT", "Ruleset compile error: expected 'service cloud.firestore { ... }'.")
    depth = 0
    for i, ch in enumerate(src):
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            raise TabError(400, "INVALID_ARGUMENT", "Ruleset compile error at character %d: unexpected '}'." % i)
    if depth:
        raise TabError(400, "INVALID_ARGUMENT", "Ruleset compile error: missing '}' (unbalanced braces).")
    for m in re.finditer(r"allow\s+([^:;]+):", src):
        for verb in [v.strip() for v in m.group(1).split(",")]:
            if verb not in ("read", "write", "get", "list", "create", "update", "delete"):
                raise TabError(400, "INVALID_ARGUMENT", "Ruleset compile error: unknown method '%s' in allow statement." % verb)
    if "match /databases/{database}/documents" not in src:
        raise TabError(400, "INVALID_ARGUMENT", "Ruleset compile error: rules must match /databases/{database}/documents.")
    return src


def firestore_op(be, project: str, db: str, op: str, body: dict):
    """One Firestore database's detail-tab op over `be`: collections(), docs(coll) ->
    [{id, fields(typed), createTime, updateTime}], create_doc(coll, id, typed),
    update_doc(coll, id, typed), delete_doc(coll, id), indexes(), create_index(cg, body),
    delete_index(name), put_object(bucket, name, text), get_object(bucket, name), root."""
    import json as _json
    op = op[0].lower() + op[1:]
    if op == "listCollections":
        return {"ok": True, "items": [{"id": c, "documents": len(be.docs(c))} for c in sorted(be.collections())]}
    if op == "listQueryFields":   # the query builder's collection + field pickers
        out = []
        for c in sorted(be.collections()):
            fields = sorted({k for d in be.docs(c) for k in (d.get("fields") or {})})
            out.append({"collection": c, "fields": fields})
        return {"ok": True, "items": out}
    if op == "listDocuments":
        coll = str(body.get("collection") or "")
        return {"ok": True, "items": [{"id": d["id"], "path": "%s/%s" % (coll, d["id"]),
                                       "data": _json.dumps({k: fs_from_typed(v) for k, v in (d.get("fields") or {}).items()}, default=str),
                                       "createTime": d.get("createTime", ""), "updateTime": d.get("updateTime", "")}
                                      for d in sorted(be.docs(coll), key=lambda d: d["id"])]}
    if op in ("createDocument", "updateDocument", "deleteDocument"):
        coll = str(body.get("collection") or "").strip("/")
        if not _FS_ID.match(coll):
            raise TabError(400, "INVALID_ARGUMENT", "Invalid collection ID '%s'." % coll)
        did = str(body.get("id") or "").strip()
        if op == "createDocument":
            did = did or hashlib.sha256(("%s%s" % (time.time(), coll)).encode()).hexdigest()[:20]
            if not _FS_ID.match(did):
                raise TabError(400, "INVALID_ARGUMENT", "Invalid document ID '%s'." % did)
            if any(d["id"] == did for d in be.docs(coll)):
                raise TabError(409, "ALREADY_EXISTS", "Document already exists: projects/%s/databases/%s/documents/%s/%s" % (project, db, coll, did))
            be.create_doc(coll, did, _fs_data(body.get("data")))
            return {"ok": True, "id": did}
        if not any(d["id"] == did for d in be.docs(coll)):
            raise TabError(404, "NOT_FOUND", "No document to update: projects/%s/databases/%s/documents/%s/%s" % (project, db, coll, did))
        if op == "updateDocument":
            be.update_doc(coll, did, _fs_data(body.get("data")))
        else:
            be.delete_doc(coll, did)
        return {"ok": True, "id": did}
    if op == "runQuery":
        from core.gcp_firestore_core import _eval_filter, _scalar
        coll = str(body.get("collection") or "")
        where = {}
        if body.get("field"):
            fop = _FS_OPS.get(str(body.get("op") or "=="))
            if not fop:
                raise TabError(400, "INVALID_ARGUMENT", "Unknown operator %s." % body.get("op"))
            raw = body.get("value")
            try:
                val = _json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                val = raw
            if fop in ("IN", "NOT_IN", "ARRAY_CONTAINS_ANY") and not isinstance(val, list):
                raise TabError(400, "INVALID_ARGUMENT", "'%s' needs a JSON array value, e.g. [\"a\", \"b\"]." % body.get("op"))
            where = {"fieldFilter": {"field": {"fieldPath": str(body["field"])}, "op": fop, "value": fs_to_typed(val)}}
        rows = [d for d in be.docs(coll) if _eval_filter(d.get("fields") or {}, where)]
        if body.get("orderBy"):
            fp = str(body["orderBy"])
            rows.sort(key=lambda d: (_scalar((d.get("fields") or {}).get(fp, {})) is None, str(_scalar((d.get("fields") or {}).get(fp, {})))),
                      reverse=str(body.get("direction") or "ASCENDING").upper() == "DESCENDING")
        lim = int(body.get("limit") or 50)
        return {"ok": True, "items": [{"id": d["id"], "path": "%s/%s" % (coll, d["id"]),
                                       "data": _json.dumps({k: fs_from_typed(v) for k, v in (d.get("fields") or {}).items()}, default=str)}
                                      for d in rows[:lim]]}
    if op == "listIndexes":
        return {"ok": True, "items": [{"name": i.get("name"), "collectionGroup": i.get("collectionGroup"),
                                       "fields": ", ".join("%s %s" % (f["fieldPath"], f.get("order") or f.get("arrayConfig")) for f in i.get("fields") or [] if f["fieldPath"] != "__name__"),
                                       "queryScope": i.get("queryScope"), "state": i.get("state", "READY")} for i in be.indexes()]}
    if op == "createIndex":
        fields = []
        for part in [p.strip() for p in str(body.get("fields") or "").split(",") if p.strip()]:
            fp, _, order = part.partition(":")
            order = order.strip().upper() or "ASCENDING"
            order = {"ASC": "ASCENDING", "DESC": "DESCENDING"}.get(order, order)
            fields.append({"fieldPath": fp.strip(), **({"arrayConfig": "CONTAINS"} if order == "CONTAINS" else {"order": order})})
        be.create_index(str(body.get("collection") or ""), {"fields": fields, "queryScope": body.get("queryScope") or "COLLECTION"})
        return {"ok": True}
    if op == "deleteIndex":
        be.delete_index(str(body.get("name") or ""))
        return {"ok": True}
    rels = children(be.root, "firestore", db, "rulesets", create=True)
    if op == "getRules":
        cur = sorted(rels.values(), key=lambda r: r["createTime"])[-1] if rels else None
        return {"ok": True, "item": {"source": cur["source"] if cur else DEFAULT_RULES,
                                     "ruleset": cur["name"] if cur else "Default rules (deny all)",
                                     "released": cur["createTime"] if cur else ""}}
    if op == "setRules":
        src = validate_rules(body.get("source"))
        rid = hashlib.sha256(("%s%s" % (src, time.time())).encode()).hexdigest()[:36]
        rels[rid] = {"name": "projects/%s/rulesets/%s" % (project, rid), "source": src, "createTime": now_iso()}
        return {"ok": True, "ruleset": rels[rid]["name"]}
    if op == "listRulesReleases":
        return {"ok": True, "items": [{"ruleset": r["name"], "createTime": r["createTime"], "lines": len(r["source"].splitlines())}
                                      for r in sorted(rels.values(), key=lambda r: r["createTime"], reverse=True)]}
    ops = children(be.root, "firestore", db, "operations", create=True)
    if op == "exportDocuments":
        bucket = str(body.get("bucket") or "").strip().replace("gs://", "").strip("/")
        if not bucket:
            raise TabError(400, "INVALID_ARGUMENT", "An export needs a Cloud Storage bucket (gs://BUCKET).")
        prefix = str(body.get("prefix") or "").strip("/")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S_00000", time.gmtime())
        colls = [c for c in (body.get("collectionIds") or be.collections())]
        dump = {"database": "projects/%s/databases/%s" % (project, db), "exportTime": now_iso(),
                "collections": {c: [{"id": d["id"], "fields": d.get("fields") or {}} for d in be.docs(c)] for c in colls}}
        obj = "/".join(x for x in (prefix, stamp, "%s.overall_export_metadata" % stamp) if x)
        be.put_object(bucket, obj, _json.dumps(dump))
        n = sum(len(v) for v in dump["collections"].values())
        name = "projects/%s/databases/%s/operations/%s" % (project, db, hashlib.sha256(obj.encode()).hexdigest()[:24])
        ops[name] = {"name": name, "operationType": "EXPORT_DOCUMENTS", "state": "SUCCESSFUL", "seq": len(ops), "startTime": now_iso(),
                     "endTime": now_iso(), "progressDocuments": n, "uri": "gs://%s/%s" % (bucket, obj),
                     "collectionIds": ", ".join(colls) or "All collections"}
        return {"ok": True, "operation": name, "outputUri": "gs://%s/%s" % (bucket, obj), "documents": n}
    if op == "importDocuments":
        uri = str(body.get("uri") or "").strip()
        if not uri.startswith("gs://") or "/" not in uri[5:]:
            raise TabError(400, "INVALID_ARGUMENT", "Import needs the export's gs://BUCKET/PATH (the .overall_export_metadata object).")
        bucket, obj = uri[5:].split("/", 1)
        text = be.get_object(bucket, obj)
        if text is None:
            raise TabError(404, "NOT_FOUND", "Export not found: %s" % uri)
        try:
            dump = _json.loads(text)
            colls = dump["collections"]
        except Exception:
            raise TabError(400, "INVALID_ARGUMENT", "%s is not a Firestore export." % uri)
        n = 0
        for c, docs in colls.items():
            have = {d["id"] for d in be.docs(c)}
            for d in docs:
                (be.update_doc if d["id"] in have else be.create_doc)(c, d["id"], d.get("fields") or {})
                n += 1
        name = "projects/%s/databases/%s/operations/%s" % (project, db, hashlib.sha256(("imp" + uri + now_iso()).encode()).hexdigest()[:24])
        ops[name] = {"name": name, "operationType": "IMPORT_DOCUMENTS", "state": "SUCCESSFUL", "seq": len(ops), "startTime": now_iso(),
                     "endTime": now_iso(), "progressDocuments": n, "uri": uri, "collectionIds": ", ".join(colls) or "All collections"}
        return {"ok": True, "operation": name, "documents": n}
    if op == "listOperations":
        return {"ok": True, "items": sorted(ops.values(), key=lambda o: (o["startTime"], o.get("seq", 0)), reverse=True)}
    return None


# ---------------------------------------------------------------------------
# Secret Manager — versions, rotation, replication, encryption
# ---------------------------------------------------------------------------
def secret_op(be, op: str, body: dict):
    """One secret's detail-tab op over `be`: meta() (labels/rotation/topics/replication/
    createTime), patch(fields), versions() newest first, add_version(value) -> version,
    set_state(version, state), topic_exists(topic_id)."""
    from core import gcp_secretmanager_core as smc
    op = op[0].lower() + op[1:]
    meta = be.meta()
    if op in ("getRotation", "getReplication", "getEncryption", "getLabels"):
        keep = {"getRotation": ("rotation", "topics", "createTime"), "getReplication": ("replication", "createTime"),
                "getEncryption": ("replication",), "getLabels": ("labels",)}[op]
        return {"ok": True, "item": {"name": be.name, **{k: meta[k] for k in keep if k in meta}}}
    vs = be.versions()
    if op == "getLatestVersion":
        live = [v for v in vs if v["state"] != "DESTROYED"]
        return {"ok": True, "item": {"name": be.name, "versionCount": len(vs), **({"latest": live[0]} if live else {})}}
    if op == "listVersions":
        return {"ok": True, "items": vs}
    if op == "accessVersion":   # versions/{v}:access — "latest" = newest version that isn't destroyed
        ref = str(body.get("version") or "latest")
        live = [v for v in vs if v["state"] != "DESTROYED"]
        cur = (live[0] if live else None) if ref == "latest" else next((v for v in vs if v["version"] == ref), None)
        if cur is None:
            raise TabError(404, "NOT_FOUND", "Secret Version [%s/versions/%s] not found." % (be.name, ref))
        if cur["state"] != "ENABLED":
            raise TabError(400, "FAILED_PRECONDITION", "Secret Version [%s/versions/%s] is in %s state." % (be.name, cur["version"], cur["state"]))
        return {"ok": True, "version": cur["version"], "value": be.access(cur["version"])}
    if op == "addVersion":
        value = str(body.get("value") if body.get("value") is not None else "")
        if not value:
            raise TabError(400, "INVALID_ARGUMENT", "A secret version needs a value (payload.data).")
        if len(value.encode()) > 65536:
            raise TabError(400, "INVALID_ARGUMENT", "Secret payload must be at most 64 KiB.")
        return {"ok": True, "version": be.add_version(value)}
    if op in ("enableVersion", "disableVersion", "destroyVersion"):
        ver = str(body.get("version") or "")
        cur = next((v for v in vs if v["version"] == ver), None)
        if cur is None:
            raise TabError(404, "NOT_FOUND", "Secret Version [%s/versions/%s] not found." % (be.name, ver))
        if cur["state"] == "DESTROYED":
            raise TabError(400, "FAILED_PRECONDITION", "Secret Version [%s/versions/%s] is destroyed." % (be.name, ver))
        be.set_state(ver, {"enableVersion": "ENABLED", "disableVersion": "DISABLED", "destroyVersion": "DESTROYED"}[op])
        return {"ok": True, "version": ver}
    patch = mask = None
    if op == "setRotation":
        topics = [{"name": t} for t in (body.get("topics") or []) if t]
        if body.get("enabled") is False:
            patch, mask = {"rotation": None}, "rotation"
        else:
            days = body.get("rotationPeriodDays")
            rot = {**({"rotationPeriod": "%ds" % int(float(days) * 86400)} if days not in (None, "") else {}),
                   **({"nextRotationTime": body["nextRotationTime"]} if body.get("nextRotationTime") else {})}
            patch, mask = {"topics": topics, "rotation": rot}, "topics,rotation"
    elif op == "setTopics":
        patch, mask = {"topics": [{"name": t} for t in (body.get("topics") or []) if t]}, "topics"
    elif op == "setLabels":
        patch, mask = {"labels": validate_labels(body.get("labels", {}))}, "labels"
    if patch is None:
        return None
    try:
        fields = smc.validate_secret_patch(meta, patch, mask, be.topic_exists)
    except smc.SecretPatchError as e:
        raise TabError(e.status, e.token, e.message)
    be.patch(fields)
    return {"ok": True}


def auto_subnet_second_octet(region: str) -> int:
    for r, cidr in AUTO_SUBNETS:
        if r == region:
            return int(cidr.split(".")[1])
    return 128
