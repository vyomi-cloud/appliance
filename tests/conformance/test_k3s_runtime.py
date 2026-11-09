"""k3s runtime + RealK8sBackend + AKS/GKE wiring, against a FAKE docker (always runs; no Docker needed).
The live counterpart (real k3s container) is tests/conformance/test_k3s_live.py.
Run: PYTHONPATH=. python3 tests/conformance/test_k3s_runtime.py"""
import base64
import json
import time

from core import k3s_runtime as k3s
from core import kube_state_core as kube
from core import gcp_container_core as gke
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S

KUBECONFIG = """apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: Q0FEQVRB
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
kind: Config
users:
- name: default
  user:
    client-certificate-data: Q0VSVA==
    client-key-data: S0VZ
"""


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _obj(kind, name, ns=None, owner=False, **extra):
    md = {"name": name, "uid": "u", "resourceVersion": "1", "creationTimestamp": "t", "managedFields": [{}]}
    if ns:
        md["namespace"] = ns
    if owner:
        md["ownerReferences"] = [{"kind": "ReplicaSet", "name": "x"}]
    return {"apiVersion": "v1", "kind": kind, "metadata": md, "status": {"x": 1}, **extra}


class FakeDocker:
    def __init__(self):
        self.calls, self.containers, self.volumes, self.networks = [], {}, set(), set()
        self.items = {}            # kubectl resource -> list of objects
        self.applied, self.nodes_ready = [], 1

    def __call__(self, args, stdin=None, timeout=120):
        self.calls.append((list(args), stdin))
        a = list(args)
        if a[:2] == ["network", "inspect"]:
            return (0 if a[2] in self.networks else 1), "", ""
        if a[:2] == ["network", "create"]:
            self.networks.add(a[2]); return 0, "", ""
        if a[:2] == ["volume", "create"]:
            self.volumes.add(a[-1]); return 0, "", ""
        if a[:2] == ["volume", "ls"]:
            return 0, "\n".join(sorted(self.volumes)) + "\n", ""
        if a[:2] == ["volume", "rm"]:
            self.volumes.discard(a[-1]); return 0, "", ""
        if a[0] == "run":
            name = a[a.index("--name") + 1]
            self.containers[name] = a
            return 0, "cid\n", ""
        if a[:3] == ["inspect", "--type", "container"]:
            return (0 if a[3] in self.containers else 1), "", ""
        if a[0] == "ps":
            if any(x.startswith("label=vyomi.k3s.name=") for x in a):
                return 0, "\n".join(self.containers) + "\n", ""
            return 0, "".join("%s\tazure\tcid\trunning\n" % n for n in self.containers if "agent" not in n), ""
        if a[0] == "rm":
            self.containers.pop(a[-1], None); return 0, "", ""
        if a[0] == "port":
            return 0, "127.0.0.1:49152\n", ""
        if a[0] == "exec":
            if "cat" in a and k3s.KUBECONFIG_PATH in a:
                return 0, KUBECONFIG, ""
            i = a.index("kubectl") if "kubectl" in a else None
            if i is None:
                return 0, "", ""
            k = a[i + 1:]
            if k[:2] == ["get", "--raw"]:
                return 0, "ok", ""
            if k[:2] == ["get", "nodes"]:
                return 0, "\n".join("n%d Ready control-plane 1m v1" % j for j in range(self.nodes_ready)) + "\n", ""
            if k[0] == "get":
                return 0, json.dumps({"items": self.items.get(k[1], [])}), ""
            if k[0] == "apply":
                try:
                    d = json.loads(stdin)
                except ValueError:
                    return 0, "applied (yaml)\n", ""
                self.applied.append(d); return 0, "%s/%s serverside-applied\n" % (d["kind"].lower(), d["metadata"]["name"]), ""
            if k[0] == "delete":
                return 0, "deleted\n", ""
            return 0, "ran %s\n" % " ".join(k), ""
        return 0, "", ""


def run():
    fd = FakeDocker()
    rt = k3s.K3sRuntime(docker=fd, sleep=lambda s: None)

    # ── lifecycle ──
    fd.nodes_ready = 2
    info = rt.create_cluster("azure", "/subs/x/aks1", "1.29.0", 2, ["aks1.hcp.azmk8s.io"], wait=True)
    name = k3s.server_name("azure", "/subs/x/aks1")
    run_args = fd.containers[name]
    _check("server named vyomi-k3s-<hash>", name.startswith("vyomi-k3s-") and info["name"] == name)
    _check("network vyomi-net created", k3s.NETWORK in fd.networks and run_args[run_args.index("--network") + 1] == k3s.NETWORK)
    _check("privileged + pinned image + persistent volume", "--privileged" in run_args and ("rancher/k3s:" + k3s.PINNED_K3S_VERSION) in run_args
           and (name + "-data:/var/lib/rancher/k3s") in run_args)
    tail = run_args[run_args.index("server"):]
    _check("--cluster-init, 3 components disabled", "--cluster-init" in tail and all(tail[tail.index("--disable") + 2 * i + 1] in ("traefik", "servicelb", "metrics-server") for i in range(3)))
    _check("--tls-san 127.0.0.1 + stable name + extra", all(("--tls-san", x) in list(zip(tail, tail[1:])) for x in ("127.0.0.1", name, "aks1.hcp.azmk8s.io")))
    _check("node_count=2 -> 1 agent", (name + "-agent-1") in fd.containers and len([c for c in fd.containers if "agent" in c]) == 1)
    _check("exists() / idempotent create", rt.exists("azure", "/subs/x/aks1") and rt.create_cluster("azure", "/subs/x/aks1")["name"] == name
           and len([c for c in fd.containers if "agent" not in c]) == 1)
    kc = rt.kubeconfig("azure", "/subs/x/aks1")
    _check("kubeconfig: client cert kept, server rewritten, context named", "client-certificate-data: Q0VSVA==" in kc and "server: https://127.0.0.1:49152" in kc and ("current-context: " + name) in kc)
    _check("kubeconfig custom server_url", "server: https://k3s.local:6443" in rt.kubeconfig("azure", "/subs/x/aks1", "https://k3s.local:6443"))
    _check("list_clusters", rt.list_clusters() == [{"name": name, "cloud": "azure", "cluster": "cid", "state": "running"}])
    _check("wait_ready times out when nodes never Ready", _raises(lambda: _wait(k3s.K3sRuntime(docker=fd, sleep=lambda s: None), 5)))

    # ── RealK8sBackend contract ──
    be = rt.backend_factory()("azure", "/subs/x/aks1")
    _check("factory -> RealK8sBackend", isinstance(be, kube.RealK8sBackend) and rt.backend_factory()("azure", "nope") is None)
    fd.items = {
        "namespaces": [_obj("Namespace", n) for n in ("default", "kube-system", "kube-public", "kube-node-lease", "app")],
        "services": [_obj("Service", "web", "app", spec={"clusterIP": "10.0.0.1", "clusterIPs": ["10.0.0.1"], "ports": [{"port": 80}]}),
                     _obj("Service", "kubernetes", "default"), _obj("Service", "dns", "kube-system")],
        "configmaps": [_obj("ConfigMap", "cfg", "app", data={"a": "b"}), _obj("ConfigMap", "kube-root-ca.crt", "app")],
        "secrets": [_obj("Secret", "s", "app", type="Opaque"), _obj("Secret", "tok", "app", type="kubernetes.io/service-account-token")],
        "serviceaccounts": [_obj("ServiceAccount", "default", "app"), _obj("ServiceAccount", "sa1", "app")],
        "deployments.apps": [_obj("Deployment", "web", "app", spec={"replicas": 2})],
        "pods": [_obj("Pod", "web-1", "app", owner=True), _obj("Pod", "solo", "app", spec={"nodeName": "n0", "containers": []})],
        "persistentvolumeclaims": [_obj("PersistentVolumeClaim", "data", "app", spec={"volumeName": "pv-1", "resources": {}})],
    }
    snap = be.export_resources()
    objs = {(o["kind"], o["metadata"]["name"]) for o in snap["objects"]}
    _check("namespaces: user ns only, system + default excluded", [n["name"] for n in snap["namespaces"]] == ["app"])
    _check("owned pods, root-ca, default SA, token secret, kubernetes svc, kube-system skipped",
           objs == {("Service", "web"), ("ConfigMap", "cfg"), ("Secret", "s"), ("ServiceAccount", "sa1"), ("Deployment", "web"), ("Pod", "solo"), ("PersistentVolumeClaim", "data")})
    svc = next(o for o in snap["objects"] if o["kind"] == "Service")
    pvc = next(o for o in snap["objects"] if o["kind"] == "PersistentVolumeClaim")
    _check("cleaned: no status/uid/clusterIP/volumeName/nodeName", "status" not in svc and "uid" not in svc["metadata"] and "clusterIP" not in svc["spec"]
           and "volumeName" not in pvc["spec"] and "nodeName" not in next(o for o in snap["objects"] if o["kind"] == "Pod")["spec"])
    _check("same document shape as InMemory (kind/version/counts)", snap["kind"] == "VyomiKubeSnapshot" and snap["version"] == 1 and snap["counts"]["namespaces"] == 1 and snap["counts"]["deployments"] == 1)
    _check("namespaces filter", be.export_resources(["nonexistent"])["objects"] == [])
    out = be.apply([{"kind": "Deployment", "apiVersion": "apps/v1", "metadata": {"name": "d", "namespace": "app"}}, {"kind": "Namespace", "apiVersion": "v1", "metadata": {"name": "app"}}])
    _check("apply: namespaces first, one server-side apply each", [d["kind"] for d in fd.applied[-2:]] == ["Namespace", "Deployment"] and len(out) == 2)
    _check("apply used --server-side --force-conflicts", any(c[0][:2] == ["exec", "-i"] and "--server-side" in c[0] and "--force-conflicts" in c[0] for c in fd.calls))
    _check("health Healthy", be.health()["status"] == "Healthy")
    r = be.kubectl("kubectl get pods\ncat <<EOF | kubectl apply -f -\nkind: x\nEOF")
    _check("kubectl runCommand (argv exec'd, heredoc -> stdin)", r["exitCode"] == 0 and r["changed"] and "applied (yaml)" in r["logs"])
    _check("non-kubectl command refused (no shell)", be.kubectl("rm -rf /")["exitCode"] == 127)

    # ── AKS wiring ──
    old = (kube.CLUSTER_RUNTIME, kube.BACKEND_FACTORY)
    try:
        fd2 = FakeDocker()
        rt2 = k3s.K3sRuntime(docker=fd2, sleep=lambda s: None)
        k3s.install(rt2)
        a = AzureArm()
        h = lambda m, p, b=None, av="2024-04-01": a.handle(m, p, {"api-version": av}, b)
        R = f"/subscriptions/{S}/resourceGroups"
        h("PUT", f"{R}/rg1", {"location": "eastus"}, "2021-04-01")
        CL = f"{R}/rg1/providers/Microsoft.ContainerService/managedClusters/aks1"
        r = h("PUT", CL, {"location": "eastus", "properties": {"kubernetesVersion": "1.29.0", "dnsPrefix": "a", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_B2s", "mode": "System"}]}}, "2024-09-02-preview")
        _check("AKS PUT starts a k3s server container", r["status"] in (200, 201) and len([c for c in fd2.containers if "agent" not in c]) == 1)
        for _ in range(100):
            if h("GET", CL, None, "2024-09-02-preview")["body"]["properties"]["provisioningState"] == "Succeeded":
                break
            time.sleep(0.05)
        _check("provisioningState Creating -> Succeeded once k3s is Ready", h("GET", CL, None, "2024-09-02-preview")["body"]["properties"]["provisioningState"] == "Succeeded")
        rc = h("POST", CL + "/runCommand", {"command": "kubectl get pods"}, "2024-09-02-preview")["body"]["properties"]
        _check("runCommand executes the REAL kubectl (via docker exec)", rc["exitCode"] == 0 and any(c[0][0] == "exec" and "kubectl" in c[0] and "pods" in c[0] for c in fd2.calls))
        cred = h("POST", CL + "/listClusterUserCredential", None, "2024-09-02-preview")["body"]["kubeconfigs"][0]
        _check("listClusterUserCredential returns the real kubeconfig", "client-certificate-data: Q0VSVA==" in base64.b64decode(cred["value"]).decode())
        _check("AKS DELETE removes the k3s container + volume", h("DELETE", CL, None, "2024-09-02-preview")["status"] in (200, 202, 204) and not fd2.containers and not fd2.volumes)

        # ── GKE wiring ──
        store = gke.ContainerStore()
        gke.create_cluster(store, "p", "us-central1-a", {"cluster": {"name": "g1", "initialNodeCount": 1}})
        full = gke.cluster_name("p", "us-central1-a", "g1")
        _check("GKE create starts k3s, status PROVISIONING|RUNNING", full in store.clusters and any("g1" not in c and c.startswith("vyomi-k3s-") for c in fd2.containers))
        for _ in range(100):
            if store.clusters[full]["status"] == gke.RUNNING:
                break
            time.sleep(0.05)
        _check("GKE status RUNNING + real CA in masterAuth", store.clusters[full]["status"] == gke.RUNNING and store.clusters[full]["masterAuth"]["clusterCaCertificate"] == "Q0FEQVRB")
        creds = gke.get_credentials(store, "p", "us-central1-a", "g1")
        _check("GKE getCredentials -> real kubeconfig", "client-key-data: S0VZ" in creds["kubeconfig"] and creds["endpoint"] == "https://127.0.0.1:49152")
        gke.delete_cluster(store, "p", "us-central1-a", "g1")
        _check("GKE delete removes the k3s container", not fd2.containers)
    finally:
        kube.CLUSTER_RUNTIME, kube.BACKEND_FACTORY = old

    # without the runtime the cores are unchanged (default Nano / dev path)
    store = gke.ContainerStore()
    gke.create_cluster(store, "p", "us-central1-a", {"cluster": {"name": "g2", "initialNodeCount": 1}})
    _check("no runtime installed -> cluster RUNNING immediately, no credentials", next(iter(store.clusters.values()))["status"] == gke.RUNNING
           and _raises(lambda: gke.get_credentials(store, "p", "us-central1-a", "g2")))
    print("k3s runtime (fake docker): ok")


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def _wait(r, n):
    import core.k3s_runtime as m
    orig = time.time
    t = [orig()]
    time.time = lambda: (t.__setitem__(0, t[0] + 100) or t[0])
    try:
        r.wait_ready("azure", "/subs/x/aks1", n, 300)
    finally:
        time.time = orig


if __name__ == "__main__":
    run()
