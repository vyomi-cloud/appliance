/* Smoke: AKS GitOps (Flux) + Automated deployments pages are real: create via the UI, push, see reconcile + runs.
 *   BASE=http://127.0.0.1:9073 node consoles/tests/smoke-azure-gitops.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9073";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `go-rg-${n}`, AKS = `goaks${n}`, ACR = `goacr${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, url, body]);
const arm = (m, path, body, v = "2024-05-01") => call(m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1500, height: 1000 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
const C = `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}`;
await arm("PUT", C, { location: "eastus", properties: { dnsPrefix: "go", agentPoolProfiles: [{ name: "np", count: 1, vmSize: "Standard_DS2_v2", mode: "System" }] } });
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}`, { location: "eastus", sku: { name: "Standard" } }, "2023-07-01");

await pg.goto(`${UI}#/aks/${RG}/${AKS}/gitops`); await pg.waitForTimeout(1500);
ok("GitOps is a real page, not a not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0 && (await pg.getByRole("button", { name: "Create Flux configuration" }).count()) === 1);
await pg.getByLabel("Configuration name").fill("flux1");
await pg.getByLabel("Repository URL").fill("vyomi://gitops-app");
await pg.getByLabel("Kustomization path").fill("./apps");
await pg.getByRole("button", { name: "Create Flux configuration" }).click(); await pg.waitForTimeout(1500);
ok("configuration listed, Non-Compliant (empty source) with the git reason", /Non-Compliant/.test(await pg.getByRole("table", { name: "Flux configurations" }).innerText()));
const F = `${C}/providers/Microsoft.KubernetesConfiguration/fluxConfigurations/flux1`;
const dep = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\nspec:\n  replicas: 1\n  selector:\n    matchLabels: {app: web}\n  template:\n    metadata:\n      labels: {app: web}\n    spec:\n      containers:\n      - name: web\n        image: nginx:1.25\n";
const r = await arm("POST", `${F}/vyomiPush`, { files: { "apps/dep.yaml": dep }, message: "add web" }, "2023-05-01");
ok("push accepted", r.status === 200, JSON.stringify(r.body).slice(0, 200));
await pg.reload(); await pg.waitForTimeout(1500);
const tbl = await pg.getByRole("table", { name: "Flux configurations" }).innerText();
ok("push reconciled: Compliant with a synced revision", /Compliant/.test(tbl) && !/Non-Compliant/.test(tbl) && /main@/.test(tbl), tbl.slice(0, 200));
const k = await arm("POST", `${C}/runCommand`, { command: "kubectl get deploy -A" });
ok("the Deployment really exists in the AKS object store", /web/.test(JSON.stringify(k.body)));
await pg.getByRole("button", { name: "Delete flux1" }).click(); await pg.waitForTimeout(1200);
const k2 = await arm("POST", `${C}/runCommand`, { command: "kubectl get deploy -A" });
ok("deleting the configuration prunes the Deployment", !/\bweb\b/.test(JSON.stringify(k2.body).replace(/\\n/g, " ").replace(/No resources found/, "")) || /No resources/.test(JSON.stringify(k2.body)));

await pg.goto(`${UI}#/aks/${RG}/${AKS}/automateddeployments`); await pg.waitForTimeout(1500);
ok("Automated deployments is a real page", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0 && (await pg.getByRole("button", { name: "Create automated deployment" }).count()) === 1);
await pg.getByLabel("Deployment name").fill("ad1");
await pg.getByLabel("Repository", { exact: true }).fill("vyomi://shop");
await pg.getByLabel("Image name").fill("contoso/web");
await pg.getByRole("button", { name: "Create automated deployment" }).click(); await pg.waitForTimeout(1800);
const sec = pg.getByRole("region", { name: "Deployment ad1" });
ok("deployment shown with the generated workflow", (await sec.count()) === 1 && /azure\/k8s-deploy/.test(await sec.locator("textarea").inputValue()));
ok("run recorded (Failed here: dev server has no container builder, never a fake success)", /Failed/.test(await sec.innerText()));
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
