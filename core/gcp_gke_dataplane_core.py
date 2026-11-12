"""GKE *data plane* — a real, substrate-independent simulation of the Kubernetes objects a
cluster's own API server would hold (Namespaces, Deployments/StatefulSets/Jobs + their Pods,
Services/Ingresses/Gateways, Secrets/ConfigMaps, PersistentVolumeClaims/PersistentVolumes/
StorageClasses, read-only Nodes, and the ConfigManagement/Policy Controller singleton), keyed
per-cluster inside `core/gcp_container_core.py`'s `ContainerStore.k8s` dict (public-dict-only,
so it rides the same Nano persistence as clusters/node pools — see that module's docstring).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.

Why this exists: `core/gcp_container_core.py` models the GKE *control plane* (clusters, node
pools) but Vyomi runs no real Kubernetes API server behind a cluster's endpoint — see that
module's docstring and `core/capabilities/gcp/kubernetes.json`. Real kubectl/client-go talk
directly to `https://<cluster-endpoint>/api/v1/...`; Vyomi's relay has no per-cluster network
identity to dial, so this module is reached instead through the one address every other
resource on a cluster already has — its GKE resource name:
    /v1/projects/{p}/locations/{l}/clusters/{c}/k8s/{the real Kubernetes REST path}
e.g. .../k8s/api/v1/namespaces/default/pods, .../k8s/apis/apps/v1/namespaces/default/deployments,
.../k8s/apis/batch/v1/namespaces/default/jobs, .../k8s/apis/networking.k8s.io/v1/namespaces/{ns}/ingresses,
.../k8s/apis/gateway.networking.k8s.io/v1/namespaces/{ns}/gateways, .../k8s/apis/storage.k8s.io/v1/storageclasses,
.../k8s/api/v1/persistentvolumes, .../k8s/api/v1/nodes,
.../k8s/apis/configmanagement.gke.io/v1/configmanagements/config-management,
.../k8s/apis/constraints.gatekeeper.sh/v1beta1/k8srequiredlabels[/{name}].
Everything AFTER `/k8s/` is the literal, real Kubernetes API path/verb/body shape a real
client would send — only the routing prefix (needed because there is no real network) is
Vyomi-specific. Deployments/StatefulSets/Jobs materialize real owned Pod objects (a tiny
ReplicaSet-equivalent controller: scaling up/down and deleting a controller-owned Pod both
reconcile immediately, synchronously). Policy Controller constraints (`K8sRequiredLabels`)
are enforced on object admission, not just stored — see `_admission_check`.

What stays genuinely out of reach of a local simulator (see core/capabilities/gcp/kubernetes.json):
  - Config Sync's git pull: cloning a real external git repo needs real internet egress,
    which `tests/conformance/test_no_cloud_egress.py` and the "nothing leaves the simulator"
    rule forbid outright — so `spec.git` is stored (same shape a real ConfigManagement
    object carries) but never fetched.
  - Real compute telemetry (CPU/memory *utilization over time*): there is no real kubelet
    cAdvisor sampling a real container's cgroup, so Vyomi derives only STRUCTURAL numbers
    (counts, and requested-vs-allocatable sums from objects that are genuinely stored) —
    never a synthetic time series.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone

_K8S_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
DEFAULT_NAMESPACES = ("default", "kube-system", "kube-public", "kube-node-lease")
DEFAULT_STORAGE_CLASSES = (
    {"name": "standard-rwo", "provisioner": "pd.csi.storage.gke.io", "parameters": {"type": "pd-balanced"}, "default": True},
    {"name": "premium-rwo", "provisioner": "pd.csi.storage.gke.io", "parameters": {"type": "pd-ssd"}, "default": False},
    {"name": "standard", "provisioner": "kubernetes.io/gce-pd", "parameters": {"type": "pd-standard"}, "default": False},
)


class _KErr(Exception):
    """A real Kubernetes API error: the response body is a `Status` object, not Google's
    `{"error":{...}}` envelope — this module speaks the Kubernetes API, not a Google API."""
    def __init__(self, status, reason, message):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _copy(x):
    return json.loads(json.dumps(x))


def _uid(*parts):
    return hashlib.sha1("/".join(parts).encode()).hexdigest()


def _stable_hash(s):
    """A deterministic replacement for Python's builtin `hash()`, which is randomized
    per-process for strings — unusable for anything that must match across Nano/offline
    or survive a restart."""
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16)


def _check_name(kind, name):
    if not name or not _K8S_NAME.match(name) or len(name) > 63:
        raise _KErr(422, "Invalid", "%s %r is invalid: a lowercase RFC 1123 label must consist of lower case "
                                     "alphanumeric characters or '-', start and end with an alphanumeric character." % (kind, name))


# ── per-cluster store ───────────────────────────────────────────────────────
def ensure_cluster(k8s, cluster_full):
    """`k8s` is `ContainerStore.k8s` (plain dict). Returns (creating if absent) this
    cluster's nested dict of collections, seeded with the namespaces/StorageClasses every
    real GKE cluster already has the moment it comes up."""
    cs = k8s.get(cluster_full)
    if cs is not None:
        return cs
    now = _ts()
    cs = {
        "namespaces": {n: _namespace_obj(n, now) for n in DEFAULT_NAMESPACES},
        "deployments": {}, "statefulsets": {}, "jobs": {}, "pods": {},
        "services": {}, "ingresses": {}, "gateways": {},
        "secrets": {}, "configmaps": {},
        "pvcs": {}, "pvs": {},
        "storageclasses": {sc["name"]: _storageclass_obj(sc, now) for sc in DEFAULT_STORAGE_CLASSES},
        "configmanagement": None,
        "constraints": {},
    }
    k8s[cluster_full] = cs
    return cs


def _namespace_obj(name, now):
    return {"apiVersion": "v1", "kind": "Namespace",
            "metadata": {"name": name, "uid": _uid("ns", name), "creationTimestamp": now, "labels": {"kubernetes.io/metadata.name": name}},
            "status": {"phase": "Active"}}


def _storageclass_obj(sc, now):
    ann = {"storageclass.kubernetes.io/is-default-class": "true"} if sc.get("default") else {}
    return {"apiVersion": "storage.k8s.io/v1", "kind": "StorageClass",
            "metadata": {"name": sc["name"], "uid": _uid("sc", sc["name"]), "creationTimestamp": now, "annotations": ann},
            "provisioner": sc["provisioner"], "parameters": sc.get("parameters", {}),
            "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer", "allowVolumeExpansion": True}


# ── namespaces ──────────────────────────────────────────────────────────────
def list_namespaces(cs):
    return [_copy(n) for _, n in sorted(cs["namespaces"].items())]


def get_namespace(cs, name):
    n = cs["namespaces"].get(name)
    if not n:
        raise _KErr(404, "NotFound", "namespaces %r not found" % name)
    return _copy(n)


def create_namespace(cs, body):
    name = (body.get("metadata") or {}).get("name", "")
    _check_name("namespaces", name)
    if name in cs["namespaces"]:
        raise _KErr(409, "AlreadyExists", "namespaces %r already exists" % name)
    n = _namespace_obj(name, _ts())
    n["metadata"]["labels"].update((body.get("metadata") or {}).get("labels") or {})
    cs["namespaces"][name] = n
    return _copy(n)


def delete_namespace(cs, name):
    if name not in cs["namespaces"]:
        raise _KErr(404, "NotFound", "namespaces %r not found" % name)
    if name in DEFAULT_NAMESPACES:
        raise _KErr(403, "Forbidden", "namespace %r is a system namespace and cannot be deleted" % name)
    prefix = name + "/"
    for coll in ("deployments", "statefulsets", "jobs", "pods", "services", "ingresses", "gateways", "secrets", "configmaps", "pvcs"):
        for k in [k for k in cs[coll] if k.startswith(prefix)]:
            del cs[coll][k]
    del cs["namespaces"][name]
    return {"kind": "Status", "apiVersion": "v1", "status": "Success"}


def _require_ns(cs, ns):
    if ns not in cs["namespaces"]:
        raise _KErr(404, "NotFound", "namespaces %r not found" % ns)


# ── resource quantities (requests only — enough for a real, non-random cost rollup) ────────
def _parse_cpu(v):
    v = str(v or "0")
    return float(v[:-1]) / 1000 if v.endswith("m") else float(v or 0)


def _parse_mem(v):
    v = str(v or "0")
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024, "K": 1 / 1024, "M": 1, "G": 1024}
    for suf, mult in units.items():
        if v.endswith(suf):
            return float(v[: -len(suf)]) * mult
    return float(v or 0) / (1024 * 1024)


# ── Policy Controller admission ─────────────────────────────────────────────
def _admission_check(cs, kind, namespace, labels):
    cm = cs.get("configmanagement")
    if not cm or not (cm.get("spec", {}).get("policyController") or {}).get("enabled"):
        return
    labels = labels or {}
    for _, c in sorted(cs["constraints"].items()):
        m = c.get("spec", {}).get("match") or {}
        kinds = [k.get("kinds", []) for k in (m.get("kinds") or [{"kinds": []}])]
        kind_ok = not any(kinds) or any(kind in ks for ks in kinds)
        ns_ok = not m.get("namespaces") or namespace in m["namespaces"]
        if not (kind_ok and ns_ok):
            continue
        required = (c.get("spec", {}).get("parameters") or {}).get("labels") or []
        missing = [k for k in required if k not in labels]
        if missing:
            raise _KErr(403, "Forbidden",
                         'admission webhook "validation.gatekeeper.sh" denied the request: %s violation: '
                         'missing required labels: %s' % (c["metadata"]["name"], ", ".join(missing)))


# ── workloads: Deployment / StatefulSet (+ owned Pods) ──────────────────────
_WORKLOAD_GROUP_KIND = {"deployments": ("apps/v1", "Deployment"), "statefulsets": ("apps/v1", "StatefulSet")}


def _pod_template(owner, ns, name_prefix, index, labels, spec, phase, node):
    pod_name = "%s-%s" % (name_prefix, hashlib.sha1(("%s%d" % (name_prefix, index)).encode()).hexdigest()[:10])
    containers = spec.get("containers") or []
    h = hashlib.sha1(pod_name.encode()).hexdigest()
    ip = "10.%d.%d.%d" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    now = _ts()
    return pod_name, {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": pod_name, "namespace": ns, "uid": _uid("pod", ns, pod_name), "creationTimestamp": now,
                     "labels": dict(labels), "ownerReferences": [owner]},
        "spec": {"containers": containers, "nodeName": node},
        "status": {"phase": phase, "podIP": ip, "hostIP": "10.128.0.%d" % (_stable_hash(node) % 200 + 2) if node else None,
                    "conditions": [{"type": "Ready", "status": "True" if phase == "Running" else "False"}],
                    "containerStatuses": [{"name": c.get("name", "main"), "ready": phase == "Running", "restartCount": 0,
                                            "state": {"running": {"startedAt": now}} if phase == "Running" else {"terminated": {"reason": "Completed"}}} for c in containers]},
    }


def _reconcile_pods(cs, ns, name, owner_ref, labels, spec, want, phase, node):
    prefix = ns + "/"
    existing = {k: p for k, p in cs["pods"].items() if k.startswith(prefix) and any(
        r.get("name") == name and r.get("kind") == owner_ref["kind"] for r in p["metadata"].get("ownerReferences", []))}
    have = len(existing)
    if have < want:
        for i in range(have, want):
            pod_name, pod = _pod_template(owner_ref, ns, name, i, labels, spec, phase, node)
            cs["pods"]["%s/%s" % (ns, pod_name)] = pod
    elif have > want:
        for k in list(existing)[: have - want]:
            del cs["pods"][k]


def list_pods(cs, ns=None):
    items = [p for k, p in sorted(cs["pods"].items()) if ns is None or k.startswith(ns + "/")]
    return [_copy(p) for p in items]


def _owned_pods(cs, ns, kind, name):
    return [p for k, p in cs["pods"].items() if k.startswith(ns + "/") and any(
        r.get("kind") == kind and r.get("name") == name for r in p["metadata"].get("ownerReferences", []))]


def create_workload(cs, coll, ns, body, node_hint=None):
    api_version, kind = _WORKLOAD_GROUP_KIND[coll]
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name(coll, name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs[coll]:
        raise _KErr(409, "AlreadyExists", "%s %r already exists" % (coll, name))
    spec = body.get("spec") or {}
    tmpl = (spec.get("template") or {})
    tspec = tmpl.get("spec") or {}
    if not tspec.get("containers"):
        raise _KErr(422, "Invalid", "%s %r is invalid: spec.template.spec.containers: at least 1 container is required" % (kind, name))
    for c in tspec["containers"]:
        if not c.get("name") or not c.get("image"):
            raise _KErr(422, "Invalid", "%s %r is invalid: every container needs a name and an image" % (kind, name))
    labels = dict((tmpl.get("metadata") or {}).get("labels") or md.get("labels") or {"app": name})
    _admission_check(cs, kind, ns, labels)
    replicas = int(spec.get("replicas", 1))
    if replicas < 0:
        raise _KErr(422, "Invalid", "%s %r is invalid: spec.replicas must be >= 0" % (kind, name))
    now = _ts()
    obj = {
        "apiVersion": api_version, "kind": kind,
        "metadata": {"name": name, "namespace": ns, "uid": _uid(coll, ns, name), "creationTimestamp": now,
                     "labels": md.get("labels") or labels, "annotations": md.get("annotations") or {}},
        "spec": {"replicas": replicas, "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": tspec}},
        "status": {"replicas": replicas, "readyReplicas": replicas, "availableReplicas": replicas, "updatedReplicas": replicas,
                   "conditions": [{"type": "Available", "status": "True" if replicas else "False", "reason": "MinimumReplicasAvailable"}]},
    }
    cs[coll][key] = obj
    owner_ref = {"apiVersion": api_version, "kind": kind, "name": name, "uid": obj["metadata"]["uid"]}
    _reconcile_pods(cs, ns, name, owner_ref, labels, tspec, replicas, "Running", node_hint)
    return _copy(obj)


def list_workloads(cs, coll, ns=None):
    items = [w for k, w in sorted(cs[coll].items()) if ns is None or k.startswith(ns + "/")]
    out = []
    for w in items:
        v = _copy(w)
        v["_podsReady"] = len(_owned_pods(cs, w["metadata"]["namespace"], w["kind"], w["metadata"]["name"]))
        out.append(v)
    return out


def get_workload(cs, coll, ns, name):
    w = cs[coll].get("%s/%s" % (ns, name))
    if not w:
        raise _KErr(404, "NotFound", "%s %r not found" % (coll, name))
    return _copy(w)


def scale_workload(cs, coll, ns, name, replicas, node_hint=None):
    key = "%s/%s" % (ns, name)
    w = cs[coll].get(key)
    if not w:
        raise _KErr(404, "NotFound", "%s %r not found" % (coll, name))
    replicas = int(replicas)
    if replicas < 0:
        raise _KErr(422, "Invalid", "spec.replicas must be >= 0")
    w["spec"]["replicas"] = replicas
    w["status"].update(replicas=replicas, readyReplicas=replicas, availableReplicas=replicas, updatedReplicas=replicas)
    owner_ref = {"apiVersion": w["apiVersion"], "kind": w["kind"], "name": name, "uid": w["metadata"]["uid"]}
    _reconcile_pods(cs, ns, name, owner_ref, w["spec"]["template"]["metadata"]["labels"], w["spec"]["template"]["spec"], replicas, "Running", node_hint)
    return _copy(w)


def delete_workload(cs, coll, ns, name):
    key = "%s/%s" % (ns, name)
    w = cs[coll].get(key)
    if not w:
        raise _KErr(404, "NotFound", "%s %r not found" % (coll, name))
    for p in _owned_pods(cs, ns, w["kind"], name):
        del cs["pods"]["%s/%s" % (ns, p["metadata"]["name"])]
    del cs[coll][key]
    return {"kind": "Status", "apiVersion": "v1", "status": "Success"}


def delete_pod(cs, ns, name):
    key = "%s/%s" % (ns, name)
    p = cs["pods"].get(key)
    if not p:
        raise _KErr(404, "NotFound", "pods %r not found" % name)
    owners = p["metadata"].get("ownerReferences") or []
    del cs["pods"][key]
    # A controller-owned pod is replaced immediately — the same reconciliation a real
    # ReplicaSet/StatefulSet controller performs on the next sync.
    for ref in owners:
        coll = {"Deployment": "deployments", "StatefulSet": "statefulsets"}.get(ref["kind"])
        if coll and "%s/%s" % (ns, ref["name"]) in cs[coll]:
            w = cs[coll]["%s/%s" % (ns, ref["name"])]
            _reconcile_pods(cs, ns, ref["name"], ref, w["spec"]["template"]["metadata"]["labels"], w["spec"]["template"]["spec"], w["spec"]["replicas"], "Running", p["spec"].get("nodeName"))
    return {"kind": "Status", "apiVersion": "v1", "status": "Success"}


# ── Jobs (batch/v1): run-to-completion, no scaling endpoint ────────────────
def create_job(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("jobs", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["jobs"]:
        raise _KErr(409, "AlreadyExists", "jobs %r already exists" % name)
    spec = body.get("spec") or {}
    tmpl = spec.get("template") or {}
    tspec = tmpl.get("spec") or {}
    if not tspec.get("containers"):
        raise _KErr(422, "Invalid", "Job %r is invalid: spec.template.spec.containers: at least 1 container is required" % name)
    labels = dict((tmpl.get("metadata") or {}).get("labels") or md.get("labels") or {"job-name": name, "app": name})
    _admission_check(cs, "Job", ns, labels)
    parallelism = max(1, int(spec.get("parallelism", 1)))
    completions = max(parallelism, int(spec.get("completions", parallelism)))
    now = _ts()
    obj = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": ns, "uid": _uid("jobs", ns, name), "creationTimestamp": now, "labels": md.get("labels") or labels},
        "spec": {"parallelism": parallelism, "completions": completions, "selector": {"matchLabels": labels},
                 "template": {"metadata": {"labels": labels}, "spec": tspec}},
        "status": {"succeeded": completions, "active": 0, "failed": 0, "startTime": now, "completionTime": now,
                   "conditions": [{"type": "Complete", "status": "True"}]},
    }
    cs["jobs"][key] = obj
    owner_ref = {"apiVersion": "batch/v1", "kind": "Job", "name": name, "uid": obj["metadata"]["uid"]}
    _reconcile_pods(cs, ns, name, owner_ref, labels, tspec, completions, "Succeeded", None)
    return _copy(obj)


# ── Services / Ingress / Gateway ─────────────────────────────────────────────
def _cluster_ip(ns, name):
    h = hashlib.sha256(("svc" + ns + name).encode()).digest()
    return "10.%d.%d.%d" % (h[0] % 60 + 100, h[1], h[2] % 253 + 1)


def _lb_ip(seed):
    h = hashlib.sha256(seed.encode()).digest()
    return "35.%d.%d.%d" % (h[0] % 200 + 20, h[1], h[2] % 253 + 1)


def _match_pods(cs, ns, selector):
    if not selector:
        return []
    return [p for p in list_pods(cs, ns) if all(p["metadata"]["labels"].get(k) == v for k, v in selector.items())]


def create_service(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("services", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["services"]:
        raise _KErr(409, "AlreadyExists", "services %r already exists" % name)
    spec = body.get("spec") or {}
    svc_type = spec.get("type", "ClusterIP")
    if svc_type not in ("ClusterIP", "NodePort", "LoadBalancer"):
        raise _KErr(422, "Invalid", "spec.type: unsupported value %r" % svc_type)
    ports = spec.get("ports") or []
    if svc_type == "NodePort":
        for i, p in enumerate(ports):
            p.setdefault("nodePort", 30000 + (_stable_hash("%s%s%d" % (ns, name, i)) % 2767))
    now = _ts()
    obj = {"apiVersion": "v1", "kind": "Service",
           "metadata": {"name": name, "namespace": ns, "uid": _uid("svc", ns, name), "creationTimestamp": now, "labels": md.get("labels") or {}},
           "spec": {"type": svc_type, "selector": spec.get("selector") or {}, "ports": ports, "clusterIP": _cluster_ip(ns, name)},
           "status": {"loadBalancer": {"ingress": [{"ip": _lb_ip(key)}]}} if svc_type == "LoadBalancer" else {}}
    cs["services"][key] = obj
    return _copy(obj)


def list_services(cs, ns=None):
    out = []
    for k, s in sorted(cs["services"].items()):
        if ns is not None and not k.startswith(ns + "/"):
            continue
        v = _copy(s)
        v["_endpoints"] = len(_match_pods(cs, s["metadata"]["namespace"], s["spec"].get("selector")))
        out.append(v)
    return out


def create_ingress(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("ingresses", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["ingresses"]:
        raise _KErr(409, "AlreadyExists", "ingresses %r already exists" % name)
    spec = body.get("spec") or {}
    rules = spec.get("rules") or []
    for r in rules:
        for p in ((r.get("http") or {}).get("paths") or []):
            svc = ((p.get("backend") or {}).get("service") or {}).get("name")
            if svc and "%s/%s" % (ns, svc) not in cs["services"]:
                raise _KErr(422, "Invalid", "spec.rules: backend service %r not found in namespace %r" % (svc, ns))
    now = _ts()
    obj = {"apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
           "metadata": {"name": name, "namespace": ns, "uid": _uid("ing", ns, name), "creationTimestamp": now, "labels": md.get("labels") or {}},
           "spec": {"rules": rules, "ingressClassName": spec.get("ingressClassName", "gce")},
           "status": {"loadBalancer": {"ingress": [{"ip": _lb_ip(key)}]}}}
    cs["ingresses"][key] = obj
    return _copy(obj)


def create_gateway(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("gateways", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["gateways"]:
        raise _KErr(409, "AlreadyExists", "gateways %r already exists" % name)
    spec = body.get("spec") or {}
    if not spec.get("gatewayClassName"):
        raise _KErr(422, "Invalid", "spec.gatewayClassName is required")
    now = _ts()
    obj = {"apiVersion": "gateway.networking.k8s.io/v1", "kind": "Gateway",
           "metadata": {"name": name, "namespace": ns, "uid": _uid("gw", ns, name), "creationTimestamp": now, "labels": md.get("labels") or {}},
           "spec": {"gatewayClassName": spec["gatewayClassName"], "listeners": spec.get("listeners") or []},
           "status": {"addresses": [{"type": "IPAddress", "value": _lb_ip(key)}]}}
    cs["gateways"][key] = obj
    return _copy(obj)


def list_simple(cs, coll, ns=None):
    return [_copy(v) for k, v in sorted(cs[coll].items()) if ns is None or k.startswith(ns + "/")]


def get_simple(cs, coll, ns, name, kind):
    v = cs[coll].get("%s/%s" % (ns, name))
    if not v:
        raise _KErr(404, "NotFound", "%s %r not found" % (coll, name))
    return _copy(v)


def delete_simple(cs, coll, ns, name, kind):
    key = "%s/%s" % (ns, name)
    if key not in cs[coll]:
        raise _KErr(404, "NotFound", "%s %r not found" % (coll, name))
    del cs[coll][key]
    return {"kind": "Status", "apiVersion": "v1", "status": "Success"}


# ── Secrets / ConfigMaps ─────────────────────────────────────────────────────
def create_secret(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("secrets", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["secrets"]:
        raise _KErr(409, "AlreadyExists", "secrets %r already exists" % name)
    data = dict(body.get("data") or {})
    for k, v in (body.get("stringData") or {}).items():
        data[k] = base64.b64encode(str(v).encode()).decode()
    now = _ts()
    obj = {"apiVersion": "v1", "kind": "Secret",
           "metadata": {"name": name, "namespace": ns, "uid": _uid("sec", ns, name), "creationTimestamp": now, "labels": md.get("labels") or {}},
           "type": body.get("type", "Opaque"), "data": data}
    cs["secrets"][key] = obj
    return _copy(obj)


def create_configmap(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("configmaps", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["configmaps"]:
        raise _KErr(409, "AlreadyExists", "configmaps %r already exists" % name)
    now = _ts()
    obj = {"apiVersion": "v1", "kind": "ConfigMap",
           "metadata": {"name": name, "namespace": ns, "uid": _uid("cm", ns, name), "creationTimestamp": now, "labels": md.get("labels") or {}},
           "data": dict(body.get("data") or {})}
    cs["configmaps"][key] = obj
    return _copy(obj)


# ── Storage: StorageClasses (seeded) + PersistentVolumeClaims/Volumes ───────
def list_storageclasses(cs):
    return [_copy(v) for _, v in sorted(cs["storageclasses"].items())]


def create_pvc(cs, ns, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("persistentvolumeclaims", name)
    _require_ns(cs, ns)
    key = "%s/%s" % (ns, name)
    if key in cs["pvcs"]:
        raise _KErr(409, "AlreadyExists", "persistentvolumeclaims %r already exists" % name)
    spec = body.get("spec") or {}
    sc_name = spec.get("storageClassName") or next((n for n, v in cs["storageclasses"].items() if "is-default-class" in str(v["metadata"].get("annotations", {}))), "standard-rwo")
    if sc_name not in cs["storageclasses"]:
        raise _KErr(422, "Invalid", "spec.storageClassName: storageclass %r not found" % sc_name)
    size = ((spec.get("resources") or {}).get("requests") or {}).get("storage")
    if not size:
        raise _KErr(422, "Invalid", "spec.resources.requests.storage is required")
    now = _ts()
    pv_name = "pvc-%s" % _uid("pv", ns, name)[:20]
    pv = {"apiVersion": "v1", "kind": "PersistentVolume",
          "metadata": {"name": pv_name, "uid": _uid("pv", ns, name), "creationTimestamp": now},
          "spec": {"capacity": {"storage": size}, "accessModes": spec.get("accessModes") or ["ReadWriteOnce"],
                   "storageClassName": sc_name, "claimRef": {"namespace": ns, "name": name},
                   "csi": {"driver": "pd.csi.storage.gke.io", "volumeHandle": pv_name}},
          "status": {"phase": "Bound"}}
    cs["pvs"][pv_name] = pv
    pvc = {"apiVersion": "v1", "kind": "PersistentVolumeClaim",
           "metadata": {"name": name, "namespace": ns, "uid": _uid("pvc", ns, name), "creationTimestamp": now, "labels": md.get("labels") or {}},
           "spec": {"accessModes": spec.get("accessModes") or ["ReadWriteOnce"], "storageClassName": sc_name,
                     "resources": {"requests": {"storage": size}}, "volumeName": pv_name},
           "status": {"phase": "Bound", "capacity": {"storage": size}}}
    cs["pvcs"][key] = pvc
    return _copy(pvc)


def delete_pvc(cs, ns, name):
    key = "%s/%s" % (ns, name)
    pvc = cs["pvcs"].get(key)
    if not pvc:
        raise _KErr(404, "NotFound", "persistentvolumeclaims %r not found" % name)
    pv_name = pvc["spec"].get("volumeName")
    if pv_name in cs["pvs"]:
        del cs["pvs"][pv_name]
    del cs["pvcs"][key]
    return {"kind": "Status", "apiVersion": "v1", "status": "Success"}


def list_pvs(cs):
    return [_copy(v) for _, v in sorted(cs["pvs"].items())]


# ── Nodes — READ ONLY, computed from the cluster's real node pools (never stored,
# never random: a node pool with N nodes of machine type M always yields exactly N Node
# objects with M's real allocatable shape) ──────────────────────────────────
def list_nodes(cluster, shape_fn):
    pools = cluster.get("nodePools") or []
    out = []
    for p in pools:
        n = int(p.get("initialNodeCount") or 0)
        cpu, mem_gb = shape_fn(p["config"]["machineType"])
        for i in range(n):
            name = "gke-%s-%s-%s" % (cluster["name"], p["name"], hashlib.sha1(("%s%d" % (p["name"], i)).encode()).hexdigest()[:8])
            out.append({
                "apiVersion": "v1", "kind": "Node",
                "metadata": {"name": name, "labels": {"cloud.google.com/gke-nodepool": p["name"], "node.kubernetes.io/instance-type": p["config"]["machineType"]}},
                "status": {
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "allocatable": {"cpu": str(cpu), "memory": "%dMi" % int(mem_gb * 1024 * 0.95)},
                    "capacity": {"cpu": str(cpu), "memory": "%dMi" % int(mem_gb * 1024)},
                    "nodeInfo": {"kubeletVersion": p.get("version", ""), "osImage": p["config"].get("imageType", "")},
                },
            })
    return out


# ── ConfigManagement (Config Sync + Policy Controller) ──────────────────────
def get_configmanagement(cs):
    cm = cs.get("configmanagement")
    if not cm:
        cm = {"apiVersion": "configmanagement.gke.io/v1", "kind": "ConfigManagement",
              "metadata": {"name": "config-management"},
              "spec": {"git": None, "policyController": {"enabled": False}},
              "status": {"configSyncStatus": "", "policyControllerStatus": {"enabled": False, "constraintViolationCount": 0}}}
        cs["configmanagement"] = cm
    return _copy(cm)


def apply_configmanagement(cs, body):
    spec = body.get("spec") or {}
    cm = cs.get("configmanagement") or get_configmanagement(cs)
    cm["spec"]["git"] = spec.get("git")
    cm["spec"]["policyController"] = {"enabled": bool((spec.get("policyController") or {}).get("enabled"))}
    cm["status"]["configSyncStatus"] = "SYNCED" if spec.get("git") else ""
    cm["status"]["policyControllerStatus"] = {"enabled": cm["spec"]["policyController"]["enabled"],
                                               "constraintViolationCount": 0}
    cs["configmanagement"] = cm
    return _copy(cm)


def list_constraints(cs):
    return [_copy(v) for _, v in sorted(cs["constraints"].items())]


def create_constraint(cs, body):
    md = body.get("metadata") or {}
    name = md.get("name", "")
    _check_name("k8srequiredlabels", name)
    if name in cs["constraints"]:
        raise _KErr(409, "AlreadyExists", "k8srequiredlabels %r already exists" % name)
    spec = body.get("spec") or {}
    if not (spec.get("parameters") or {}).get("labels"):
        raise _KErr(422, "Invalid", "spec.parameters.labels: at least one required label key is needed")
    obj = {"apiVersion": "constraints.gatekeeper.sh/v1beta1", "kind": "K8sRequiredLabels",
           "metadata": {"name": name, "uid": _uid("constraint", name), "creationTimestamp": _ts()},
           "spec": {"match": spec.get("match") or {"kinds": [{"kinds": []}]}, "parameters": {"labels": list(spec["parameters"]["labels"])}}}
    cs["constraints"][name] = obj
    return _copy(obj)


def delete_constraint(cs, name):
    if name not in cs["constraints"]:
        raise _KErr(404, "NotFound", "k8srequiredlabels %r not found" % name)
    del cs["constraints"][name]
    return {"kind": "Status", "apiVersion": "v1", "status": "Success"}


# ── Observability: real, derived-only counts (never a synthetic time series) ───────────────
def resource_counts(cs):
    workloads = len(cs["deployments"]) + len(cs["statefulsets"]) + len(cs["jobs"])
    requested_cpu = requested_mem = 0.0
    for p in cs["pods"].values():
        for c in p["spec"].get("containers", []):
            req = (c.get("resources") or {}).get("requests") or {}
            requested_cpu += _parse_cpu(req.get("cpu"))
            requested_mem += _parse_mem(req.get("memory"))
    return {
        "namespaces": len(cs["namespaces"]), "workloads": workloads, "pods": len(cs["pods"]),
        "deployments": len(cs["deployments"]), "statefulsets": len(cs["statefulsets"]), "jobs": len(cs["jobs"]),
        "services": len(cs["services"]), "ingresses": len(cs["ingresses"]), "gateways": len(cs["gateways"]),
        "secrets": len(cs["secrets"]), "configmaps": len(cs["configmaps"]),
        "pvcs": len(cs["pvcs"]), "storageclasses": len(cs["storageclasses"]),
        "requestedCpu": round(requested_cpu, 3), "requestedMemoryMi": round(requested_mem, 1),
    }


def observability(cs, cluster, shape_fn):
    """Everything here is derived from objects genuinely stored in `cs` and the cluster's
    real node pools — a cost-optimization-style requested-vs-allocatable rollup, never a
    synthetic time series. See core/capabilities/gcp/kubernetes.json's `gcp.kubernetes.observability`."""
    counts = resource_counts(cs)
    allocatable_cpu = allocatable_mem = 0.0
    for p in (cluster.get("nodePools") or []):
        n = int(p.get("initialNodeCount") or 0)
        cpu, mem_gb = shape_fn(p["config"]["machineType"])
        allocatable_cpu += cpu * n
        allocatable_mem += mem_gb * 1024 * n
    counts["allocatableCpu"] = round(allocatable_cpu, 3)
    counts["allocatableMemoryMi"] = round(allocatable_mem, 1)
    counts["cpuUtilizationPct"] = round(100 * counts["requestedCpu"] / allocatable_cpu, 1) if allocatable_cpu else 0.0
    counts["memoryUtilizationPct"] = round(100 * counts["requestedMemoryMi"] / allocatable_mem, 1) if allocatable_mem else 0.0
    return counts


# ── applications: a computed grouping of workloads by their app label — no extra storage ───
def list_applications(cs):
    groups = {}
    for coll, kind in (("deployments", "Deployment"), ("statefulsets", "StatefulSet"), ("jobs", "Job")):
        for w in cs[coll].values():
            labels = w["metadata"].get("labels") or {}
            app = labels.get("app.kubernetes.io/name") or labels.get("app") or w["metadata"]["name"]
            g = groups.setdefault((w["metadata"]["namespace"], app), {"name": app, "namespace": w["metadata"]["namespace"], "workloads": 0, "pods": 0})
            g["workloads"] += 1
            g["pods"] += len(_owned_pods(cs, w["metadata"]["namespace"], kind, w["metadata"]["name"]))
    return sorted(groups.values(), key=lambda g: (g["namespace"], g["name"]))
