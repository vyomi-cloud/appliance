"""Docker-driven k3s lifecycle: one REAL Kubernetes (k3s) per managed cluster (AKS / EKS / GKE) on the offline appliance / booster.

OFFLINE-ONLY module (shells out to the ``docker`` CLI). It is deliberately NOT part of the Pyodide/Nano core set
(``wasm/build_cores.py``): the substrate-free cores (azure_arm_core, gcp_container_core, kube_state_core) only see the
``kube_state_core.CLUSTER_RUNTIME`` hook, which ``install()`` fills in when ``VYOMI_K8S_BACKEND=k3s``.
The shared platform API (versions, node pools, stop/start/upgrade, workload identity, LoadBalancer, storage, user/admin credentials) is
documented in docs/architecture/v4.0/K8S-PLATFORM.md.

Everything that touches Docker goes through ONE injectable function (``set_docker`` / ``K3sRuntime(docker=...)``):
``docker(args: list[str], stdin: str | None, timeout: float) -> (returncode, stdout, stderr)``. Unit tests swap in a fake.

State lives in Docker itself (labels on containers/volumes), never in this process, so an appliance restart finds its clusters again:
  server container  vyomi-k3s-<hash>                 control plane only (--disable-agent); labels vyomi.k3s=server, vyomi.cloud, vyomi.cluster, ...
  agent containers  vyomi-k3s-<hash>-<pool>-<i>      the worker nodes; labels vyomi.k3s=agent, vyomi.k3s.pool, vyomi.k3s.poolcfg
  volumes           <container>-data                 /var/lib/rancher/k3s (etcd/certs for the server; containerd + local-path PV data for agents)
                    <server>-pool-<pool>             zero-size marker carrying the node pool definition (survives scale-to-0)
All on network ``vyomi-net``; the API server is also published on a random 127.0.0.1 host port for kubeconfigs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from core import k3s_identity, k3s_versions

NETWORK = "vyomi-net"
K3S_IMAGE_REPO = "rancher/k3s"
PINNED_K3S_VERSION = k3s_versions.K3S_BY_MINOR[k3s_versions.DEFAULT_MINOR]    # default image; see core/k3s_versions.py for the per-minor table
SERVER_FLAGS = ["--cluster-init", "--disable", "traefik", "--disable", "servicelb", "--disable", "metrics-server",
                "--disable-agent", "--write-kubeconfig-mode", "644"]         # control plane only: workers are the node-pool agents
KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"
DEFAULT_POOL = {"azure": "nodepool1", "aws": "ng-default", "gcp": "default-pool"}
USER_SA, USER_NS = "vyomi-cluster-user", "kube-system"

# StorageClasses every managed cluster ships (all backed by the k3s local-path provisioner; first = the default class)
STORAGE_CLASSES = {
    "azure": ["managed-csi", "managed-csi-premium", "azurefile-csi", "default"],
    "aws": ["gp2", "gp3"],
    "gcp": ["standard-rwo", "premium-rwo", "standard"],
}


def default_docker(args, stdin=None, timeout=120):
    try:
        p = subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "docker %s: timed out after %ss" % (args[0] if args else "", timeout)
    except FileNotFoundError:
        return 127, "", "docker CLI not found"


def cluster_hash(cloud, cluster_id):
    return hashlib.sha1(("%s:%s" % (cloud, cluster_id)).lower().encode()).hexdigest()[:10]


def server_name(cloud, cluster_id):
    return "vyomi-k3s-" + cluster_hash(cloud, cluster_id)


def pool_slug(pool):
    return re.sub(r"[^a-z0-9-]", "-", str(pool).lower())[:24].strip("-") or "pool"


def agent_name(server, pool, idx):
    return "%s-%s-%d" % (server, pool_slug(pool), idx)


def node_labels(cloud, pool, vm_size=None, extra=None):
    """Real per-cloud node-pool labels (AKS agentpool=, EKS eks.amazonaws.com/nodegroup=, GKE cloud.google.com/gke-nodepool=)."""
    cloud = (cloud or "").lower()
    if cloud == "azure":
        lab = {"agentpool": pool, "kubernetes.azure.com/agentpool": pool, "kubernetes.azure.com/cluster": "vyomi", "kubernetes.io/role": "agent"}
    elif cloud == "aws":
        lab = {"eks.amazonaws.com/nodegroup": pool, "eks.amazonaws.com/capacityType": "ON_DEMAND"}
    else:
        lab = {"cloud.google.com/gke-nodepool": pool, "cloud.google.com/gke-provisioning": "standard"}
    if vm_size:
        lab["node.kubernetes.io/instance-type"] = str(vm_size)
    lab.update({str(k): str(v) for k, v in (extra or {}).items()})
    return lab


_EFFECTS = {"NO_SCHEDULE": "NoSchedule", "PREFER_NO_SCHEDULE": "PreferNoSchedule", "NO_EXECUTE": "NoExecute"}


def normalize_taints(taints):
    """AKS ``["k=v:NoSchedule"]``, GKE ``[{key,value,effect:NO_SCHEDULE}]`` or EKS ``[{key,value,effect:NO_SCHEDULE}]`` -> ``["k=v:NoSchedule"]``."""
    out = []
    for t in taints or []:
        if isinstance(t, dict):
            eff = _EFFECTS.get(str(t.get("effect", "")).upper(), t.get("effect") or "NoSchedule")
            out.append("%s=%s:%s" % (t["key"], t.get("value", ""), eff))
        else:
            out.append(str(t))
    return out


def normalize_pool(cloud, p):
    p = dict(p or {})
    name = p.get("name") or DEFAULT_POOL.get((cloud or "").lower(), "pool1")
    return {"name": name, "count": max(0, int(p.get("count", 1) if p.get("count") is not None else 1)),
            "vmSize": p.get("vmSize") or p.get("machineType") or p.get("instanceType") or "",
            "labels": dict(p.get("labels") or {}), "taints": normalize_taints(p.get("taints"))}


class K3sError(Exception):
    pass


class K3sRuntime:
    def __init__(self, docker=None, sleep=time.sleep, image_version=None, issuer_base=None):
        self.docker = docker or default_docker
        self.sleep = sleep
        self.image_version = image_version                 # forces ONE tag for every cluster (tests / air-gapped); None = per-minor table
        self.issuer_base = (issuer_base or os.environ.get("VYOMI_OIDC_BASE") or "https://oidc.vyomi.local").rstrip("/")
        self._known = {}                  # server name -> True (positive cache only; Docker is the source of truth)
        self._ready = {}                  # server name -> True once wait_ready succeeded
        self.lb_allocator = default_lb_allocator   # (cloud, cluster, ns, svc, used: set) -> {"ip": ..} | {"hostname": ..}
        self.warnings = []                # post-ready platform steps that failed (storage / rbac); surfaced, never silent
        self._forwards = {}               # (name, ns, svc, port) -> forwarder
        self._lb_thread = None
        self._lb_stop = threading.Event()
        self._locks = {}

    @property
    def image(self):
        return "%s:%s" % (K3S_IMAGE_REPO, self.image_version or PINNED_K3S_VERSION)

    def _tag_for(self, cloud, requested):
        if self.image_version:
            return self.image_version, {"minor": k3s_versions.tag_minor(self.image_version), "exact": True}
        r = k3s_versions.resolve(cloud, requested)
        return r["k3sTag"], r

    # ── docker plumbing ──────────────────────────────────────────────────────────────
    def _d(self, args, stdin=None, timeout=120):
        return self.docker(list(args), stdin, timeout)

    def _must(self, args, stdin=None, timeout=120):
        rc, out, err = self._d(args, stdin, timeout)
        if rc != 0:
            raise K3sError("docker %s failed (%s): %s" % (" ".join(args[:2]), rc, (err or out).strip()[:400]))
        return out

    def available(self):
        return self._d(["version", "--format", "{{.Server.Version}}"], None, 15)[0] == 0

    def _ensure_network(self):
        if self._d(["network", "inspect", NETWORK], None, 20)[0] != 0:
            self._must(["network", "create", NETWORK], None, 30)

    def _inspect(self, name):
        rc, out, _ = self._d(["inspect", "--type", "container", name], None, 20)
        if rc != 0:
            return None
        try:
            return json.loads(out)[0]
        except Exception:
            return None

    def _labels(self, name):
        i = self._inspect(name)
        return ((i or {}).get("Config") or {}).get("Labels") or {}

    # ── lifecycle ────────────────────────────────────────────────────────────────────
    def exists(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        if self._known.get(name):
            return True
        if self._d(["inspect", "--type", "container", name], None, 20)[0] == 0:
            self._known[name] = True
            return True
        return False

    def _server_args(self, name, cloud, cluster_id, tag, token, sans, oidc, issuer, requested):
        labels = {"vyomi.k3s": "server", "vyomi.cloud": cloud, "vyomi.cluster": cluster_id, "vyomi.k3s.name": name,
                  "vyomi.k3s.tag": tag, "vyomi.k3s.requested": requested or "", "vyomi.k3s.sans": ",".join(sans),
                  "vyomi.k3s.oidc": json.dumps(oidc) if oidc else ""}
        args = ["run", "-d", "--name", name, "--hostname", name, "--privileged", "--network", NETWORK,
                "--network-alias", name, "--restart", "unless-stopped", "--add-host", "host.docker.internal:host-gateway",
                "-v", name + "-data:/var/lib/rancher/k3s", "--tmpfs", "/run", "--tmpfs", "/var/run",
                "-e", "K3S_TOKEN=" + token, "-p", "127.0.0.1::6443"]
        for k, v in labels.items():
            args += ["--label", "%s=%s" % (k, v)]
        args += ["%s:%s" % (K3S_IMAGE_REPO, tag), "server", *SERVER_FLAGS,
                 "--kube-apiserver-arg", "service-account-issuer=" + issuer, "--kube-apiserver-arg", "service-account-jwks-uri=" + issuer + "/keys"]
        if oidc:
            for flag, val in (("oidc-issuer-url", oidc["issuerUrl"]), ("oidc-client-id", oidc["clientId"]),
                              ("oidc-username-claim", oidc["usernameClaim"]), ("oidc-groups-claim", oidc["groupsClaim"]),
                              ("oidc-username-prefix", oidc["usernamePrefix"])):
                args += ["--kube-apiserver-arg", "%s=%s" % (flag, val)]
        for s in dict.fromkeys(sans):
            args += ["--tls-san", s]
        return args

    def issuer(self, cloud, cluster_id):
        return "%s/oidc/%s/%s" % (self.issuer_base, cloud, cluster_hash(cloud, cluster_id))

    def _oidc_cfg(self, cloud, oidc):
        if not oidc:
            return None
        o = {} if oidc is True else dict(oidc)
        return {"issuerUrl": o.get("issuerUrl") or "%s/oidc/idp/%s" % (self.issuer_base, cloud), "clientId": o.get("clientId") or "kubernetes",
                "usernameClaim": o.get("usernameClaim") or "email", "groupsClaim": o.get("groupsClaim") or "groups",
                "usernamePrefix": o.get("usernamePrefix") or "oidc:"}

    def _agent_run(self, server, cloud, pool, idx, token, tag, ready_wait=True):
        """(Re)create one agent container for ``pool`` (a normalized pool dict) at ordinal ``idx``."""
        an = agent_name(server, pool["name"], idx)
        labels = node_labels(cloud, pool["name"], pool.get("vmSize"), pool.get("labels"))
        if self._d(["volume", "inspect", an + "-data"], None, 20)[0] != 0:
            self._must(["volume", "create", "--label", "vyomi.k3s.name=" + server, an + "-data"], None, 30)
        args = ["run", "-d", "--name", an, "--hostname", an, "--privileged", "--network", NETWORK, "--restart", "unless-stopped",
                "-v", an + "-data:/var/lib/rancher/k3s", "--tmpfs", "/run", "--tmpfs", "/var/run",
                "-e", "K3S_TOKEN=" + token, "-e", "K3S_URL=https://%s:6443" % server,
                "--label", "vyomi.k3s=agent", "--label", "vyomi.k3s.name=" + server, "--label", "vyomi.k3s.pool=" + pool["name"],
                "--label", "vyomi.k3s.index=%d" % idx, "--label", "vyomi.k3s.tag=" + tag,
                "%s:%s" % (K3S_IMAGE_REPO, tag), "agent"]
        for k, v in labels.items():
            args += ["--node-label", "%s=%s" % (k, v)]
        for t in pool.get("taints") or []:
            args += ["--node-taint", t]
        self._must(args, None, 600)
        return an

    def _pool_marker(self, server, pool):
        slug = pool_slug(pool["name"])
        vol = "%s-pool-%s" % (server, slug)
        self._d(["volume", "rm", "-f", vol], None, 20)
        self._must(["volume", "create", "--label", "vyomi.k3s.name=" + server, "--label", "vyomi.k3s.pool=" + pool["name"],
                    "--label", "vyomi.k3s.poolcfg=" + json.dumps({k: pool[k] for k in ("vmSize", "labels", "taints")}), vol], None, 30)

    def create_cluster(self, cloud, cluster_id, version=None, node_count=1, tls_sans=(), on_ready=None, wait=False, ready_timeout=300,
                       pools=None, oidc=None):
        """Start (idempotently) a k3s control plane + one agent per node-pool node. ``pools`` = [{name,count,vmSize,labels,taints}]; omitted ->
        one default pool of ``node_count`` nodes; ``[]`` -> control plane only (EKS: nodes exist only once a node group is created). Returns immediately with the cluster info unless ``wait``;
        ``on_ready(ok: bool, info: dict)`` is called from a background thread once the API + every node is Ready."""
        name = server_name(cloud, cluster_id)
        plist = [normalize_pool(cloud, p) for p in (pools if pools is not None else [{"name": None, "count": max(1, int(node_count or 1))}])]
        tag, res = self._tag_for(cloud, version)
        total = sum(p["count"] for p in plist)
        info = {"name": name, "cloud": cloud, "cluster": cluster_id, "image": "%s:%s" % (K3S_IMAGE_REPO, tag), "k3sVersion": tag,
                "requestedVersion": version, "actualVersion": k3s_versions.tag_to_version(tag), "minor": res.get("minor"),
                "nodeCount": total, "pools": plist, "issuer": self.issuer(cloud, cluster_id)}
        if not self.exists(cloud, cluster_id):
            self._ensure_network()
            token = secrets.token_hex(16)
            sans = ["127.0.0.1", "localhost", name] + [s for s in tls_sans if s]
            self._must(["volume", "create", "--label", "vyomi.k3s.name=" + name, name + "-data"], None, 30)
            self._must(self._server_args(name, cloud, cluster_id, tag, token, list(dict.fromkeys(sans)), self._oidc_cfg(cloud, oidc),
                                         self.issuer(cloud, cluster_id), version), None, 600)     # first run of a tag pulls its image
            self._known[name] = True
            for p in plist:
                self._pool_marker(name, p)
                for i in range(p["count"]):
                    self._agent_run(name, cloud, p, i, token, tag)
        if wait:
            self.wait_ready(cloud, cluster_id, total, ready_timeout)
        elif on_ready is not None:
            self._bg_ready(cloud, cluster_id, total, ready_timeout, info, on_ready)
        return info

    def _bg_ready(self, cloud, cluster_id, total, timeout, info, on_ready):
        def _bg():
            ok = True
            try:
                self.wait_ready(cloud, cluster_id, total, timeout)
            except Exception:
                ok = False
            try:
                on_ready(ok, info)
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True, name="k3s-ready-" + server_name(cloud, cluster_id)).start()

    def kubectl(self, cloud, cluster_id, argv, stdin=None, workdir=None, timeout=120):
        """`docker exec <server> kubectl ...` (the k3s image ships kubectl and the server's own kubeconfig)."""
        name = server_name(cloud, cluster_id)
        a = ["exec", "-i"] + (["-w", workdir] if workdir else []) + [name, "kubectl", *argv]
        return self._d(a, stdin if stdin is not None else "", timeout)

    def expected_nodes(self, cloud, cluster_id):
        return sum(1 for _ in self._agents(cloud, cluster_id))

    def wait_ready(self, cloud, cluster_id, node_count=None, timeout=300):
        name = server_name(cloud, cluster_id)
        deadline = time.time() + timeout
        last = ""
        while True:
            rc, out, err = self.kubectl(cloud, cluster_id, ["get", "--raw", "/readyz"], timeout=20)
            if rc == 0:
                rc, out, err = self.kubectl(cloud, cluster_id, ["get", "nodes", "--no-headers"], timeout=20)
                rows = [l.split() for l in out.splitlines() if l.strip()]
                ready = [r for r in rows if len(r) > 1 and r[1] == "Ready"]
                want = self.expected_nodes(cloud, cluster_id) if node_count is None else node_count
                if len(ready) >= want:
                    self._post_ready(cloud, cluster_id)
                    self._ready[name] = True
                    return True
                last = "nodes Ready %d/%d" % (len(ready), want)
            else:
                last = (err or out).strip()[:200]
            if time.time() >= deadline:
                raise K3sError("k3s %s not ready after %ss: %s" % (name, timeout, last))
            self.sleep(3)

    def is_ready(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        if self._ready.get(name):
            return True
        if not self.exists(cloud, cluster_id):
            return False
        ok = self.kubectl(cloud, cluster_id, ["get", "--raw", "/readyz"], timeout=15)[0] == 0
        if ok:
            self._ready[name] = True
        return ok

    def host_port(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        out = self._must(["port", name, "6443/tcp"], None, 20)
        return out.strip().splitlines()[0].rsplit(":", 1)[1]

    # ── credentials: admin (client cert, cluster-admin) vs user (bearer token of a restricted ServiceAccount) ──
    def _admin_kubeconfig_raw(self, cloud, cluster_id):
        return self._must(["exec", server_name(cloud, cluster_id), "cat", KUBECONFIG_PATH], None, 30)

    @staticmethod
    def _rename(text, name):
        return text.replace("name: default", "name: " + name).replace("cluster: default", "cluster: " + name) \
                   .replace("user: default", "user: " + name).replace("current-context: default", "current-context: " + name)

    def kubeconfig(self, cloud, cluster_id, server_url=None, role="admin"):
        """The cluster kubeconfig with ``server`` rewritten to ``server_url`` (default https://127.0.0.1:<published host port>).
        ``role="admin"``: the k3s admin client certificate (cluster-admin). ``role="user"``: a bearer token of the restricted
        ``kube-system/vyomi-cluster-user`` ServiceAccount (cluster-wide ``view`` + ``edit`` in ``default``); no certificate material of the admin."""
        name = server_name(cloud, cluster_id)
        raw = self._admin_kubeconfig_raw(cloud, cluster_id)
        url = server_url or "https://127.0.0.1:%s" % self.host_port(cloud, cluster_id)
        if role == "user":
            ca = next((l.split(":", 1)[1].strip() for l in raw.splitlines() if "certificate-authority-data:" in l), "")
            token = self.user_token(cloud, cluster_id)
            user = "clusterUser_" + name
            return ("apiVersion: v1\nkind: Config\nclusters:\n- name: %s\n  cluster:\n    server: %s\n    certificate-authority-data: %s\n"
                    "users:\n- name: %s\n  user:\n    token: %s\ncontexts:\n- name: %s\n  context:\n    cluster: %s\n    user: %s\n"
                    "current-context: %s\n" % (name, url, ca, user, token, name, name, user, name))
        out = []
        for line in raw.splitlines():
            if line.strip().startswith("server:"):
                line = line[:line.index("server:")] + "server: " + url
            out.append(line)
        return self._rename("\n".join(out) + "\n", name)

    def user_token(self, cloud, cluster_id, timeout=60):
        end = time.time() + timeout
        while True:
            rc, out, err = self.kubectl(cloud, cluster_id, ["-n", USER_NS, "get", "secret", USER_SA + "-token", "-o", "jsonpath={.data.token}"], timeout=20)
            if rc == 0 and out.strip():
                return base64.b64decode(out.strip()).decode()
            if time.time() >= end:
                raise K3sError("user credential not provisioned yet: %s" % (err or out).strip()[:200])
            self.sleep(2)

    # ── post-ready platform objects: restricted user, StorageClasses ──
    def _post_ready(self, cloud, cluster_id):
        for step in (self.ensure_user_rbac, self.ensure_storage):
            try:
                step(cloud, cluster_id)
            except Exception as e:
                self.warnings.append("%s %s: %s" % (step.__name__, cluster_id, str(e)[:200]))

    def ensure_user_rbac(self, cloud, cluster_id):
        y = """apiVersion: v1
kind: ServiceAccount
metadata: {name: %(sa)s, namespace: %(ns)s}
---
apiVersion: v1
kind: Secret
metadata: {name: %(sa)s-token, namespace: %(ns)s, annotations: {kubernetes.io/service-account.name: %(sa)s}}
type: kubernetes.io/service-account-token
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: vyomi-cluster-user-view}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: view}
subjects: [{kind: ServiceAccount, name: %(sa)s, namespace: %(ns)s}]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: vyomi-cluster-user-edit, namespace: default}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: edit}
subjects: [{kind: ServiceAccount, name: %(sa)s, namespace: %(ns)s}]
""" % {"sa": USER_SA, "ns": USER_NS}
        rc, out, err = self.kubectl(cloud, cluster_id, ["apply", "-f", "-"], y, timeout=60)
        if rc != 0:
            raise K3sError("user rbac: " + (err or out).strip()[:200])

    def ensure_storage(self, cloud, cluster_id):
        """Per-cloud StorageClass names backed by rancher.io/local-path; the first is the default class (k3s' own ``local-path`` is demoted)."""
        names = STORAGE_CLASSES.get(cloud, STORAGE_CLASSES["azure"])
        docs = []
        for i, n in enumerate(names):
            ann = '{storageclass.kubernetes.io/is-default-class: "true"}' if i == 0 else "{}"
            docs.append("apiVersion: storage.k8s.io/v1\nkind: StorageClass\nmetadata: {name: %s, annotations: %s}\nprovisioner: rancher.io/local-path\n"
                        "volumeBindingMode: WaitForFirstConsumer\nreclaimPolicy: Delete\nallowVolumeExpansion: true\n" % (n, ann))
        rc, out, err = self.kubectl(cloud, cluster_id, ["apply", "-f", "-"], "---\n".join(docs), timeout=60)
        if rc != 0:
            raise K3sError("storageclasses: " + (err or out).strip()[:200])
        self.kubectl(cloud, cluster_id, ["patch", "storageclass", "local-path", "-p",
                                         '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'], timeout=30)

    def volumes(self, cloud, cluster_id):
        """PV -> Docker-volume mapping (data model for the cloud's disk list): [{pv, claim, namespace, storageClass, sizeGiB, node, dockerVolume, path,
        diskName, phase}]. ``diskName`` is the cloud-flavoured disk id (``pvc-<uid>`` for Azure/GCP, ``vol-<hex>`` for AWS)."""
        rc, out, _ = self.kubectl(cloud, cluster_id, ["get", "pv", "-o", "json"], timeout=30)
        if rc != 0:
            return []
        server = server_name(cloud, cluster_id)
        rows = []
        for pv in json.loads(out or "{}").get("items", []):
            sp = pv.get("spec") or {}
            path = (sp.get("hostPath") or sp.get("local") or {}).get("path", "")
            terms = ((sp.get("nodeAffinity") or {}).get("required") or {}).get("nodeSelectorTerms") or [{}]
            node = next((v for e in terms[0].get("matchExpressions", []) for v in e.get("values", [])), "")
            claim = sp.get("claimRef") or {}
            size = (sp.get("capacity") or {}).get("storage", "")
            name = pv["metadata"]["name"]
            rows.append({"pv": name, "claim": claim.get("name"), "namespace": claim.get("namespace"), "storageClass": sp.get("storageClassName"),
                         "size": size, "node": node, "dockerVolume": node + "-data" if node.startswith(server) else None, "path": path,
                         "diskName": ("vol-" + hashlib.sha1(name.encode()).hexdigest()[:17]) if cloud == "aws" else name,
                         "phase": (pv.get("status") or {}).get("phase")})
        return rows

    # ── node pools ───────────────────────────────────────────────────────────────────
    def _agents(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        out = self._d(["ps", "-a", "--filter", "label=vyomi.k3s=agent", "--filter", "label=vyomi.k3s.name=" + name, "--format", "{{.Names}}"], None, 30)[1]
        return sorted(n for n in out.split() if n)

    def list_pools(self, cloud, cluster_id):
        """[{name, count, vmSize, labels, taints, nodes:[node names], k3sTag}] from the pool marker volumes + agent containers."""
        name = server_name(cloud, cluster_id)
        vols = self._d(["volume", "ls", "-q", "--filter", "label=vyomi.k3s.name=" + name, "--filter", "label=vyomi.k3s.pool"], None, 30)[1].split()
        pools = {}
        for v in vols:
            rc, out, _ = self._d(["volume", "inspect", v], None, 20)
            if rc != 0:
                continue
            lab = (json.loads(out)[0] or {}).get("Labels") or {}
            cfg = json.loads(lab.get("vyomi.k3s.poolcfg") or "{}")
            pools[lab["vyomi.k3s.pool"]] = {"name": lab["vyomi.k3s.pool"], "count": 0, "vmSize": cfg.get("vmSize", ""),
                                            "labels": cfg.get("labels") or {}, "taints": cfg.get("taints") or [], "nodes": [], "k3sTag": None}
        for an in self._agents(cloud, cluster_id):
            lab = self._labels(an)
            p = pools.setdefault(lab.get("vyomi.k3s.pool", "?"), {"name": lab.get("vyomi.k3s.pool", "?"), "count": 0, "vmSize": "", "labels": {},
                                                              "taints": [], "nodes": [], "k3sTag": None})
            p["nodes"].append(an)
            p["count"] += 1
            p["k3sTag"] = lab.get("vyomi.k3s.tag")
        return sorted(pools.values(), key=lambda p: p["name"])

    def _token(self, cloud, cluster_id):
        i = self._inspect(server_name(cloud, cluster_id)) or {}
        for e in (i.get("Config") or {}).get("Env") or []:
            if e.startswith("K3S_TOKEN="):
                return e.split("=", 1)[1]
        raise K3sError("cluster token not found")

    def _server_tag(self, cloud, cluster_id):
        return self._labels(server_name(cloud, cluster_id)).get("vyomi.k3s.tag") or PINNED_K3S_VERSION

    def add_pool(self, cloud, cluster_id, pool, wait=True):
        p = normalize_pool(cloud, pool)
        if any(x["name"] == p["name"] for x in self.list_pools(cloud, cluster_id)):
            raise K3sError("node pool %r already exists" % p["name"])
        name, token, tag = server_name(cloud, cluster_id), self._token(cloud, cluster_id), self._server_tag(cloud, cluster_id)
        self._pool_marker(name, p)
        for i in range(p["count"]):
            self._agent_run(name, cloud, p, i, token, tag)
        if wait:
            self.wait_ready(cloud, cluster_id, None, 300)
        return p

    def scale_pool(self, cloud, cluster_id, pool_name, count, wait=True):
        """Grow (new agent containers, lowest free ordinals) or shrink (highest ordinals are drained away, their node objects deleted)."""
        pools = {p["name"]: p for p in self.list_pools(cloud, cluster_id)}
        if pool_name not in pools:
            raise K3sError("node pool %r not found" % pool_name)
        count, cur = max(0, int(count)), pools[pool_name]
        name, token, tag = server_name(cloud, cluster_id), self._token(cloud, cluster_id), self._server_tag(cloud, cluster_id)
        have = {int(self._labels(n).get("vyomi.k3s.index", "0")): n for n in cur["nodes"]}
        spec = {"name": pool_name, "vmSize": cur["vmSize"], "labels": cur["labels"], "taints": cur["taints"]}
        if count > len(have):
            free = (i for i in range(1000) if i not in have)
            for _ in range(count - len(have)):
                self._agent_run(name, cloud, spec, next(free), token, tag)
        else:
            for idx in sorted(have, reverse=True)[:len(have) - count]:
                self.kubectl(cloud, cluster_id, ["drain", have[idx], "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=60s"], timeout=90)
                self._d(["rm", "-f", "-v", have[idx]], None, 60)
                self._d(["volume", "rm", "-f", have[idx] + "-data"], None, 30)
                self.kubectl(cloud, cluster_id, ["delete", "node", have[idx], "--ignore-not-found"], timeout=30)
        if wait and count > len(have):
            self.wait_ready(cloud, cluster_id, None, 300)
        return count

    def sync_pools(self, cloud, cluster_id, desired, wait=True):
        """Reconcile the real pools with the cloud core's desired pool list (add / scale / delete). Serialised per cluster."""
        want = {}
        for p in desired or []:
            np_ = normalize_pool(cloud, p)
            want[np_["name"]] = np_
        if not want:
            return
        with self._pool_lock(cloud, cluster_id):
            have = {p["name"]: p for p in self.list_pools(cloud, cluster_id)}
            for n, p in want.items():
                if n not in have:
                    self.add_pool(cloud, cluster_id, p, wait=wait)
                elif p["count"] != have[n]["count"]:
                    self.scale_pool(cloud, cluster_id, n, p["count"], wait=wait)
            for n in have:
                if n not in want:
                    self.delete_pool(cloud, cluster_id, n)

    def _pool_lock(self, cloud, cluster_id):
        return self._locks.setdefault(server_name(cloud, cluster_id), threading.RLock())

    def delete_pool(self, cloud, cluster_id, pool_name):
        self.scale_pool(cloud, cluster_id, pool_name, 0, wait=False)
        self._d(["volume", "rm", "-f", "%s-pool-%s" % (server_name(cloud, cluster_id), pool_slug(pool_name))], None, 30)
        return True

    # ── stop / start (containers really stop; volumes keep etcd, images and PV data) ──
    def stop_cluster(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        self._stop_forwards(name)
        for n in self._agents(cloud, cluster_id) + [name]:
            self._d(["stop", "-t", "20", n], None, 90)
        self._ready.pop(name, None)
        return True

    def start_cluster(self, cloud, cluster_id, wait=True, on_ready=None, ready_timeout=300):
        name = server_name(cloud, cluster_id)
        self._must(["start", name], None, 60)
        for n in self._agents(cloud, cluster_id):
            self._must(["start", n], None, 60)
        if wait:
            self.wait_ready(cloud, cluster_id, None, ready_timeout)
        elif on_ready is not None:
            self._bg_ready(cloud, cluster_id, None, ready_timeout, {"name": name}, on_ready)
        return True

    def is_running(self, cloud, cluster_id):
        return bool(((self._inspect(server_name(cloud, cluster_id)) or {}).get("State") or {}).get("Running"))

    # ── version upgrade: control plane first (same data volume), then agents rolled one at a time ──
    def upgrade_cluster(self, cloud, cluster_id, version, wait=True, ready_timeout=300):
        name = server_name(cloud, cluster_id)
        old = self._labels(name)
        if not old:
            raise K3sError("cluster not found")
        new_tag, res = self._tag_for(cloud, version)
        if new_tag == old.get("vyomi.k3s.tag"):
            return {"upgraded": False, "k3sVersion": new_tag, "actualVersion": k3s_versions.tag_to_version(new_tag)}
        om, nm = k3s_versions.parse_minor(old.get("vyomi.k3s.tag")), k3s_versions.parse_minor(new_tag)
        if om and nm and tuple(map(int, nm.split("."))) < tuple(map(int, om.split("."))):
            raise K3sError("cannot downgrade a cluster from %s to %s" % (om, nm))
        token = self._token(cloud, cluster_id)
        agents = []
        for an in self._agents(cloud, cluster_id):
            lab = self._labels(an)
            agents.append((an, lab))
        pools = {p["name"]: p for p in self.list_pools(cloud, cluster_id)}
        self._stop_forwards(name)
        self._ready.pop(name, None)
        sans = [s for s in old.get("vyomi.k3s.sans", "").split(",") if s]
        oidc = json.loads(old["vyomi.k3s.oidc"]) if old.get("vyomi.k3s.oidc") else None
        self._d(["rm", "-f", name], None, 60)                                     # NOT -v: the data volume stays
        self._must(self._server_args(name, cloud, old.get("vyomi.cluster", cluster_id), new_tag, token, sans, oidc,
                                     self.issuer(cloud, cluster_id), old.get("vyomi.k3s.requested")), None, 600)
        self._known[name] = True
        for _ in range(100):
            if self.kubectl(cloud, cluster_id, ["get", "--raw", "/readyz"], timeout=20)[0] == 0:
                break
            self.sleep(3)
        for an, lab in agents:                                                    # rolling: replace one node, wait Ready, next
            pool = pools.get(lab.get("vyomi.k3s.pool"), {"name": lab.get("vyomi.k3s.pool"), "vmSize": "", "labels": {}, "taints": []})
            self.kubectl(cloud, cluster_id, ["drain", an, "--ignore-daemonsets", "--delete-emptydir-data", "--force", "--timeout=60s"], timeout=90)
            self._d(["rm", "-f", an], None, 60)                                   # volume kept: containerd images + local-path PV data
            self._agent_run(name, cloud, pool, int(lab.get("vyomi.k3s.index", "0")), token, new_tag)
            self.kubectl(cloud, cluster_id, ["delete", "node", an, "--ignore-not-found"], timeout=30)
            if wait:
                self.wait_ready(cloud, cluster_id, None, ready_timeout)
        if wait:
            self.wait_ready(cloud, cluster_id, None, ready_timeout)
        return {"upgraded": True, "k3sVersion": new_tag, "actualVersion": k3s_versions.tag_to_version(new_tag)}

    def cluster_version(self, cloud, cluster_id):
        tag = self._labels(server_name(cloud, cluster_id)).get("vyomi.k3s.tag")
        return k3s_versions.tag_to_version(tag) if tag else None

    # ── raw Kubernetes REST passthrough (GKE ``clusters/{c}/k8s/<real path>``) ──
    _STATUS = {"NotFound": 404, "AlreadyExists": 409, "Conflict": 409, "Forbidden": 403, "Unauthorized": 401, "Invalid": 422,
               "BadRequest": 400, "MethodNotAllowed": 405, "Timeout": 504, "ServiceUnavailable": 503}

    def api_request(self, cloud, cluster_id, method, path, body=None):
        """Send one request to the REAL API server (``kubectl <verb> --raw``). -> (http_status, parsed_json_or_text). PATCH is applied as a JSON merge patch
        (GET + deep merge + PUT) since ``kubectl --raw`` has no PATCH verb."""
        m = method.upper()
        data = json.dumps(body) if body is not None else ""
        if m == "GET":
            rc, out, err = self.kubectl(cloud, cluster_id, ["get", "--raw", path], timeout=60)
        elif m == "POST":
            rc, out, err = self.kubectl(cloud, cluster_id, ["create", "--raw", path, "-f", "-"], data, timeout=60)
        elif m == "PUT":
            rc, out, err = self.kubectl(cloud, cluster_id, ["replace", "--raw", path, "-f", "-"], data, timeout=60)
        elif m == "DELETE":
            rc, out, err = self.kubectl(cloud, cluster_id, ["delete", "--raw", path], data or None, timeout=60)
        elif m == "PATCH":
            rc, cur, err = self.kubectl(cloud, cluster_id, ["get", "--raw", path], timeout=60)
            if rc == 0:
                def merge(a, b):
                    for k, v in (b or {}).items():
                        if v is None:
                            a.pop(k, None)
                        elif isinstance(v, dict) and isinstance(a.get(k), dict):
                            merge(a[k], v)
                        else:
                            a[k] = v
                    return a
                rc, out, err = self.kubectl(cloud, cluster_id, ["replace", "--raw", path, "-f", "-"], json.dumps(merge(json.loads(cur), body or {})), timeout=60)
            else:
                out = cur
        else:
            return 405, {"kind": "Status", "apiVersion": "v1", "status": "Failure", "reason": "MethodNotAllowed", "code": 405, "message": "method not supported"}
        if rc == 0:
            try:
                return 200, json.loads(out) if out.strip() else {}
            except ValueError:
                return 200, out
        text = (err or out).strip()
        mt = re.search(r"Error from server \((\w+)\)", text)
        reason = mt.group(1) if mt else "InternalError"
        return self._STATUS.get(reason, 500), {"kind": "Status", "apiVersion": "v1", "status": "Failure", "reason": reason,
                                               "code": self._STATUS.get(reason, 500), "message": text[:400]}

    # ── workload identity ────────────────────────────────────────────────────────────
    def oidc_jwks(self, cloud, chash):
        """The cluster's real public signing keys (JWKS), read from its API server. ``chash`` = cluster_hash(cloud, id)."""
        name = "vyomi-k3s-" + chash
        rc, out, err = self._d(["exec", "-i", name, "kubectl", "get", "--raw", "/openid/v1/jwks"], "", 30)
        if rc != 0:
            raise K3sError("jwks unavailable: " + (err or out).strip()[:200])
        return json.loads(out)

    def oidc_discovery(self, cloud, chash):
        if self._d(["inspect", "--type", "container", "vyomi-k3s-" + chash], None, 20)[0] != 0:
            raise K3sError("unknown cluster")
        return k3s_identity.discovery_document("%s/oidc/%s/%s" % (self.issuer_base, cloud, chash))

    def mint_service_account_token(self, cloud, cluster_id, namespace, name, audience, expiration_seconds=3600):
        """`kubectl create token` (the TokenRequest API, i.e. a projected-token equivalent) -> JWT signed by the cluster's SA key."""
        rc, out, err = self.kubectl(cloud, cluster_id, ["-n", namespace, "create", "token", name, "--audience", audience,
                                                       "--duration", "%ds" % expiration_seconds], timeout=30)
        if rc != 0:
            raise K3sError("create token: " + (err or out).strip()[:200])
        return out.strip()

    def verify_token(self, token, audience=None):
        return k3s_identity.verify_token(token, audience, self.oidc_jwks)

    # ── Services of type LoadBalancer ────────────────────────────────────────────────
    def reconcile_loadbalancers(self, cloud, cluster_id):
        """One pass of the LB controller: for every ``type: LoadBalancer`` Service allocate an address from the simulator pool (``lb_allocator``),
        write ``status.loadBalancer.ingress`` and keep a host-reachable forward per port (annotation ``vyomi.cloud/host-endpoint``).
        Returns [{namespace, name, ingress, endpoints}]."""
        name = server_name(cloud, cluster_id)
        rc, out, _ = self.kubectl(cloud, cluster_id, ["get", "svc", "-A", "-o", "json"], timeout=30)
        if rc != 0:
            return []
        items = [s for s in json.loads(out or "{}").get("items", []) if (s.get("spec") or {}).get("type") == "LoadBalancer"]
        used = {i.get("ip") or i.get("hostname") for s in items for i in ((s.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []}
        live, result = set(), []
        for s in items:
            md, sp = s["metadata"], s["spec"]
            ing = ((s.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []
            if not ing:
                alloc = self.lb_allocator(cloud, cluster_id, md["namespace"], md["name"], used)
                used.add(alloc.get("ip") or alloc.get("hostname"))
                patch = json.dumps({"status": {"loadBalancer": {"ingress": [alloc]}}})
                rc, _, err = self.kubectl(cloud, cluster_id, ["-n", md["namespace"], "patch", "svc", md["name"], "--subresource=status", "--type=merge", "-p", patch], timeout=30)
                if rc != 0:
                    continue
                ing = [alloc]
            eps = {}
            for p in sp.get("ports") or []:
                key = (name, md["namespace"], md["name"], p["port"])
                live.add(key)
                fw = self._forwards.get(key) or self._start_forward(cloud, cluster_id, md["namespace"], md["name"], p)
                if fw:
                    self._forwards[key] = fw
                    eps[p["port"]] = "127.0.0.1:%d" % fw.port
            if eps and (md.get("annotations") or {}).get("vyomi.cloud/host-endpoint") != json.dumps(eps, sort_keys=True):
                self.kubectl(cloud, cluster_id, ["-n", md["namespace"], "annotate", "svc", md["name"], "--overwrite",
                                                 "vyomi.cloud/host-endpoint=" + json.dumps(eps, sort_keys=True)], timeout=30)
            result.append({"namespace": md["namespace"], "name": md["name"], "ingress": ing, "endpoints": eps})
        for key in [k for k in self._forwards if k[0] == name and k not in live]:
            self._forwards.pop(key).stop()
        return result

    def _node_ip(self, node):
        rc, out, _ = self._d(["inspect", "-f", '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % NETWORK, node], None, 20)
        return out.strip() if rc == 0 and out.strip() else None

    def _start_forward(self, cloud, cluster_id, ns, svc, port):
        """Host reachability. Preferred: a Python TCP forwarder straight to <node container IP>:<nodePort> (works when the appliance shares the Docker
        network, e.g. runs in a container). Fallback (Docker Desktop: container IPs are not routable from the host): `kubectl port-forward` on the host."""
        node_port = port.get("nodePort")
        agents = self._agents(cloud, cluster_id)
        ip = self._node_ip(agents[0]) if agents else None
        if node_port and ip:
            try:
                socket.create_connection((ip, node_port), timeout=1.5).close()
                return _Forwarder(lambda: socket.create_connection((ip, node_port), timeout=5))
            except OSError:
                pass
            except Exception:
                pass
        return _KubectlForward(self, cloud, cluster_id, ns, svc, port["port"])

    def start_lb_controller(self, interval=5.0):
        """Background LB reconciler for every running cluster (started by install())."""
        if self._lb_thread and self._lb_thread.is_alive():
            return

        def _loop():
            while not self._lb_stop.wait(interval):
                try:
                    for c in self.list_clusters():
                        if c["state"] == "running" and self._ready.get(c["name"]):
                            self.reconcile_loadbalancers(c["cloud"], c["cluster"])
                except Exception:
                    pass
        self._lb_stop.clear()
        self._lb_thread = threading.Thread(target=_loop, daemon=True, name="k3s-lb-controller")
        self._lb_thread.start()

    def _stop_forwards(self, name):
        for key in [k for k in self._forwards if k[0] == name]:
            self._forwards.pop(key).stop()

    # ── teardown / listing ───────────────────────────────────────────────────────────
    def delete_cluster(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        self._stop_forwards(name)
        out = self._d(["ps", "-a", "--filter", "label=vyomi.k3s.name=" + name, "--format", "{{.Names}}"], None, 30)[1]
        names = [n for n in out.split() if n] or [name]
        for n in names:
            self._d(["rm", "-f", "-v", n], None, 60)
        vols = self._d(["volume", "ls", "-q", "--filter", "label=vyomi.k3s.name=" + name], None, 30)[1].split()
        for v in vols:
            self._d(["volume", "rm", "-f", v], None, 30)
        self._known.pop(name, None)
        self._ready.pop(name, None)
        k3s_identity.CACHE.clear((cloud, cluster_hash(cloud, cluster_id)))
        return True

    def list_clusters(self):
        fmt = '{{.Names}}\t{{.Label "vyomi.cloud"}}\t{{.Label "vyomi.cluster"}}\t{{.State}}'
        out = self._d(["ps", "-a", "--filter", "label=vyomi.k3s=server", "--format", fmt], None, 30)[1]
        rows = []
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) == 4:
                rows.append({"name": p[0], "cloud": p[1], "cluster": p[2], "state": p[3]})
        return rows

    # ── backend factory (kube_state_core.BACKEND_FACTORY) ────────────────────────────
    def backend_factory(self):
        from core import kube_state_core as kube

        def factory(cloud, cluster_id):
            if not self.exists(cloud, cluster_id):
                return None
            return kube.RealK8sBackend(lambda argv, stdin=None, workdir=None, timeout=120:
                                       self.kubectl(cloud, cluster_id, argv, stdin, workdir, timeout),
                                       file_writer=lambda files, wd: self.run_context_files(cloud, cluster_id, files, wd))
        return factory

    def run_context_files(self, cloud, cluster_id, files, workdir):
        """Materialise runCommand context files in the server container (az aks command invoke --file)."""
        name = server_name(cloud, cluster_id)
        for rel, body in files.items():
            if rel.startswith("/") or ".." in rel.split("/"):
                raise K3sError("invalid context file path %r" % rel)
            path = workdir.rstrip("/") + "/" + rel
            self._must(["exec", "-i", name, "sh", "-c", "mkdir -p %s && cat > %s" % (shlex.quote(os.path.dirname(path)), shlex.quote(path))], body, 30)


# ── LB address pool + host forwarders ────────────────────────────────────────────────
_LB_USED = set()                # process-wide so two clusters never get the same address


def default_lb_allocator(cloud, cluster_id, ns, svc, used):
    """Default simulator LB pool: a /24 per cluster inside a per-cloud public-looking range (AKS/GKE: public IP; EKS: ELB hostname).
    Replace ``runtime().lb_allocator`` to draw from the cloud core's own IP pool instead."""
    h = int(cluster_hash(cloud, cluster_id), 16)
    a, b = h & 0xFF, (h >> 8) & 0xFF
    for n in range(10, 250):
        if cloud == "aws":
            cand = {"hostname": "%s-%s-%d.elb.us-east-1.amazonaws.com" % (svc, ("%08x" % h)[:8], n)}
        else:
            cand = {"ip": "%s.%d.%d.%d" % ("20" if cloud == "azure" else "34", a, b, n)}
        key = cand.get("ip") or cand.get("hostname")
        if key not in used and key not in _LB_USED:
            _LB_USED.add(key)
            return cand
    raise K3sError("load balancer address pool exhausted")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Forwarder:
    """127.0.0.1:<free port> -> upstream, one thread per connection."""
    def __init__(self, connect):
        self.connect, self.port, self._stop = connect, _free_port(), threading.Event()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.listen(32)
        threading.Thread(target=self._accept, daemon=True, name="k3s-lb-fwd-%d" % self.port).start()

    def _accept(self):
        while not self._stop.is_set():
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        try:
            u = self.connect()
        except OSError:
            c.close()
            return

        def pump(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        threading.Thread(target=pump, args=(u, c), daemon=True).start()
        pump(c, u)

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


class _KubectlForward:
    """`kubectl port-forward svc/<svc> <free>:<port>` on the host against the cluster's published API port (user needs kubectl on the host)."""
    def __init__(self, rt, cloud, cluster_id, ns, svc, port):
        self.port, self.proc, self.tmp = None, None, None
        kubectl = shutil.which("kubectl")
        if not kubectl:
            raise K3sError("no host route to the node network and no kubectl on the host for the LoadBalancer forward")
        fd, self.tmp = tempfile.mkstemp(prefix="vyomi-lb-", suffix=".kubeconfig")
        with os.fdopen(fd, "w") as f:
            f.write(rt.kubeconfig(cloud, cluster_id))
        os.chmod(self.tmp, 0o600)
        self.port = _free_port()
        self.proc = subprocess.Popen([kubectl, "--kubeconfig", self.tmp, "-n", ns, "port-forward", "--address", "127.0.0.1", "svc/" + svc,
                                      "%d:%d" % (self.port, port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 15
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                time.sleep(0.3)

    def stop(self):
        try:
            if self.proc:
                self.proc.terminate()
        finally:
            if self.tmp and os.path.exists(self.tmp):
                os.unlink(self.tmp)


_runtime = None


def runtime():
    global _runtime
    if _runtime is None:
        _runtime = K3sRuntime()
    return _runtime


def set_docker(fn):
    """Test seam: replace the single Docker entry point on the shared runtime."""
    runtime().docker = fn or default_docker


def enabled():
    return os.environ.get("VYOMI_K8S_BACKEND", "").lower() == "k3s"


def install(rt=None, lb_controller=False):
    """Wire the runtime into the substrate-free cores. Called by the offline appliance at startup when VYOMI_K8S_BACKEND=k3s."""
    from core import kube_state_core as kube
    rt = rt or runtime()
    kube.CLUSTER_RUNTIME = rt
    kube.BACKEND_FACTORY = rt.backend_factory()
    if lb_controller:
        rt.start_lb_controller()
    return rt


def install_if_enabled():
    return install(lb_controller=True) if enabled() else None
