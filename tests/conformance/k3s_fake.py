"""A stateful fake of the `docker` CLI for the k3s runtime tests (containers, labels, env, volumes, networks, kubectl via `exec`)."""
import json

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


def _flags(a, flag):
    return [a[i + 1] for i, x in enumerate(a) if x == flag and i + 1 < len(a)]


def _kv(items):
    return dict(x.split("=", 1) for x in items)


class FakeDocker:
    def __init__(self):
        self.calls, self.containers, self.volumes, self.networks = [], {}, {}, set()
        self.items = {}               # kubectl `get <resource>` -> list of objects
        self.applied, self.kube_calls = [], []
        self.kubectl_hook = None      # (argv, stdin) -> (rc, out, err) | None
        self.node_ip = "10.9.0.5"
        self.nodes_ready = None       # None = one Ready node per running agent

    # ── helpers ──
    def agents(self, server=None):
        return sorted(n for n, c in self.containers.items() if c["labels"].get("vyomi.k3s") == "agent"
                      and (server is None or c["labels"].get("vyomi.k3s.name") == server))

    def _match(self, c, filters):
        for f in filters:
            f = f[len("label="):]
            k, _, v = f.partition("=")
            if k not in c["labels"] or (v and c["labels"][k] != v):
                return False
        return True

    def __call__(self, args, stdin=None, timeout=120):
        self.calls.append((list(args), stdin))
        a = list(args)
        if a[:2] == ["network", "inspect"]:
            return (0 if a[2] in self.networks else 1), "", ""
        if a[:2] == ["network", "create"]:
            self.networks.add(a[2]); return 0, "", ""
        if a[:2] == ["volume", "create"]:
            self.volumes[a[-1]] = _kv(_flags(a, "--label")); return 0, "", ""
        if a[:2] == ["volume", "inspect"]:
            return (0, json.dumps([{"Name": a[2], "Labels": self.volumes[a[2]]}]), "") if a[2] in self.volumes else (1, "", "no such volume")
        if a[:2] == ["volume", "ls"]:
            fl = {"labels": _flags(a, "--filter")}
            names = [n for n, l in self.volumes.items() if self._match({"labels": l}, fl["labels"])]
            return 0, "\n".join(sorted(names)) + "\n", ""
        if a[:2] == ["volume", "rm"]:
            self.volumes.pop(a[-1], None); return 0, "", ""
        if a[0] == "run":
            name = a[a.index("--name") + 1]
            img = next(x for x in a if x.startswith("rancher/k3s:"))
            self.containers[name] = {"args": a, "labels": _kv(_flags(a, "--label")), "env": _flags(a, "-e"), "image": img, "running": True}
            return 0, "cid\n", ""
        if a[0] == "inspect":
            if a[1] == "-f":
                return 0, self.node_ip + "\n", ""
            n = a[-1]
            c = self.containers.get(n)
            if not c:
                return 1, "", "No such container"
            return 0, json.dumps([{"Config": {"Labels": c["labels"], "Env": c["env"], "Image": c["image"]}, "State": {"Running": c["running"]}}]), ""
        if a[0] == "ps":
            fl = [x for x in _flags(a, "--filter")]
            sel = [n for n, c in self.containers.items() if self._match(c, fl)]
            if "{{.Names}}" in a:
                return 0, "\n".join(sel) + "\n", ""
            return 0, "".join("%s\t%s\t%s\t%s\n" % (n, self.containers[n]["labels"].get("vyomi.cloud", ""), self.containers[n]["labels"].get("vyomi.cluster", ""),
                                                  "running" if self.containers[n]["running"] else "exited") for n in sel), ""
        if a[0] == "rm":
            self.containers.pop(a[-1], None); return 0, "", ""
        if a[0] in ("stop", "start"):
            if a[-1] not in self.containers:
                return 1, "", "No such container"
            self.containers[a[-1]]["running"] = a[0] == "start"; return 0, "", ""
        if a[0] == "port":
            return 0, "127.0.0.1:49152\n", ""
        if a[0] == "exec":
            name = next(x for x in a[1:] if x.startswith("vyomi-k3s-"))
            if name not in self.containers or not self.containers[name]["running"]:
                return 1, "", "container not running"
            if "cat" in a and "/etc/rancher/k3s/k3s.yaml" in a:
                return 0, KUBECONFIG, ""
            if "kubectl" not in a:
                return 0, "", ""
            k = a[a.index("kubectl") + 1:]
            self.kube_calls.append((k, stdin))
            if self.kubectl_hook:
                r = self.kubectl_hook(k, stdin)
                if r is not None:
                    return r
            if k[:2] == ["get", "--raw"]:
                return 0, "ok", ""
            if k[:2] == ["get", "nodes"]:
                n = self.nodes_ready if self.nodes_ready is not None else sum(1 for x in self.agents() if self.containers[x]["running"])
                return 0, "\n".join("n%d Ready <none> 1m v1" % j for j in range(n)) + "\n", ""
            if "secret" in k and "jsonpath={.data.token}" in k:
                return 0, "dXNlci10b2tlbg==", ""
            if k[0] == "get":
                return 0, json.dumps({"items": self.items.get(k[1], [])}), ""
            if k[0] == "apply":
                try:
                    d = json.loads(stdin)
                except (ValueError, TypeError):
                    return 0, "applied (yaml)\n", ""
                self.applied.append(d); return 0, "%s/%s serverside-applied\n" % (d["kind"].lower(), d["metadata"]["name"]), ""
            if k[0] == "delete":
                return 0, "deleted\n", ""
            return 0, "ran %s\n" % " ".join(k), ""
        return 0, "", ""
