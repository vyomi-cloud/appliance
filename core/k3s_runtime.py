"""Docker-driven k3s lifecycle: one REAL Kubernetes (k3s) per managed cluster on the offline appliance / booster.

OFFLINE-ONLY module (shells out to the ``docker`` CLI). It is deliberately NOT part of the Pyodide/Nano core set
(``wasm/build_cores.py``): the substrate-free cores (azure_arm_core, gcp_container_core, kube_state_core) only see the
``kube_state_core.CLUSTER_RUNTIME`` hook, which ``install()`` fills in when ``VYOMI_K8S_BACKEND=k3s``.

Everything that touches Docker goes through ONE injectable function (``set_docker`` / ``K3sRuntime(docker=...)``):
``docker(args: list[str], stdin: str | None, timeout: float) -> (returncode, stdout, stderr)``. Unit tests swap in a fake.

State lives in Docker itself (labels on containers/volumes), never in this process, so an appliance restart finds its
clusters again:
  server container  vyomi-k3s-<hash>            labels vyomi.k3s=server, vyomi.cloud, vyomi.cluster, vyomi.k3s.name
  agent containers  vyomi-k3s-<hash>-agent-<i>  labels vyomi.k3s=agent,  vyomi.k3s.name
  volumes           <container>-data            label  vyomi.k3s.name   (persists /var/lib/rancher/k3s)
All on network ``vyomi-net``; the API server is also published on a random 127.0.0.1 host port for kubeconfigs.

TODO (not built): EKS. There is no EKS core/console yet, so ``create_cluster("aws", ...)`` has no caller; when an EKS control-plane core
lands it only needs the same two hook calls AKS/GKE use (kube_state_core.CLUSTER_RUNTIME.create_cluster / delete_cluster) plus
eks:CreateCluster/DescribeCluster endpoint + certificateAuthority from ``kubeconfig``. Also NOT built: per-node-pool agents (all agents
form one pool), cloud-identity -> k8s RBAC mapping (credentials are the k3s admin client cert), cloud load balancers / disks for
Services and PVCs (local-path storage only), start/stop of the cluster containers.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shlex
import subprocess
import threading
import time

NETWORK = "vyomi-net"
K3S_IMAGE_REPO = "rancher/k3s"
PINNED_K3S_VERSION = "v1.30.5-k3s1"     # the ONE image we pull; any requested Kubernetes version maps onto it (honest: see actual_version)
SERVER_FLAGS = ["--cluster-init", "--disable", "traefik", "--disable", "servicelb", "--disable", "metrics-server",
                "--write-kubeconfig-mode", "644"]
KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"


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


class K3sError(Exception):
    pass


class K3sRuntime:
    def __init__(self, docker=None, sleep=time.sleep, image_version=PINNED_K3S_VERSION):
        self.docker = docker or default_docker
        self.sleep = sleep
        self.image = "%s:%s" % (K3S_IMAGE_REPO, image_version)
        self.image_version = image_version
        self._known = {}                  # server name -> True (positive cache only; Docker is the source of truth)
        self._ready = {}                  # server name -> True once wait_ready succeeded

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

    # ── lifecycle ────────────────────────────────────────────────────────────────────
    def exists(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        if self._known.get(name):
            return True
        if self._d(["inspect", "--type", "container", name], None, 20)[0] == 0:
            self._known[name] = True
            return True
        return False

    def create_cluster(self, cloud, cluster_id, version=None, node_count=1, tls_sans=(), on_ready=None, wait=False, ready_timeout=300):
        """Start (idempotently) a k3s server (+ node_count-1 agents). Returns immediately with the cluster info unless
        ``wait``; ``on_ready(ok: bool, info: dict)`` is called from a background thread once the API + nodes are Ready."""
        name = server_name(cloud, cluster_id)
        node_count = max(1, int(node_count or 1))
        info = {"name": name, "cloud": cloud, "cluster": cluster_id, "image": self.image,
                "requestedVersion": version, "actualVersion": self.image_version, "nodeCount": node_count}
        if not self.exists(cloud, cluster_id):
            self._ensure_network()
            token = secrets.token_hex(16)
            sans = ["127.0.0.1", "localhost", name] + [s for s in tls_sans if s]
            labels = {"vyomi.k3s": "server", "vyomi.cloud": cloud, "vyomi.cluster": cluster_id, "vyomi.k3s.name": name}
            self._must(["volume", "create", "--label", "vyomi.k3s.name=" + name, name + "-data"], None, 30)
            args = ["run", "-d", "--name", name, "--hostname", name, "--privileged", "--network", NETWORK,
                    "--network-alias", name, "--restart", "unless-stopped", "-v", name + "-data:/var/lib/rancher/k3s",
                    "--tmpfs", "/run", "--tmpfs", "/var/run", "-e", "K3S_TOKEN=" + token, "-p", "127.0.0.1::6443"]
            for k, v in labels.items():
                args += ["--label", "%s=%s" % (k, v)]
            args += [self.image, "server", *SERVER_FLAGS]
            for s in dict.fromkeys(sans):
                args += ["--tls-san", s]
            self._must(args, None, 600)               # first run pulls the single image
            self._known[name] = True
            for i in range(1, node_count):
                an = "%s-agent-%d" % (name, i)
                self._must(["volume", "create", "--label", "vyomi.k3s.name=" + name, an + "-data"], None, 30)
                self._must(["run", "-d", "--name", an, "--hostname", an, "--privileged", "--network", NETWORK,
                            "--restart", "unless-stopped", "-v", an + "-data:/var/lib/rancher/k3s", "--tmpfs", "/run",
                            "--tmpfs", "/var/run", "-e", "K3S_TOKEN=" + token, "-e", "K3S_URL=https://%s:6443" % name,
                            "--label", "vyomi.k3s=agent", "--label", "vyomi.k3s.name=" + name,
                            self.image, "agent"], None, 120)
        if wait:
            self.wait_ready(cloud, cluster_id, node_count, ready_timeout)
        elif on_ready is not None:
            def _bg():
                ok = True
                try:
                    self.wait_ready(cloud, cluster_id, node_count, ready_timeout)
                except Exception:
                    ok = False
                try:
                    on_ready(ok, info)
                except Exception:
                    pass
            threading.Thread(target=_bg, daemon=True, name="k3s-ready-" + name).start()
        return info

    def kubectl(self, cloud, cluster_id, argv, stdin=None, workdir=None, timeout=120):
        """`docker exec <server> kubectl ...` (the k3s image ships kubectl and the server's own kubeconfig)."""
        name = server_name(cloud, cluster_id)
        a = ["exec", "-i"] + (["-w", workdir] if workdir else []) + [name, "kubectl", *argv]
        return self._d(a, stdin if stdin is not None else "", timeout)

    def wait_ready(self, cloud, cluster_id, node_count=1, timeout=300):
        name = server_name(cloud, cluster_id)
        deadline = time.time() + timeout
        last = ""
        while True:
            rc, out, err = self.kubectl(cloud, cluster_id, ["get", "--raw", "/readyz"], timeout=20)
            if rc == 0:
                rc, out, err = self.kubectl(cloud, cluster_id, ["get", "nodes", "--no-headers"], timeout=20)
                rows = [l.split() for l in out.splitlines() if l.strip()]
                ready = [r for r in rows if len(r) > 1 and r[1] == "Ready"]
                if len(ready) >= node_count:
                    self._ready[name] = True
                    return True
                last = "nodes Ready %d/%d" % (len(ready), node_count)
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

    def kubeconfig(self, cloud, cluster_id, server_url=None):
        """The cluster's admin kubeconfig (client certificate) with ``server`` rewritten to ``server_url``
        (default: https://127.0.0.1:<published host port>)."""
        name = server_name(cloud, cluster_id)
        raw = self._must(["exec", name, "cat", KUBECONFIG_PATH], None, 30)
        url = server_url or "https://127.0.0.1:%s" % self.host_port(cloud, cluster_id)
        out = []
        for line in raw.splitlines():
            if line.strip().startswith("server:"):
                line = line[:line.index("server:")] + "server: " + url
            out.append(line)
        text = "\n".join(out) + "\n"
        return text.replace("name: default", "name: " + name).replace("cluster: default", "cluster: " + name) \
                   .replace("user: default", "user: " + name).replace("current-context: default", "current-context: " + name)

    def delete_cluster(self, cloud, cluster_id):
        name = server_name(cloud, cluster_id)
        out = self._d(["ps", "-a", "--filter", "label=vyomi.k3s.name=" + name, "--format", "{{.Names}}"], None, 30)[1]
        names = [n for n in out.split() if n] or [name]
        for n in names:
            self._d(["rm", "-f", "-v", n], None, 60)
        vols = self._d(["volume", "ls", "-q", "--filter", "label=vyomi.k3s.name=" + name], None, 30)[1].split()
        for v in vols:
            self._d(["volume", "rm", "-f", v], None, 30)
        self._known.pop(name, None)
        self._ready.pop(name, None)
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


def install(rt=None):
    """Wire the runtime into the substrate-free cores. Called by the offline appliance at startup when VYOMI_K8S_BACKEND=k3s."""
    from core import kube_state_core as kube
    rt = rt or runtime()
    kube.CLUSTER_RUNTIME = rt
    kube.BACKEND_FACTORY = rt.backend_factory()
    return rt


def install_if_enabled():
    return install() if enabled() else None
