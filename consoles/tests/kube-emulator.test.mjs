/* Unit test (node, no browser) for the shared kube layer: kubectl emulator over an in-memory KubeStore + k3s control-plane front.
 *   node consoles/tests/kube-emulator.test.mjs */
import { runKubectl } from "../src/common/kube/kubectl.js";
import { front, credentials, contextName } from "../src/common/kube/controlPlane.js";
import { MOCK_YAML } from "../src/common/kube/mockApp.js";
let bad = 0;
const check = (n, c) => { if (!c) bad++; console.log(`${c ? "PASS" : "FAIL"} ${n}`); };
const objs = new Map(); let n = 0;
const key = (o) => `${o.kind}/${o.metadata.namespace || ""}/${o.metadata.name}`;
const store = {
  async list(kind, ns) { return [...objs.values()].filter((o) => o.kind === kind && (ns == null || kind === "Namespace" || o.metadata.namespace === ns)); },
  async apply(docs) { const out = []; for (const d of docs) { d.metadata.creationTimestamp ||= new Date().toISOString(); objs.set(key(d), d); out.push(`${d.kind.toLowerCase()}/${d.metadata.name} created`); } return out; },
  async delete(kind, name, ns) { return objs.delete(`${kind}/${ns || ""}/${name}`); },
  async deleteNamespace(name) { let f = false; for (const [k, o] of objs) if (o.metadata.name === name && o.kind === "Namespace" || o.metadata.namespace === name) { objs.delete(k); f = true; } return f; },
  async scale(name, ns, r) { const d = objs.get(`Deployment/${ns}/${name}`); if (!d) return false; d.spec.replicas = r; return true; },
};
const run = (l) => runKubectl(store, l);
check("get pods in missing ns -> No resources found in <ns> namespace.", (await run("kubectl get pods -n simulation-app")).logs === "No resources found in simulation-app namespace.\n");
check("apply heredoc", (await run(`kubectl apply -f - <<'EOF'\n${MOCK_YAML}EOF`)).logs.includes("namespace/simulation-app created"));
check("get pods lists pods", (await run("kubectl get pods -n simulation-app")).logs.split("Pending").length === 3);
check("get -A shows NAMESPACE column", (await run("kubectl get pods -A")).logs.startsWith("NAMESPACE"));
check("-o json", JSON.parse((await run("kubectl get pods -n simulation-app -o json")).logs).items.length === 2);
check("scale", (await run("kubectl scale deployment web --replicas=4 -n simulation-app")).logs.includes("scaled") && (await run("kubectl get deployment web -n simulation-app -o json")).logs.includes('"replicas": 4'));
check("delete namespace", (await run("kubectl delete namespace simulation-app")).logs.includes("deleted"));
check("empty again", (await run("kubectl get pods -n simulation-app")).logs.startsWith("No resources found"));
check("unknown verb fails honestly", (await run("kubectl exec foo")).exitCode === 1);
const ad = { cluster: { cloud: "gcp", name: "c1", project: "p", zone: "us-central1-a" }, store };
check("gke context name", contextName(ad.cluster) === "gke_p_us-central1-a_c1" && contextName({ cloud: "aws", name: "e", region: "us-west-2", account: "123456789012" }) === "arn:aws:eks:us-west-2:123456789012:cluster/e");
check("current-context", (await front(ad, "kubectl config current-context")).logs.trim() === "gke_p_us-central1-a_c1");
check("get nodes", /Ready\s+control-plane,master/.test((await front(ad, "kubectl get nodes")).logs) && (await front(ad, "kubectl get nodes -o wide")).logs.includes("INTERNAL-IP"));
check("version server k3s", /Server Version: v\d+\.\d+\.\d+\+k3s1/.test((await front(ad, "kubectl version")).logs));
check("use-context unknown", (await front(ad, "kubectl config use-context nope")).exitCode === 1);
const out = []; const io = { print: (s) => out.push(s), error: (s) => out.push("E:" + s) };
check("gcloud get-credentials", credentials(ad, "gcloud container clusters get-credentials c1 --zone us-central1-a", io) && out.join().includes("kubeconfig entry generated"));
check("gcloud wrong cluster rejected", (credentials(ad, "gcloud container clusters get-credentials zz --zone a", io), out.join().includes("E:ERROR")));
check("view --minify", (await front(ad, "kubectl config view --minify")).logs.includes("current-context: gke_p_us-central1-a_c1"));
console.log(bad ? `FAILED ${bad}` : "ALL PASS"); process.exit(bad ? 1 : 0);
