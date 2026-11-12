/* kubectl emulator for clouds whose cluster has no native "run a command" action. It parses the command and answers it from a
 * KubeStore (see README.md) -- the same interface the offline appliance's real k3s backend implements, so the terminal never
 * knows where cluster state lives. Output text follows real kubectl ("No resources found in <ns> namespace.").
 * Supported: get | delete | scale | apply -f (JSON/`---` docs, `-f -` heredoc) | create namespace|deployment, with -n/--namespace, -A/--all-namespaces,
 * -o wide|json|yaml|name, kinds namespaces/ns, deployments/deploy, pods/po, services/svc, configmaps/cm, secrets, `all`.
 * Anything else fails with exit 1 and an honest reason -- never a fake success. */
const KINDS = {
  namespace: ["Namespace", false], namespaces: ["Namespace", false], ns: ["Namespace", false],
  pod: ["Pod", true], pods: ["Pod", true], po: ["Pod", true],
  deployment: ["Deployment", true], deployments: ["Deployment", true], deploy: ["Deployment", true],
  service: ["Service", true], services: ["Service", true], svc: ["Service", true],
  configmap: ["ConfigMap", true], configmaps: ["ConfigMap", true], cm: ["ConfigMap", true],
  secret: ["Secret", true], secrets: ["Secret", true],
};
const LABEL = { Namespace: "namespace", Pod: "pod", Deployment: "deployment.apps", Service: "service", ConfigMap: "configmap", Secret: "secret" };
const PLURAL = { Namespace: "namespaces", Pod: "pods", Deployment: "deployments", Service: "services", ConfigMap: "configmaps", Secret: "secrets" };

export function tokenize(line) {
  const out = []; const re = /"([^"]*)"|'([^']*)'|(\S+)/g; let m;
  while ((m = re.exec(line))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}
const age = (ts) => {
  const s = Math.max(0, Math.floor((Date.now() - Date.parse(ts || 0)) / 1000));
  return s < 120 ? `${s}s` : s < 7200 ? `${Math.floor(s / 60)}m` : s < 172800 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`;
};
const table = (rows) => {
  const w = rows[0].map((_, i) => Math.max(...rows.map((r) => String(r[i]).length)));
  return rows.map((r) => r.map((c, i) => (i === r.length - 1 ? String(c) : String(c).padEnd(w[i] + 3))).join("")).join("\n") + "\n";
};
const HEAD = { Namespace: ["NAME", "STATUS", "AGE"], Pod: ["NAME", "READY", "STATUS", "RESTARTS", "AGE"], Deployment: ["NAME", "READY", "UP-TO-DATE", "AVAILABLE", "AGE"],
  Service: ["NAME", "TYPE", "CLUSTER-IP", "PORT(S)", "AGE"], ConfigMap: ["NAME", "DATA", "AGE"], Secret: ["NAME", "TYPE", "DATA", "AGE"] };
function row(o) {
  const md = o.metadata, a = age(md.creationTimestamp);
  switch (o.kind) {
    case "Namespace": return [md.name, o.status?.phase || "Active", a];
    case "Pod": return [md.name, `0/${(o.spec?.containers || []).length || 1}`, o.status?.phase || "Pending", "0", a];
    case "Deployment": return [md.name, `0/${o.spec?.replicas ?? 1}`, "0", "0", a];
    case "Service": return [md.name, o.spec?.type || "ClusterIP", o.spec?.clusterIP || "<none>", (o.spec?.ports || []).map((p) => `${p.port}/${p.protocol || "TCP"}`).join(",") || "<none>", a];
    case "ConfigMap": return [md.name, Object.keys(o.data || {}).length, a];
    default: return [md.name, o.type || "Opaque", Object.keys(o.data || {}).length, a];
  }
}
function yaml(v, ind = 0) {
  const pad = " ".repeat(ind);
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" && x ? `${pad}- ${yaml(x, ind + 2).trimStart()}` : `${pad}- ${JSON.stringify(x)}`)).join("\n") || `${pad}[]`;
  if (v && typeof v === "object") return Object.entries(v).map(([k, x]) => (x && typeof x === "object" && (Array.isArray(x) ? x.length : Object.keys(x).length) ? `${pad}${k}:\n${yaml(x, ind + 2)}` : `${pad}${k}: ${x && typeof x === "object" ? (Array.isArray(x) ? "[]" : "{}") : JSON.stringify(x)}`)).join("\n");
  return `${pad}${JSON.stringify(v)}`;
}
function flags(args) {
  const f = { n: null, A: false, o: null, f: null, pos: [] };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "-n" || a === "--namespace") f.n = args[++i];
    else if (a.startsWith("--namespace=")) f.n = a.slice(12);
    else if (a === "-A" || a === "--all-namespaces") f.A = true;
    else if (a === "-o" || a === "--output") f.o = args[++i];
    else if (a.startsWith("-o=") || a.startsWith("--output=")) f.o = a.split("=")[1];
    else if (a.startsWith("-o") && a.length > 2) f.o = a.slice(2);
    else if (a === "-f" || a === "--filename") f.f = args[++i];
    else if (a.startsWith("--image=")) f.image = a.slice(8);
    else if (a.startsWith("--replicas=")) f.replicas = Number(a.slice(11));
    else if (a.startsWith("-")) throw new Error(`error: unknown flag: ${a}`);
    else f.pos.push(a);
  }
  return f;
}
const kindOf = (t) => { const k = KINDS[String(t).toLowerCase()]; if (!k) throw new Error(`error: the server doesn't have a resource type "${t}"`); return k; };

export function parseManifests(text) {
  const docs = [];
  for (const part of String(text).split(/^---\s*$/m)) {
    if (!part.trim()) continue;
    try { docs.push(JSON.parse(part)); } catch { throw new Error("error: the in-browser kubectl emulator reads JSON manifests only (this cluster has no native YAML runCommand)"); }
  }
  return docs;
}

/** runKubectl(store, commandLine) -> {exitCode, logs}. `store` is a KubeStore (README.md). */
export async function runKubectl(store, line) {
  const src = String(line).replace(/<<-?\s*'?"?(\w+)"?'?\n([\s\S]*?)\n\1\s*$/, "").trim();
  const heredoc = /<<-?\s*'?"?(\w+)"?'?\n([\s\S]*?)\n\1\s*$/.exec(String(line));
  const args = tokenize(src);
  if (args[0] !== "kubectl") return { exitCode: 127, logs: `${args[0] || ""}: command not found\n` };
  try { return { exitCode: 0, logs: await exec(store, args.slice(1), heredoc ? heredoc[2] + "\n" : null) }; }
  catch (e) { return { exitCode: 1, logs: String(e.message || e).replace(/\n?$/, "\n") }; }
}

async function exec(store, args, stdin) {
  const verb = args[0];
  if (!verb) throw new Error("kubectl controls the Kubernetes cluster manager.\n\nUsage: kubectl get|delete|apply|create ...");
  const f = flags(args.slice(1));
  if (verb === "get") {
    if (!f.pos.length) throw new Error('error: you must specify the type of resource to get. Use "kubectl api-resources" for a complete list of supported resources.');
    const kinds = f.pos[0] === "all" ? ["Pod", "Service", "Deployment"] : f.pos[0].split(",").map((t) => kindOf(t)[0]);
    const names = f.pos.slice(1);
    const items = [];
    for (const k of kinds) {
      const nsd = Object.values(KINDS).find(([kk]) => kk === k)[1];
      for (const o of await store.list(k, nsd && !f.A ? f.n || "default" : null)) if (!names.length || names.includes(o.metadata.name)) items.push(o);
    }
    if (names.length) { const miss = names.filter((n) => !items.some((o) => o.metadata.name === n)); if (miss.length) throw new Error(miss.map((n) => `Error from server (NotFound): ${PLURAL[kinds[0]]} "${n}" not found`).join("\n")); }
    if (f.o === "json") return JSON.stringify(items.length === 1 && names.length ? items[0] : { apiVersion: "v1", kind: "List", items }, null, 4) + "\n";
    if (f.o === "yaml") return yaml(items.length === 1 && names.length ? items[0] : { apiVersion: "v1", kind: "List", items }) + "\n";
    if (f.o === "name") return items.map((o) => `${LABEL[o.kind]}/${o.metadata.name}\n`).join("");
    if (f.o && f.o !== "wide") throw new Error(`error: unable to match a printer suitable for the output format "${f.o}", allowed formats are: json,name,wide,yaml`);
    if (!items.length) return f.A || kinds.every((k) => k === "Namespace") ? "No resources found\n" : `No resources found in ${f.n || "default"} namespace.\n`;
    return kinds.map((k) => {
      const ks = items.filter((o) => o.kind === k); if (!ks.length) return "";
      const nsd = k !== "Namespace";
      const head = [...(f.A && nsd ? ["NAMESPACE"] : []), ...HEAD[k], ...(f.o === "wide" && k === "Pod" ? ["IP", "NODE"] : [])];
      return table([head, ...ks.map((o) => [...(f.A && nsd ? [o.metadata.namespace] : []), ...row(o), ...(f.o === "wide" && k === "Pod" ? ["<none>", "<none>"] : [])])]);
    }).filter(Boolean).join("\n");
  }
  if (verb === "delete") {
    if (f.f) { const docs = parseManifests(f.f === "-" ? stdin || "" : ""); return (await Promise.all(docs.map(async (d) => { await delOne(store, d.kind, d.metadata.name, d.metadata.namespace || "default"); return `${LABEL[d.kind]} "${d.metadata.name}" deleted\n`; }))).join(""); }
    if (f.pos.length < 2) throw new Error("error: resource(s) were provided, but no name was specified");
    const [kind, nsd] = kindOf(f.pos[0]);
    let out = "";
    for (const n of f.pos.slice(1)) { await delOne(store, kind, n, nsd ? f.n || "default" : null); out += `${LABEL[kind]} "${n}" deleted\n`; }
    return out;
  }
  if (verb === "apply" || (verb === "create" && f.f)) {
    if (!f.f) throw new Error("error: must specify one of -f and -k");
    if (f.f !== "-") throw new Error("error: only `-f -` (stdin/heredoc) is supported in this terminal");
    const docs = parseManifests(stdin || "");
    const verbs = await store.apply(docs);
    return verbs.join("\n") + "\n";
  }
  if (verb === "create") {
    const [what, name] = f.pos;
    if (what === "namespace" || what === "ns") { if (!name) throw new Error("error: exactly one NAME is required, got 0"); return (await store.apply([{ apiVersion: "v1", kind: "Namespace", metadata: { name } }])).join("\n") + "\n"; }
    if (what === "deployment" || what === "deploy") {
      if (!name || !f.image) throw new Error("error: exactly one NAME is required, and --image is required");
      const lab = { app: name };
      return (await store.apply([{ apiVersion: "apps/v1", kind: "Deployment", metadata: { name, namespace: f.n || "default", labels: lab }, spec: { replicas: f.replicas ?? 1, selector: { matchLabels: lab }, template: { metadata: { labels: lab }, spec: { containers: [{ name: f.image.split(":")[0].split("/").pop(), image: f.image }] } } } }])).join("\n") + "\n";
    }
    throw new Error(`error: unknown command "${what || ""}" for "kubectl create" (the in-browser emulator supports: namespace, deployment)`);
  }
  if (verb === "api-resources") {
    const rows = [["NAME", "SHORTNAMES", "APIVERSION", "NAMESPACED", "KIND"], ["configmaps", "cm", "v1", "true", "ConfigMap"], ["namespaces", "ns", "v1", "false", "Namespace"], ["pods", "po", "v1", "true", "Pod"], ["secrets", "", "v1", "true", "Secret"], ["services", "svc", "v1", "true", "Service"], ["deployments", "deploy", "apps/v1", "true", "Deployment"]];
    return table(rows);
  }
  if (verb === "describe") {
    const [kind, nsd] = kindOf(f.pos[0] || ""); const name = f.pos[1];
    const o = (await store.list(kind, nsd ? f.n || "default" : null)).find((x) => x.metadata.name === name);
    if (!o) throw new Error(`Error from server (NotFound): ${PLURAL[kind]} "${name}" not found`);
    const md = o.metadata;
    return `Name:         ${md.name}\n${nsd ? `Namespace:    ${md.namespace}\n` : ""}Labels:       ${Object.entries(md.labels || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "<none>"}\nStatus:       ${o.status?.phase || ""}\n${yaml({ spec: o.spec || {} })}\n`;
  }
  if (verb === "scale") {
    const [kind] = kindOf(f.pos[0].split("/")[0]); const name = f.pos[0].includes("/") ? f.pos[0].split("/")[1] : f.pos[1];
    if (kind !== "Deployment" || !store.scale) throw new Error("error: only `kubectl scale deployment <name> --replicas=N` is supported");
    if (!(await store.scale(name, f.n || "default", f.replicas))) throw new Error(`Error from server (NotFound): deployments.apps "${name}" not found`);
    return `deployment.apps/${name} scaled\n`;
  }
  throw new Error(`error: "kubectl ${verb}" is not simulated by Vyomi (supported: get, delete, apply, create); there is no running container or API server behind this cluster for logs/exec/port-forward.`);
}
async function delOne(store, kind, name, ns) {
  const ok = kind === "Namespace" ? await store.deleteNamespace(name) : await store.delete(kind, name, ns);
  if (!ok) throw new Error(`Error from server (NotFound): ${PLURAL[kind]} "${name}" not found`);
}
