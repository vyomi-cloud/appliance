# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AKS Kubernetes object store + the `kubectl` subset behind runCommand (substrate-free).

Real AKS answers `az aks command invoke` (ARM POST .../managedClusters/{c}/runCommand) by running
the command in a pod against the cluster's API server. Vyomi runs no API server, kubelet or
container runtime — but it CAN hold the Kubernetes objects a user applies, exactly as an API
server's etcd would, so that the cluster's Workloads / Services and ingresses blades and the
Kubescape posture scan (Microsoft Defender for Cloud) see real objects. This module is that store:

  * objects live ON the cluster's ARM record (``rec["_k8s"]``) — persisted with the rest of the
    ARM state on both substrates (Nano IndexedDB snapshot / offline kernel state store), JSON-only,
    and deleted with the cluster;
  * namespaces stay ONE truth: ``properties.namespaces`` (what the Namespaces blade edits over
    ARM) — `kubectl apply` of a Namespace adds to it, deleting one removes it and cascades its
    objects, like the real namespace controller;
  * nothing is scheduled: workload ``status`` says so (0 ready replicas, Pods ``Pending`` with a
    ``PodScheduled=False`` condition whose message is "Not scheduled — Vyomi doesn't run
    containers"), Services get a ClusterIP from the cluster's serviceCidr and LoadBalancers stay
    ``<pending>`` (no cloud load balancer is provisioned);
  * real controllers DO run for storage and events: a PersistentVolumeClaim is bound to a volume
    (static, by ``spec.volumeName``, or dynamically provisioned from its StorageClass — AKS's
    disk/file CSI driver add-ons seed the usual default StorageClasses on every new cluster) and
    released/deleted on the claim's reclaim policy when it's removed; every one of those
    mutations — and the honest scheduling/load-balancer/ingress failures above — emits a real
    Event object, listed and gettable like any other kind;
  * CustomResourceDefinitions are themselves stored objects: once one is applied, its Kind is
    registered for this cluster and its custom resource instances apply/get/describe/delete like
    any built-in kind (``_kind_spec``/``_resolve_kind`` fall back to a cluster's own CRDs).

Supported kubectl: apply / create -f (files from the runCommand ``context`` zip, `-f -` with a
heredoc or `cat <<EOF |` pipe), create namespace, get (table, -o json|yaml|name|wide, -A, -n,
-l), describe (YAML view), delete (-f or kind/name), scale, version, api-resources. Anything
else — logs, exec, port-forward, rollout, helm, … — fails with exit code 1 and an honest reason
(there is no running container or API server to talk to), never a fake success.

Kinds: Namespace, Pod, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job, CronJob, Service,
ConfigMap, Secret (``stringData`` folded into base64 ``data`` like the real API server),
ServiceAccount, Role, ClusterRole, RoleBinding, ClusterRoleBinding, NetworkPolicy, Ingress,
PersistentVolume, PersistentVolumeClaim, StorageClass, Event, CustomResourceDefinition (+ any
Kind a cluster's own CRDs register).
"""
from __future__ import annotations

import base64
import binascii
import copy
import datetime
import io
import ipaddress
import json
import re
import shlex
import uuid
import zipfile
import zlib

try:
    from core import k8s_yaml
except ImportError:                     # Pyodide flat layout
    import k8s_yaml                     # type: ignore

# kind -> (group, versions, plural, short names, namespaced)
KINDS = {
    "Namespace":          ("", ["v1"], "namespaces", ["ns"], False),
    "Pod":                ("", ["v1"], "pods", ["po"], True),
    "Service":            ("", ["v1"], "services", ["svc"], True),
    "ConfigMap":          ("", ["v1"], "configmaps", ["cm"], True),
    "Secret":             ("", ["v1"], "secrets", [], True),
    "ServiceAccount":     ("", ["v1"], "serviceaccounts", ["sa"], True),
    "Deployment":         ("apps", ["v1"], "deployments", ["deploy"], True),
    "ReplicaSet":         ("apps", ["v1"], "replicasets", ["rs"], True),
    "StatefulSet":        ("apps", ["v1"], "statefulsets", ["sts"], True),
    "DaemonSet":          ("apps", ["v1"], "daemonsets", ["ds"], True),
    "Job":                ("batch", ["v1"], "jobs", [], True),
    "CronJob":            ("batch", ["v1"], "cronjobs", ["cj"], True),
    "Role":               ("rbac.authorization.k8s.io", ["v1"], "roles", [], True),
    "ClusterRole":        ("rbac.authorization.k8s.io", ["v1"], "clusterroles", [], False),
    "RoleBinding":        ("rbac.authorization.k8s.io", ["v1"], "rolebindings", [], True),
    "ClusterRoleBinding": ("rbac.authorization.k8s.io", ["v1"], "clusterrolebindings", [], False),
    "NetworkPolicy":      ("networking.k8s.io", ["v1"], "networkpolicies", ["netpol"], True),
    "Ingress":            ("networking.k8s.io", ["v1"], "ingresses", ["ing"], True),
    "PersistentVolume":      ("", ["v1"], "persistentvolumes", ["pv"], False),
    "PersistentVolumeClaim": ("", ["v1"], "persistentvolumeclaims", ["pvc"], True),
    "StorageClass":          ("storage.k8s.io", ["v1"], "storageclasses", ["sc"], False),
    "Event":                 ("", ["v1"], "events", ["ev"], True),
    "CustomResourceDefinition": ("apiextensions.k8s.io", ["v1"], "customresourcedefinitions", ["crd", "crds"], False),
}
WORKLOAD_KINDS = ("Deployment", "ReplicaSet", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod")
NOT_SCHEDULED = "Not scheduled — Vyomi doesn't run containers"

_ALIASES = {}
for _k, (_g, _v, _plural, _short, _ns) in KINDS.items():
    for _a in [_k.lower(), _plural, _plural.rstrip("s") if _plural.endswith("s") else _plural, *_short]:
        _ALIASES[_a] = _k
    if _g:
        _ALIASES[f"{_plural}.{_g}"] = _k
        _ALIASES[f"{_k.lower()}.{_g}"] = _k
_ALIASES.update({"ingress": "Ingress", "networkpolicy": "NetworkPolicy", "policy": "NetworkPolicy"})


class KubectlError(Exception):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store(rec: dict) -> dict:
    st = rec.setdefault("_k8s", {})
    st.setdefault("objects", {})
    st.setdefault("rv", 0)
    return st


def version(rec: dict) -> str:
    """Change stamp of everything a scan reads: the object store's counter + the namespace list
    (which the Namespaces blade edits over ARM, outside kubectl). Drives scan staleness."""
    nss = json.dumps([[n.get("name"), n.get("labels") or {}] for n in ((rec.get("properties") or {}).get("namespaces") or [])],
                     sort_keys=True)
    return f"{int((rec.get('_k8s') or {}).get('rv', 0))}-{zlib.crc32(nss.encode()) & 0xffffffff:08x}"


def _kind_spec(rec: dict, kind: str):
    """(group, versions, plural, shortNames, namespaced) for a built-in kind, or for a custom
    kind registered by a CustomResourceDefinition this cluster has applied. None if unknown."""
    spec = KINDS.get(kind)
    if spec is not None:
        return spec
    for crd in _store(rec)["objects"].values():
        if crd.get("kind") != "CustomResourceDefinition":
            continue
        names = (crd.get("spec") or {}).get("names") or {}
        if names.get("kind") != kind:
            continue
        group = (crd.get("spec") or {}).get("group") or ""
        versions = [v.get("name") for v in (crd.get("spec") or {}).get("versions") or [] if isinstance(v, dict) and v.get("name")]
        namespaced = ((crd.get("spec") or {}).get("scope") or "Namespaced") == "Namespaced"
        return (group, versions or ["v1"], names.get("plural") or kind.lower() + "s", list(names.get("shortNames") or []), namespaced)
    return None


def _prune(rec: dict) -> None:
    """Objects of a namespace removed over ARM (Namespaces blade) go with it — the namespace
    controller's cascade."""
    st = rec.get("_k8s") or {}
    objs = st.get("objects") or {}
    live = {n.get("name") for n in ((rec.get("properties") or {}).get("namespaces") or [])}
    gone = [k for k, o in objs.items() if (_kind_spec(rec, o.get("kind")) or ("", [], "", [], False))[4]
            and (o.get("metadata") or {}).get("namespace") not in live]
    for k in gone:
        del objs[k]
    if gone:
        st["rv"] = int(st.get("rv", 0)) + 1


def _key(kind: str, ns: str, name: str) -> str:
    return f"{kind}/{ns or ''}/{name}"


def _namespaces(rec: dict) -> list:
    return rec.setdefault("properties", {}).setdefault("namespaces", [])


def _ns_exists(rec: dict, ns: str) -> bool:
    return any(n.get("name") == ns for n in _namespaces(rec))


def _age(ts) -> str:
    try:
        t = datetime.datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return "<unknown>"
    s = max(0, int((datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()))
    if s < 120:
        return f"{s}s"
    if s < 7200:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


# ── object model ─────────────────────────────────────────────────────────────────────────
def namespace_object(entry: dict, created: str = "") -> dict:
    md = {"name": entry.get("name"), "creationTimestamp": entry.get("createdAt") or entry.get("creationTimestamp") or created or "",
          "uid": entry.get("uid") or str(uuid.uuid5(uuid.NAMESPACE_URL, "ns/" + str(entry.get("name"))))}
    labels = dict(entry.get("labels") or {})
    labels.setdefault("kubernetes.io/metadata.name", entry.get("name"))
    md["labels"] = labels
    if entry.get("annotations"):
        md["annotations"] = dict(entry["annotations"])
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": md,
            "spec": {"finalizers": ["kubernetes"]}, "status": {"phase": entry.get("status") or "Active"}}


def list_objects(rec: dict, kind: str | None = None, namespace: str | None = None) -> list:
    _prune(rec)
    out = []
    if kind in (None, "Namespace"):
        if namespace is None:
            out += [namespace_object(n, str(rec.get("_created") or "")) for n in _namespaces(rec)]
    for obj in _store(rec)["objects"].values():
        if kind and obj.get("kind") != kind:
            continue
        nsd = (_kind_spec(rec, obj["kind"]) or ("", [], "", [], False))[4]
        if namespace is not None and nsd and obj["metadata"].get("namespace") != namespace:
            continue
        if namespace is not None and not nsd:
            continue
        out.append(obj)
    out.sort(key=lambda o: (o["kind"], o["metadata"].get("namespace") or "", o["metadata"]["name"]))
    return out


def export_objects(rec: dict) -> list:
    """Every object in the cluster (namespaces included), as a Kubernetes API list would return —
    the input a Kubescape scan gets."""
    return copy.deepcopy(list_objects(rec))


def _service_ip(rec: dict, taken: set) -> str:
    cidr = ((rec.get("properties") or {}).get("networkProfile") or {}).get("serviceCidr") or "10.0.0.0/16"
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        net = ipaddress.ip_network("10.0.0.0/16")
    dns = ((rec.get("properties") or {}).get("networkProfile") or {}).get("dnsServiceIP")
    for i, host in enumerate(net.hosts()):
        if i < 1:
            continue                     # .1 is the kubernetes service in a real cluster
        ip = str(host)
        if ip != dns and ip not in taken:
            return ip
        if i > 65000:
            break
    raise KubectlError("error: the Service's ClusterIP range is exhausted")


def _validate(doc, default_ns: str, rec: dict, pending_ns: set) -> dict:
    if not isinstance(doc, dict):
        raise KubectlError("error: error validating data: the object is not a Kubernetes object (expected a mapping)")
    av, kind = doc.get("apiVersion"), doc.get("kind")
    md = doc.get("metadata") or {}
    if not av or not kind:
        raise KubectlError("error: error validating data: [apiVersion not set, kind not set]" if not av and not kind
                           else f"error: error validating data: {'apiVersion' if not av else 'kind'} not set")
    spec = KINDS.get(kind) or _kind_spec(rec, kind)
    group, ver = (av.split("/", 1) if "/" in av else ("", av))
    if spec is None or group != spec[0] or ver not in spec[1]:
        raise KubectlError(f'error: resource mapping not found for name: "{md.get("name", "")}" namespace: "{md.get("namespace", "")}" '
                           f'from "STDIN": no matches for kind "{kind}" in version "{av}"\n'
                           f"ensure CRDs are installed first (`kubectl apply` a CustomResourceDefinition for \"{kind}\" "
                           f"before applying its custom resources)")
    name = md.get("name")
    if not name or not re.match(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$", str(name)):
        raise KubectlError(f'The {kind} "{name or ""}" is invalid: metadata.name: Invalid value: "{name or ""}": a lowercase RFC 1123 subdomain must consist of lower case alphanumeric characters, \'-\' or \'.\'')
    obj = copy.deepcopy(doc)
    obj["metadata"] = dict(md)
    if spec[4]:
        ns = md.get("namespace") or default_ns
        if not _ns_exists(rec, ns) and ns not in pending_ns:
            raise KubectlError(f'Error from server (NotFound): error when creating "STDIN": namespaces "{ns}" not found')
        obj["metadata"]["namespace"] = ns
    else:
        obj["metadata"].pop("namespace", None)
    if kind == "Secret":
        data = dict(obj.get("data") or {})
        for k, v in (obj.pop("stringData", None) or {}).items():
            data[k] = base64.b64encode(str(v).encode()).decode()
        for k, v in data.items():
            try:
                base64.b64decode(str(v), validate=True)
            except (binascii.Error, ValueError):
                raise KubectlError(f'Error from server (BadRequest): error when creating "STDIN": Secret in version "v1" cannot be handled as a Secret: illegal base64 data at input byte 0 (key "{k}")')
        obj["data"] = data
        obj.setdefault("type", "Opaque")
    elif kind == "StorageClass" and not obj.get("provisioner"):
        raise KubectlError(f'StorageClass.storage.k8s.io "{name}" is invalid: provisioner: Required value')
    elif kind == "CustomResourceDefinition":
        _validate_crd(obj)
    return obj


def _validate_crd(obj: dict) -> None:
    cname = obj["metadata"].get("name")
    spec = obj.get("spec") or {}
    group = spec.get("group")
    names = spec.get("names") or {}
    plural, kind_name = names.get("plural"), names.get("kind")
    versions = [v for v in (spec.get("versions") or []) if isinstance(v, dict) and v.get("name")]
    if not group or not plural or not kind_name or not versions:
        raise KubectlError(f'The CustomResourceDefinition "{cname}" is invalid: spec.group, spec.names.plural, '
                           f"spec.names.kind and at least one spec.versions entry are required")
    want_name = f"{plural}.{group}"
    if cname != want_name:
        raise KubectlError(f'The CustomResourceDefinition "{cname}" is invalid: metadata.name: Invalid value: '
                           f'"{cname}": must be spec.names.plural + "." + spec.group ("{want_name}")')
    if (spec.get("scope") or "Namespaced") not in ("Namespaced", "Cluster"):
        raise KubectlError(f'The CustomResourceDefinition "{cname}" is invalid: spec.scope: Unsupported value: '
                           f'"{spec.get("scope")}": supported values: "Namespaced", "Cluster"')


_WORKLOAD_COMPONENT = {"Deployment": "deployment-controller", "ReplicaSet": "replicaset-controller",
                       "StatefulSet": "statefulset-controller", "DaemonSet": "daemonset-controller",
                       "Job": "job-controller", "CronJob": "cronjob-controller"}


def _emit_event(rec: dict, obj: dict, type_: str, reason: str, message: str, component: str) -> None:
    """Store one Event the way a real controller/scheduler would after acting on `obj` — tied to
    a real mutation, never a fabricated readout. Events are regular stored objects (kubectl get
    events, -A, -o json, … all work on them like any other kind)."""
    st = _store(rec)
    md = obj["metadata"]
    ns = md.get("namespace") or "default"
    now = _now()
    name = f"{md['name']}.{uuid.uuid4().hex[:16]}"
    ev = {
        "apiVersion": "v1", "kind": "Event",
        "metadata": {"name": name, "namespace": ns, "uid": str(uuid.uuid4()),
                     "creationTimestamp": now, "resourceVersion": str(st["rv"])},
        "involvedObject": {"apiVersion": obj.get("apiVersion", "v1"), "kind": obj["kind"],
                           "name": md["name"], "namespace": md.get("namespace")},
        "reason": reason, "message": message, "type": type_,
        "source": {"component": component}, "firstTimestamp": now, "lastTimestamp": now, "count": 1,
    }
    st["objects"][_key("Event", ns, name)] = ev
    st["rv"] += 1


def _decorate(rec: dict, obj: dict, prev: dict | None, rv: int, applied: dict | None):
    md = obj["metadata"]
    md["uid"] = (prev or {}).get("metadata", {}).get("uid") or str(uuid.uuid4())
    md["creationTimestamp"] = (prev or {}).get("metadata", {}).get("creationTimestamp") or _now()
    md["resourceVersion"] = str(rv)
    gen = int((prev or {}).get("metadata", {}).get("generation", 0))
    if prev is None or json.dumps(prev.get("spec"), sort_keys=True) != json.dumps(obj.get("spec"), sort_keys=True):
        gen += 1
    if obj["kind"] in WORKLOAD_KINDS or obj["kind"] in ("Service", "Ingress", "NetworkPolicy"):
        md["generation"] = max(gen, 1)
    if applied is not None:
        ann = dict(md.get("annotations") or {})
        ann["kubectl.kubernetes.io/last-applied-configuration"] = json.dumps(applied, separators=(",", ":"), sort_keys=True) + "\n"
        md["annotations"] = ann
    kind = obj["kind"]
    spec = obj.setdefault("spec", {}) if kind not in ("ConfigMap", "Secret", "ServiceAccount", "Role", "ClusterRole",
                                                      "RoleBinding", "ClusterRoleBinding", "StorageClass") else None
    cond = {"type": "Available", "status": "False", "reason": "VyomiNotScheduled", "message": NOT_SCHEDULED,
            "lastTransitionTime": md["creationTimestamp"]}
    if kind in ("Deployment", "ReplicaSet", "StatefulSet"):
        desired = spec.get("replicas", 1) if isinstance(spec.get("replicas", 1), int) else 1
        spec.setdefault("replicas", desired)
        obj["status"] = {"observedGeneration": md.get("generation", 1), "replicas": 0, "readyReplicas": 0,
                         "availableReplicas": 0, "updatedReplicas": 0,
                         **({"unavailableReplicas": desired} if kind == "Deployment" else {}),
                         "conditions": [cond]}
        if prev is None:
            _emit_event(rec, obj, "Warning", "FailedCreate", f"Error creating: {NOT_SCHEDULED}", _WORKLOAD_COMPONENT[kind])
    elif kind == "DaemonSet":
        obj["status"] = {"observedGeneration": md.get("generation", 1), "currentNumberScheduled": 0,
                         "desiredNumberScheduled": 0, "numberReady": 0, "numberAvailable": 0, "numberMisscheduled": 0,
                         "conditions": [cond]}
        if prev is None:
            _emit_event(rec, obj, "Warning", "FailedCreate", f"Error creating: {NOT_SCHEDULED}", _WORKLOAD_COMPONENT[kind])
    elif kind == "Job":
        obj["status"] = {"active": 0, "succeeded": 0, "failed": 0,
                         "conditions": [{**cond, "type": "Complete"}]}
        if prev is None:
            _emit_event(rec, obj, "Warning", "FailedCreate", f"Error creating: {NOT_SCHEDULED}", _WORKLOAD_COMPONENT[kind])
    elif kind == "CronJob":
        obj["status"] = {"active": [], "lastScheduleTime": None}
    elif kind == "Pod":
        obj["status"] = {"phase": "Pending", "qosClass": _qos(spec),
                         "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable",
                                         "message": NOT_SCHEDULED, "lastTransitionTime": md["creationTimestamp"]}]}
        if prev is None:
            _emit_event(rec, obj, "Warning", "FailedScheduling", NOT_SCHEDULED, "default-scheduler")
    elif kind == "Service":
        stype = spec.get("type") or "ClusterIP"
        spec["type"] = stype
        if stype != "ExternalName" and spec.get("clusterIP") != "None":
            prev_ip = ((prev or {}).get("spec") or {}).get("clusterIP")
            if not spec.get("clusterIP"):
                taken = {(o.get("spec") or {}).get("clusterIP") for o in _store(rec)["objects"].values() if o.get("kind") == "Service"}
                spec["clusterIP"] = prev_ip or _service_ip(rec, taken)
            spec["clusterIPs"] = [spec["clusterIP"]]
        for p in spec.get("ports") or []:
            if isinstance(p, dict):
                p.setdefault("protocol", "TCP")
                p.setdefault("targetPort", p.get("port"))
        obj["status"] = {"loadBalancer": {}}
        if prev is None and stype == "LoadBalancer":
            _emit_event(rec, obj, "Warning", "SyncLoadBalancerFailed",
                       "Error syncing load balancer: no cloud load balancer provider runs in Vyomi", "service-controller")
    elif kind == "Ingress":
        obj["status"] = {"loadBalancer": {}}
        if prev is None:
            _emit_event(rec, obj, "Warning", "Sync", "no ingress controller runs in Vyomi to assign an address", "ingress-controller")
    elif kind == "PersistentVolumeClaim":
        # A reapply of an already-bound claim keeps its binding — only a brand-new claim starts
        # Pending and goes through dynamic provisioning (_provision_pvc, called by _put).
        if prev is not None and (prev.get("status") or {}).get("phase") == "Bound":
            obj["status"] = dict(prev["status"])
            obj["spec"]["volumeName"] = (prev.get("spec") or {}).get("volumeName")
        else:
            obj["status"] = {"phase": "Pending"}
    elif kind == "PersistentVolume":
        obj["status"] = dict(prev["status"]) if prev is not None and prev.get("status") else {"phase": "Available"}


def _qos(spec: dict) -> str:
    cs = (spec or {}).get("containers") or []
    if cs and all(((c or {}).get("resources") or {}).get("limits") for c in cs):
        return "Guaranteed"
    if any(((c or {}).get("resources") or {}) for c in cs):
        return "Burstable"
    return "BestEffort"


def _put(rec: dict, obj: dict, mode: str, applied=None) -> str:
    """Store one validated object. mode: apply | create | replace. Returns kubectl's verb."""
    st = _store(rec)
    kind, md = obj["kind"], obj["metadata"]
    if kind == "Namespace":
        nss = _namespaces(rec)
        cur = next((n for n in nss if n.get("name") == md["name"]), None)
        if cur is not None and mode == "create":
            raise KubectlError(f'Error from server (AlreadyExists): error when creating "STDIN": namespaces "{md["name"]}" already exists')
        if cur is None:
            nss.append({"name": md["name"], "status": "Active", "createdAt": _now(),
                        "uid": str(uuid.uuid4()), "labels": dict(md.get("labels") or {})})
            st["rv"] += 1
            return "created"
        changed = dict(md.get("labels") or {}) != dict(cur.get("labels") or {})
        cur["labels"] = dict(md.get("labels") or {})
        if changed:
            st["rv"] += 1
        return "configured" if changed else "unchanged"
    key = _key(kind, md.get("namespace"), md["name"])
    prev = st["objects"].get(key)
    if prev is not None and mode == "create":
        rspec = _kind_spec(rec, kind) or ("", [], kind.lower(), [], True)
        raise KubectlError(f'Error from server (AlreadyExists): error when creating "STDIN": {rspec[2]}{"." + rspec[0] if rspec[0] else ""} "{md["name"]}" already exists')
    if prev is not None:
        def _cmp(o):
            o = copy.deepcopy(o)
            o.pop("status", None)
            m = o.get("metadata") or {}
            for f in ("uid", "creationTimestamp", "resourceVersion", "generation"):
                m.pop(f, None)
            (m.get("annotations") or {}).pop("kubectl.kubernetes.io/last-applied-configuration", None)
            if not m.get("annotations"):
                m.pop("annotations", None)
            if o.get("kind") == "Service":
                for f in ("clusterIP", "clusterIPs"):
                    (o.get("spec") or {}).pop(f, None)
                for p in (o.get("spec") or {}).get("ports") or []:
                    if isinstance(p, dict):
                        p.pop("protocol", None); p.pop("targetPort", None)
                (o.get("spec") or {}).pop("type", None) if (o.get("spec") or {}).get("type") == "ClusterIP" else None
            if o.get("kind") in ("Deployment", "ReplicaSet", "StatefulSet") and (o.get("spec") or {}).get("replicas") == 1:
                o["spec"].pop("replicas", None)
            if o.get("kind") == "Secret" and o.get("type") == "Opaque":
                o.pop("type", None)
            if o.get("kind") == "PersistentVolumeClaim":
                (o.get("spec") or {}).pop("volumeName", None)       # set by dynamic provisioning, not user input
            return json.dumps(o, sort_keys=True)
        if _cmp(prev) == _cmp(obj):
            return "unchanged"
    st["rv"] += 1
    _decorate(rec, obj, prev, st["rv"], applied)
    st["objects"][key] = obj
    if kind == "PersistentVolumeClaim" and prev is None:
        _provision_pvc(rec, obj)
    return "configured" if prev is not None else "created"


def _provision_pvc(rec: dict, pvc: dict) -> None:
    """Bind a brand-new PersistentVolumeClaim the way the real persistentvolume-controller would:
    static provisioning (spec.volumeName names an existing, unbound PV) or dynamic provisioning
    (the resolved StorageClass gets a freshly "provisioned" PV, matching AKS's disk/file CSI
    driver default). A claim with no resolvable volume or storage class just stays Pending —
    the same outcome a real cluster gives, never a fake Bound."""
    st = _store(rec)
    spec = pvc.setdefault("spec", {})
    md = pvc["metadata"]
    vol = spec.get("volumeName")
    if vol:
        pv = st["objects"].get(_key("PersistentVolume", None, vol))
        if pv is None or (pv.get("spec") or {}).get("claimRef"):
            _emit_event(rec, pvc, "Warning", "ProvisioningFailed",
                       f'persistentvolume "{vol}" {"not found" if pv is None else "is already bound to another claim"}',
                       "persistentvolume-controller")
            return
        pv["spec"]["claimRef"] = {"name": md["name"], "namespace": md["namespace"]}
        pv["status"] = {"phase": "Bound"}
        pvc["status"] = {"phase": "Bound", "accessModes": list(pv["spec"].get("accessModes") or []),
                         "capacity": dict(pv["spec"].get("capacity") or {})}
        st["rv"] += 1
        _emit_event(rec, pvc, "Normal", "ProvisioningSucceeded", f'Successfully bound to pre-provisioned volume "{vol}"', "persistentvolume-controller")
        return
    sc_name = spec.get("storageClassName")
    if sc_name is None:
        for o in st["objects"].values():
            if o.get("kind") == "StorageClass" and (o.get("metadata", {}).get("annotations") or {}).get("storageclass.kubernetes.io/is-default-class") == "true":
                sc_name = o["metadata"]["name"]
                break
    if not sc_name:
        return                                          # no storage class resolved — stays Pending, like real k8s
    sc = st["objects"].get(_key("StorageClass", None, sc_name))
    if sc is None:
        _emit_event(rec, pvc, "Warning", "ProvisioningFailed", f'storageclass.storage.k8s.io "{sc_name}" not found', "persistentvolume-controller")
        return
    capacity = ((spec.get("resources") or {}).get("requests") or {}).get("storage") or "1Gi"
    pv_name = f"pvc-{uuid.uuid4()}"
    now = _now()
    access_modes = list(spec.get("accessModes") or ["ReadWriteOnce"])
    pv = {
        "apiVersion": "v1", "kind": "PersistentVolume",
        "metadata": {"name": pv_name, "uid": str(uuid.uuid4()), "creationTimestamp": now, "resourceVersion": str(st["rv"])},
        "spec": {
            "capacity": {"storage": capacity}, "accessModes": access_modes,
            "persistentVolumeReclaimPolicy": sc.get("reclaimPolicy") or "Delete",
            "storageClassName": sc_name, "volumeMode": spec.get("volumeMode") or "Filesystem",
            "claimRef": {"name": md["name"], "namespace": md["namespace"]},
            "csi": {"driver": sc.get("provisioner") or "disk.csi.azure.com", "volumeHandle": pv_name},
        },
        "status": {"phase": "Bound"},
    }
    st["objects"][_key("PersistentVolume", None, pv_name)] = pv
    spec["volumeName"] = pv_name
    pvc["status"] = {"phase": "Bound", "accessModes": access_modes, "capacity": {"storage": capacity}}
    st["rv"] += 1
    _emit_event(rec, pvc, "Normal", "ProvisioningSucceeded",
               f'Successfully provisioned volume "{pv_name}" using {sc.get("provisioner") or "disk.csi.azure.com"}', "persistentvolume-controller")


_DEFAULT_STORAGE_CLASSES = [
    {"name": "default", "provisioner": "disk.csi.azure.com", "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer",
     "allowVolumeExpansion": True, "parameters": {"skuname": "StandardSSD_LRS"}, "is_default": True},
    {"name": "managed-csi", "provisioner": "disk.csi.azure.com", "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer",
     "allowVolumeExpansion": True, "parameters": {"skuname": "StandardSSD_LRS"}},
    {"name": "managed-csi-premium", "provisioner": "disk.csi.azure.com", "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer",
     "allowVolumeExpansion": True, "parameters": {"skuname": "Premium_LRS"}},
    {"name": "azurefile-csi", "provisioner": "file.csi.azure.com", "reclaimPolicy": "Delete", "volumeBindingMode": "Immediate",
     "allowVolumeExpansion": True, "parameters": {"skuName": "Standard_LRS"}},
    {"name": "azurefile-csi-premium", "provisioner": "file.csi.azure.com", "reclaimPolicy": "Delete", "volumeBindingMode": "Immediate",
     "allowVolumeExpansion": True, "parameters": {"skuName": "Premium_LRS"}},
]


def seed_storage_classes(rec: dict) -> None:
    """AKS's disk/file CSI driver add-ons provision these StorageClasses on every new cluster,
    present from the moment it comes up — same seeding convention as the default namespaces
    (properties.namespaces), just in the Kubernetes object store instead."""
    for sc in _DEFAULT_STORAGE_CLASSES:
        obj = {
            "apiVersion": "storage.k8s.io/v1", "kind": "StorageClass",
            "metadata": {"name": sc["name"],
                        **({"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}} if sc.get("is_default") else {})},
            "provisioner": sc["provisioner"], "reclaimPolicy": sc["reclaimPolicy"],
            "volumeBindingMode": sc["volumeBindingMode"], "allowVolumeExpansion": sc["allowVolumeExpansion"],
            "parameters": dict(sc["parameters"]),
        }
        _put(rec, obj, "create")


def _release_pv(rec: dict, pvc: dict) -> None:
    """A deleted PVC's dynamically-bound volume follows its reclaim policy: Delete (the AKS
    default for the built-in storage classes) removes the PV with it, Retain just releases it —
    same cascade the real persistentvolume-controller runs on PVC deletion."""
    st = _store(rec)
    vol = (pvc.get("spec") or {}).get("volumeName")
    if not vol:
        return
    pv_key = _key("PersistentVolume", None, vol)
    pv = st["objects"].get(pv_key)
    if pv is None:
        return
    if (pv.get("spec") or {}).get("persistentVolumeReclaimPolicy", "Delete") == "Delete":
        del st["objects"][pv_key]
    else:
        pv["status"] = {"phase": "Released"}
    st["rv"] += 1


def _delete(rec: dict, kind: str, ns: str | None, name: str) -> bool:
    st = _store(rec)
    if kind == "Namespace":
        nss = _namespaces(rec)
        if not any(n.get("name") == name for n in nss):
            return False
        if name in ("default", "kube-system", "kube-public", "kube-node-lease"):
            raise KubectlError(f'Error from server (Forbidden): namespaces "{name}" is forbidden: this namespace may not be deleted')
        rec["properties"]["namespaces"] = [n for n in nss if n.get("name") != name]
        for k in [k for k, o in st["objects"].items() if (_kind_spec(rec, o["kind"]) or ("", [], "", [], False))[4] and o["metadata"].get("namespace") == name]:
            del st["objects"][k]
        st["rv"] += 1
        return True
    nsd = (_kind_spec(rec, kind) or ("", [], "", [], False))[4]
    key = _key(kind, ns if nsd else None, name)
    obj = st["objects"].get(key)
    if obj is None:
        return False
    del st["objects"][key]
    st["rv"] += 1
    if kind == "PersistentVolumeClaim":
        _release_pv(rec, obj)
    return True


# ── kubectl ──────────────────────────────────────────────────────────────────────────────
def _resource_label(rec: dict, kind: str) -> str:
    g = (_kind_spec(rec, kind) or (kind.lower(),))[0]
    return f"{kind.lower()}.{g}" if g else kind.lower()


def _resolve_kind(token: str, rec: dict) -> str:
    k = _ALIASES.get(token.lower())
    if k:
        return k
    low = token.lower()
    for crd in _store(rec)["objects"].values():
        if crd.get("kind") != "CustomResourceDefinition":
            continue
        names = (crd.get("spec") or {}).get("names") or {}
        group = (crd.get("spec") or {}).get("group") or ""
        kind_name, plural = names.get("kind"), names.get("plural")
        if not kind_name:
            continue
        candidates = {kind_name.lower(), (plural or "").lower(), (names.get("singular") or "").lower(),
                      *[s.lower() for s in names.get("shortNames") or []]}
        if group and plural:
            candidates.add(f"{plural.lower()}.{group.lower()}")
        if low in candidates:
            return kind_name
    raise KubectlError(f'error: the server doesn\'t have a resource type "{token}"')


def _split_commands(command: str):
    """Shell-ish split: heredocs become stdin, `cat <<EOF | kubectl …` pipes, && / ; / newlines."""
    lines = command.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.strip().startswith("#"):
            continue
        stdin, at = None, -1
        m = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", line)
        if m:
            delim, body = m.group(2), []
            while i < len(lines) and lines[i].strip() != delim:
                body.append(lines[i]); i += 1
            i += 1                                   # the delimiter line
            stdin, at = "\n".join(body) + "\n", m.start()
            line = line[:m.start()] + line[m.end():]
        pos = 0
        for sep in list(re.finditer(r"\s*(?:&&|;)\s*", line)) + [None]:
            end = sep.start() if sep else len(line)
            part = line[pos:end].strip()
            if part:                                 # the heredoc feeds the segment it was written on
                out.append((part, stdin if pos <= at <= end else None))
            pos = sep.end() if sep else end
    return out


def _flags(args: list):
    pos, fl = [], {"f": [], "n": None, "A": False, "o": None, "l": None, "replicas": None, "R": False}
    i = 0
    while i < len(args):
        a = args[i]
        def val():
            nonlocal i
            if "=" in a:
                return a.split("=", 1)[1]
            i += 1
            if i >= len(args):
                raise KubectlError(f"error: flag needs an argument: {a}")
            return args[i]
        if a in ("-f", "--filename") or a.startswith("--filename=") or (a.startswith("-f") and len(a) > 2 and not a.startswith("--")):
            fl["f"].append(a[2:] if a.startswith("-f") and len(a) > 2 and not a.startswith("--") else val())
        elif a in ("-n", "--namespace") or a.startswith("--namespace="):
            fl["n"] = val()
        elif a.startswith("-n") and len(a) > 2 and not a.startswith("--"):
            fl["n"] = a[2:]
        elif a in ("-A", "--all-namespaces"):
            fl["A"] = True
        elif a in ("-o", "--output") or a.startswith("--output="):
            fl["o"] = val()
        elif a.startswith("-o") and len(a) > 2 and not a.startswith("--"):
            fl["o"] = a[2:]
        elif a in ("-l", "--selector") or a.startswith("--selector="):
            fl["l"] = val()
        elif a.startswith("--replicas"):
            fl["replicas"] = val()
        elif a in ("-R", "--recursive"):
            fl["R"] = True
        elif a.startswith("--"):
            if "=" not in a and i + 1 < len(args) and not args[i + 1].startswith("-") and a in ("--context", "--kubeconfig", "--field-manager", "--timeout", "--grace-period", "--dry-run"):
                i += 1
        else:
            pos.append(a)
        i += 1
    return pos, fl


def _read_files(names: list, files: dict, stdin: str | None) -> list:
    docs = []
    for name in names:
        if name == "-":
            if stdin is None:
                raise KubectlError("error: no objects passed to apply (stdin is empty — use a heredoc: kubectl apply -f - <<EOF … EOF)")
            src = stdin
            docs += _parse(src, "STDIN")
            continue
        if re.match(r"^https?://", name):
            raise KubectlError(f'error: unable to read URL "{name}": runCommand in Vyomi has no outbound network access — attach the file instead (az aks command invoke --file)')
        n = name[2:] if name.startswith("./") else name
        hits = [k for k in sorted(files) if k == n or (k.startswith(n.rstrip("/") + "/") and k.endswith((".yaml", ".yml", ".json")))]
        if not hits:
            raise KubectlError(f'error: the path "{name}" does not exist')
        for k in hits:
            docs += _parse(files[k], k)
    return docs


def _parse(src: str, where: str) -> list:
    try:
        docs = k8s_yaml.load_all(src)
    except k8s_yaml.YAMLError as e:
        raise KubectlError(f'error: error parsing {where}: {e}')
    out = []
    for d in docs:
        if isinstance(d, dict) and d.get("kind") == "List" and isinstance(d.get("items"), list):
            out += d["items"]
        else:
            out.append(d)
    return out


def _unzip(context_b64: str | None) -> dict:
    if not context_b64:
        return {}
    try:
        raw = base64.b64decode(context_b64)
        z = zipfile.ZipFile(io.BytesIO(raw))
        return {n.lstrip("./"): z.read(n).decode("utf-8") for n in z.namelist() if not n.endswith("/")}
    except Exception as e:
        raise KubectlError(f"error: the runCommand context is not a valid base64-encoded zip archive ({type(e).__name__})")


def _match_labels(obj: dict, selector: str | None) -> bool:
    if not selector:
        return True
    labels = (obj.get("metadata") or {}).get("labels") or {}
    for term in selector.split(","):
        term = term.strip()
        if "!=" in term:
            k, v = term.split("!=", 1)
            if labels.get(k.strip()) == v.strip():
                return False
        elif "=" in term:
            k, v = term.split("==" if "==" in term else "=", 1)
            if labels.get(k.strip()) != v.strip():
                return False
        elif term.startswith("!"):
            if term[1:] in labels:
                return False
        elif term not in labels:
            return False
    return True


def _ports(spec: dict) -> str:
    ps = []
    for p in spec.get("ports") or []:
        s = str(p.get("port"))
        if p.get("nodePort"):
            s += f":{p['nodePort']}"
        ps.append(f"{s}/{p.get('protocol') or 'TCP'}")
    return ",".join(ps) or "<none>"


def _row(kind: str, o: dict, wide: bool):
    md, spec, status = o.get("metadata") or {}, o.get("spec") or {}, o.get("status") or {}
    age = _age(md.get("creationTimestamp"))
    if kind == "Pod":
        n = len(spec.get("containers") or [])
        return [md["name"], f"0/{n}", "Pending", "0", age] + (["<none>", "<none>"] if wide else [])
    if kind == "Deployment":
        r = spec.get("replicas", 1)
        return [md["name"], f"0/{r}", "0", "0", age]
    if kind in ("StatefulSet",):
        return [md["name"], f"0/{spec.get('replicas', 1)}", age]
    if kind == "ReplicaSet":
        return [md["name"], str(spec.get("replicas", 1)), "0", "0", age]
    if kind == "DaemonSet":
        sel = ",".join(f"{k}={v}" for k, v in (((spec.get("template") or {}).get("spec") or {}).get("nodeSelector") or {}).items()) or "<none>"
        return [md["name"], "0", "0", "0", "0", "0", sel, age]
    if kind == "Job":
        return [md["name"], "Pending", "0/1", "", age]
    if kind == "CronJob":
        return [md["name"], str(spec.get("schedule")), "<none>", str(bool(spec.get("suspend", False))), "0", "<none>", age]
    if kind == "Service":
        ext = "<pending>" if spec.get("type") == "LoadBalancer" else (spec.get("externalName") or ",".join(spec.get("externalIPs") or []) or "<none>")
        return [md["name"], spec.get("type") or "ClusterIP", spec.get("clusterIP") or "None", ext, _ports(spec), age]
    if kind == "ConfigMap":
        return [md["name"], str(len(o.get("data") or {}) + len(o.get("binaryData") or {})), age]
    if kind == "Secret":
        return [md["name"], o.get("type") or "Opaque", str(len(o.get("data") or {})), age]
    if kind == "ServiceAccount":
        return [md["name"], str(len(o.get("secrets") or [])), age]
    if kind == "Namespace":
        return [md["name"], status.get("phase") or "Active", age]
    if kind in ("Role", "ClusterRole", "CustomResourceDefinition"):
        return [md["name"], md.get("creationTimestamp") or ""]
    if kind in ("RoleBinding", "ClusterRoleBinding"):
        rr = o.get("roleRef") or {}
        return [md["name"], f"{rr.get('kind')}/{rr.get('name')}", age]
    if kind == "NetworkPolicy":
        sel = ",".join(f"{k}={v}" for k, v in ((spec.get("podSelector") or {}).get("matchLabels") or {}).items()) or "<none>"
        return [md["name"], sel, age]
    if kind == "Ingress":
        hosts = ",".join(r.get("host") for r in (spec.get("rules") or []) if r.get("host")) or "*"
        return [md["name"], spec.get("ingressClassName") or "<none>", hosts, "", "443" if spec.get("tls") else "80", age]
    if kind == "PersistentVolumeClaim":
        return [md["name"], status.get("phase") or "Pending", spec.get("volumeName") or "",
               (status.get("capacity") or {}).get("storage") or "", ",".join(spec.get("accessModes") or []),
               spec.get("storageClassName") or "", age]
    if kind == "PersistentVolume":
        claim = spec.get("claimRef") or {}
        return [md["name"], (spec.get("capacity") or {}).get("storage") or "", ",".join(spec.get("accessModes") or []),
               spec.get("persistentVolumeReclaimPolicy") or "Delete", status.get("phase") or "Available",
               f"{claim['namespace']}/{claim['name']}" if claim else "", spec.get("storageClassName") or "", age]
    if kind == "StorageClass":
        return [md["name"], o.get("provisioner") or "", o.get("reclaimPolicy") or "Delete", o.get("volumeBindingMode") or "Immediate", age]
    if kind == "Event":
        io = o.get("involvedObject") or {}
        return [age, o.get("type") or "Normal", o.get("reason") or "", f"{io.get('kind', '')}/{io.get('name', '')}", o.get("message") or ""]
    return [md["name"], age]


_HEADERS = {
    "Pod": ["NAME", "READY", "STATUS", "RESTARTS", "AGE"], "Deployment": ["NAME", "READY", "UP-TO-DATE", "AVAILABLE", "AGE"],
    "StatefulSet": ["NAME", "READY", "AGE"], "ReplicaSet": ["NAME", "DESIRED", "CURRENT", "READY", "AGE"],
    "DaemonSet": ["NAME", "DESIRED", "CURRENT", "READY", "UP-TO-DATE", "AVAILABLE", "NODE SELECTOR", "AGE"],
    "Job": ["NAME", "STATUS", "COMPLETIONS", "DURATION", "AGE"],
    "CronJob": ["NAME", "SCHEDULE", "TIMEZONE", "SUSPEND", "ACTIVE", "LAST SCHEDULE", "AGE"],
    "Service": ["NAME", "TYPE", "CLUSTER-IP", "EXTERNAL-IP", "PORT(S)", "AGE"], "ConfigMap": ["NAME", "DATA", "AGE"],
    "Secret": ["NAME", "TYPE", "DATA", "AGE"], "ServiceAccount": ["NAME", "SECRETS", "AGE"], "Namespace": ["NAME", "STATUS", "AGE"],
    "Role": ["NAME", "CREATED AT"], "ClusterRole": ["NAME", "CREATED AT"], "RoleBinding": ["NAME", "ROLE", "AGE"],
    "ClusterRoleBinding": ["NAME", "ROLE", "AGE"], "NetworkPolicy": ["NAME", "POD-SELECTOR", "AGE"],
    "Ingress": ["NAME", "CLASS", "HOSTS", "ADDRESS", "PORTS", "AGE"],
    "PersistentVolumeClaim": ["NAME", "STATUS", "VOLUME", "CAPACITY", "ACCESS MODES", "STORAGECLASS", "AGE"],
    "PersistentVolume": ["NAME", "CAPACITY", "ACCESS MODES", "RECLAIM POLICY", "STATUS", "CLAIM", "STORAGECLASS", "AGE"],
    "StorageClass": ["NAME", "PROVISIONER", "RECLAIMPOLICY", "VOLUMEBINDINGMODE", "AGE"],
    "CustomResourceDefinition": ["NAME", "CREATED AT"],
    "Event": ["LAST SEEN", "TYPE", "REASON", "OBJECT", "MESSAGE"],
}


def _table(rows: list) -> str:
    w = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("   ".join(str(c).ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows) + "\n"


def _get(rec: dict, pos: list, fl: dict, describe=False) -> str:
    if not pos:
        raise KubectlError("error: you must specify the type of resource to get. Use \"kubectl api-resources\" for a complete list of supported resources.")
    first = pos[0]
    if "/" in first:                                   # kind/name form
        kinds, names = [_resolve_kind(first.split("/", 1)[0], rec)], [first.split("/", 1)[1]] + pos[1:]
    elif first == "all":
        kinds, names = ["Pod", "Service", "DaemonSet", "Deployment", "ReplicaSet", "StatefulSet", "Job", "CronJob"], pos[1:]
    else:
        kinds, names = [_resolve_kind(t, rec) for t in first.split(",") if t], pos[1:]
    nsd_of = {k: (_kind_spec(rec, k) or ("", [], "", [], False))[4] for k in kinds}
    ns = None if fl["A"] else (fl["n"] or "default")
    items = []
    for kind in kinds:
        for o in list_objects(rec, kind, ns if nsd_of[kind] else None):
            if names and o["metadata"]["name"] not in names:
                continue
            if not _match_labels(o, fl["l"]):
                continue
            items.append(o)
    if names:
        found = {o["metadata"]["name"] for o in items}
        missing = [n for n in names if n not in found]
        if missing:
            rspec = _kind_spec(rec, kinds[0]) or ("", [], kinds[0].lower(), [], True)
            raise KubectlError("\n".join(f'Error from server (NotFound): {rspec[2]}{"." + rspec[0] if rspec[0] else ""} "{n}" not found' for n in missing))
    out = fl["o"]
    if describe or out == "yaml":
        if len(items) == 1 and names:
            return k8s_yaml.dump(items[0])
        return k8s_yaml.dump({"apiVersion": "v1", "items": items, "kind": "List", "metadata": {"resourceVersion": ""}})
    if out == "json":
        if len(items) == 1 and names:
            return json.dumps(items[0], indent=4) + "\n"
        return json.dumps({"apiVersion": "v1", "items": items, "kind": "List", "metadata": {"resourceVersion": ""}}, indent=4) + "\n"
    if out == "name":
        return "".join(f"{_resource_label(rec, o['kind'])}/{o['metadata']['name']}\n" for o in items)
    if out not in (None, "wide"):
        raise KubectlError(f'error: unable to match a printer suitable for the output format "{out}", allowed formats are: json,name,wide,yaml')
    if not items:
        if fl["A"] or not any(nsd_of[k] for k in kinds):
            return "No resources found\n"
        return f"No resources found in {ns} namespace.\n"
    chunks = []
    for kind in kinds:
        ks = [o for o in items if o["kind"] == kind]
        if not ks:
            continue
        head = list(_HEADERS.get(kind, ["NAME", "AGE"])) + (["IP", "NODE"] if kind == "Pod" and out == "wide" else [])
        prefix = len(kinds) > 1
        rows = [(["NAMESPACE"] if fl["A"] and nsd_of[kind] else []) + head]
        for o in ks:
            r = _row(kind, o, out == "wide")
            if prefix:
                r[0] = f"{_resource_label(rec, kind)}/{r[0]}"
            rows.append(([o["metadata"].get("namespace", "")] if fl["A"] and nsd_of[kind] else []) + r)
        chunks.append(_table(rows))
    return "\n".join(chunks)


def _api_resources() -> str:
    rows = [["NAME", "SHORTNAMES", "APIVERSION", "NAMESPACED", "KIND"]]
    for kind, (g, vs, plural, short, nsd) in sorted(KINDS.items(), key=lambda kv: kv[1][2]):
        rows.append([plural, ",".join(short), f"{g}/{vs[0]}" if g else vs[0], str(nsd).lower(), kind])
    return _table(rows)


def _kubectl(rec: dict, args: list, files: dict, stdin: str | None, k8s_version: str) -> str:
    if not args:
        raise KubectlError("kubectl controls the Kubernetes cluster manager.\nerror: no command given")
    verb, rest = args[0], args[1:]
    pos, fl = _flags(rest)
    if verb in ("apply", "create", "replace") and fl["f"]:
        docs = _read_files(fl["f"], files, stdin)
        if not docs:
            raise KubectlError("error: no objects passed to " + verb)
        default_ns = fl["n"] or "default"
        pending = {d.get("metadata", {}).get("name") for d in docs if isinstance(d, dict) and d.get("kind") == "Namespace"}
        validated = [_validate(d, default_ns, rec, pending) for d in docs]   # all-or-nothing validation
        out = []
        for d, obj in zip(docs, validated):
            res = _put(rec, obj, "create" if verb == "create" else "apply", applied=d if verb == "apply" else None)
            if verb == "create":
                res = "created"
            out.append(f"{_resource_label(rec, obj['kind'])}/{obj['metadata']['name']} {res}")
        return "\n".join(out) + "\n"
    if verb == "create" and pos[:1] in (["namespace"], ["ns"]) and len(pos) == 2:
        obj = _validate({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": pos[1]}}, "default", rec, set())
        _put(rec, obj, "create")
        return f"namespace/{pos[1]} created\n"
    if verb in ("get",):
        return _get(rec, pos, fl)
    if verb == "describe":
        return _get(rec, pos, fl, describe=True)
    if verb == "delete":
        targets = []
        if fl["f"]:
            for d in _read_files(fl["f"], files, stdin):
                if not isinstance(d, dict) or _kind_spec(rec, d.get("kind")) is None:
                    continue
                md = d.get("metadata") or {}
                targets.append((d["kind"], md.get("namespace") or fl["n"] or "default", md.get("name")))
        elif pos:
            if "/" in pos[0]:
                for p in pos:
                    k, n = p.split("/", 1)
                    targets.append((_resolve_kind(k, rec), fl["n"] or "default", n))
            else:
                kind = _resolve_kind(pos[0], rec)
                if len(pos) < 2:
                    raise KubectlError("error: resource(s) were provided, but no name was specified")
                targets += [(kind, fl["n"] or "default", n) for n in pos[1:]]
        else:
            raise KubectlError("error: You must provide one or more resources by argument or filename.")
        out = []
        for kind, ns, name in targets:
            if _delete(rec, kind, ns, name):
                out.append(f'{_resource_label(rec, kind)} "{name}" deleted')
            else:
                rspec = _kind_spec(rec, kind) or ("", [], kind.lower(), [], True)
                raise KubectlError("\n".join(out + [f'Error from server (NotFound): {rspec[2]}{"." + rspec[0] if rspec[0] else ""} "{name}" not found']))
        return "\n".join(out) + "\n"
    if verb == "scale":
        if fl["replicas"] is None or not pos:
            raise KubectlError("error: --replicas=COUNT is required, and you must specify a resource")
        kind, name = (_resolve_kind(pos[0].split("/", 1)[0], rec), pos[0].split("/", 1)[1]) if "/" in pos[0] else (_resolve_kind(pos[0], rec), pos[1] if len(pos) > 1 else "")
        if kind not in ("Deployment", "ReplicaSet", "StatefulSet"):
            raise KubectlError(f"error: cannot scale a {kind}")
        key = _key(kind, fl["n"] or "default", name)
        obj = _store(rec)["objects"].get(key)
        if obj is None:
            rspec = _kind_spec(rec, kind) or ("", [], kind.lower(), [], True)
            raise KubectlError(f'Error from server (NotFound): {rspec[2]}.{rspec[0]} "{name}" not found')
        new = copy.deepcopy(obj)
        new["spec"]["replicas"] = int(fl["replicas"])
        _put(rec, new, "replace")
        return f"{_resource_label(rec, kind)}/{name} scaled\n"
    if verb == "version":
        v = str(k8s_version or "")
        return (f"Client Version: v{v}\nKustomize Version: v5.0.4\nServer Version: v{v}\n"
                if v else "Client Version: unknown\n")
    if verb == "api-resources":
        return _api_resources()
    if verb in ("logs", "exec", "attach", "port-forward", "cp", "top", "debug", "proxy", "run", "rollout", "auth", "events", "wait"):
        raise KubectlError(f"error: 'kubectl {verb}' needs running containers or a live API server — Vyomi stores Kubernetes "
                           f"objects but doesn't run containers, so there is nothing for '{verb}' to act on")
    raise KubectlError(f"error: 'kubectl {verb}' is not simulated by Vyomi (supported: apply, create, get, describe, delete, "
                       f"scale, version, api-resources)")


def run_command(rec: dict, command: str, context_b64: str | None = None) -> dict:
    """Execute a runCommand `command` against this cluster's object store.
    -> {exitCode, logs, changed} (changed = the object store moved; drives a posture rescan)."""
    before = version(rec)
    try:
        files = _unzip(context_b64)
    except KubectlError as e:
        return {"exitCode": 1, "logs": str(e) + "\n", "changed": False}
    k8s_version = (rec.get("properties") or {}).get("currentKubernetesVersion") or (rec.get("properties") or {}).get("kubernetesVersion")
    logs, code = [], 0
    for line, stdin in _split_commands(command or ""):
        # `cat <<EOF | kubectl …` → the heredoc is the kubectl's stdin
        if "|" in line:
            left, right = [s.strip() for s in line.split("|", 1)]
            if left.startswith("cat") and not left[3:].strip():
                line = right
            else:
                logs.append(f"sh: pipelines other than `cat <<EOF | kubectl …` are not simulated by Vyomi: {line}\n"); code = 1
                break
        try:
            args = shlex.split(line)
        except ValueError as e:
            logs.append(f"sh: syntax error: {e}\n"); code = 2
            break
        if not args:
            continue
        if args[0] != "kubectl":
            logs.append(f"sh: {args[0]}: command not found (Vyomi's runCommand simulates kubectl object operations only)\n"); code = 127
            break
        try:
            logs.append(_kubectl(rec, args[1:], files, stdin, k8s_version))
        except KubectlError as e:
            logs.append(str(e).rstrip("\n") + "\n"); code = 1
            break
    return {"exitCode": code, "logs": "".join(logs), "changed": version(rec) != before}
