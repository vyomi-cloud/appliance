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
    """A REAL Kubernetes API server (the cluster's k3s container, see core/k3s_runtime.py). Every method talks to the API server through
    ``runner(argv, stdin=None, workdir=None, timeout=120) -> (returncode, stdout, stderr)`` -- a ``kubectl <argv>`` executed inside the
    cluster's server container -- so nothing assumes state lives in this process. ``export_resources`` returns the same document shape as
    InMemoryKubeBackend (recovery points are portable between substrates); ``apply`` is server-side apply.

    Honest limits of the export (same as the in-memory snapshot): no PV data / PVs / Events / CRDs / custom resources / system namespaces;
    objects owned by a controller (ReplicaSets, controller Pods, CronJob Jobs), the per-namespace ``kube-root-ca.crt`` ConfigMap, the
    ``default`` ServiceAccount, service-account-token Secrets and the ``kubernetes`` Service are skipped because the cluster regenerates them."""

    EXPORT_KINDS = ("Service", "ConfigMap", "Secret", "ServiceAccount", "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob",
                    "Role", "RoleBinding", "NetworkPolicy", "Ingress", "PersistentVolumeClaim", "Pod")
    _MUTATING = ("apply", "create", "delete", "scale", "patch", "label", "annotate", "set", "edit", "replace", "rollout", "expose", "run",
                 "taint", "cordon", "uncordon", "drain", "autoscale")

    def __init__(self, runner, ns_timeout=180, file_writer=None):
        self.runner = runner
        self.file_writer = file_writer          # (files: dict, workdir: str) -> None; materialises runCommand context files
        self.ns_timeout = ns_timeout

    # -- helpers --
    def _get_json(self, resource, namespace=None):
        argv = ["get", resource, "-o", "json"] + (["-n", namespace] if namespace else ["-A"])
        rc, out, err = self.runner(argv)
        if rc != 0:
            raise RuntimeError("kubectl get %s failed: %s" % (resource, (err or out).strip()[:300]))
        return json.loads(out or "{}").get("items") or []

    @staticmethod
    def _resource(kind):
        g, _v, plural, _s, _n = engine.KINDS[kind] if kind in engine.KINDS else ("", [], kind.lower() + "s", [], True)
        return plural + ("." + g if g else "")

    def list_namespaces(self):
        return [i["metadata"]["name"] for i in self._get_json("namespaces")]

    def list(self, kind, namespace=None):
        return self._get_json(self._resource(kind), namespace)

    def apply(self, manifests):
        docs = copy.deepcopy([m for m in manifests if m])
        docs.sort(key=lambda d: 0 if d.get("kind") == "Namespace" else 1)          # namespaces first
        out = []
        for d in docs:       # one apply per object: a Namespace must exist (and be Active) before its objects are applied
            rc, so, se = self.runner(["apply", "--server-side", "--force-conflicts", "-f", "-"], json.dumps(d), None, 120)
            if rc != 0:
                raise engine.KubectlError((se or so).strip())
            out.extend(l.strip() for l in so.splitlines() if l.strip())
        return out

    def delete(self, kind, name, namespace=None):
        argv = ["delete", self._resource(kind), name, "--ignore-not-found=false"] + (["-n", namespace] if namespace else [])
        return self.runner(argv)[0] == 0

    def delete_namespace(self, name):
        return self.runner(["delete", "namespace", name, "--wait=true", "--timeout=%ds" % self.ns_timeout], None, None, self.ns_timeout + 30)[0] == 0

    def export_resources(self, namespaces=None):
        ns_items = self._get_json("namespaces")
        user_ns = [n for n in ns_items if n["metadata"]["name"] not in SYSTEM_NAMESPACES and n["metadata"]["name"] != "default"]
        keep = {n["metadata"]["name"] for n in user_ns} | {"default"}
        snap_ns = [{"name": n["metadata"]["name"], "labels": {k: v for k, v in (n["metadata"].get("labels") or {}).items()
                                                               if not k.startswith("kubernetes.io/")}} for n in user_ns]
        objects = []
        for kind in self.EXPORT_KINDS:
            for o in self._get_json(self._resource(kind)):
                md = o.get("metadata") or {}
                if md.get("namespace") not in keep or md.get("ownerReferences"):
                    continue
                if (kind == "ConfigMap" and md.get("name") == "kube-root-ca.crt") or (kind == "ServiceAccount" and md.get("name") == "default") \
                        or (kind == "Secret" and o.get("type") == "kubernetes.io/service-account-token") \
                        or (kind == "Service" and md.get("namespace") == "default" and md.get("name") == "kubernetes"):
                    continue
                objects.append(self._clean(o))
        snap = {"kind": "VyomiKubeSnapshot", "version": 1, "namespaces": snap_ns, "objects": objects}
        if namespaces is not None:
            snap["namespaces"] = [n for n in snap_ns if n["name"] in namespaces]
            snap["objects"] = [o for o in objects if o["metadata"].get("namespace") in namespaces]
        snap["counts"] = counts(snap)
        return snap

    @staticmethod
    def _clean(o):
        d = copy.deepcopy(o)
        d.pop("status", None)
        md = d.get("metadata") or {}
        for f in _STRIP_META + ("selfLink",):
            md.pop(f, None)
        for a in ("kubectl.kubernetes.io/last-applied-configuration", "deployment.kubernetes.io/revision"):
            (md.get("annotations") or {}).pop(a, None)
        if not md.get("annotations"):
            md.pop("annotations", None)
        spec = d.get("spec") or {}
        kind = d.get("kind")
        if kind == "PersistentVolumeClaim":
            spec.pop("volumeName", None)
            ann = md.get("annotations") or {}
            for a in [a for a in ann if a.startswith("pv.kubernetes.io/")]:
                ann.pop(a)
            if "annotations" in md and not md["annotations"]:
                md.pop("annotations")
        if kind == "Service":
            for f in ("clusterIP", "clusterIPs"):
                spec.pop(f, None)
        if kind == "Pod":
            spec.pop("nodeName", None)
        return d

    def health(self):
        rc, out, err = self.runner(["get", "--raw", "/readyz"], None, None, 20)
        if rc != 0:
            return {"status": "Unreachable", "backend": "k3s", "error": (err or out).strip()[:200]}
        try:
            c = {"namespaces": len(self._get_json("namespaces")), "pods": len(self._get_json("pods"))}
        except Exception:
            c = {}
        return {"status": "Healthy", "backend": "k3s", **c}

    def kubectl(self, command, context_b64=None):
        """runCommand against the real cluster: kubectl lines only (no shell -- argv is exec'd), `cat <<EOF | kubectl ...` and heredocs
        feed stdin, context-zip files are materialised in a scratch dir. Returns {exitCode, logs, changed}."""
        import shlex
        try:
            files = engine._unzip(context_b64)
        except engine.KubectlError as e:
            return {"exitCode": 1, "logs": str(e) + "\n", "changed": False}
        workdir = None
        if files:
            import uuid
            workdir = "/tmp/runcmd-" + uuid.uuid4().hex[:12]
            if self.file_writer is None:
                return {"exitCode": 1, "logs": "error: this backend cannot stage runCommand context files\n", "changed": False}
            self.file_writer(files, workdir)
        logs, code, changed = [], 0, False
        for line, stdin in engine._split_commands(command or ""):
            if "|" in line:
                left, right = [s.strip() for s in line.split("|", 1)]
                if left.startswith("cat") and not left[3:].strip():
                    line = right
                else:
                    logs.append("sh: pipelines other than `cat <<EOF | kubectl ...` are not supported: %s\n" % line)
                    code = 1
                    break
            try:
                args = shlex.split(line)
            except ValueError as e:
                logs.append("sh: syntax error: %s\n" % e)
                code = 2
                break
            if not args:
                continue
            if args[0] != "kubectl":
                logs.append("sh: %s: command not found (runCommand runs kubectl against this cluster)\n" % args[0])
                code = 127
                break
            rc, so, se = self.runner(args[1:], stdin, workdir, 120)
            logs.append(so + se)
            if rc != 0:
                code = rc
                break
            if len(args) > 1 and args[1] in self._MUTATING:
                changed = True
        return {"exitCode": code, "logs": "".join(logs), "changed": changed}


def backend_for(store: dict, cloud: str, cluster_id: str, rec: dict | None = None, factory=None) -> KubeBackend:
    """Resolve a cluster's backend. ``factory(cloud, cluster_id)`` (installed by the offline appliance) may return a RealK8sBackend;
    otherwise the in-memory tree is used."""
    if factory is not None:
        b = factory(cloud, cluster_id)
        if b is not None:
            return b
    return InMemoryKubeBackend(holder(store, cloud, cluster_id, rec))


# offline appliance hooks (installed by core/k3s_runtime.install() when VYOMI_K8S_BACKEND=k3s):
BACKEND_FACTORY = None      # callable (cloud, cluster_id) -> KubeBackend | None
CLUSTER_RUNTIME = None      # the k3s lifecycle (create_cluster / delete_cluster / kubeconfig / exists ...); None on Nano + dev defaults
