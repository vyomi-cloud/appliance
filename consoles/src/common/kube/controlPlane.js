/* The emulated k3s-flavoured control plane the in-browser (free) backend presents to kubectl, shared by every cloud:
 * kubeconfig contexts (one per cluster, named like each cloud CLI generates), cluster-info, version (client + server), get nodes
 * (a single k3s control-plane node), logs (synthetic, labelled) and the cloud "get-credentials" commands that switch context.
 * It is a REAL emulation of the answers, not a real k3s: a 64-bit k3s cannot run in the browser, and nothing outside the browser tab
 * (Lens, kubectl on your machine) can connect to it -- that needs the Mesh (RealK8sBackend). All text says so where it matters.
 *
 * Adapter.cluster = { cloud: "azure"|"aws"|"gcp", name, resourceGroup?, location|region|zone, account?, project?, createdAt?, k8sVersion? } */
import { tokenize, runKubectl } from "./kubectl.js";

export const contextName = (c) => {
  if (c.cloud === "aws") return `arn:aws:eks:${c.region || c.location || "us-east-1"}:${c.account || "000000000000"}:cluster/${c.name}`;
  if (c.cloud === "gcp") return `gke_${c.project || "vyomi-project"}_${c.zone || c.location || "us-central1-a"}_${c.name}`;
  return c.name;
};
export const k3sVersion = (c) => {
  const m = /(\d+)\.(\d+)(?:\.(\d+))?/.exec(c.k8sVersion || "");
  return m ? `v${m[1]}.${m[2]}.${m[3] || "0"}+k3s1` : "v1.31.4+k3s1";
};
const server = (c) => `https://${c.name}.vyomi.invalid:6443`;
const age = (ts) => {
  const s = Math.max(0, Math.floor((Date.now() - (Date.parse(ts) || Date.now())) / 1000));
  return s < 120 ? `${s}s` : s < 7200 ? `${Math.floor(s / 60)}m` : s < 172800 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`;
};
const pad = (rows) => { const w = rows[0].map((_, i) => Math.max(...rows.map((r) => String(r[i]).length))); return rows.map((r) => r.map((c, i) => (i === r.length - 1 ? String(c) : String(c).padEnd(w[i] + 3))).join("")).join("\n") + "\n"; };

/** Per-adapter kubeconfig: the cluster's own context is present and current (the banner says so); get-credentials merges/switches. */
export function kubeconfig(adapter) {
  if (!adapter._kc) { const n = contextName(adapter.cluster); adapter._kc = { contexts: [{ name: n, cluster: n, user: `clusterUser_${adapter.cluster.name}` }], current: n }; }
  return adapter._kc;
}
export const nodeName = (c) => `${c.name}-k3s-server-0`;
function nodeObject(c) {
  return { apiVersion: "v1", kind: "Node", metadata: { name: nodeName(c), creationTimestamp: c.createdAt || new Date().toISOString(), labels: { "node-role.kubernetes.io/control-plane": "true", "node-role.kubernetes.io/master": "true", "kubernetes.io/hostname": nodeName(c), "kubernetes.io/os": "linux", "vyomi.io/emulated": "true" } },
    spec: { podCIDR: "10.42.0.0/24" }, status: { conditions: [{ type: "Ready", status: "True", reason: "KubeletReady", message: "emulated by Vyomi (no kubelet runs)" }], nodeInfo: { kubeletVersion: k3sVersion(c), osImage: "K3s (emulated in-browser)", containerRuntimeVersion: "containerd://emulated", kernelVersion: "n/a" }, addresses: [{ type: "InternalIP", address: "172.20.0.2" }] } };
}

/** Returns {exitCode, logs} when the command is answered here, or null to fall through to the backend's kubectl. */
export async function front(adapter, line) {
  const args = tokenize(line).slice(1);
  const c = adapter.cluster; const kc = kubeconfig(adapter); const verb = args[0];
  const ok = (logs) => ({ exitCode: 0, logs });
  const bad = (logs) => ({ exitCode: 1, logs: logs + "\n" });
  const rest = args.slice(1).filter((a) => !a.startsWith("-"));
  const flag = (n) => args.find((a, i) => a === n || (a.startsWith(n + "=")) ) ;
  if (verb === "config") {
    const sub = args[1];
    if (sub === "current-context") return ok(kc.current + "\n");
    if (sub === "get-contexts") {
      const rows = [["CURRENT", "NAME", "CLUSTER", "AUTHINFO", "NAMESPACE"], ...kc.contexts.map((x) => [x.name === kc.current ? "*" : "", x.name, x.cluster, x.user, ""])];
      return ok(pad(rows));
    }
    if (sub === "use-context") {
      const n = args[2]; if (!kc.contexts.some((x) => x.name === n)) return bad(`error: no context exists with the name: "${n}"`);
      kc.current = n; return ok(`Switched to context "${n}".\n`);
    }
    if (sub === "view") {
      const minify = args.includes("--minify");
      const list = minify ? kc.contexts.filter((x) => x.name === kc.current) : kc.contexts;
      return ok(`apiVersion: v1\nkind: Config\ncurrent-context: ${kc.current}\nclusters:\n${list.map((x) => `- name: ${x.cluster}\n  cluster:\n    server: ${server(c)}  # emulated in-browser API server (not reachable outside this tab)\n    certificate-authority-data: DATA+OMITTED`).join("\n")}\ncontexts:\n${list.map((x) => `- name: ${x.name}\n  context:\n    cluster: ${x.cluster}\n    user: ${x.user}`).join("\n")}\nusers:\n${list.map((x) => `- name: ${x.user}\n  user:\n    token: REDACTED`).join("\n")}\npreferences: {}\n`);
    }
    return bad(`error: "kubectl config ${sub || ""}" is not simulated (supported: get-contexts, current-context, use-context, view [--minify])`);
  }
  if (verb === "cluster-info") {
    if (args[1] === "dump") return bad("error: cluster-info dump is not simulated");
    return ok(`Kubernetes control plane is running at ${server(c)}\nCoreDNS is running at ${server(c)}/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy\nMetrics-server is running at ${server(c)}/api/v1/namespaces/kube-system/services/https:metrics-server:https/proxy\n\nThis is an emulated k3s-flavoured control plane inside your browser; it is not reachable from kubectl or Lens on your machine (that needs the Mesh).\n`);
  }
  if (verb === "version") {
    const sv = k3sVersion(c);
    const lines = ["Client Version: v1.31.4", "Kustomize Version: v5.4.2"];
    if (!args.includes("--client")) lines.push(`Server Version: ${sv}`);
    return ok(lines.join("\n") + "\n");
  }
  if (verb === "get" && /^(nodes?|no)(,|$)/.test(args[1] || "") && !String(args[1]).includes(",")) {
    const o = (args.find((a, i) => (args[i - 1] === "-o" || args[i - 1] === "--output")) || (flag("-o") || "").slice(3) || "");
    const n = nodeObject(c);
    if (o === "json") return ok(JSON.stringify({ apiVersion: "v1", kind: "List", items: [n] }, null, 4) + "\n");
    if (o === "name") return ok(`node/${nodeName(c)}\n`);
    const wide = o === "wide";
    const row = [nodeName(c), "Ready", "control-plane,master", age(n.metadata.creationTimestamp), k3sVersion(c), ...(wide ? ["172.20.0.2", "<none>", "K3s (emulated in-browser)", "n/a", "containerd://emulated"] : [])];
    return ok(pad([["NAME", "STATUS", "ROLES", "AGE", "VERSION", ...(wide ? ["INTERNAL-IP", "EXTERNAL-IP", "OS-IMAGE", "KERNEL-VERSION", "CONTAINER-RUNTIME"] : [])], row]));
  }
  if (verb === "describe" && /^(nodes?|no)$/.test(args[1] || "")) {
    const n = nodeObject(c);
    return ok(`Name:               ${nodeName(c)}\nRoles:              control-plane,master\nLabels:             ${Object.entries(n.metadata.labels).map(([k, v]) => `${k}=${v}`).join("\n                    ")}\nConditions:\n  Ready  True  KubeletReady  emulated by Vyomi (no kubelet runs)\nSystem Info:\n  Kubelet Version:   ${k3sVersion(c)}\n  OS Image:          K3s (emulated in-browser)\n`);
  }
  if (verb === "logs") {
    const pod = rest[0]; if (!pod) return bad("error: expected 'logs [-f] [-p] (POD | TYPE/NAME) [-c CONTAINER]'");
    const ns = (args.find((a, i) => args[i - 1] === "-n" || args[i - 1] === "--namespace")) || "default";
    const probe = await run(adapter, `kubectl get pod ${pod} -n ${ns} -o name`);
    if (probe.exitCode) return probe;
    return ok(`# synthetic log: Vyomi runs no containers, so this pod has no real output. Lines below are generated.\n${new Date().toISOString()} INFO  ${pod} started (emulated)\n${new Date().toISOString()} INFO  pod is Pending: not scheduled to a kubelet\n`);
  }
  return null;
}
export const run = (adapter, cmd) => (adapter.kubectl ? adapter.kubectl(cmd) : runKubectl(adapter.store, cmd));

/** Cloud get-credentials commands: merge the cluster's context into the terminal's kubeconfig and make it current. */
export function credentials(adapter, line, io) {
  const t = tokenize(line); const c = adapter.cluster; const kc = kubeconfig(adapter);
  const opt = (...names) => { for (let i = 0; i < t.length; i++) { for (const n of names) { if (t[i] === n) return t[i + 1]; if (t[i].startsWith(n + "=")) return t[i].slice(n.length + 1); } } return undefined; };
  let name, label;
  if (t[0] === "az" && t[1] === "aks" && t[2] === "get-credentials") {
    name = opt("-n", "--name"); const rg = opt("-g", "--resource-group");
    if (!name || !rg) { io.error("az: error: the following arguments are required: --resource-group/-g, --name/-n"); return true; }
    if (name !== c.name || rg.toLowerCase() !== String(c.resourceGroup).toLowerCase()) { io.error(`ERROR: (ResourceNotFound) The Resource 'Microsoft.ContainerService/managedClusters/${name}' under resource group '${rg}' was not found. This terminal is attached to ${c.name} in ${c.resourceGroup}.`); return true; }
    label = opt("--context") || contextName(c);
  } else if (t[0] === "aws" && t[1] === "eks" && t[2] === "update-kubeconfig") {
    name = opt("--name"); if (!name) { io.error("aws: error: the following arguments are required: --name"); return true; }
    if (name !== c.name) { io.error(`An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation: No cluster found for name: ${name}. This terminal is attached to ${c.name}.`); return true; }
    label = opt("--alias") || contextName(c);
  } else if (t[0] === "gcloud" && t[1] === "container" && t[2] === "clusters" && t[3] === "get-credentials") {
    name = t[4]; if (!name || name.startsWith("-")) { io.error("ERROR: (gcloud.container.clusters.get-credentials) argument NAME: Must be specified."); return true; }
    if (name !== c.name) { io.error(`ERROR: (gcloud.container.clusters.get-credentials) ResponseError: code=404, message=Not found: projects/${c.project || "vyomi-project"}/locations/${opt("--zone", "--region") || c.zone}/clusters/${name}. This terminal is attached to ${c.name}.`); return true; }
    label = contextName(c);
  } else return false;
  if (!kc.contexts.some((x) => x.name === label)) kc.contexts.push({ name: label, cluster: label, user: `clusterUser_${c.name}` });
  kc.current = label;
  io.print(t[0] === "az" ? `Merged "${label}" as current context in /home/vyomi/.kube/config` : t[0] === "aws" ? `Added new context ${label} to /home/vyomi/.kube/config` : `Fetching cluster endpoint and auth data.\nkubeconfig entry generated for ${c.name}.`);
  io.print("(kubeconfig lives in this terminal only; the in-browser API server is not reachable from outside the tab.)");
  return true;
}
