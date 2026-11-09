"""LIVE platform test on real Docker (needs VYOMI_LIVE_K3S=1): 2 nodes / 2 pools, scale, labels, workload-identity token verified against the SIMULATOR's
JWKS route (a real uvicorn server), LoadBalancer address + host reachability, PVC bound + data surviving a control-plane container restart AND a
stop/start AND an upgrade between the two pinned versions, external kubectl from the host, user-vs-admin credentials.
Images pulled: rancher/k3s:v1.30.5-k3s1 and rancher/k3s:v1.31.1-k3s1 only.
Run: VYOMI_LIVE_K3S=1 VYOMI_SERVER_PYTHON=<py3.11+ with the appliance deps> PYTHONPATH=. python3 tests/conformance/test_k3s_platform_live.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from core import k3s_identity as ident
from core import k3s_runtime as k3s

CLOUD, CID = "azure", "/subscriptions/live/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/plat1"
PORT = 9017
APP = """apiVersion: v1
kind: Namespace
metadata: {name: live}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: live}
spec:
  replicas: 1
  selector: {matchLabels: {app: web}}
  template:
    metadata: {labels: {app: web}}
    spec:
      containers:
      - name: web
        image: rancher/mirrored-library-busybox:1.36.1
        command: ["sh", "-c", "mkdir -p /www && echo vyomi-lb-ok > /www/index.html && httpd -f -p 8080 -h /www"]
---
apiVersion: v1
kind: Service
metadata: {name: web, namespace: live}
spec:
  type: LoadBalancer
  selector: {app: web}
  ports: [{port: 80, targetPort: 8080}]
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: data, namespace: live}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: managed-csi
  resources: {requests: {storage: 1Gi}}
---
apiVersion: v1
kind: Pod
metadata: {name: writer, namespace: live}
spec:
  containers:
  - name: w
    image: rancher/mirrored-library-busybox:1.36.1
    command: ["sh", "-c", "echo persisted-across-restart > /data/file && sleep 100000"]
    volumeMounts: [{name: d, mountPath: /data}]
  volumes: [{name: d, persistentVolumeClaim: {claimName: data}}]
"""


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n, flush=True)


def _until(fn, what, timeout=240, every=3):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:
            last = e
        time.sleep(every)
    raise AssertionError("timed out waiting for %s (last=%r)" % (what, last))


def host_kubectl(kcfg, *argv, timeout=60):
    p = subprocess.run(["kubectl", "--kubeconfig", kcfg, *argv], capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def run():
    tmp = tempfile.mkdtemp(prefix="vyomi-plat-")
    py = os.environ.get("VYOMI_SERVER_PYTHON") or sys.executable
    srv_proc = subprocess.Popen([py, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PORT)], stdout=open(tmp + "/server.log", "w"), stderr=subprocess.STDOUT,
                                env=dict(os.environ, PYTHONPATH=os.getcwd()))
    rt = k3s.K3sRuntime(issuer_base="https://oidc.vyomi.local")
    chash = k3s.cluster_hash(CLOUD, CID)
    try:
        _until(lambda: urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=3).status == 200, "simulator server", 120, 2)
        _check("simulator server (real uvicorn) is up", True)
        t0 = time.time()
        info = rt.create_cluster(CLOUD, CID, "1.30", pools=[{"name": "system", "count": 1, "vmSize": "Standard_D2s_v3", "labels": {"tier": "sys"}},
                                                           {"name": "user1", "count": 1, "vmSize": "Standard_B2s", "taints": ["dedicated=user:PreferNoSchedule"]}],
                                 oidc=True, wait=True, ready_timeout=900)
        print("      cluster ready in %.0fs; k3s %s; warnings=%s" % (time.time() - t0, info["k3sVersion"], rt.warnings), flush=True)
        _check("2-node cluster (2 pools) Ready, control plane has no kubelet", info["k3sVersion"] == "v1.30.5-k3s1")
        kc = rt.kubectl
        out = kc(CLOUD, CID, ["get", "nodes", "--show-labels", "--no-headers"])[1]
        _check("nodes carry AKS pool labels (agentpool=, instance-type, user label)", out.count("agentpool=system") == 1 and out.count("agentpool=user1") == 1
               and "node.kubernetes.io/instance-type=Standard_D2s_v3" in out and "tier=sys" in out)
        _check("taint applied to the user pool node", "dedicated" in kc(CLOUD, CID, ["get", "nodes", "-l", "agentpool=user1", "-o", "jsonpath={.items[0].spec.taints}"])[1])
        _check("exactly 2 nodes (control plane not a node)", len(out.strip().splitlines()) == 2)

        rt.scale_pool(CLOUD, CID, "user1", 2)
        out = kc(CLOUD, CID, ["get", "nodes", "-l", "agentpool=user1", "--no-headers"])[1]
        _check("scale pool user1 1->2: 3 Ready nodes, 2 in pool", len(out.strip().splitlines()) == 2 and rt.expected_nodes(CLOUD, CID) == 3)
        rt.scale_pool(CLOUD, CID, "user1", 1)
        _check("scale back to 1: node object gone", len(kc(CLOUD, CID, ["get", "nodes", "--no-headers"])[1].strip().splitlines()) == 2)

        # ── identity against the simulator JWKS ──
        iss = rt.issuer(CLOUD, CID)
        kc(CLOUD, CID, ["create", "namespace", "apps"])
        kc(CLOUD, CID, ["-n", "apps", "create", "serviceaccount", "builder"])
        tok = rt.mint_service_account_token(CLOUD, CID, "apps", "builder", "sts.amazonaws.com")
        disc = json.load(urllib.request.urlopen("http://127.0.0.1:%d/oidc/%s/%s/.well-known/openid-configuration" % (PORT, CLOUD, chash)))
        _check("simulator serves OIDC discovery for the cluster", disc["issuer"] == iss and disc["jwks_uri"] == iss + "/keys")
        fetch = lambda cloud, h: json.load(urllib.request.urlopen("http://127.0.0.1:%d/oidc/%s/%s/keys" % (PORT, cloud, h), timeout=10))
        jwks = fetch(CLOUD, chash)
        _check("simulator JWKS = the cluster's real public key(s)", jwks["keys"] and jwks["keys"][0]["kty"] == "RSA")
        cl = ident.verify_token(tok, audience="sts.amazonaws.com", jwks_fetcher=fetch)
        _check("projected SA token verified against the simulator JWKS (sub/aud/iss)", cl["sub"] == "system:serviceaccount:apps:builder" and cl["aud"] == ["sts.amazonaws.com"] and cl["iss"] == iss)
        _check("wrong audience rejected", _raises(lambda: ident.verify_token(tok, audience="other", jwks_fetcher=fetch)))
        _check("tampered token rejected", _raises(lambda: ident.verify_token(tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB"), jwks_fetcher=fetch)))
        a = rt._inspect(k3s.server_name(CLOUD, CID))["Args"]
        _check("API server really started with OIDC auth flags", any(x.startswith("oidc-issuer-url=") for x in a))

        # ── external client from the host ──
        adm, usr = os.path.join(tmp, "admin.kubeconfig"), os.path.join(tmp, "user.kubeconfig")
        open(adm, "w").write(rt.kubeconfig(CLOUD, CID))
        open(usr, "w").write(rt.kubeconfig(CLOUD, CID, role="user"))
        if shutil.which("kubectl"):
            rc, out, err = host_kubectl(adm, "get", "nodes")
            print(out, flush=True)
            _check("HOST kubectl (published API port, client cert) sees nodes Ready", rc == 0 and out.count(" Ready") == 2)
            _check("admin can do anything", host_kubectl(adm, "auth", "can-i", "*", "*")[1].strip() == "yes")
            _check("user credential: can read pods cluster-wide", host_kubectl(usr, "auth", "can-i", "list", "pods", "-A")[1].strip() == "yes")
            _check("user credential: can edit default ns", host_kubectl(usr, "auth", "can-i", "create", "deployments", "-n", "default")[1].strip() == "yes")
            _check("user credential: cannot touch kube-system / secrets / cluster-admin things",
                   host_kubectl(usr, "auth", "can-i", "create", "deployments", "-n", "kube-system")[1].strip() == "no"
                   and host_kubectl(usr, "auth", "can-i", "get", "secrets", "-A")[1].strip() == "no" and host_kubectl(usr, "auth", "can-i", "*", "*")[1].strip() == "no")
        else:
            print("      (no kubectl on host: external-client check skipped)")

        # ── workload: LB + PVC ──
        _check("deploy app (Deployment+LB Service+PVC+writer pod)", kc(CLOUD, CID, ["apply", "-f", "-"], APP)[0] == 0)
        _until(lambda: "Running" in kc(CLOUD, CID, ["-n", "live", "get", "pods", "--no-headers"])[1] and kc(CLOUD, CID, ["-n", "live", "get", "pods", "--no-headers"])[1].count("Running") == 2,
               "web+writer Running (nested image pull)", 420)
        _check("pods Running on the real kubelet", True)
        rt.ensure_storage(CLOUD, CID)
        sc = kc(CLOUD, CID, ["get", "sc", "--no-headers"])[1]
        _check("AKS StorageClasses present, managed-csi is the only default", "managed-csi (default)" in sc and sc.count("(default)") == 1)
        pvs = _until(lambda: rt.volumes(CLOUD, CID), "PV recorded")
        print("      volumes:", json.dumps(pvs), flush=True)
        _check("PVC bound; PV->docker volume mapping recorded", pvs[0]["claim"] == "data" and pvs[0]["dockerVolume"].endswith("-data") and pvs[0]["phase"] == "Bound")
        lbs = _until(lambda: [x for x in rt.reconcile_loadbalancers(CLOUD, CID) if x["name"] == "web"], "LB reconcile")
        ip = lbs[0]["ingress"][0]["ip"]
        ep = lbs[0]["endpoints"][80]
        _check("LB address allocated from the simulator pool and written to status", ip.startswith("20.") and
               ip in kc(CLOUD, CID, ["-n", "live", "get", "svc", "web", "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}"])[1])
        body = _until(lambda: urllib.request.urlopen("http://%s/" % ep, timeout=5).read().decode(), "LB reachable from host")
        _check("LB reachable from the HOST at %s (-> %s)" % (ep, ip), "vyomi-lb-ok" in body)

        def filecontent():
            return kc(CLOUD, CID, ["-n", "live", "exec", "writer", "--", "cat", "/data/file"])[1].strip()
        _until(lambda: filecontent() == "persisted-across-restart", "file written to PV")
        # control-plane container restart
        subprocess.run(["docker", "restart", k3s.server_name(CLOUD, CID)], capture_output=True, timeout=120)
        rt._ready.clear()
        _until(lambda: rt.is_ready(CLOUD, CID), "API back after server restart", 180)
        _check("data survives a SERVER container restart", filecontent() == "persisted-across-restart")

        # stop / start
        rt.stop_cluster(CLOUD, CID)
        states = subprocess.run(["docker", "ps", "-a", "--filter", "label=vyomi.k3s.name=" + k3s.server_name(CLOUD, CID), "--format", "{{.State}}"], capture_output=True, text=True).stdout.split()
        _check("stop: every container really exited", states and all(s == "exited" for s in states))
        _check("stop: API unreachable", not rt.is_running(CLOUD, CID) and rt.kubectl(CLOUD, CID, ["get", "nodes"], timeout=10)[0] != 0)
        rt.start_cluster(CLOUD, CID, ready_timeout=300)
        _until(lambda: "persisted-across-restart" == filecontent(), "writer pod back + data intact after stop/start", 300)
        _check("start: cluster back, PV data intact after stop/start", True)

        # upgrade
        up = rt.upgrade_cluster(CLOUD, CID, "1.31", ready_timeout=300)
        _check("upgrade reports new version", up["upgraded"] and up["actualVersion"] == "1.31.1" and rt.cluster_version(CLOUD, CID) == "1.31.1")
        ver = kc(CLOUD, CID, ["get", "nodes", "-o", "jsonpath={.items[*].status.nodeInfo.kubeletVersion}"])[1]
        _check("kubelets on all nodes run v1.31.1+k3s1", ver.split() and all(v == "v1.31.1+k3s1" for v in ver.split()))
        _check("server version v1.31.1", "v1.31.1" in kc(CLOUD, CID, ["version"])[1])
        _until(lambda: "persisted-across-restart" == filecontent(), "writer pod + data after upgrade", 300)
        _check("PV data survives the upgrade", True)
        tok2 = rt.mint_service_account_token(CLOUD, CID, "apps", "builder", "sts.amazonaws.com")
        ident.CACHE.clear()
        _check("token verification still works after upgrade (signing key kept on the data volume)", ident.verify_token(tok2, "sts.amazonaws.com", jwks_fetcher=fetch)["namespace"] == "apps")
        print("live platform: ok", flush=True)
    finally:
        rt._stop_forwards(k3s.server_name(CLOUD, CID))
        rt.delete_cluster(CLOUD, CID)
        srv_proc.terminate()
        left = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "name=" + k3s.server_name(CLOUD, CID)], capture_output=True, text=True).stdout.split()
        vols = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "label=vyomi.k3s.name=" + k3s.server_name(CLOUD, CID)], capture_output=True, text=True).stdout.split()
        print("cleanup: containers left=%s volumes left=%s" % (left, vols), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


if __name__ == "__main__":
    if os.environ.get("VYOMI_LIVE_K3S") != "1" or not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("SKIP: needs docker and VYOMI_LIVE_K3S=1")
        sys.exit(0)
    run()
