"""AKS cluster extensions + the KEDA add-on, applied to the cluster's Kubernetes object store (substrate-free; Nano + offline).

The AKS "cluster" here has a real API-server-shaped object store (core/azure_aks_k8s_core.py: ``rec["_k8s"]``) but runs no kubelet,
so NOTHING SCHEDULES (pods stay Pending). On top of that real store this module adds two controllers that do real work:

* ``install(state, ext)`` / ``uninstall(state, ext)`` -- a ``Microsoft.KubernetesConfiguration/extensions`` resource of a modelled type
  (microsoft.dapr, microsoft.azuremonitor.containers, microsoft.azuredefender.kubernetes, microsoft.azurekeyvaultsecretsprovider,
  microsoft.openservicemesh) applies that extension's real workload manifests (namespace, Deployments / DaemonSets / StatefulSets /
  ServiceAccounts, with the chart's real names and images; ``configurationSettings`` such as ``global.ha.enabled`` change the
  manifests) so ``kubectl get deploy -A`` / the Workloads blade show them, and removes them again on delete. Other extension
  types stay "recorded" with a status that says so.
* ``sync_keda(cluster)`` -- ``workloadAutoScalerProfile.keda.enabled`` installs the KEDA add-on the way AKS does (keda-operator,
  keda-operator-metrics-apiserver, keda-admission-webhooks in kube-system + the keda.sh CustomResourceDefinitions ScaledObject /
  ScaledJob / TriggerAuthentication / ClusterTriggerAuthentication) and disabling removes them.
* ``keda_reconcile(state, cluster, now)`` -- the KEDA operator loop: every ScaledObject's triggers are evaluated and its target's
  ``spec.replicas`` is SET, with min/max replica counts, ``activationThreshold``, cooldown and ScaledObject ``status`` conditions.
  Triggers: ``cron`` (start/end/timezone/desiredReplicas) and ``prometheus`` (the query runs on the PromQL engine over the Azure Monitor
  workspace's stored samples, core/azure_promql.py; replicas = ceil(value / threshold)). Any other trigger type is reported on the
  ScaledObject as ``Ready=False reason=UnsupportedTrigger`` -- never silently ignored.

Honest limit: replica counts are the Deployment ``spec.replicas`` of the stored object -- no pod is started or stopped (Vyomi runs no
container runtime inside AKS), so ``status.readyReplicas`` stays 0.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timezone

try:
    from core import azure_aks_k8s_core as k8s
    from core import azure_promql as pql
except ImportError:                                    # Pyodide flat layout
    import azure_aks_k8s_core as k8s                   # type: ignore
    import azure_promql as pql                         # type: ignore

OWNER_KEY = "vyomi.io/extension"
KEDA_OWNER = ("vyomi.io/addon", "keda")
KEDA_VERSION = "2.14.0"


def _dep(name, ns, image, replicas=1, kind="Deployment", labels=None, args=None, env=None):
    c = {"name": name, "image": image}
    if args:
        c["args"] = list(args)
    if env:
        c["env"] = [{"name": k, "value": v} for k, v in env.items()]
    lab = dict({"app": name}, **(labels or {}))
    spec = {"selector": {"matchLabels": {"app": name}}, "template": {"metadata": {"labels": lab},
            "spec": {"serviceAccountName": name, "containers": [c], "nodeSelector": {"kubernetes.io/os": "linux"}}}}
    if kind != "DaemonSet":
        spec["replicas"] = replicas
    if kind == "StatefulSet":
        spec["serviceName"] = name
    return [{"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": name, "namespace": ns}},
            {"apiVersion": "apps/v1", "kind": kind, "metadata": {"name": name, "namespace": ns, "labels": lab}, "spec": spec}]


def _flat(*parts):
    return [d for p in parts for d in p]


def _ns(name):
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name}}


def _manifests(etype, settings, release_ns):
    ha = str(settings.get("global.ha.enabled", "false")).lower() == "true"
    n = 3 if ha else 1
    if etype == "microsoft.dapr":
        ns, v = release_ns or "dapr-system", settings.get("global.tag", "1.13.2")
        img = lambda c: f"mcr.microsoft.com/oss/dapr/{c}:{v}"
        return ns, [_ns(ns)] + _flat(
            _dep("dapr-operator", ns, img("dapr"), n, args=["./operator", "--log-as-json" if str(settings.get("global.logAsJson")).lower() == "true" else "--log-level=info"]),
            _dep("dapr-sidecar-injector", ns, img("injector"), n), _dep("dapr-sentry", ns, img("sentry"), n),
            _dep("dapr-placement-server", ns, img("placement"), 3 if ha else 1, kind="StatefulSet"),
            _dep("dapr-dashboard", ns, f"mcr.microsoft.com/oss/dapr/dashboard:0.14.0", 1))
    if etype == "microsoft.azuremonitor.containers":
        ns = "kube-system"
        return ns, _flat(_dep("ama-logs", ns, "mcr.microsoft.com/azuremonitor/containerinsights/ciprod:3.1.22", kind="DaemonSet"),
                         _dep("ama-logs-rs", ns, "mcr.microsoft.com/azuremonitor/containerinsights/ciprod:3.1.22"),
                         [{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "container-azm-ms-agentconfig", "namespace": ns},
                           "data": {"schema-version": "v1", "config-version": "ver1"}}])
    if etype == "microsoft.azuredefender.kubernetes":
        ns = "mdc"
        return ns, [_ns(ns)] + _flat(_dep("microsoft-defender-collector-ds", ns, "mcr.microsoft.com/azuredefender/stable/pod-collector:1.0.67", kind="DaemonSet"),
                                     _dep("microsoft-defender-publisher-ds", ns, "mcr.microsoft.com/azuredefender/stable/pod-publisher:1.0.67", kind="DaemonSet"),
                                     _dep("microsoft-defender-collector-misc", ns, "mcr.microsoft.com/azuredefender/stable/pod-collector-misc:1.0.67"))
    if etype == "microsoft.azurekeyvaultsecretsprovider":
        ns = "kube-system"
        return ns, _flat(_dep("aks-secrets-store-csi-driver", ns, "mcr.microsoft.com/oss/kubernetes-csi/secrets-store/driver:v1.4.5", kind="DaemonSet"),
                         _dep("aks-secrets-store-provider-azure", ns, "mcr.microsoft.com/oss/azure/secrets-store/provider-azure:v1.5.3", kind="DaemonSet"))
    if etype == "microsoft.openservicemesh":
        ns = release_ns or "arc-osm-system"
        return ns, [_ns(ns)] + _flat(_dep("osm-controller", ns, "mcr.microsoft.com/oss/openservicemesh/osm-controller:v1.2.8", n),
                                     _dep("osm-injector", ns, "mcr.microsoft.com/oss/openservicemesh/osm-injector:v1.2.8", n),
                                     _dep("osm-bootstrap", ns, "mcr.microsoft.com/oss/openservicemesh/osm-bootstrap:v1.2.8", 1))
    return None, None


RELEASE_NS = {"microsoft.dapr": "dapr-system", "microsoft.azuremonitor.containers": "kube-system", "microsoft.azuredefender.kubernetes": "mdc",
              "microsoft.azurekeyvaultsecretsprovider": "kube-system", "microsoft.openservicemesh": "arc-osm-system"}
MODELLED = ("microsoft.dapr", "microsoft.azuremonitor.containers", "microsoft.azuredefender.kubernetes",
            "microsoft.azurekeyvaultsecretsprovider", "microsoft.openservicemesh")


def _cluster_of(state, ext):
    low = ext["id"].lower()
    cid = low[: low.rindex("/providers/microsoft.kubernetesconfiguration/")]
    return state.get(cid)


def install(state, ext):
    """Apply the extension's workloads to its cluster; fills ``statuses`` honestly."""
    p = ext["properties"]
    et = str(p.get("extensionType", "")).lower()
    cluster = _cluster_of(state, ext)
    if cluster is None:
        return
    if et not in MODELLED:
        p["statuses"] = [{"code": "Recorded", "displayStatus": "Extension recorded", "level": "Information",
                          "message": f"'{et}' is stored but Vyomi does not model its workloads; nothing is installed on the cluster."}]
        return
    rel = ((p.get("scope") or {}).get("cluster") or {}).get("releaseNamespace")
    ns, docs = _manifests(et, p.get("configurationSettings") or {}, rel)
    owner = (OWNER_KEY, ext["name"])
    try:
        applied = k8s.apply_manifests(cluster, docs, ns, owner)
        keep = {(d["kind"], (d["metadata"].get("namespace")), d["metadata"]["name"]) for d in docs if d["kind"] != "Namespace"}
        gone = k8s.prune_owned(cluster, owner, keep)          # settings change (e.g. HA off) drops what is no longer rendered
        p["statuses"] = [{"code": "Installed", "displayStatus": "Installed", "level": "Information",
                          "message": f"Applied {len(applied)} object(s) to namespace '{ns}'" + (f", pruned {len(gone)}" if gone else "")
                          + ". Objects are in the cluster API store; Vyomi runs no kubelet, so their pods are not scheduled."}]
        p["provisioningState"] = "Succeeded"
        p["installedObjects"] = applied
    except k8s.KubectlError as e:
        p["statuses"] = [{"code": "InstallFailed", "displayStatus": "Failed", "level": "Error", "message": str(e)[:400]}]
        p["provisioningState"] = "Failed"


def uninstall(state, ext):
    cluster = _cluster_of(state, ext)
    if cluster is not None:
        k8s.prune_owned(cluster, (OWNER_KEY, ext["name"]), set())


# ── KEDA add-on ──────────────────────────────────────────────────────────────────────────────────────
def _crd(kind, plural, group="keda.sh", scope="Namespaced", short=()):
    return {"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition", "metadata": {"name": f"{plural}.{group}"},
            "spec": {"group": group, "scope": scope, "names": {"kind": kind, "plural": plural, "singular": kind.lower(), "shortNames": list(short)},
                     "versions": [{"name": "v1alpha1", "served": True, "storage": True, "schema": {"openAPIV3Schema": {"type": "object", "x-kubernetes-preserve-unknown-fields": True}}}]}}


def _keda_docs():
    ns = "kube-system"
    img = lambda c: f"mcr.microsoft.com/oss/kedacore/{c}:{KEDA_VERSION}"
    return [_crd("ScaledObject", "scaledobjects", short=["so"]), _crd("ScaledJob", "scaledjobs", short=["sj"]),
            _crd("TriggerAuthentication", "triggerauthentications", short=["ta", "triggerauth"]),
            _crd("ClusterTriggerAuthentication", "clustertriggerauthentications", scope="Cluster", short=["cta", "clustertriggerauth"])] + _flat(
        _dep("keda-operator", ns, img("keda"), 2), _dep("keda-operator-metrics-apiserver", ns, img("keda-metrics-apiserver"), 2),
        _dep("keda-admission-webhooks", ns, img("keda-admission-webhooks"), 2))


def keda_enabled(cluster):
    return bool((((cluster.get("properties") or {}).get("workloadAutoScalerProfile") or {}).get("keda") or {}).get("enabled"))


def sync_keda(cluster):
    """Install / remove the KEDA add-on to match ``workloadAutoScalerProfile.keda.enabled``. Idempotent."""
    st = cluster.setdefault("_keda", {})
    if keda_enabled(cluster):
        try:
            k8s.apply_manifests(cluster, _keda_docs(), "kube-system", KEDA_OWNER)
            st["installed"] = True
        except k8s.KubectlError as e:
            st["error"] = str(e)[:300]
    elif st.get("installed"):
        k8s.prune_owned(cluster, KEDA_OWNER, set())
        for o in list(k8s.list_objects(cluster, "ScaledObject")):          # the CRDs go, and with them every custom resource
            k8s._delete(cluster, "ScaledObject", o["metadata"].get("namespace"), o["metadata"]["name"])
        st["installed"] = False


def _cron_replicas(meta, now):
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(meta.get("timezone") or "UTC")
    except Exception:  # noqa: BLE001
        raise ValueError(f"unknown timezone '{meta.get('timezone')}'")
    t = now.astimezone(tz)
    def _m(expr):
        mi, h, dom, mon, dow = (expr.split() + ["*"] * 5)[:5]
        return mi, h, dom, mon, dow
    def _field(f, v, lo=0):
        if f == "*":
            return True
        for part in f.split(","):
            if "-" in part:
                a, b = part.split("-")
                if int(a) <= v <= int(b):
                    return True
            elif part.isdigit() and int(part) == v:
                return True
        return False
    def _at(expr):
        mi, h, dom, mon, dow = _m(expr)
        return mi, h
    # active window = from the start cron's most recent firing to the end cron's most recent firing (KEDA semantic)
    def last_fire(expr):
        mi, h, dom, mon, dow = _m(expr)
        cur = t.replace(second=0, microsecond=0)
        for _ in range(8 * 24 * 60):
            if _field(mi, cur.minute) and _field(h, cur.hour) and _field(dom, cur.day) and _field(mon, cur.month) and _field(dow, cur.isoweekday() % 7):
                return cur
            cur = cur.fromtimestamp(cur.timestamp() - 60, tz)
        return None
    s, e = last_fire(meta["start"]), last_fire(meta["end"])
    active = s is not None and (e is None or s > e)
    return int(meta.get("desiredReplicas", 1)) if active else 0


def _prom_value(state, cluster, meta, now):
    try:
        from core import azure_alerts_core as al
    except ImportError:
        import azure_alerts_core as al                 # type: ignore
    ws = None
    hint = (meta.get("serverAddress") or "") + " " + (meta.get("workspaceId") or "")
    accts = [r for r in state.values() if isinstance(r, dict) and str(r.get("type", "")).lower() == "microsoft.monitor/accounts"]
    for a in accts:
        if a["name"].lower() in hint.lower() or a["id"].lower() in hint.lower():
            ws = a["id"]
    ws = ws or (accts[0]["id"] if accts else meta.get("workspaceId"))
    if not ws:
        raise ValueError("no Azure Monitor workspace to query (set metadata.workspaceId or serverAddress)")
    sub = cluster.get("_sub") or ""
    st = al.prom_store(state, sub, ws, create=False) or {"series": {}}
    res = pql.query(st, meta["query"], now.timestamp())
    if isinstance(res, float):
        return res
    return sum(v for _, v in res) if res else 0.0


def keda_reconcile(state, cluster, now=None):
    """One operator pass over every ScaledObject. Returns [(scaledobject, target, from, to)] for the changes made."""
    if not keda_enabled(cluster):
        return []
    now = now or datetime.now(timezone.utc)
    changes = []
    store = k8s._store(cluster)
    for so in list(k8s.list_objects(cluster, "ScaledObject")):
        md, spec = so["metadata"], so.get("spec") or {}
        ref = spec.get("scaleTargetRef") or {}
        tkind, tname = ref.get("kind", "Deployment"), ref.get("name")
        target = store["objects"].get(k8s._key(tkind, md.get("namespace"), tname))
        key = k8s._key("ScaledObject", md.get("namespace"), md["name"])
        live = store["objects"][key]
        def status(ready, reason, msg, active=False, ext=()):
            old = live.get("status") or {}
            was_active = any(c.get("type") == "Active" and c.get("status") == "True" for c in old.get("conditions", []))
            live["status"] = {"conditions": [{"type": "Ready", "status": "True" if ready else "False", "reason": reason, "message": msg},
                                             {"type": "Active", "status": "True" if active else "False", "reason": "ScalerActive" if active else "ScalerNotActive",
                                              "message": "Scaling is performed because triggers are active" if active else "Scaling is not performed because triggers are not active"}],
                              "externalMetricNames": list(ext), "originalReplicaCount": old.get("originalReplicaCount", (target or {}).get("spec", {}).get("replicas", 1)),
                              "lastActiveTime": now.strftime("%Y-%m-%dT%H:%M:%SZ") if active else old.get("lastActiveTime")}
            if not live["status"]["lastActiveTime"]:
                live["status"].pop("lastActiveTime")
            if active != was_active and ready:
                k8s._emit_event(cluster, live, "Normal", "KEDAScaleTargetActivated" if active else "KEDAScaleTargetDeactivated",
                                f"{tkind} {md.get('namespace')}/{tname} {'activated' if active else 'deactivated'} by ScaledObject {md['name']}", "keda-operator")
        if target is None:
            status(False, "ScaleTargetNotFound", f"{tkind} '{tname}' was not found in namespace '{md.get('namespace')}'")
            continue
        desired, bad, names = [], None, []
        for i, tr in enumerate(spec.get("triggers") or []):
            meta = tr.get("metadata") or {}
            try:
                if tr.get("type") == "cron":
                    desired.append(("cron", _cron_replicas(meta, now), True))
                elif tr.get("type") == "prometheus":
                    val = _prom_value(state, cluster, meta, now)
                    thr = float(meta.get("threshold", 1)) or 1.0
                    act = float(meta.get("activationThreshold", 0))
                    desired.append(("prometheus", math.ceil(val / thr) if val > act else 0, val > act))
                else:
                    bad = f"trigger type '{tr.get('type')}' is not supported by Vyomi's KEDA operator (cron and prometheus are)"
                    break
                names.append(f"s{i}-{tr.get('type')}")
            except (ValueError, KeyError, pql.PromError) as e:
                bad = f"trigger {i} ({tr.get('type')}): {e}"
                break
        if bad:
            status(False, "UnsupportedTrigger" if "not supported" in bad else "TriggerError", bad)
            continue
        mn, mx = int(spec.get("minReplicaCount", 0)), int(spec.get("maxReplicaCount", 100))
        active = any(a for _, _, a in desired)
        want = max([r for _, r, _ in desired] or [0]) if active else mn
        want = max(mn, min(mx, want)) if active else mn
        cur = int((target.get("spec") or {}).get("replicas", 1))
        cd = int(spec.get("cooldownPeriod", 300))
        last = (live.get("status") or {}).get("lastActiveTime")
        if not active and cur > mn and last:           # cooldown: scale to the minimum only after the triggers stayed inactive for cooldownPeriod
            la = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now - la).total_seconds() < cd:
                want = cur
        if want != cur:
            target.setdefault("spec", {})["replicas"] = want
            store["rv"] = int(store.get("rv", 0)) + 1
            changes.append((md["name"], tname, cur, want))
        status(True, "ScaledObjectReady", "ScaledObject is defined correctly and is ready for scaling", active, names)
    return changes
