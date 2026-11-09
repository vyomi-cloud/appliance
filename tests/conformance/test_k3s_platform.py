"""Shared k3s PLATFORM layer (versions, pools, stop/start, upgrade, workload identity, LoadBalancer, storage, user/admin creds, startup wiring)
against a FAKE docker (always runs). Live counterpart: tests/conformance/test_k3s_platform_live.py (VYOMI_LIVE_K3S=1).
Run: PYTHONPATH=. python3 tests/conformance/test_k3s_platform.py"""
import base64
import hashlib
import json
import os
import random
import socket
import threading
import time

from core import k3s_identity as ident
from core import k3s_runtime as k3s
from core import k3s_versions as ver
from core import kube_state_core as kube
from core import gcp_container_core as gke
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
from tests.conformance.k3s_fake import FakeDocker


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _raises(fn, exc=Exception):
    try:
        fn()
    except exc:
        return True
    return False


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ── tiny RSA for signing test tokens (no crypto libs in the appliance) ──
def _prime(bits, rnd):
    while True:
        n = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13)) and all(n % p for p in (3, 5, 7, 11, 13)):
            return n


def _rsa(bits=1024, seed=7):
    rnd = random.Random(seed)
    while True:
        p, q = _prime(bits // 2, rnd), _prime(bits // 2, rnd)
        e = 65537
        try:
            d = pow(e, -1, (p - 1) * (q - 1))
        except ValueError:
            continue
        return p * q, e, d


def _jwk(n, e, kid):
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "n": _b64(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": _b64(e.to_bytes(3, "big"))}


def _sign(n, d, kid, claims):
    h = _b64(json.dumps({"alg": "RS256", "kid": kid}).encode())
    c = _b64(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    t = ident._SHA256_PREFIX + hashlib.sha256((h + "." + c).encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return h + "." + c + "." + _b64(pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big"))


def run():
    # ── versions ──
    _check("resolve exact minor", ver.resolve("azure", "1.30.2")["k3sTag"] == "v1.30.5-k3s1" and ver.resolve("azure", "1.30.2")["exact"])
    _check("resolve nearest: AKS has no 1.28 -> 1.29", ver.resolve("azure", "1.28")["minor"] == "1.29")
    _check("resolve nearest: GKE 1.40 -> newest 1.32", ver.resolve("gcp", "1.40.1-gke.100")["minor"] == "1.32")
    _check("resolve latest/None -> default minor, EKS keeps 1.28", ver.resolve("aws", None)["minor"] == "1.30" and ver.resolve("aws", "1.28")["minor"] == "1.28")
    _check("actual version is the k3s patch, not the request", ver.resolve("gcp", "1.31")["version"] == "1.31.1")
    _check("every table tag is a k3s image tag", all(t.startswith("v1.") and t.endswith("-k3s1") for t in ver.K3S_BY_MINOR.values()))

    fd = FakeDocker()
    rt = k3s.K3sRuntime(docker=fd, sleep=lambda s: None)

    # ── pools ──
    pools = [{"name": "system", "count": 1, "vmSize": "Standard_D2s_v3", "labels": {"tier": "sys"}, "taints": ["CriticalAddonsOnly=true:NoSchedule"]},
             {"name": "user1", "count": 2, "vmSize": "Standard_B2s"}]
    info = rt.create_cluster("azure", "/subs/x/aks2", "1.31", pools=pools, wait=True)
    srv = info["name"]
    _check("version 1.31 -> v1.31.1-k3s1 image, reported 1.31.1", info["k3sVersion"] == "v1.31.1-k3s1" and info["actualVersion"] == "1.31.1"
           and fd.containers[srv]["image"] == "rancher/k3s:v1.31.1-k3s1")
    _check("3 agents, one per pool node", len(fd.agents(srv)) == 3)
    a0 = fd.containers[k3s.agent_name(srv, "system", 0)]["args"]
    pairs = list(zip(a0, a0[1:]))
    _check("AKS node labels agentpool=/kubernetes.azure.com/agentpool= + instance-type + user label",
           ("--node-label", "agentpool=system") in pairs and ("--node-label", "kubernetes.azure.com/agentpool=system") in pairs
           and ("--node-label", "node.kubernetes.io/instance-type=Standard_D2s_v3") in pairs and ("--node-label", "tier=sys") in pairs)
    _check("taint passed to the kubelet", ("--node-taint", "CriticalAddonsOnly=true:NoSchedule") in pairs)
    _check("EKS / GKE label conventions", k3s.node_labels("aws", "ng1")["eks.amazonaws.com/nodegroup"] == "ng1"
           and k3s.node_labels("gcp", "p1")["cloud.google.com/gke-nodepool"] == "p1")
    _check("GKE taint objects normalised", k3s.normalize_taints([{"key": "k", "value": "v", "effect": "NO_SCHEDULE"}]) == ["k=v:NoSchedule"])
    lp = {p["name"]: p for p in rt.list_pools("azure", "/subs/x/aks2")}
    _check("list_pools: counts + config recovered from Docker", lp["system"]["count"] == 1 and lp["user1"]["count"] == 2 and lp["system"]["taints"] == ["CriticalAddonsOnly=true:NoSchedule"]
           and lp["user1"]["vmSize"] == "Standard_B2s")
    _check("control plane has no kubelet (--disable-agent)", "--disable-agent" in fd.containers[srv]["args"])
    rt.scale_pool("azure", "/subs/x/aks2", "user1", 4)
    _check("scale up adds agents with the next ordinals", len(fd.agents(srv)) == 5 and k3s.agent_name(srv, "user1", 3) in fd.containers)
    rt.scale_pool("azure", "/subs/x/aks2", "user1", 1)
    _check("scale down removes highest ordinals + their volume", fd.agents(srv) == sorted([k3s.agent_name(srv, "system", 0), k3s.agent_name(srv, "user1", 0)])
           and (k3s.agent_name(srv, "user1", 3) + "-data") not in fd.volumes)
    _check("scale down drains and deletes the node", any(k[:1] == ["drain"] for k, _ in fd.kube_calls) and any(k[:2] == ["delete", "node"] for k, _ in fd.kube_calls))
    rt.add_pool("azure", "/subs/x/aks2", {"name": "extra", "count": 1, "labels": {"workload": "batch"}})
    _check("add_pool", len(fd.agents(srv)) == 3 and _raises(lambda: rt.add_pool("azure", "/subs/x/aks2", {"name": "extra", "count": 1}), k3s.K3sError))
    rt.scale_pool("azure", "/subs/x/aks2", "extra", 0)
    _check("scale to 0 keeps the pool definition", any(p["name"] == "extra" and p["count"] == 0 for p in rt.list_pools("azure", "/subs/x/aks2")))
    rt.sync_pools("azure", "/subs/x/aks2", [{"name": "system", "count": 2, "vmSize": "x"}, {"name": "user1", "count": 1}])
    names = {p["name"]: p["count"] for p in rt.list_pools("azure", "/subs/x/aks2")}
    _check("sync_pools: scaled system, kept user1, deleted extra", names == {"system": 2, "user1": 1})
    rt.delete_pool("azure", "/subs/x/aks2", "user1")
    _check("delete_pool removes agents + marker", "user1" not in {p["name"] for p in rt.list_pools("azure", "/subs/x/aks2")})

    # ── stop / start ──
    rt.stop_cluster("azure", "/subs/x/aks2")
    _check("stop: server + agents stopped, volumes kept", not fd.containers[srv]["running"] and not any(fd.containers[n]["running"] for n in fd.agents(srv))
           and (srv + "-data") in fd.volumes and not rt.is_running("azure", "/subs/x/aks2"))
    rt.start_cluster("azure", "/subs/x/aks2")
    _check("start: everything running again and Ready", rt.is_running("azure", "/subs/x/aks2") and all(fd.containers[n]["running"] for n in fd.agents(srv)))

    # ── upgrade ──
    tok = rt._token("azure", "/subs/x/aks2")
    before_vol = dict(fd.volumes)
    res = rt.upgrade_cluster("azure", "/subs/x/aks2", "1.32")
    _check("upgrade: new server image, same data volume, same token", res["upgraded"] and fd.containers[srv]["image"] == "rancher/k3s:v1.32.0-k3s1"
           and (srv + "-data") in fd.volumes and rt._token("azure", "/subs/x/aks2") == tok)
    _check("upgrade: server removed WITHOUT -v (volume kept)", any(c[0] == ["rm", "-f", srv] for c in fd.calls) and not any(c[0][:3] == ["rm", "-f", "-v"] and c[0][-1] == srv for c in fd.calls))
    _check("upgrade: agents rolled onto the new image, pool/labels preserved", all(fd.containers[n]["image"] == "rancher/k3s:v1.32.0-k3s1" for n in fd.agents(srv))
           and ("--node-label", "agentpool=system") in list(zip(fd.containers[fd.agents(srv)[0]]["args"], fd.containers[fd.agents(srv)[0]]["args"][1:])))
    _check("upgrade: cluster_version reflects it; same version = no-op; downgrade refused", rt.cluster_version("azure", "/subs/x/aks2") == "1.32.0"
           and not rt.upgrade_cluster("azure", "/subs/x/aks2", "1.32")["upgraded"] and _raises(lambda: rt.upgrade_cluster("azure", "/subs/x/aks2", "1.30"), k3s.K3sError))

    # ── identity plumbing ──
    iss = rt.issuer("azure", "/subs/x/aks2")
    a = fd.containers[srv]["args"]
    _check("API server flags: service-account-issuer + jwks-uri point at the simulator", ("service-account-issuer=" + iss) in a
           and ("service-account-jwks-uri=" + iss + "/keys") in a and "/oidc/azure/" + k3s.cluster_hash("azure", "/subs/x/aks2") in iss)
    _check("OIDC discovery doc", rt.oidc_discovery("azure", k3s.cluster_hash("azure", "/subs/x/aks2"))["jwks_uri"] == iss + "/keys")
    n, e, d = _rsa()
    chash = k3s.cluster_hash("azure", "/subs/x/aks2")
    fd.kubectl_hook = lambda k, st: (0, json.dumps({"keys": [_jwk(n, e, "k1")]}), "") if k[:3] == ["get", "--raw", "/openid/v1/jwks"] else None
    jw = rt.oidc_jwks("azure", chash)
    _check("JWKS read from the cluster's API server", jw["keys"][0]["kid"] == "k1")
    now = int(time.time())
    claims = {"iss": iss, "sub": "system:serviceaccount:app:builder", "aud": ["sts.amazonaws.com"], "exp": now + 600, "iat": now}
    good = _sign(n, d, "k1", claims)
    c = rt.verify_token(good, audience="sts.amazonaws.com")
    _check("verify_token: claims + ns/sa/cluster", c["sub"] == "system:serviceaccount:app:builder" and c["namespace"] == "app" and c["serviceAccount"] == "builder"
           and c["cloud"] == "azure" and c["clusterHash"] == chash and c["aud"] == ["sts.amazonaws.com"])
    _check("verify_token: wrong audience rejected", _raises(lambda: rt.verify_token(good, audience="api://AzureADTokenExchange"), ident.TokenError))
    _check("verify_token: expired rejected", _raises(lambda: rt.verify_token(_sign(n, d, "k1", dict(claims, exp=now - 3600))), ident.TokenError))
    parts = good.split(".")
    _check("verify_token: tampered payload rejected", _raises(lambda: rt.verify_token(parts[0] + "." + _b64(json.dumps(dict(claims, sub="system:serviceaccount:kube-system:admin")).encode()) + "." + parts[2]), ident.TokenError))
    n2, e2, d2 = _rsa(seed=11)
    _check("verify_token: signed by another key rejected", _raises(lambda: rt.verify_token(_sign(n2, d2, "k1", claims)), ident.TokenError))
    _check("verify_token: unknown kid rejected (after one JWKS refetch)", _raises(lambda: rt.verify_token(_sign(n, d, "zz", claims)), ident.TokenError))
    _check("verify_token: foreign issuer rejected", _raises(lambda: rt.verify_token(_sign(n, d, "k1", dict(claims, iss="https://evil.example/")) ), ident.TokenError))
    # API-server OIDC authentication option
    rt.create_cluster("gcp", "p/l/oidc1", "1.30", 1, oidc={"clientId": "vyomi-k8s"}, wait=True)
    oa = fd.containers[k3s.server_name("gcp", "p/l/oidc1")]["args"]
    _check("--oidc-* kube-apiserver args when oidc= is requested", "oidc-client-id=vyomi-k8s" in oa and any(x.startswith("oidc-issuer-url=") and "/oidc/idp/gcp" in x for x in oa))
    _check("no oidc args by default", not any(str(x).startswith("oidc-issuer-url") for x in fd.containers[srv]["args"]))

    # ── storage + user/admin credentials ──
    fd.applied.clear()
    rt.ensure_storage("azure", "/subs/x/aks2")
    docs = [x for k, st in fd.kube_calls if k[:1] == ["apply"] and st and "StorageClass" in st for x in [st]]
    _check("AKS StorageClasses (managed-csi default) on local-path", docs and "name: managed-csi," in docs[-1] and "is-default-class" in docs[-1].split("---")[0]
           and docs[-1].count("rancher.io/local-path") == len(k3s.STORAGE_CLASSES["azure"]))
    _check("k3s' own local-path class demoted from default", any(k[:3] == ["patch", "storageclass", "local-path"] for k, _ in fd.kube_calls))
    _check("per-cloud class names", k3s.STORAGE_CLASSES["aws"][0] == "gp2" and k3s.STORAGE_CLASSES["gcp"][0] == "standard-rwo")
    fd.items["pv"] = [{"metadata": {"name": "pvc-abc"}, "spec": {"capacity": {"storage": "1Gi"}, "storageClassName": "managed-csi", "hostPath": {"path": "/var/lib/rancher/k3s/storage/pvc-abc_app_data"},
                       "claimRef": {"name": "data", "namespace": "app"},
                       "nodeAffinity": {"required": {"nodeSelectorTerms": [{"matchExpressions": [{"key": "kubernetes.io/hostname", "operator": "In", "values": [fd.agents(srv)[0]]}]}]}}},
                       "status": {"phase": "Bound"}}]
    v = rt.volumes("azure", "/subs/x/aks2")[0]
    _check("PV -> docker volume mapping", v["pv"] == "pvc-abc" and v["claim"] == "data" and v["dockerVolume"] == fd.agents(srv)[0] + "-data" and v["size"] == "1Gi" and v["phase"] == "Bound")
    uk = rt.kubeconfig("azure", "/subs/x/aks2", role="user")
    ak = rt.kubeconfig("azure", "/subs/x/aks2")
    _check("user kubeconfig: CA + bearer token only; admin: client cert + key", "token: user-token" in uk and "certificate-authority-data: Q0FEQVRB" in uk and "client-key-data" not in uk and "client-key-data: S0VZ" in ak)
    rt.ensure_user_rbac("azure", "/subs/x/aks2")
    rb = [st for k, st in fd.kube_calls if k[:1] == ["apply"] and st and "ClusterRoleBinding" in st][-1]
    _check("user SA bound to view cluster-wide + edit in default only (not cluster-admin)", "name: view" in rb and "name: edit" in rb and "cluster-admin" not in rb)

    # ── LoadBalancer ──
    echo = socket.socket(); echo.bind(("127.0.0.1", 0)); echo.listen(5); ep = echo.getsockname()[1]
    def serve():
        while True:
            try:
                c, _ = echo.accept()
            except OSError:
                return
            c.sendall(c.recv(100).upper()); c.close()
    threading.Thread(target=serve, daemon=True).start()
    fd.node_ip = "127.0.0.1"
    svcs = [{"metadata": {"name": "web", "namespace": "app"}, "spec": {"type": "LoadBalancer", "ports": [{"port": 80, "nodePort": ep}]}, "status": {}},
            {"metadata": {"name": "web2", "namespace": "app"}, "spec": {"type": "LoadBalancer", "ports": [{"port": 80, "nodePort": ep}]}, "status": {}},
            {"metadata": {"name": "internal", "namespace": "app"}, "spec": {"type": "ClusterIP", "ports": [{"port": 80}]}}]
    fd.items["svc"] = svcs
    res = rt.reconcile_loadbalancers("azure", "/subs/x/aks2")
    ips = [r["ingress"][0]["ip"] for r in res]
    _check("LB: two distinct addresses from the pool, ClusterIP service ignored", len(res) == 2 and len(set(ips)) == 2 and all(i.startswith("20.") for i in ips))
    patches = [k for k, _ in fd.kube_calls if k and k[0:3] and "--subresource=status" in k]
    _check("LB: status.loadBalancer.ingress written via the status subresource", len(patches) == 2 and "loadBalancer" in patches[0][-1])
    port = int(res[0]["endpoints"][80].split(":")[1])
    s = socket.create_connection(("127.0.0.1", port), timeout=5); s.sendall(b"hello"); got = s.recv(100); s.close()
    _check("LB: address reachable on the host (forwarded to the node port)", got == b"HELLO")
    svcs[0]["status"] = {"loadBalancer": {"ingress": [res[0]["ingress"][0]]}}
    n_before = len(patches)
    rt.reconcile_loadbalancers("azure", "/subs/x/aks2")
    _check("LB: idempotent (no re-allocation of an assigned service)", len([k for k, _ in fd.kube_calls if "--subresource=status" in k]) == n_before + 1)
    eks = k3s.default_lb_allocator("aws", "arn:eks/x", "d", "api", set())
    _check("EKS gets an ELB hostname, not an IP", "hostname" in eks and eks["hostname"].endswith(".elb.us-east-1.amazonaws.com"))
    del fd.items["svc"][0]
    rt.reconcile_loadbalancers("azure", "/subs/x/aks2")
    _check("LB: forward torn down when the Service goes away", all(k[2] != "web" for k in rt._forwards))
    echo.close()

    # ── raw API passthrough (GKE /k8s) ──
    fd.kubectl_hook = lambda k, st: (0, json.dumps({"kind": "NamespaceList", "items": []}), "") if k[:3] == ["get", "--raw", "/api/v1/namespaces"] else \
        (1, "", "Error from server (NotFound): the server could not find the requested resource") if k[:2] == ["get", "--raw"] else None
    _check("api_request GET passes through", rt.api_request("gcp", "p/l/oidc1", "GET", "/api/v1/namespaces") == (200, {"kind": "NamespaceList", "items": []}))
    _check("api_request maps API errors to a Status", rt.api_request("gcp", "p/l/oidc1", "GET", "/api/v1/nope")[0] == 404)
    fd.kubectl_hook = None

    # ── GKE: real pools / upgrade / data plane passthrough ──
    old = (kube.CLUSTER_RUNTIME, kube.BACKEND_FACTORY)
    try:
        fd3 = FakeDocker()
        rt3 = k3s.K3sRuntime(docker=fd3, sleep=lambda s: None)
        k3s.install(rt3)
        store = gke.ContainerStore()
        gke.create_cluster(store, "p", "us-central1-a", {"cluster": {"name": "g1", "nodePools": [{"name": "gp1", "initialNodeCount": 1, "config": {"machineType": "e2-standard-2", "labels": {"x": "y"}}}]}})
        full = gke.cluster_name("p", "us-central1-a", "g1")
        for _ in range(100):
            if store.clusters[full]["status"] == gke.RUNNING:
                break
            time.sleep(0.05)
        sn = k3s.server_name("gcp", full)
        _check("GKE node pool -> agent labelled cloud.google.com/gke-nodepool + user labels", len(fd3.agents(sn)) == 1
               and any(x == "cloud.google.com/gke-nodepool=gp1" for x in fd3.containers[fd3.agents(sn)[0]]["args"]))
        gke.create_pool(store, "p", "us-central1-a", "g1", {"nodePool": {"name": "gp2", "initialNodeCount": 2}})
        for _ in range(100):
            if len(fd3.agents(sn)) == 3:
                break
            time.sleep(0.05)
        _check("GKE nodePools.create really adds nodes", len(fd3.agents(sn)) == 3)
        gke.pool_setting(store, "p", "us-central1-a", "g1", "gp2", "setSize", {"nodeCount": 1})
        for _ in range(100):
            if len(fd3.agents(sn)) == 2:
                break
            time.sleep(0.05)
        _check("GKE setSize really scales", len(fd3.agents(sn)) == 2)
        fd3.kubectl_hook = lambda k, st: (0, json.dumps({"kind": "PodList", "items": []}), "") if k[:3] == ["get", "--raw", "/api/v1/namespaces/default/pods"] else None
        r = gke._clusters(store, "GET", "p", "us-central1-a", ["g1", "k8s", "api", "v1", "namespaces", "default", "pods"], None, {}, False)
        _check("GKE /k8s dataplane served by the REAL API server (not the simulated store)", json.loads(r.body)["kind"] == "PodList" and "g1" not in store.k8s)
        gke.update_cluster(store, "p", "us-central1-a", "g1", {"update": {"desiredMasterVersion": gke.VALID_VERSIONS[0]}})
        for _ in range(100):
            if store.clusters[full]["status"] == gke.RUNNING:
                break
            time.sleep(0.05)
        _check("GKE master upgrade replaces the server image", store.clusters[full]["status"] == gke.RUNNING and fd3.containers[sn]["image"].startswith("rancher/k3s:v1."))

        # ── AKS: pools via agentPools child + stop/start via the ARM action ──
        arm = AzureArm()
        h = lambda m, p, b=None, av="2024-09-02-preview": arm.handle(m, p, {"api-version": av}, b)
        R = f"/subscriptions/{S}/resourceGroups"
        CL = f"{R}/rg1/providers/Microsoft.ContainerService/managedClusters/aks9"
        h("PUT", f"{R}/rg1", {"location": "eastus"}, "2021-04-01")
        h("PUT", CL, {"location": "eastus", "properties": {"kubernetesVersion": "1.30", "dnsPrefix": "a", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_B2s", "mode": "System", "nodeLabels": {"k": "v"}}]}})
        for _ in range(100):
            if h("GET", CL)["body"]["properties"]["provisioningState"] == "Succeeded":
                break
            time.sleep(0.05)
        rid = h("GET", CL)["body"]["id"]
        sn = k3s.server_name("azure", rid)
        _check("AKS pool -> agent with agentpool= label", len(fd3.agents(sn)) == 1 and any(x == "agentpool=np" for x in fd3.containers[fd3.agents(sn)[0]]["args"]))
        h("PUT", CL + "/agentPools/user2", {"properties": {"count": 2, "vmSize": "Standard_D4s_v3", "mode": "User", "nodeTaints": ["gpu=true:NoSchedule"]}})
        for _ in range(100):
            if len(fd3.agents(sn)) == 3:
                break
            time.sleep(0.05)
        _check("AKS agentPools PUT adds a real pool (labels, taints, size)", len(fd3.agents(sn)) == 3 and any(x == "gpu=true:NoSchedule" for n_ in fd3.agents(sn) for x in fd3.containers[n_]["args"]))
        h("DELETE", CL + "/agentPools/user2")
        for _ in range(100):
            if len(fd3.agents(sn)) == 1:
                break
            time.sleep(0.05)
        _check("AKS agentPools DELETE removes the nodes", len(fd3.agents(sn)) == 1)
        st = h("POST", CL + "/stop")
        _check("AKS stop really stops the containers", st["status"] == 200 and not fd3.containers[sn]["running"] and h("GET", CL)["body"]["properties"]["powerState"]["code"] == "Stopped")
        _check("stopped cluster refuses runCommand", h("POST", CL + "/runCommand", {"command": "kubectl get pods"})["status"] == 409)
        sr = h("POST", CL + "/start")
        for _ in range(100):
            if h("GET", CL)["body"]["properties"]["provisioningState"] == "Succeeded":
                break
            time.sleep(0.05)
        _check("AKS start really starts them", sr["status"] == 200 and fd3.containers[sn]["running"])
        h("PUT", CL, {"location": "eastus", "properties": {"kubernetesVersion": "1.31", "dnsPrefix": "a", "agentPoolProfiles": [{"name": "np", "count": 1, "vmSize": "Standard_B2s"}]}})
        for _ in range(200):
            if fd3.containers[sn]["image"].endswith("v1.31.1-k3s1") and h("GET", CL)["body"]["properties"]["provisioningState"] == "Succeeded":
                break
            time.sleep(0.05)
        _check("AKS kubernetesVersion bump upgrades the cluster", fd3.containers[sn]["image"].endswith("v1.31.1-k3s1"))
    finally:
        kube.CLUSTER_RUNTIME, kube.BACKEND_FACTORY = old

    # ── startup wiring ──
    os.environ.pop("VYOMI_K8S_BACKEND", None)
    _check("install_if_enabled: off by default", k3s.install_if_enabled() is None and kube.CLUSTER_RUNTIME is None)
    os.environ["VYOMI_K8S_BACKEND"] = "k3s"
    try:
        r = k3s.install_if_enabled()
        _check("install_if_enabled: VYOMI_K8S_BACKEND=k3s installs the runtime + backend factory + LB controller", kube.CLUSTER_RUNTIME is r and kube.BACKEND_FACTORY is not None
               and r._lb_thread is not None and r._lb_thread.is_alive())
        r._lb_stop.set()
    finally:
        os.environ.pop("VYOMI_K8S_BACKEND", None)
        kube.CLUSTER_RUNTIME = kube.BACKEND_FACTORY = None
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "server.py")).read()
    _check("server.py startup hook calls install_if_enabled + serves /oidc/<cloud>/<hash>/keys", "_k3s.install_if_enabled()" in src and '"/oidc/{cloud}/{chash}/keys"' in src
           and '/.well-known/openid-configuration' in src)
    print("k3s platform (fake docker): ok")


if __name__ == "__main__":
    run()
