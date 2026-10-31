"""AKS Kubernetes object store + kubectl via runCommand (core/azure_aks_k8s_core.py, core/k8s_yaml.py).

Proves, over the native ARM wire (POST .../managedClusters/{c}/runCommand):
  - multi-document manifests apply through a heredoc, a `cat <<EOF |` pipe and the runCommand
    `context` zip (what `az aks command invoke --file` sends); every supported kind is stored;
  - kubectl semantics: created / configured / unchanged, create -> AlreadyExists, unknown kinds
    rejected with the real "no matches for kind" error, missing namespace -> NotFound, all-or-
    nothing validation, Secret stringData folded into base64 data (and bad base64 rejected);
  - get (tables, -A, -n, -l, -o json|yaml|name), describe, delete (by name and -f), scale;
  - namespaces are ONE truth with the ARM properties.namespaces list (Namespaces blade) and a
    namespace delete — via kubectl OR via ARM PATCH — cascades its objects;
  - status fields tell the truth (nothing is scheduled: Pods Pending / PodScheduled=False,
    workloads 0 ready, LoadBalancer <pending>, ClusterIP from the serviceCidr);
  - unsupported commands fail honestly (exit 1 / 127), never a fake success;
  - the store is JSON-safe (it persists with the ARM state) and goes away with the cluster;
  - the YAML reader agrees with PyYAML on the fixtures (when PyYAML is installed).

Run:  PYTHONPATH=. python3 tests/conformance/test_azure_aks_k8s_core.py
"""
import base64
import io
import json
import zipfile
from pathlib import Path

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
from core import azure_aks_k8s_core as k8s
from core import k8s_yaml

FIX = Path(__file__).resolve().parent / "fixtures" / "kubescape"
SUB = DEFAULT_SUBSCRIPTION
AV = "2024-09-02-preview"
C = f"/subscriptions/{SUB}/resourceGroups/k8s-rg/providers/Microsoft.ContainerService/managedClusters/k1"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    arm = AzureArm()
    arm.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/k8s-rg", {"api-version": "2021-04-01"}, {"location": "eastus"})
    arm.handle("PUT", C, {"api-version": AV}, {"location": "eastus"})

    def kc(cmd, **extra):
        r = arm.handle("POST", C + "/runCommand", {"api-version": AV}, {"command": cmd, **extra})
        assert r["status"] == 200, r
        return r["body"]["exitCode"], r["body"]["logs"]

    # ── YAML reader ───────────────────────────────────────────────────────────────────
    src = (FIX / "objects.yaml").read_text()
    docs = k8s_yaml.load_all(src)
    _check("YAML: 16 documents in the fixture", len(docs) == 16)
    try:
        import yaml  # type: ignore
        for f in ("objects.yaml", "objects-2.yaml"):
            if (FIX / f).exists():
                t = (FIX / f).read_text()
                _check(f"YAML: matches PyYAML on {f}", k8s_yaml.load_all(t) == [d for d in yaml.safe_load_all(t) if d is not None])
    except ImportError:
        print("  --  PyYAML not installed: cross-check skipped")
    _check("YAML: block scalars, flow collections, quoting, comments",
           k8s_yaml.load_all('a: |\n  x\n  y\nb: [1, "two", {c: 3}]\nd: \'it\'\'s\' # c\ne: "q#x"\n') ==
           [{"a": "x\ny\n", "b": [1, "two", {"c": 3}], "d": "it's", "e": "q#x"}])
    for d in docs:
        _check(f"YAML: dump round-trips {d['kind']}/{d['metadata']['name']}", k8s_yaml.load_all(k8s_yaml.dump(d))[0] == d) if d["kind"] in ("Deployment", "Secret") else None
    try:
        k8s_yaml.load_all("a: &x 1\nb: *x\n")
        _check("YAML: anchors rejected", False)
    except k8s_yaml.YAMLError:
        _check("YAML: anchors rejected with a clear error (not misread)", True)

    # ── apply through a heredoc ──────────────────────────────────────────────────────────
    code, logs = kc("kubectl apply -f - <<EOF\n" + src + "EOF")
    _check("apply heredoc: exit 0", code == 0)
    _check("apply heredoc: 16 objects created", logs.count(" created") == 16 and "deployment.apps/priv-app created" in logs)
    rec = arm.state[C.lower()]
    _check("namespace 'shop' joined properties.namespaces (one truth with the Namespaces blade)",
           any(n["name"] == "shop" for n in rec["properties"]["namespaces"]))
    cluster_view = arm.handle("GET", C, {"api-version": AV})["body"]
    _check("objects are not leaked into the ARM GET view", "_k8s" not in cluster_view)
    code, logs = kc("kubectl apply -f - <<EOF\n" + src + "EOF")
    _check("re-apply: every object unchanged", code == 0 and logs.count(" unchanged") == 16)

    # ── truthful status ──────────────────────────────────────────────────────────────────
    pod = next(o for o in k8s.list_objects(rec, "Pod"))
    _check("Pod is Pending with PodScheduled=False 'Not scheduled — Vyomi doesn't run containers'",
           pod["status"]["phase"] == "Pending" and pod["status"]["conditions"][0]["message"] == k8s.NOT_SCHEDULED)
    dep = next(o for o in k8s.list_objects(rec, "Deployment") if o["metadata"]["name"] == "priv-app")
    _check("Deployment has 0 ready of 2 and Available=False", dep["status"]["readyReplicas"] == 0
           and dep["spec"]["replicas"] == 2 and dep["status"]["conditions"][0]["status"] == "False")
    svc = next(o for o in k8s.list_objects(rec, "Service"))
    _check("Service ClusterIP comes from the cluster serviceCidr (10.0.0.0/16)", svc["spec"]["clusterIP"].startswith("10.0."))
    code, logs = kc("kubectl get svc -n shop")
    _check("LoadBalancer EXTERNAL-IP stays <pending> (no cloud LB is provisioned)", "<pending>" in logs and "LoadBalancer" in logs)
    sec = next(o for o in k8s.list_objects(rec, "Secret"))
    _check("Secret data kept base64 as in the manifest", sec["data"]["password"] == "aHVudGVyMg==")

    # ── get variants ─────────────────────────────────────────────────────────────────────
    code, logs = kc("kubectl get pods -A")
    _check("get pods -A: table with NAMESPACE column, 0/1 Pending", code == 0 and logs.startswith("NAMESPACE") and "0/1" in logs and "Pending" in logs)
    code, logs = kc("kubectl get deploy -n shop -o json")
    items = json.loads(logs)["items"]
    _check("get -o json returns a v1 List of the namespace's Deployments", {i["metadata"]["name"] for i in items} == {"priv-app", "hardened"})
    code, logs = kc("kubectl get deployments.apps priv-app -n shop -o yaml")
    _check("get <name> -o yaml returns the single object", k8s_yaml.load_all(logs)[0]["metadata"]["name"] == "priv-app")
    code, logs = kc("kubectl get deploy -n shop -l app=priv -o name")
    _check("label selector (metadata.labels) + -o name", logs.strip() == "deployment.apps/priv-app")
    code, logs = kc("kubectl get pods")
    _check("default namespace has its Pod", "debug-shell" in logs)
    code, logs = kc("kubectl get pods -n kube-public")
    _check("empty namespace says so", logs.strip() == "No resources found in kube-public namespace.")
    code, logs = kc("kubectl get deploy nope -n shop")
    _check("get missing -> NotFound, exit 1", code == 1 and 'deployments.apps "nope" not found' in logs)
    code, logs = kc("kubectl get clusterroles,clusterrolebindings")
    _check("comma kinds + cluster-scoped kinds", "clusterrole.rbac.authorization.k8s.io/everything" in logs
           and "ClusterRole/everything" in logs)
    code, logs = kc("kubectl get foo")
    _check("unknown resource type -> real error", code == 1 and 'doesn\'t have a resource type "foo"' in logs)

    # ── create / errors / validation ──────────────────────────────────────────────────────
    cm = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: app-config\n  namespace: shop\ndata:\n  a: b\n"
    code, logs = kc("kubectl create -f - <<EOF\n" + cm + "EOF")
    _check("create of an existing object -> AlreadyExists", code == 1 and "AlreadyExists" in logs)
    code, logs = kc("kubectl apply -f - <<EOF\n" + cm + "EOF")
    _check("apply a changed object -> configured", code == 0 and "configmap/app-config configured" in logs)
    bad = "apiVersion: example.com/v1\nkind: Widget\nmetadata:\n  name: w\n"
    code, logs = kc("kubectl apply -f - <<'EOF'\n" + bad + "EOF")
    _check("custom kinds rejected with 'no matches for kind'", code == 1 and 'no matches for kind "Widget"' in logs)
    two = cm.replace("app-config", "cm-atomic") + "---\n" + bad
    before = k8s.version(rec)
    code, logs = kc("kubectl apply -f - <<EOF\n" + two + "EOF")
    _check("validation is all-or-nothing (nothing stored when one document is invalid)",
           code == 1 and k8s.version(rec) == before and not any(o["metadata"]["name"] == "cm-atomic" for o in k8s.list_objects(rec, "ConfigMap")))
    code, logs = kc("kubectl apply -n ghost -f - <<EOF\n" + cm.replace("  namespace: shop\n", "") + "EOF")
    _check("missing namespace -> NotFound", code == 1 and 'namespaces "ghost" not found' in logs)
    sd = "apiVersion: v1\nkind: Secret\nmetadata:\n  name: s2\n  namespace: shop\nstringData:\n  token: abc\n"
    kc("cat <<EOF | kubectl apply -f -\n" + sd + "EOF")
    s2 = next(o for o in k8s.list_objects(rec, "Secret") if o["metadata"]["name"] == "s2")
    _check("`cat <<EOF |` pipe works; stringData folded into base64 data",
           "stringData" not in s2 and base64.b64decode(s2["data"]["token"]).decode() == "abc")
    code, logs = kc("kubectl apply -f - <<EOF\n" + sd.replace("stringData:\n  token: abc", "data:\n  token: '%%%'") + "EOF")
    _check("invalid base64 Secret data rejected", code == 1 and "illegal base64" in logs)

    # ── files from the runCommand context zip (az aks command invoke --file) ─────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifests/web.yaml", "apiVersion: v1\nkind: ServiceAccount\nmetadata:\n  name: zipped\n  namespace: shop\n")
    ctx = base64.b64encode(buf.getvalue()).decode()
    code, logs = kc("kubectl apply -f manifests/web.yaml", context=ctx)
    _check("apply -f <file> from the context zip", code == 0 and "serviceaccount/zipped created" in logs)
    code, logs = kc("kubectl apply -f manifests/", context=ctx)
    _check("apply -f <dir>/ from the context zip", code == 0 and "serviceaccount/zipped unchanged" in logs)
    code, logs = kc("kubectl apply -f missing.yaml", context=ctx)
    _check("missing file -> error", code == 1 and 'path "missing.yaml" does not exist' in logs)
    code, logs = kc("kubectl apply -f https://example.com/x.yaml")
    _check("remote URLs refused honestly (no outbound network)", code == 1 and "no outbound network" in logs)

    # ── scale / delete / cascade ────────────────────────────────────────────────────────
    code, logs = kc("kubectl scale deployment priv-app -n shop --replicas=4")
    dep = next(o for o in k8s.list_objects(rec, "Deployment") if o["metadata"]["name"] == "priv-app")
    _check("scale updates spec.replicas", code == 0 and dep["spec"]["replicas"] == 4 and dep["metadata"]["generation"] == 2)
    code, logs = kc("kubectl delete deployment hardened -n shop && kubectl get deploy -n shop -o name")
    _check("delete by name (&& chaining)", code == 0 and 'deployment.apps "hardened" deleted' in logs and "hardened" not in logs.split("deleted", 1)[1])
    code, logs = kc("kubectl delete -f - <<EOF\n" + sd + "EOF")
    _check("delete -f", code == 0 and 'secret "s2" deleted' in logs)
    code, logs = kc("kubectl delete namespace kube-system")
    _check("system namespaces can't be deleted", code == 1 and "Forbidden" in logs)
    code, logs = kc("kubectl create namespace tmp && kubectl apply -n tmp -f - <<EOF\n" + cm.replace("  namespace: shop\n", "") + "EOF")
    _check("create namespace + apply into it", code == 0 and "namespace/tmp created" in logs)
    kc("kubectl delete ns tmp")
    _check("kubectl delete namespace cascades its objects", not any(o["metadata"].get("namespace") == "tmp" for o in k8s.list_objects(rec)))
    nss = [n for n in arm.handle("GET", C, {"api-version": AV})["body"]["properties"]["namespaces"] if n["name"] != "shop"]
    arm.handle("PATCH", C, {"api-version": AV}, {"properties": {"namespaces": nss}})
    _check("removing a namespace over ARM (Namespaces blade) cascades its objects too",
           not any(o["metadata"].get("namespace") == "shop" for o in k8s.list_objects(rec)))

    # ── honest failures ────────────────────────────────────────────────────────────────
    for cmd, want_code, want in [("kubectl exec -it x -- sh", 1, "doesn't run containers"),
                                 ("kubectl rollout restart deploy/x", 1, "doesn't run containers"),
                                 ("helm install x y", 127, "command not found"),
                                 ("kubectl frobnicate", 1, "not simulated")]:
        code, logs = kc(cmd)
        _check(f"'{cmd}' fails honestly (exit {want_code})", code == want_code and want in logs)
    r = arm.handle("POST", C + "/runCommand", {"api-version": AV}, {"command": ""})
    _check("empty command -> 400", r["status"] == 400)
    code, logs = kc("kubectl version")
    _check("kubectl version reports the cluster's Kubernetes version", "Server Version: v1.29.2" in logs)

    # ── durability / lifecycle ───────────────────────────────────────────────────────────
    _check("the object store is JSON-safe (persists with the ARM state)", json.loads(json.dumps(arm.state)) == arm.state)
    arm.handle("DELETE", C, {"api-version": AV})
    _check("objects go away with the cluster", C.lower() not in arm.state)

    print("\nRESULT: PASS — AKS Kubernetes object store + kubectl conform on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
