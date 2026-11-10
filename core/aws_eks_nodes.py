"""EKS managed node groups -> REAL k3s agent nodes (offline appliance / mesh only; shells out through the K3sRuntime's single docker seam).

Each node group becomes ``desiredSize`` k3s agent containers that join the cluster's k3s server and carry the EKS labels:

  eks.amazonaws.com/nodegroup=<name>   eks.amazonaws.com/nodegroup-image=<ami>   eks.amazonaws.com/capacityType=ON_DEMAND|SPOT
  node.kubernetes.io/instance-type=<first instanceTypes entry>                      + the nodegroup's ``labels`` / ``taints``

``kubectl get nodes -l eks.amazonaws.com/nodegroup=<name>`` therefore lists real nodes, and pods with a matching nodeSelector really land
on them. State lives in Docker labels (``vyomi.k3s.name`` = the k3s server, so ``K3sRuntime.delete_cluster`` also removes node-group agents;
``vyomi.eks.nodegroup``), never in this process.

Why this is in the EKS layer: ``K3sRuntime.create_cluster`` only creates agents at cluster creation (one anonymous pool). Per-pool agents are the
platform branch's job (core/k3s_runtime.py, branch v4/k8s-platform); until it exposes a node-pool API this module does the equivalent through
``runtime.docker`` only (see docs/architecture/v4.0/EKS-NEEDS.md). It uses no private runtime state.
"""
from __future__ import annotations

import os

from core import k3s_runtime as k3s

NODE_TOKEN_PATH = "/var/lib/rancher/k3s/server/node-token"
EFFECT = {"NO_SCHEDULE": "NoSchedule", "NO_EXECUTE": "NoExecute", "PREFER_NO_SCHEDULE": "PreferNoSchedule"}


def max_agents():
    """Appliance guard: every agent is a privileged k3s container (~400 MB). Override with VYOMI_EKS_MAX_NODES."""
    try:
        return max(1, int(os.environ.get("VYOMI_EKS_MAX_NODES", "3")))
    except ValueError:
        return 3


class NodeLimitError(Exception):
    pass


class NodeProvisioner:
    def __init__(self, rt):
        self.rt = rt

    # -- docker seam ------------------------------------------------------------------------------------------------------
    def _d(self, args, stdin=None, timeout=120):
        return self.rt.docker(list(args), stdin, timeout)

    def _must(self, args, stdin=None, timeout=120):
        rc, out, err = self._d(args, stdin, timeout)
        if rc != 0:
            raise k3s.K3sError("docker %s failed (%s): %s" % (" ".join(args[:2]), rc, (err or out).strip()[:400]))
        return out

    def _agents(self, server, nodegroup=None):
        flt = ["--filter", "label=vyomi.k3s=agent", "--filter", "label=vyomi.k3s.name=" + server]
        if nodegroup:
            flt += ["--filter", "label=vyomi.eks.nodegroup=" + nodegroup]
        out = self._d(["ps", "-a"] + flt + ["--format", "{{.Names}}"], None, 30)[1]
        return sorted(n for n in out.split() if n)

    # -- queries ----------------------------------------------------------------------------------------------------------
    def node_names(self, key, nodegroup):
        return self._agents(k3s.server_name("aws", key), nodegroup)

    def other_count(self, key, nodegroup):
        """Agents of this cluster that belong to OTHER node groups."""
        server = k3s.server_name("aws", key)
        return len(self._agents(server)) - len(self._agents(server, nodegroup))

    def ready_count(self, key, nodegroup):
        rc, out, _ = self.rt.kubectl("aws", key, ["get", "nodes", "-l", "eks.amazonaws.com/nodegroup=" + nodegroup, "--no-headers"], timeout=20)
        if rc != 0:
            return 0
        return sum(1 for l in out.splitlines() if len(l.split()) > 1 and l.split()[1] == "Ready")

    # -- lifecycle --------------------------------------------------------------------------------------------------------
    def scale(self, key, ng, desired):
        """Make exactly ``desired`` agent containers exist for node group record ``ng`` (a describe-shaped dict + the optional ``_labels``)."""
        server = k3s.server_name("aws", key)
        name = ng["nodegroupName"]
        have = self._agents(server, name)
        others = len(self._agents(server)) - len(have)
        if others + desired > max_agents():
            raise NodeLimitError("This appliance runs at most %d EKS worker nodes per cluster (VYOMI_EKS_MAX_NODES); %d other node(s) already exist." % (max_agents(), others))
        if len(have) < desired:
            token = self._must(["exec", server, "cat", NODE_TOKEN_PATH], None, 30).strip()
            used = {int(n.rsplit("-", 1)[1]) for n in have if n.rsplit("-", 1)[1].isdigit()}
            i = 0
            while len(have) < desired:
                while i in used:
                    i += 1
                used.add(i)
                have.append(self._launch(server, name, i, token, ng))
        for extra in have[desired:]:
            self.remove(key, name, [extra])
        return desired

    def _launch(self, server, nodegroup, idx, token, ng):
        an = "%s-ng-%s-%d" % (server, nodegroup, idx)
        labels = {"eks.amazonaws.com/nodegroup": nodegroup, "eks.amazonaws.com/capacityType": ng.get("capacityType", "ON_DEMAND"),
                  "eks.amazonaws.com/nodegroup-image": ng.get("_ami_id", "ami-0vyomi"), "eks.amazonaws.com/sourceLaunchTemplateId": "",
                  "node.kubernetes.io/instance-type": (ng.get("instanceTypes") or ["t3.medium"])[0]}
        labels.update(ng.get("labels") or {})
        labels = {k: v for k, v in labels.items() if v != ""}
        args = ["run", "-d", "--name", an, "--hostname", an, "--privileged", "--network", k3s.NETWORK, "--restart", "unless-stopped",
                "-v", an + "-data:/var/lib/rancher/k3s", "--tmpfs", "/run", "--tmpfs", "/var/run", "-e", "K3S_TOKEN=" + token,
                "-e", "K3S_URL=https://%s:6443" % server, "--label", "vyomi.k3s=agent", "--label", "vyomi.k3s.name=" + server,
                "--label", "vyomi.eks.nodegroup=" + nodegroup, self.rt.image, "agent"]
        for k, v in labels.items():
            args += ["--node-label", "%s=%s" % (k, v)]
        for t in ng.get("taints") or []:
            args += ["--node-taint", "%s=%s:%s" % (t["key"], t.get("value", ""), EFFECT.get(t.get("effect", "NO_SCHEDULE"), "NoSchedule"))]
        self._must(["volume", "create", "--label", "vyomi.k3s.name=" + server, an + "-data"], None, 30)
        self._must(args, None, 300)
        return an

    def remove(self, key, nodegroup, names=None):
        server = k3s.server_name("aws", key)
        for n in (names if names is not None else self._agents(server, nodegroup)):
            self._d(["rm", "-f", "-v", n], None, 60)
            self._d(["volume", "rm", "-f", n + "-data"], None, 30)
            self.rt.kubectl("aws", key, ["delete", "node", n, "--ignore-not-found"], timeout=30)
