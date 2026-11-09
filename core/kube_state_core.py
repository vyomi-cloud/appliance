"""Cloud-agnostic Kubernetes state tree for cluster backup/restore simulation (substrate-free; loads under Pyodide).

One in-memory JSON tree of Namespaces / Deployments / Pods / Services / ConfigMaps / Secrets ... per cluster, keyed by
``(cloud, cluster_id)``. The tree and the `kubectl` subset that mutates it are the ones in ``core/azure_aks_k8s_core.py``
(the engine only needs a dict shaped ``{"properties": {"namespaces": [...]}, "_k8s": {...}}``), so every cloud's
backup service -- Azure Backup for AKS, AWS Backup for EKS, Backup for GKE -- shares ONE definition of "the cluster's
resources", one kubectl, and one snapshot/restore format:

  holder(store, cloud, cluster_id[, rec])  -> the rec-shaped dict for that cluster. AKS passes its ARM cluster record as
                                             ``rec`` (the tree then lives ON the record, persisted with the ARM state);
                                             other clouds keep it in ``store`` (a plain dict that rides their own
                                             Nano/offline persistence).
  run_command(holder, "kubectl ...")       -> {exitCode, logs, changed}
  snapshot(holder)                         -> JSON-safe doc: the user namespaces + their namespaced objects
  restore(holder, snap)                    -> re-injects a snapshot (server-side apply: missing objects come back, objects
                                             that still exist are patched), returns the list of `kubectl apply` verbs.
  counts(snap_or_holder)                   -> {"namespaces": n, "deployments": n, "pods": n, ...} for dashboards.

KubeBackend seam: nothing above the backend (kubectl emulation, backup engines) assumes the cluster's state lives in our process.
``KubeBackend`` is the interface; ``InMemoryKubeBackend`` (Nano + dev server + the default offline path) implements it over the JSON
tree; ``RealK8sBackend`` is the SEAM for the offline appliance's real API server (k3s) -- intentionally NOT implemented here.
Backup engines call only ``export_resources`` / ``apply`` / ``health`` / ``kubectl``; they never touch the tree.

What a snapshot is NOT (honest limits): persistent-volume DATA, PersistentVolumes, Events, CustomResourceDefinitions and
custom resources, and the system namespaces (kube-system, kube-public, kube-node-lease). Nothing is scheduled: restored
Pods are Pending exactly like freshly applied ones (Vyomi runs no kubelet).
"""
from __future__ import annotations

import copy
import json

try:
    from core import azure_aks_k8s_core as engine
except ImportError:                      # Pyodide flat layout
    import azure_aks_k8s_core as engine  # type: ignore

SYSTEM_NAMESPACES = ("kube-system", "kube-public", "kube-node-lease")
SKIP_KINDS = ("Event", "PersistentVolume", "StorageClass", "CustomResourceDefinition", "Namespace")
_STRIP_META = ("uid", "resourceVersion", "creationTimestamp", "generation", "managedFields", "selfLink")


def holder(store: dict, cloud: str, cluster_id: str, rec: dict | None = None) -> dict:
    """The rec-shaped state holder for one cluster. ``rec`` (e.g. AKS's ARM cluster record) wins; otherwise the tree lives
    in ``store[cloud + ':' + cluster_id]``."""
    if rec is not None:
        rec.setdefault("properties", {}).setdefault("namespaces", [{"name": n, "status": "Active"} for n in ("default",) + SYSTEM_NAMESPACES])
        return rec
    key = f"{cloud}:{cluster_id}".lower()
    h = store.get(key)
    if h is None:
        h = store[key] = {"cloud": cloud, "id": cluster_id, "properties": {"namespaces": [{"name": n, "status": "Active"} for n in ("default",) + SYSTEM_NAMESPACES]}}
    return h


def run_command(h: dict, command: str, context_b64: str | None = None) -> dict:
    return engine.run_command(h, command, context_b64)


def snapshot(h: dict) -> dict:
    namespaces, objects = [], []
    keep = set()
    for n in (h.get("properties") or {}).get("namespaces") or []:
        if n.get("name") in SYSTEM_NAMESPACES or n.get("name") == "default":
            continue
        keep.add(n["name"])
        namespaces.append({"name": n["name"], "labels": dict(n.get("labels") or {})})
    for o in engine.list_objects(h):
        md = o.get("metadata") or {}
        if o.get("kind") in SKIP_KINDS or o.get("kind") not in engine.KINDS:
            continue
        if md.get("namespace") not in keep and md.get("namespace") != "default":
            continue
        d = copy.deepcopy(o)
        d.pop("status", None)
        for f in _STRIP_META:
            (d.get("metadata") or {}).pop(f, None)
        if d["kind"] == "PersistentVolumeClaim":
            (d.get("spec") or {}).pop("volumeName", None)       # PV data is not backed up; the claim re-provisions empty
        if d["kind"] == "Service":
            for f in ("clusterIP", "clusterIPs"):
                (d.get("spec") or {}).pop(f, None)
        objects.append(d)
    return {"kind": "VyomiKubeSnapshot", "version": 1, "namespaces": namespaces, "objects": objects, "counts": counts({"namespaces": namespaces, "objects": objects})}


def counts(x: dict) -> dict:
    snap = x if "objects" in x else snapshot(x)
    out = {"namespaces": len(snap.get("namespaces") or [])}
    for o in snap.get("objects") or []:
        k = engine.KINDS.get(o.get("kind"), ("", [], str(o.get("kind", "")).lower() + "s"))[2]
        out[k] = out.get(k, 0) + 1
    return out


def restore(h: dict, snap: dict) -> list:
    docs = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": n["name"], "labels": dict(n.get("labels") or {})}} for n in snap.get("namespaces") or []]
    docs += copy.deepcopy(snap.get("objects") or [])
    for d in docs:
        if d.get("kind") == "PersistentVolumeClaim":
            (d.get("spec") or {}).pop("volumeName", None)       # PV data is not backed up; the claim re-provisions empty
    return engine.apply_manifests(h, docs)


def dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── KubeBackend interface ────────────────────────────────────────────────────────────
class KubeBackend:
    """What any backing store of a cluster's Kubernetes objects must provide. Manifests are plain Kubernetes objects (dicts)."""

    def list_namespaces(self) -> list: raise NotImplementedError
    def list(self, kind: str, namespace: str | None = None) -> list: raise NotImplementedError          # kind e.g. "Pod", "Deployment"
    def apply(self, manifests: list) -> list: raise NotImplementedError                                  # -> ["deployment.apps/web created", ...]
    def delete(self, kind: str, name: str, namespace: str | None = None) -> bool: raise NotImplementedError
    def delete_namespace(self, name: str) -> bool: raise NotImplementedError                             # cascades the namespace's objects
    def export_resources(self, namespaces: list | None = None) -> dict: raise NotImplementedError       # Velero-style: {"namespaces":[...],"objects":[manifests],"counts":{}}
    def health(self) -> dict: raise NotImplementedError                                                  # {"status": "Healthy"|"Unreachable", "namespaces": n, "pods": n, ...}
    def kubectl(self, command: str, context_b64: str | None = None) -> dict: raise NotImplementedError  # -> {exitCode, logs, changed}


class InMemoryKubeBackend(KubeBackend):
    """The JSON-tree backend (Nano, dev_server, default offline). ``h`` is a holder() dict."""

    def __init__(self, h: dict):
        self.h = h

    def list_namespaces(self):
        return [n["name"] for n in (self.h.get("properties") or {}).get("namespaces") or []]

    def list(self, kind, namespace=None):
        return copy.deepcopy(engine.list_objects(self.h, kind, namespace))

    def apply(self, manifests):
        return engine.apply_manifests(self.h, copy.deepcopy(manifests))

    def delete(self, kind, name, namespace=None):
        return engine._delete(self.h, kind, namespace, name)

    def delete_namespace(self, name):
        return engine._delete(self.h, "Namespace", None, name)

    def export_resources(self, namespaces=None):
        snap = snapshot(self.h)
        if namespaces is not None:
            snap["namespaces"] = [n for n in snap["namespaces"] if n["name"] in namespaces]
            snap["objects"] = [o for o in snap["objects"] if o["metadata"].get("namespace") in namespaces]
            snap["counts"] = counts(snap)
        return snap

    def health(self):
        c = counts(self.h)
        return {"status": "Healthy", "backend": "in-memory", **{k: v for k, v in c.items()}}

    def kubectl(self, command, context_b64=None):
        return run_command(self.h, command, context_b64)


class RealK8sBackend(KubeBackend):
    """SEAM ONLY -- the offline appliance's real API server (k3s container + kubeconfig). Implemented by a later agent: every method
    must talk to the cluster's API server (nothing may assume state lives in this process), `export_resources` must return the same
    document shape as InMemoryKubeBackend (so recovery points are portable between substrates), and `apply` must be server-side apply."""

    def __init__(self, kubeconfig: str | None = None):
        self.kubeconfig = kubeconfig


def backend_for(store: dict, cloud: str, cluster_id: str, rec: dict | None = None, factory=None) -> KubeBackend:
    """Resolve a cluster's backend. ``factory(cloud, cluster_id)`` (installed by the offline appliance) may return a RealK8sBackend;
    otherwise the in-memory tree is used."""
    if factory is not None:
        b = factory(cloud, cluster_id)
        if b is not None:
            return b
    return InMemoryKubeBackend(holder(store, cloud, cluster_id, rec))


# offline appliance hook: set to a callable (cloud, cluster_id) -> KubeBackend | None
BACKEND_FACTORY = None
