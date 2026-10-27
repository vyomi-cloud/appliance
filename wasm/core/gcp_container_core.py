"""GCP Kubernetes Engine (GKE) core — substrate-independent. Speaks the native
**Kubernetes Engine REST API v1** (`container.googleapis.com/v1`) so the native
`google-cloud-container` SDKs and `gcloud container clusters ...` work unchanged against it
(point them at the endpoint via api_endpoint / api_endpoint_overrides).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano. This is the GKE *control plane*: clusters, node pools,
operations and the server config. No Kubernetes API server runs behind a cluster's
`endpoint` (that data plane needs the Max-tier k3s backend; below Max the console says so).

Resources (Discovery doc `container/v1`):
    projects/{p}/locations/{l}/clusters/{c}
    projects/{p}/locations/{l}/clusters/{c}/nodePools/{np}
    projects/{p}/locations/{l}/operations/{op}
Methods: clusters.create/get/list/update/delete/setResourceLabels/setLoggingService/
setMonitoringService/setMaintenancePolicy/setLegacyAbac, nodePools.create/get/list/update/
delete/setSize/setAutoscaling/setManagement, operations.get/list/cancel,
locations.getServerConfig. The legacy `projects/{p}/zones/{z}/...` paths are served too.
Every mutation returns a completed `Operation` (DONE) like a very fast real cloud; errors
use the Google shape `{"error":{"code","message","status"}}`.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

RUNNING, PROVISIONING, STOPPING, RECONCILING, ERROR, DEGRADED = (
    "RUNNING", "PROVISIONING", "STOPPING", "RECONCILING", "ERROR", "DEGRADED")
REGIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1", "europe-west2",
           "europe-west3", "europe-west4", "asia-east1", "asia-northeast1", "asia-south1",
           "asia-southeast1", "australia-southeast1", "southamerica-east1"]
DEFAULT_VERSION = "1.30.5-gke.1014001"
VALID_VERSIONS = ["1.31.1-gke.1146000", "1.30.5-gke.1014001", "1.30.4-gke.1348000", "1.29.9-gke.1177000",
                  "1.28.14-gke.1022000"]
IMAGE_TYPES = ["COS_CONTAINERD", "UBUNTU_CONTAINERD", "COS", "UBUNTU"]
DEFAULT_IMAGE = "COS_CONTAINERD"
DEFAULT_MACHINE = "e2-medium"
CHANNELS = ("RAPID", "REGULAR", "STABLE", "EXTENDED")
MAX_NODES_PER_POOL = 5000

# machine type -> (vCPUs, memory GB) for the common shapes; others derive from the -N suffix
_SHAPES = {"e2-micro": (2, 1), "e2-small": (2, 2), "e2-medium": (2, 4), "f1-micro": (1, 0.6),
           "g1-small": (1, 1.7), "n1-standard-1": (1, 3.75), "n1-standard-2": (2, 7.5)}


# ── store ──────────────────────────────────────────────────────────────────
class ContainerStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.clusters: dict = {}     # full cluster name -> Cluster resource
        self.operations: dict = {}   # full operation name -> Operation resource
        self.seq: dict = {"op": 0}


_SHARED: ContainerStore | None = None


def shared_store() -> ContainerStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = ContainerStore()
    return _SHARED


@dataclass
class ContainerResponse:
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
    return ContainerResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return ContainerResponse(status=status, body=json.dumps(obj).encode())


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _copy(x):
    return json.loads(json.dumps(x))


# ── names / validation ─────────────────────────────────────────────────────
_NAME = re.compile(r"^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$")
_ZONE = re.compile(r"^[a-z]+-[a-z]+[0-9]+-[a-z]$")
_LABEL = re.compile(r"^[a-z][-_a-z0-9]{0,62}$")


def cluster_name(project, location, cid):
    return "projects/%s/locations/%s/clusters/%s" % (project, location, cid)


def _region_of(location):
    return location[:-2] if _ZONE.match(location) else location


def _valid_location(location):
    return _region_of(location) in REGIONS and (location in REGIONS or bool(_ZONE.match(location)))


def _selflink(project, location, tail):
    kind = "zones" if _ZONE.match(location) else "locations"
    return "https://container.googleapis.com/v1/projects/%s/%s/%s/%s" % (project, kind, location, tail)


def shape(machine_type):
    """(vCPUs, GB memory) of a machine type."""
    if machine_type in _SHAPES:
        return _SHAPES[machine_type]
    m = re.search(r"-(\d+)$", machine_type or "")
    n = int(m.group(1)) if m else 2
    return (n, n * (3.75 if machine_type.startswith("n1-") else 4))


def _endpoint(name):
    h = hashlib.sha256(name.encode()).digest()
    return "34.%d.%d.%d" % (h[0] % 200 + 20, h[1], h[2] % 253 + 1)


def _check_labels(labels, what="resourceLabels"):
    if not isinstance(labels, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid %s." % what)
    if len(labels) > 64:
        raise _E(400, "INVALID_ARGUMENT", "A cluster may have at most 64 labels.")
    for k, v in labels.items():
        if not _LABEL.match(str(k)) or len(str(v)) > 63:
            raise _E(400, "INVALID_ARGUMENT", "Invalid label %r: keys must match [a-z][-_a-z0-9]{0,62} and values be at most 63 characters." % k)


def _fingerprint(labels):
    return hashlib.sha1(json.dumps(labels, sort_keys=True).encode()).hexdigest()[:8]


def _norm_autoscaling(a):
    if not isinstance(a, dict):
        raise _E(400, "INVALID_ARGUMENT", "Invalid autoscaling.")
    if a.get("enabled"):
        lo, hi = a.get("minNodeCount", 0), a.get("maxNodeCount", 0)
        if not isinstance(lo, int) or not isinstance(hi, int) or lo < 0 or hi < max(lo, 1):
            raise _E(400, "INVALID_ARGUMENT", "Autoscaling: maxNodeCount must be >= max(1, minNodeCount).")
    return a


# ── node pools ─────────────────────────────────────────────────────────────
def _make_pool(project, location, cluster, spec, default_name="default-pool", version=None):
    spec = dict(spec or {})
    name = spec.get("name") or default_name
    if not _NAME.match(name):
        raise _E(400, "INVALID_ARGUMENT", "Invalid node pool name %r: must match %s." % (name, _NAME.pattern))
    count = spec.get("initialNodeCount", 3)
    if not isinstance(count, int) or count < 0 or count > MAX_NODES_PER_POOL:
        raise _E(400, "INVALID_ARGUMENT", "initialNodeCount must be between 0 and %d." % MAX_NODES_PER_POOL)
    nc = dict(spec.get("config") or {})
    nc.setdefault("machineType", DEFAULT_MACHINE)
    nc.setdefault("diskSizeGb", 100)
    nc.setdefault("diskType", "pd-balanced")
    nc.setdefault("imageType", DEFAULT_IMAGE)
    nc.setdefault("oauthScopes", ["https://www.googleapis.com/auth/devstorage.read_only",
                                  "https://www.googleapis.com/auth/logging.write",
                                  "https://www.googleapis.com/auth/monitoring"])
    if nc["imageType"] not in IMAGE_TYPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid image type %r; valid: %s." % (nc["imageType"], ", ".join(IMAGE_TYPES)))
    pool = {
        "name": name, "config": nc, "initialNodeCount": count,
        "version": spec.get("version") or version or DEFAULT_VERSION,
        "status": RUNNING,
        "selfLink": _selflink(project, location, "clusters/%s/nodePools/%s" % (cluster, name)),
        "instanceGroupUrls": ["https://www.googleapis.com/compute/v1/projects/%s/zones/%s/instanceGroupManagers/gke-%s-%s-%s-grp" % (
            project, location if _ZONE.match(location) else location + "-a", cluster, name,
            hashlib.sha1((cluster + name).encode()).hexdigest()[:8])],
        "management": dict({"autoUpgrade": True, "autoRepair": True}, **(spec.get("management") or {})),
        "maxPodsConstraint": spec.get("maxPodsConstraint") or {"maxPodsPerNode": "110"},
        "podIpv4CidrSize": spec.get("podIpv4CidrSize", 24),
        "locations": spec.get("locations") or [location if _ZONE.match(location) else location + "-a"],
        "upgradeSettings": spec.get("upgradeSettings") or {"maxSurge": 1, "strategy": "SURGE"},
        "etag": hashlib.md5((cluster + name).encode()).hexdigest()[:16],
    }
    if spec.get("autoscaling"):
        pool["autoscaling"] = _norm_autoscaling(spec["autoscaling"])
    return pool


def pool_node_count(pool):
    return int(pool.get("initialNodeCount") or 0)


# ── operations ─────────────────────────────────────────────────────────────
def _operation(store, project, location, op_type, target):
    store.seq["op"] += 1
    oid = "operation-%d-%s" % (store.seq["op"], hashlib.sha1(("%s%d" % (target, store.seq["op"])).encode()).hexdigest()[:8])
    name = "projects/%s/locations/%s/operations/%s" % (project, location, oid)
    now = _ts()
    op = {"name": oid, "zone": location, "operationType": op_type, "status": "DONE",
          "selfLink": _selflink(project, location, "operations/" + oid),
          "targetLink": _selflink(project, location, target), "location": location,
          "startTime": now, "endTime": now}
    store.operations[name] = op
    return op


# ── views ──────────────────────────────────────────────────────────────────
def cluster_view(c):
    v = _copy(c)
    v["currentNodeCount"] = sum(pool_node_count(p) for p in v.get("nodePools", []))
    return v


def _mode(c):
    return "Autopilot" if (c.get("autopilot") or {}).get("enabled") else "Standard"


def console_view(c):
    """Flat row for the console grid / detail: every column filled."""
    full = c["_full"]
    seg = full.split("/")
    v = cluster_view({k: x for k, x in c.items() if k != "_full"})
    pools = c.get("nodePools", [])
    nodes = sum(pool_node_count(p) for p in pools)
    cpus = mem = 0
    for p in pools:
        n = pool_node_count(p)
        cpu, gb = shape(p["config"]["machineType"])
        cpus += cpu * n
        mem += gb * n
    auto = _mode(c) == "Autopilot"
    cfg = (pools[0]["config"] if pools else {})
    v.update({
        "id": c["name"], "resourceName": full, "project": seg[1], "location_name": seg[3],
        "region": seg[3],
        "mode": _mode(c),
        "version": c.get("currentMasterVersion", ""),
        "nodes": nodes,
        "vcpus": ("%g" % cpus) if not auto else "Autopilot-managed",
        "memory": ("%g GB" % mem) if not auto else "Autopilot-managed",
        "channel": (c.get("releaseChannel") or {}).get("channel", "UNSPECIFIED") if c.get("releaseChannel") else "No channel",
        "notifications": "Disabled",
        "pool_summary": ", ".join("%s (%d × %s)" % (p["name"], pool_node_count(p), p["config"]["machineType"])
                                  for p in pools) or "None",
        "machine_types": ", ".join(sorted({p["config"]["machineType"] for p in pools})) or "Autopilot-managed",
        "image_type": cfg.get("imageType", DEFAULT_IMAGE),
        "disk": ("%s GB %s" % (cfg.get("diskSizeGb", 100), cfg.get("diskType", "pd-balanced"))) if pools else "Autopilot-managed",
        "autoscaling": ", ".join("%s: %s-%s nodes" % (p["name"], p["autoscaling"].get("minNodeCount", 0), p["autoscaling"].get("maxNodeCount", 0))
                                 for p in pools if p.get("autoscaling", {}).get("enabled")) or "Disabled",
        "auto_upgrade": "Enabled" if all(p.get("management", {}).get("autoUpgrade") for p in pools) else "Disabled",
        "labels_text": ", ".join("%s=%s" % kv for kv in sorted((c.get("resourceLabels") or {}).items())) or "None",
        "data_plane": "Control plane only (Kubernetes API needs the Max-tier k3s backend)",
        "created": c.get("createTime", ""),
        "description_text": c.get("description") or "No description",
    })
    return v


def _with_full(store):
    return [dict(c, _full=n) for n, c in sorted(store.clusters.items())]


def view_by_name(store, full):
    return console_view(dict(store.clusters[full], _full=full))


def list_all(store, project=None):
    """Console grid: every cluster (optionally for one project)."""
    return [console_view(c) for c in _with_full(store)
            if project is None or c["_full"].startswith("projects/%s/" % project)]


# ── cluster operations ─────────────────────────────────────────────────────
def _get(store, project, location, cid):
    full = cluster_name(project, location, cid)
    c = store.clusters.get(full)
    if not c:
        raise _E(404, "NOT_FOUND", "Not found: %s." % full)
    return c


def create_cluster(store, project, location, payload):
    if not _valid_location(location):
        raise _E(400, "INVALID_ARGUMENT", "Location %r does not exist." % location)
    spec = dict(payload.get("cluster") or {})
    if not spec:
        raise _E(400, "INVALID_ARGUMENT", "Cluster must be specified.")
    cid = spec.get("name") or ""
    if not _NAME.match(cid):
        raise _E(400, "INVALID_ARGUMENT", "Invalid cluster name %r: must match %s (at most 40 characters)." % (cid, _NAME.pattern))
    full = cluster_name(project, location, cid)
    if full in store.clusters:
        raise _E(409, "ALREADY_EXISTS", "Already exists: %s." % full)
    auto = bool((spec.get("autopilot") or {}).get("enabled"))
    version = spec.get("initialClusterVersion") or DEFAULT_VERSION
    if spec.get("initialClusterVersion") and not any(v.startswith(spec["initialClusterVersion"]) for v in VALID_VERSIONS):
        raise _E(400, "INVALID_ARGUMENT", "Master version %r is unsupported." % spec["initialClusterVersion"])
    version = next((v for v in VALID_VERSIONS if v.startswith(version)), version)
    pools = [_make_pool(project, location, cid, p, version=version) for p in (spec.get("nodePools") or [])]
    if not pools and not auto:
        n = spec.get("initialNodeCount", 3)
        if not isinstance(n, int) or n < 0:
            raise _E(400, "INVALID_ARGUMENT", "initialNodeCount must be >= 0.")
        pools = [_make_pool(project, location, cid, {"initialNodeCount": n, "config": spec.get("nodeConfig")}, version=version)]
    if auto and spec.get("nodePools"):
        raise _E(400, "INVALID_ARGUMENT", "Node pools cannot be specified on an Autopilot cluster.")
    names = [p["name"] for p in pools]
    if len(set(names)) != len(names):
        raise _E(400, "INVALID_ARGUMENT", "Duplicate node pool names.")
    if "resourceLabels" in spec:
        _check_labels(spec["resourceLabels"])
    ch = (spec.get("releaseChannel") or {}).get("channel")
    if ch is not None and ch not in CHANNELS + ("UNSPECIFIED",):
        raise _E(400, "INVALID_ARGUMENT", "Invalid release channel %r." % ch)
    zone_like = location if _ZONE.match(location) else location
    c = {k: spec[k] for k in ("description", "network", "subnetwork", "clusterIpv4Cidr", "loggingService",
                              "monitoringService", "resourceLabels", "releaseChannel", "autopilot",
                              "enableKubernetesAlpha", "legacyAbac", "networkPolicy", "maintenancePolicy",
                              "addonsConfig", "ipAllocationPolicy", "privateClusterConfig", "labelFingerprint",
                              "locations", "initialClusterVersion") if k in spec}
    c.update({
        "name": cid, "location": location, "zone": zone_like,
        "network": spec.get("network") or "default", "subnetwork": spec.get("subnetwork") or "default",
        "clusterIpv4Cidr": spec.get("clusterIpv4Cidr") or "10.%d.0.0/14" % (4 * (int(hashlib.sha1(cid.encode()).hexdigest()[:2], 16) % 60) + 4),
        "servicesIpv4Cidr": "34.118.224.0/20", "nodeIpv4CidrSize": 24,
        "loggingService": spec.get("loggingService") or "logging.googleapis.com/kubernetes",
        "monitoringService": spec.get("monitoringService") or "monitoring.googleapis.com/kubernetes",
        "nodePools": pools,
        "locations": spec.get("locations") or [zone_like if _ZONE.match(location) else location + "-a"],
        "endpoint": _endpoint(full),
        "masterAuth": {"clusterCaCertificate": hashlib.sha256(full.encode()).hexdigest()},
        "currentMasterVersion": version, "currentNodeVersion": version,
        "initialClusterVersion": version,
        "status": RUNNING, "createTime": _ts(),
        "selfLink": _selflink(project, location, "clusters/" + cid),
        "currentNodeCount": 0,
        "resourceLabels": spec.get("resourceLabels") or {},
        "databaseEncryption": {"state": "DECRYPTED"},
        "networkConfig": {"network": "projects/%s/global/networks/%s" % (project, spec.get("network") or "default"),
                          "subnetwork": "projects/%s/regions/%s/subnetworks/%s" % (project, _region_of(location), spec.get("subnetwork") or "default")},
        "etag": hashlib.md5(full.encode()).hexdigest()[:16],
    })
    c["labelFingerprint"] = _fingerprint(c["resourceLabels"])
    if not auto:
        c["initialNodeCount"] = sum(pool_node_count(p) for p in pools)
    store.clusters[full] = c
    return _operation(store, project, location, "CREATE_CLUSTER", "clusters/" + cid)


def update_cluster(store, project, location, cid, payload):
    c = _get(store, project, location, cid)
    u = payload.get("update") or {}
    if not u:
        raise _E(400, "INVALID_ARGUMENT", "Update must be specified.")
    op_type = "UPDATE_CLUSTER"
    changed = False
    if "desiredMasterVersion" in u:
        v = next((x for x in VALID_VERSIONS if x.startswith(u["desiredMasterVersion"])), None)
        if u["desiredMasterVersion"] != "latest" and not v:
            raise _E(400, "INVALID_ARGUMENT", "Master version %r is unsupported." % u["desiredMasterVersion"])
        c["currentMasterVersion"] = v or VALID_VERSIONS[0]
        op_type, changed = "UPGRADE_MASTER", True
    if "desiredNodeVersion" in u:
        v = next((x for x in VALID_VERSIONS if x.startswith(u["desiredNodeVersion"])), None)
        if u["desiredNodeVersion"] != "-" and not v:
            raise _E(400, "INVALID_ARGUMENT", "Node version %r is unsupported." % u["desiredNodeVersion"])
        pid = u.get("desiredNodePoolId")
        for p in c["nodePools"]:
            if not pid or p["name"] == pid:
                p["version"] = v or c["currentMasterVersion"]
        if not pid:
            c["currentNodeVersion"] = v or c["currentMasterVersion"]
        op_type, changed = "UPGRADE_NODES", True
    for src, dst in (("desiredLoggingService", "loggingService"), ("desiredMonitoringService", "monitoringService")):
        if src in u:
            c[dst], changed = u[src], True
    if "desiredReleaseChannel" in u:
        c["releaseChannel"], changed = u["desiredReleaseChannel"], True
    if "desiredNodePoolAutoscaling" in u:
        pid = u.get("desiredNodePoolId")
        for p in c["nodePools"]:
            if not pid or p["name"] == pid:
                p["autoscaling"] = _norm_autoscaling(u["desiredNodePoolAutoscaling"])
        changed = True
    if "desiredImageType" in u:
        if u["desiredImageType"] not in IMAGE_TYPES:
            raise _E(400, "INVALID_ARGUMENT", "Invalid image type %r." % u["desiredImageType"])
        for p in c["nodePools"]:
            if not u.get("desiredNodePoolId") or p["name"] == u["desiredNodePoolId"]:
                p["config"]["imageType"] = u["desiredImageType"]
        changed = True
    if not changed:
        raise _E(400, "INVALID_ARGUMENT", "ClusterUpdate carries no supported desired* field.")
    return _operation(store, project, location, op_type, "clusters/" + cid)


def delete_cluster(store, project, location, cid):
    _get(store, project, location, cid)
    del store.clusters[cluster_name(project, location, cid)]
    return _operation(store, project, location, "DELETE_CLUSTER", "clusters/" + cid)


def cluster_setting(store, project, location, cid, verb, payload):
    c = _get(store, project, location, cid)
    if verb == "setResourceLabels":
        labels = payload.get("resourceLabels")
        _check_labels(labels if labels is not None else {})
        fp = payload.get("labelFingerprint")
        if fp and fp != c.get("labelFingerprint"):
            raise _E(409, "ABORTED", "Labels fingerprint mismatch: the cluster was modified since it was read.")
        c["resourceLabels"] = dict(labels or {})
        c["labelFingerprint"] = _fingerprint(c["resourceLabels"])
        return _operation(store, project, location, "SET_LABELS", "clusters/" + cid)
    if verb in ("setLoggingService", "setMonitoringService"):
        key = "loggingService" if verb == "setLoggingService" else "monitoringService"
        if not payload.get(key):
            raise _E(400, "INVALID_ARGUMENT", "%s is required." % key)
        c[key] = payload[key]
        return _operation(store, project, location, "UPDATE_CLUSTER", "clusters/" + cid)
    if verb == "setLegacyAbac":
        c["legacyAbac"] = {"enabled": bool(payload.get("enabled"))}
        return _operation(store, project, location, "SET_LEGACY_ABAC", "clusters/" + cid)
    if verb == "setMaintenancePolicy":
        c["maintenancePolicy"] = payload.get("maintenancePolicy") or {}
        return _operation(store, project, location, "SET_MAINTENANCE_POLICY", "clusters/" + cid)
    raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)


# ── node pool operations ───────────────────────────────────────────────────
def _pool(c, pid):
    for p in c["nodePools"]:
        if p["name"] == pid:
            return p
    raise _E(404, "NOT_FOUND", "Not found: %s/nodePools/%s." % (c["selfLink"].split("/v1/")[1], pid))


def create_pool(store, project, location, cid, payload):
    c = _get(store, project, location, cid)
    if (c.get("autopilot") or {}).get("enabled"):
        raise _E(400, "INVALID_ARGUMENT", "Node pools are managed by Autopilot and cannot be created.")
    spec = payload.get("nodePool")
    if not spec or not spec.get("name"):
        raise _E(400, "INVALID_ARGUMENT", "nodePool.name is required.")
    if any(p["name"] == spec["name"] for p in c["nodePools"]):
        raise _E(409, "ALREADY_EXISTS", "Already exists: %s/nodePools/%s." % (cluster_name(project, location, cid), spec["name"]))
    c["nodePools"].append(_make_pool(project, location, cid, spec, version=c["currentNodeVersion"]))
    return _operation(store, project, location, "CREATE_NODE_POOL", "clusters/%s/nodePools/%s" % (cid, spec["name"]))


def delete_pool(store, project, location, cid, pid):
    c = _get(store, project, location, cid)
    p = _pool(c, pid)
    if len(c["nodePools"]) == 1 and not (c.get("autopilot") or {}).get("enabled"):
        raise _E(400, "FAILED_PRECONDITION", "Cannot delete the last node pool of a cluster; delete the cluster instead.")
    c["nodePools"].remove(p)
    return _operation(store, project, location, "DELETE_NODE_POOL", "clusters/%s/nodePools/%s" % (cid, pid))


def pool_setting(store, project, location, cid, pid, verb, payload):
    c = _get(store, project, location, cid)
    p = _pool(c, pid)
    target = "clusters/%s/nodePools/%s" % (cid, pid)
    if verb == "setSize":
        n = payload.get("nodeCount")
        if not isinstance(n, int) or n < 0 or n > MAX_NODES_PER_POOL:
            raise _E(400, "INVALID_ARGUMENT", "nodeCount must be between 0 and %d." % MAX_NODES_PER_POOL)
        if p.get("autoscaling", {}).get("enabled"):
            raise _E(400, "FAILED_PRECONDITION", "Cannot resize node pool %s while autoscaling is enabled." % pid)
        p["initialNodeCount"] = n
        return _operation(store, project, location, "SET_NODE_POOL_SIZE", target)
    if verb == "setAutoscaling":
        p["autoscaling"] = _norm_autoscaling(payload.get("autoscaling") or {})
        return _operation(store, project, location, "SET_NODE_POOL_AUTOSCALING", target)
    if verb == "setManagement":
        p["management"] = dict(p.get("management") or {}, **(payload.get("management") or {}))
        return _operation(store, project, location, "SET_NODE_POOL_MANAGEMENT", target)
    if verb == "update":
        if payload.get("nodeVersion"):
            v = next((x for x in VALID_VERSIONS if x.startswith(payload["nodeVersion"])), None)
            if not v:
                raise _E(400, "INVALID_ARGUMENT", "Node version %r is unsupported." % payload["nodeVersion"])
            p["version"] = v
        if payload.get("imageType"):
            if payload["imageType"] not in IMAGE_TYPES:
                raise _E(400, "INVALID_ARGUMENT", "Invalid image type %r." % payload["imageType"])
            p["config"]["imageType"] = payload["imageType"]
        if "labels" in payload:
            p["config"]["labels"] = (payload["labels"] or {}).get("labels", {})
        return _operation(store, project, location, "UPDATE_CLUSTER", target)
    raise _E(404, "NOT_FOUND", "Unknown method :%s" % verb)


# ── operations / server config ─────────────────────────────────────────────
def _get_op(store, project, location, oid):
    op = store.operations.get("projects/%s/locations/%s/operations/%s" % (project, location, oid))
    if not op:
        raise _E(404, "NOT_FOUND", "Not found: projects/%s/locations/%s/operations/%s." % (project, location, oid))
    return op


def server_config(location):
    return {"defaultClusterVersion": DEFAULT_VERSION, "validNodeVersions": list(VALID_VERSIONS),
            "defaultImageType": DEFAULT_IMAGE, "validImageTypes": list(IMAGE_TYPES),
            "validMasterVersions": list(VALID_VERSIONS),
            "channels": [{"channel": ch, "defaultVersion": VALID_VERSIONS[i % 3 + 1] if i < 3 else VALID_VERSIONS[3],
                          "validVersions": VALID_VERSIONS[: 4 - min(i, 2)]} for i, ch in enumerate(CHANNELS)]}


def job_from_form(b, project="demo"):
    """Console create form (catalog createFields) → REST `CreateClusterRequest` body, shared by
    the offline console REST and the Nano adapter so both consoles create identical clusters."""
    location = str(b.get("region") or b.get("location") or "us-central1")
    auto = str(b.get("mode") or "Standard").lower() == "autopilot"
    cluster = {"name": str(b.get("name") or "").strip(),
               "network": str(b.get("network") or "default").strip() or "default"}
    if b.get("description"):
        cluster["description"] = str(b["description"])
    if b.get("version"):
        cluster["initialClusterVersion"] = str(b["version"]).strip()
    ch = str(b.get("releaseChannel") or "").upper()
    if ch and ch not in ("NONE", "NO CHANNEL"):
        cluster["releaseChannel"] = {"channel": ch}
    if auto:
        cluster["autopilot"] = {"enabled": True}
    else:
        try:
            n = int(b.get("nodeCount") if b.get("nodeCount") not in (None, "") else 3)
        except (TypeError, ValueError):
            n = -1
        cluster["nodePools"] = [{"name": "default-pool", "initialNodeCount": n,
                                 "config": {"machineType": str(b.get("machineType") or DEFAULT_MACHINE)}}]
    if isinstance(b.get("labels"), dict) and b["labels"]:
        cluster["resourceLabels"] = b["labels"]
    return {"parent": "projects/%s/locations/%s" % (project, location), "location": location, "cluster": cluster}


# ── enum encoding ──────────────────────────────────────────────────────────
# Proto enums are strings on the wire by default, but the Java / .NET / Go-gapic REST clients
# send `$alt=json;enum-encoding=int` and expect integers back (and send integers in bodies).
_CL_STATUS = {"STATUS_UNSPECIFIED": 0, "PROVISIONING": 1, "RUNNING": 2, "RECONCILING": 3, "STOPPING": 4,
              "ERROR": 5, "DEGRADED": 6}
_OP_STATUS = {"STATUS_UNSPECIFIED": 0, "PENDING": 1, "RUNNING": 2, "DONE": 3, "ABORTING": 4}
_OP_TYPE = {"TYPE_UNSPECIFIED": 0, "CREATE_CLUSTER": 1, "DELETE_CLUSTER": 2, "UPGRADE_MASTER": 3,
            "UPGRADE_NODES": 4, "REPAIR_CLUSTER": 5, "UPDATE_CLUSTER": 6, "CREATE_NODE_POOL": 7,
            "DELETE_NODE_POOL": 8, "SET_NODE_POOL_MANAGEMENT": 9, "AUTO_REPAIR_NODES": 10,
            "AUTO_UPGRADE_NODES": 11, "SET_LABELS": 12, "SET_MASTER_AUTH": 13, "SET_NODE_POOL_SIZE": 14,
            "SET_NETWORK_POLICY": 15, "SET_MAINTENANCE_POLICY": 16, "SET_NODE_POOL_AUTOSCALING": 0,
            "SET_LEGACY_ABAC": 0}
_CHANNEL = {"UNSPECIFIED": 0, "RAPID": 1, "REGULAR": 2, "STABLE": 3, "EXTENDED": 4}
_UPGRADE_STRATEGY = {"NODE_POOL_UPDATE_STRATEGY_UNSPECIFIED": 0, "BLUE_GREEN": 2, "SURGE": 3}


def _inv(m):
    return {v: k for k, v in m.items() if v or k.endswith("UNSPECIFIED")}


def _enum_walk(o, to_int):
    """Convert the enum fields of a Cluster / NodePool / Operation tree (either direction)."""
    if isinstance(o, list):
        return [_enum_walk(x, to_int) for x in o]
    if not isinstance(o, dict):
        return o
    o = dict(o)
    def conv(key, table, nested=None):
        d = table if to_int else _inv(table)
        if key in o and (o[key] in d):
            o[key] = d[o[key]]
    is_op = "operationType" in o
    conv("status", _OP_STATUS if is_op else _CL_STATUS)
    conv("operationType", _OP_TYPE)
    for rk in ("releaseChannel", "desiredReleaseChannel"):
        if isinstance(o.get(rk), dict):
            rc = dict(o[rk])
            d = _CHANNEL if to_int else _inv(_CHANNEL)
            if rc.get("channel") in d:
                rc["channel"] = d[rc["channel"]]
            o[rk] = rc
    if isinstance(o.get("upgradeSettings"), dict) and o["upgradeSettings"].get("strategy") in (_UPGRADE_STRATEGY if to_int else _inv(_UPGRADE_STRATEGY)):
        d = _UPGRADE_STRATEGY if to_int else _inv(_UPGRADE_STRATEGY)
        o["upgradeSettings"] = dict(o["upgradeSettings"], strategy=d[o["upgradeSettings"]["strategy"]])
    for k in ("cluster", "nodePool", "update", "clusters", "nodePools", "operations", "channels"):
        if k in o:
            o[k] = _enum_walk(o[k], to_int)
    if "channel" in o and not isinstance(o.get("channel"), dict):
        d = _CHANNEL if to_int else _inv(_CHANNEL)
        if o["channel"] in d:
            o["channel"] = d[o["channel"]]
    return o


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
    if len(segs) < 4 or segs[0] != "projects" or segs[2] not in ("locations", "zones"):
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project, location = segs[1], segs[3]
    rest = segs[4:]
    legacy = segs[2] == "zones"
    try:
        if rest == ["serverConfig"] and method == "GET":
            return _json(200, server_config(location))
        if not rest:
            return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
        if rest[0] == "clusters":
            return _clusters(store, method, project, location, rest[1:], verb, payload, legacy)
        if rest[0] == "operations":
            if len(rest) == 1 and method == "GET":
                ops = [o for n, o in sorted(store.operations.items())
                       if n.startswith("projects/%s/locations/%s/operations/" % (project, location)) or location == "-"]
                return _json(200, {"operations": ops, "missingZones": []})
            if len(rest) == 2 and method == "GET" and not verb:
                return _json(200, _get_op(store, project, location, rest[1]))
            if len(rest) == 2 and verb == "cancel" and method == "POST":
                op = _get_op(store, project, location, rest[1])
                raise _E(400, "FAILED_PRECONDITION", "Operation %s is already %s and cannot be cancelled." % (op["name"], op["status"]))
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)


def _clusters(store, method, project, location, rest, verb, payload, legacy):
    if not rest:
        if method == "POST":
            if legacy and payload.get("cluster") is None:
                raise _E(400, "INVALID_ARGUMENT", "Cluster must be specified.")
            return _json(200, create_cluster(store, project, location, payload))
        if method == "GET":
            if location != "-" and not _valid_location(location):
                raise _E(400, "INVALID_ARGUMENT", "Location %r does not exist." % location)
            out = [cluster_view(c) for n, c in sorted(store.clusters.items())
                   if n.startswith("projects/%s/locations/" % project) and (location == "-" or n.split("/")[3] == location)]
            return _json(200, {"clusters": out, "missingZones": []})
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on clusters collection." % method)
    cid = rest[0]
    if len(rest) == 1:
        if verb:
            if method != "POST":
                raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
            return _json(200, cluster_setting(store, project, location, cid, verb, payload))
        if method == "GET":
            return _json(200, cluster_view(_get(store, project, location, cid)))
        if method in ("PUT", "PATCH"):
            return _json(200, update_cluster(store, project, location, cid, payload))
        if method == "DELETE":
            return _json(200, delete_cluster(store, project, location, cid))
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on cluster." % method)
    if rest[1] != "nodePools":
        raise _E(404, "NOT_FOUND", "Unknown path.")
    c = _get(store, project, location, cid)
    if len(rest) == 2:
        if method == "GET":
            return _json(200, {"nodePools": _copy(c["nodePools"])})
        if method == "POST":
            return _json(200, create_pool(store, project, location, cid, payload))
        raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on nodePools collection." % method)
    pid = rest[2]
    if verb:
        if method != "POST":
            raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
        return _json(200, pool_setting(store, project, location, cid, pid, verb, payload))
    if method == "GET":
        return _json(200, _copy(_pool(c, pid)))
    if method in ("PUT", "PATCH"):
        return _json(200, pool_setting(store, project, location, cid, pid, "update", payload))
    if method == "DELETE":
        return _json(200, delete_pool(store, project, location, cid, pid))
    raise _E(405, "UNIMPLEMENTED", "Method %s not allowed on nodePool." % method)
