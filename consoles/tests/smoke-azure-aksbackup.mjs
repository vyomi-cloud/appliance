/* Azure Backup for AKS: split-screen dashboard + terminal, full scenario through the UI, verified over native ARM.
 *   deploy mock app -> create vault -> adhoc backup (async job) -> delete namespace -> kubectl get pods none -> restore -> pods back
 *   BASE=http://127.0.0.1:9141 node consoles/tests/smoke-azure-aksbackup.mjs   (SHOT=<png path> saves a screenshot) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9141";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `bk-rg${n}`, CL = `bk-aks${n}`, VAULT = "sim-vault";
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI);
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2024-04-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${CL}`, { location: "eastus", properties: { kubernetesVersion: "1.29.0", dnsPrefix: "bk", agentPoolProfiles: [{ name: "np", count: 1, vmSize: "Standard_B2s", mode: "System" }] } }, "2024-09-02-preview");

await page.goto(UI + `#/aks/${RG}/${CL}/backup`);
await page.getByTestId("kube-dashboard").waitFor({ timeout: 20000 });
check("Backup panel is real (no Not-simulated 'Azure Backup for AKS' panel)", (await page.getByText("Azure Backup for AKS").count()) >= 1 && (await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.textContent)).then((t) => !t.some((x) => /^Azure Backup for AKS/.test(x)))));
const term = page.getByTestId("kube-terminal-out");
const type = async (cmd, waitFor, timeout = 20000) => { await page.getByLabel("Terminal input").fill(cmd); await page.getByLabel("Terminal input").press("Enter"); if (waitFor) await page.waitForFunction(([w]) => document.querySelector('[data-testid="kube-terminal-out"]').innerText.includes(w), [waitFor], { timeout }); };
const K = `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${CL}/runCommand`;
const kube = async (c) => json(await arm("POST", K, { command: c }, "2024-09-02-preview")).properties?.logs || "";

await page.getByTestId("deploy-mock").click();
await page.getByTestId("ns-simulation-app").waitFor({ timeout: 15000 });
check("Deploy mock application created the namespace + pods (ARM runCommand)", (await kube("kubectl get pods -n simulation-app")).split("Pending").length === 3);
await type("kubectl get pods -n simulation-app", "web-");
await type("az dataprotection backup-vault create --vault-name sim-vault", "is ready");
check("vault exists over native ARM", json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.DataProtection/backupVaults/${VAULT}`)).properties?.provisioningState === "Succeeded");
await page.getByTestId("vault-state").getByText(VAULT).waitFor({ timeout: 8000 });
await type("az dataprotection backup-instance adhoc-backup --vault-name sim-vault --instance-name aks-cluster-instance", "Backup completed", 30000);
const I = `/resourceGroups/${RG}/providers/Microsoft.DataProtection/backupVaults/${VAULT}/backupInstances/aks-cluster-instance`;
const rps = json(await arm("GET", `${I}/recoveryPoints`)).value || [];
check("backup job produced one recovery point (blob artifact)", rps.length === 1 && !!rps[0].properties.artifact && rps[0].properties.objectCounts?.Pod === 2);
await page.getByTestId("rp-table").waitFor({ timeout: 8000 });
await page.getByTestId("inject-disaster").click();
await page.waitForFunction(() => !document.querySelector('[data-testid="ns-simulation-app"]'), null, { timeout: 15000 });
await type("kubectl get pods -n simulation-app", "No resources found in simulation-app namespace.");
check("namespace wiped (ARM view)", (await kube("kubectl get pods -n simulation-app")).includes("No resources found"));
await type("az dataprotection backup-instance restore trigger --vault-name sim-vault --instance-name aks-cluster-instance", "Restore completed", 30000);
await page.getByTestId("ns-simulation-app").waitFor({ timeout: 15000 });
check("restore re-injected the pods", (await kube("kubectl get pods -n simulation-app")).split("Pending").length === 3);
await type("kubectl get pods -n simulation-app", "Pending");
await type("kubectl config current-context", CL);
await type("kubectl get nodes", "control-plane,master");
await type("kubectl version", "+k3s1");
await type("az aks get-credentials -g " + RG + " -n " + CL, "Merged");
await type("kubectl config get-contexts", "CURRENT");
await type("kubectl scale deployment web --replicas=3 -n simulation-app", "scaled");
check("scale updated the deployment spec via ARM", /0\/3/.test(await kube("kubectl get deployment web -n simulation-app")));
await type("kubectl get nope", "doesn't have a resource type");
await type("az dataprotection job list --vault-name sim-vault", "Restore");
check("no page errors", errors.length === 0, errors.join("|"));
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await browser.close();
console.log(bad ? `FAILED (${bad})` : "ALL PASS");
process.exit(bad ? 1 : 0);
