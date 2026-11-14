/* GCP v4 console (consoles/src/gcp -> /v4/gcp/) UI <-> native REST bi-directional round-trip.
 * UI = the v4 console in Playwright; "SDK/CLI/API" = the real Google REST surface on the SAME wire (/_wire).
 *   A UI create -> native GET sees it   B native create -> UI lists it   C native delete -> UI drops it   D UI delete -> native 404
 * Env: BASE (default http://127.0.0.1:9310 = `python3 consoles/dev_server.py --port 9310`, or an appliance), UI_PATH (/v4/gcp/index.html),
 *      WIRE_PATH (/_wire), PROJECT (nano-project), ONLY=vpc,storage,..., OUT (json report).
 * Honest SKIPs are printed with their reason and never counted as PASS. */
import { chromium, sleep } from "../../../wasm/ui-tests/lib.mjs";
import { nanoStart } from "./lib/nano-gcp.mjs";
const NANO = !!process.env.NANO;   // NANO=1: genuine Nano (in-browser engines, wasm/ bundle) instead of dev_server
let NH = null;
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import net from "node:net";
import { createServer } from "node:http";

const HERE = dirname(fileURLToPath(import.meta.url));
// BASE unset -> start `consoles/dev_server.py` (the same router the appliance and Nano use) on a free port for this run.
let dev = null;
const freePort = () => new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
let BASE = process.env.BASE || "";
// A real local HTTP backend for the API Gateway data-plane checks. The control plane only accepts https:// backends, so the spawned dev server
// is told (VYOMI_GATEWAY_BACKEND_OVERRIDES, a test hook) to send https://backend.rt.test to this loopback port. Skipped against BASE/SIM_URL.
const BACKEND = await new Promise((res) => { const srv = createServer((rq, rs) => { const c = []; rq.on("data", (d) => c.push(d)); rq.on("end", () => { rs.writeHead(200, { "content-type": "application/json", "x-rt-backend": "1" }); rs.end(JSON.stringify({ hit: rq.url, method: rq.method })); }); }).listen(0, "127.0.0.1", () => res({ srv, port: srv.address().port })); });
if (!BASE && !NANO) {
  const port = await freePort();
  dev = spawn(process.env.PY || "python3", [resolve(HERE, "../../../consoles/dev_server.py"), "--port", String(port), "--tier", "max", "--primary", "gcp"], { stdio: "ignore", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", VYOMI_GATEWAY_BACKEND_OVERRIDES: `https://backend.rt.test=http://127.0.0.1:${BACKEND.port}` } });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/v4/gcp/")).ok) break; } catch (_) {} await new Promise((r) => setTimeout(r, 500)); }
}
// SIM_URL = a real simulator/appliance (e.g. a Mesh Codespace through `vyomi-tunnel forward`): the console bundle still comes from BASE, but a small
// proxy sends the console's /_wire calls to SIM_URL, and the "SDK/CLI/API" side talks to SIM_URL directly, like gcloud/curl would.
const SIM = (process.env.SIM_URL || "").replace(/\/$/, "");
if (SIM) {
  const origin = BASE, http = await import("node:http");
  const proxy = http.createServer(async (rq, rs) => {
    const chunks = []; for await (const c of rq) chunks.push(c);
    const wire = rq.url.startsWith("/_wire/");
    const url = (wire ? SIM + rq.url.slice(6) : origin + rq.url);
    try {
      const r = await fetch(url, { method: rq.method, headers: { "content-type": rq.headers["content-type"] || "application/json" }, body: ["GET", "HEAD"].includes(rq.method) ? undefined : Buffer.concat(chunks) });
      const h = {}; r.headers.forEach((v, k) => { if (!["content-encoding", "content-length", "transfer-encoding", "connection"].includes(k)) h[k] = v; });
      const buf = Buffer.from(await r.arrayBuffer());
      if (process.env.TRACE && wire && r.status >= 400 && rq.method !== "GET") console.log("  [wire-err]", rq.method, rq.url.slice(0, 100), "REQ", Buffer.concat(chunks).toString().slice(0, 600), "RESP", buf.toString().slice(0, 400));
      rs.writeHead(r.status, h); rs.end(buf);
    } catch (e) { rs.writeHead(502); rs.end(String(e)); }
  });
  await new Promise((res) => proxy.listen(0, "127.0.0.1", res));
  BASE = `http://127.0.0.1:${proxy.address().port}`;
}
let UI = BASE + (process.env.UI_PATH || "/v4/gcp/index.html");
const WIRE = SIM ? SIM : BASE + (process.env.WIRE_PATH || "/_wire");
const P = process.env.PROJECT || (SIM ? "vyomi-project" : "nano-project");
const R = "us-central1", Z = "us-central1-a";
const OUT = process.env.OUT || resolve(HERE, "../hourly/out/gcp-v4-roundtrip.json");

const rest = async (method, path, body) => {
  if (NH) return NH.rest(method, path, body);
  const r = await fetch(WIRE + path, { method, headers: { "content-type": "application/json" }, body: body === undefined || method === "GET" || method === "DELETE" ? undefined : JSON.stringify(body) });
  let j = null; try { j = await r.json(); } catch (_) {}
  return { status: r.status, body: j };
};

// Services addressed by a server-assigned id (Monitoring alert policies) give idOf(n): look the id up by display name.
const nget = async (s, n) => { if (s.idOf) { const id = await s.idOf(n); return id ? rest("GET", s.get(id)) : { status: 404, body: null }; } return rest("GET", s.get(n)); };
const ndel = async (s, n) => { if (s.idOf) { const id = await s.idOf(n); return id ? rest("DELETE", s.del(id)) : { status: 404, body: null }; } return rest("DELETE", s.del(n)); };
// Each service: ui = [list route, create route|null]; create(n) -> [method, path, body]; get(n) -> path; del(n) -> path.
const EA = { bucket: "rt-ea-" + Date.now().toString(36).slice(-6), svc: "rt-ea-dest" };
const AG = { api: "rt-agw-api", cfg: "rt-agw-cfg" };
const AG_SPEC = "swagger: \"2.0\"\ninfo:\n  title: rt\n  version: \"1\"\nx-google-backend:\n  address: https://example.com\npaths:\n  /ping:\n    get:\n      operationId: ping\n      responses:\n        \"200\":\n          description: ok\n";
const SVC = {
  vpc: { ui: ["networking/networks/list", "networking/networks/add"],
    create: (n) => ["POST", `/compute/v1/projects/${P}/global/networks`, { name: n, autoCreateSubnetworks: false }],
    get: (n) => `/compute/v1/projects/${P}/global/networks/${n}`, del: (n) => `/compute/v1/projects/${P}/global/networks/${n}` },
  // On a Mesh appliance VMs are admitted against a real memory budget (ZONE_RESOURCE_POOL_EXHAUSTED), so the UI create picks the smallest shape.
  compute: { serial: true, pre: async (pg) => { const cb = pg.locator("[role=combobox]", { hasText: /e2-medium/ }).first(); if (await cb.count()) { await cb.click(); await pg.locator("[role=option]", { hasText: /^e2-micro/ }).first().click(); } },
    fills: [["/^instance-\\d/.test(e.value)", "$N"]], ui: ["compute/instances", "compute/instances/create"],
    create: (n) => ["POST", `/compute/v1/projects/${P}/zones/${Z}/instances`, { name: n, machineType: `zones/${Z}/machineTypes/e2-micro`,
      disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }],
      networkInterfaces: [{ network: `projects/${P}/global/networks/default` }] }],
    get: (n) => `/compute/v1/projects/${P}/zones/${Z}/instances/${n}`, del: (n) => `/compute/v1/projects/${P}/zones/${Z}/instances/${n}` },
  // Eventarc triggers need a bucket and a Cloud Run service to point at; both are created natively once, below.
  eventarc: { pre: async (pg) => { await pg.getByRole("combobox", { name: "Bucket" }).click(); await pg.getByRole("option", { name: EA.bucket }).click();
      await pg.getByRole("combobox", { name: "Service" }).click(); await pg.getByRole("option", { name: EA.svc }).click(); },
    nfill: 1, ui: ["eventarc/triggers", "eventarc/triggers/new"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/triggers?triggerId=${n}`, { eventFilters: [{ attribute: "type", value: "google.cloud.storage.object.v1.finalized" }, { attribute: "bucket", value: EA.bucket }], destination: { cloudRun: { service: EA.svc, region: R } } }],
    get: (n) => `/v1/projects/${P}/locations/${R}/triggers/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/triggers/${n}` },
  // API Gateway: gateways need an API + config natively created once, below; the API list/create is its own service.
  apigateway: { nfill: 1, ui: ["apigateway/gateways", "apigateway/gateways/new"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/gateways?gatewayId=${n}`, { apiConfig: `projects/${P}/locations/global/apis/${AG.api}/configs/${AG.cfg}` }],
    get: (n) => `/v1/projects/${P}/locations/${R}/gateways/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/gateways/${n}` },
  "apigateway-apis": { nfill: 1, ui: ["apigateway/apis", "apigateway/apis/new"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/global/apis?apiId=${n}`, { displayName: n }],
    get: (n) => `/v1/projects/${P}/locations/global/apis/${n}`, del: (n) => `/v1/projects/${P}/locations/global/apis/${n}` },
  // API keys page (API Keys v2): the "create" is a dialog on the list page.
  "apigateway-keys": { fills: [["e.getAttribute('aria-label')==='Key ID (optional)'", "$N"]], delBtn: (n) => `button[aria-label="Delete key ${n}"]`, pre: async (pg) => { await pg.getByRole("button", { name: /^Create API key/ }).first().click(); await sleep(500); },
    ui: ["apigateway/keys", "apigateway/keys"],
    create: (n) => ["POST", `/v2/projects/${P}/locations/global/keys?keyId=${n}`, { displayName: n }],
    get: (n) => `/v2/projects/${P}/locations/global/keys/${n}`, del: (n) => `/v2/projects/${P}/locations/global/keys/${n}` },
  storage: { ui: ["storage/browser", "storage/create-bucket"],
    create: (n) => ["POST", `/storage/v1/b?project=${P}`, { name: n }],
    get: (n) => `/storage/v1/b/${n}`, del: (n) => `/storage/v1/b/${n}` },
  pubsub: { ui: ["pubsub/topics", "pubsub/topics/create"],
    create: (n) => ["PUT", `/v1/projects/${P}/topics/${n}`, {}],
    get: (n) => `/v1/projects/${P}/topics/${n}`, del: (n) => `/v1/projects/${P}/topics/${n}` },
  iam: { nfill: 2, ui: ["iam-admin/serviceaccounts", "iam-admin/serviceaccounts/create"],
    create: (n) => ["POST", `/v1/projects/${P}/serviceAccounts`, { accountId: n, serviceAccount: { displayName: n } }],
    get: (n) => `/v1/projects/${P}/serviceAccounts/${n}@${P}.iam.gserviceaccount.com`, del: (n) => `/v1/projects/${P}/serviceAccounts/${n}@${P}.iam.gserviceaccount.com` },
  firestore: { fills: [["e.value === \"(default)\"", "$N"]], ui: ["firestore/databases", "firestore/create-database"],
    create: (n) => ["POST", `/v1/projects/${P}/databases?databaseId=${n}`, { type: "FIRESTORE_NATIVE", locationId: R }],
    get: (n) => `/v1/projects/${P}/databases/${n}`, del: (n) => `/v1/projects/${P}/databases/${n}` },
  artifactregistry: { ui: ["artifacts", "artifacts/create-repo"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/repositories?repositoryId=${n}`, { format: "DOCKER" }],
    get: (n) => `/v1/projects/${P}/locations/${R}/repositories/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/repositories/${n}` },
  redis: { ui: ["memorystore", "memorystore/create"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/instances?instanceId=${n}`, { tier: "BASIC", memorySizeGb: 1 }],
    get: (n) => `/v1/projects/${P}/locations/${R}/instances/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/instances/${n}` },
  cloudsql: { fills: [["(e.placeholder||e.getAttribute('aria-label')||e.name)==='Instance ID'", "$N"], ["(e.placeholder||e.getAttribute('aria-label')||e.name)==='Password'", "Passw0rd-RT1x"]], ui: ["sql", "sql/create/instance"],
    create: (n) => ["POST", `/sql/v1beta4/projects/${P}/instances`, { name: n, region: R, databaseVersion: "POSTGRES_15", settings: { tier: "db-f1-micro" } }],
    get: (n) => `/sql/v1beta4/projects/${P}/instances/${n}`, del: (n) => `/sql/v1beta4/projects/${P}/instances/${n}` },
  run: { ui: ["run/services", "run/create"],
    create: (n) => ["POST", `/v2/projects/${P}/locations/${R}/services?serviceId=${n}`, { template: { containers: [{ image: "us-docker.pkg.dev/cloudrun/container/hello" }] } }],
    get: (n) => `/v2/projects/${P}/locations/${R}/services/${n}`, del: (n) => `/v2/projects/${P}/locations/${R}/services/${n}` },
  secretmanager: { ui: ["security/secret-manager", "security/secret-manager/create"],
    create: (n) => ["POST", `/v1/projects/${P}/secrets?secretId=${n}`, { replication: { automatic: {} } }],
    get: (n) => `/v1/projects/${P}/secrets/${n}`, del: (n) => `/v1/projects/${P}/secrets/${n}` },
  kms: { noDelete: true, ui: ["security/kms/keyrings", "security/kms/keyring/create"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/global/keyRings?keyRingId=${n}`, {}],
    get: (n) => `/v1/projects/${P}/locations/${R}/keyRings/${n}`, del: (n) => `/v1/projects/${P}/locations/global/keyRings/${n}` },
  kubernetes: { fills: [["/cluster-\\d/.test(e.value)", "$N"]], ui: ["kubernetes/clusters", "kubernetes/clusters/create"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/clusters`, { cluster: { name: n, initialNodeCount: 1 } }],
    get: (n) => `/v1/projects/${P}/locations/${R}/clusters/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/clusters/${n}` },
  monitoring: { walk: true, delBtn: (n) => `button[aria-label="Delete ${n}"]`, ui: ["monitoring/alerting", "monitoring/alerting/policies/create"],
    idOf: async (n) => { const l = await rest("GET", `/v3/projects/${P}/alertPolicies`); const h = ((l.body || {}).alertPolicies || []).find((x) => x.displayName === n); return h ? String(h.name).split("/").pop() : ""; },
    create: (n) => ["POST", `/v3/projects/${P}/alertPolicies`, { displayName: n, combiner: "OR", conditions: [{ displayName: "c", conditionThreshold: { filter: 'metric.type="compute.googleapis.com/instance/cpu/utilization"', comparison: "COMPARISON_GT", thresholdValue: 0.9, duration: "60s" } }] }],
    get: (id) => `/v3/projects/${P}/alertPolicies/${id}`, del: (id) => `/v3/projects/${P}/alertPolicies/${id}` },
  cloudscheduler: { seq: ["$N", "rt job", "* * * * *", "https://example.com/handler"], ui: ["cloudscheduler/jobs", "cloudscheduler/jobs/new"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: `projects/${P}/locations/${R}/jobs/${n}`, schedule: "* * * * *", timeZone: "UTC", httpTarget: { uri: "https://example.com/", httpMethod: "GET" } }],
    get: (n) => `/v1/projects/${P}/locations/${R}/jobs/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/jobs/${n}` },
};
const SKIP = {
  "functions:*": "the v4 'functions' console IS Cloud Run (see run), not the Cloud Functions API",
};
const ONLY = (process.env.ONLY || [...Object.keys(SVC), "functions"].join(",")).split(",");

const browser = await chromium.launch();
if (NANO) { NH = await nanoStart(browser, P); UI = NH.base + "/v4/gcp/index.html"; BASE = NH.base; }
const ctx = NH ? NH.ctx : await browser.newContext({ viewport: { width: 1500, height: 1100 } });
await ctx.addInitScript((p) => { try { localStorage.setItem("vyomi.v4.gcp.project", p); } catch (_) {} }, P);
const page = await ctx.newPage();
if (process.env.TRACE) page.on("response", (r) => { if (r.request().method() !== "GET" || r.status() >= 400) console.log("  [net]", r.request().method(), r.status(), r.url().replace(/^https?:\/\/[^/]+/, "").slice(0, 150)); });
page.on("dialog", (d) => d.accept("delete").catch(() => {}));
const results = [], skipped = [];
const check = (svc, step, ok, extra = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${svc}: ${step}${ok ? "" : " :: " + String(extra).slice(0, 220)}`);
  results.push({ service: svc, step, ok, detail: ok ? "" : String(extra).slice(0, 300) });
};
const vis = (sel, re) => page.locator(sel, { hasText: re }).filter({ visible: true });
const go = async (route) => { await page.goto(`${UI}#/${route}`); await page.reload(); await sleep(2500); };
const body = () => page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
// Poll: an in-browser (Nano) engine can answer a beat after the list renders; an absent row is only reported after ~9s.
const listed = async (svc, name, poll = true) => { await go(SVC[svc].ui[0]); for (let i = 0; i < (poll ? 6 : 1); i++) { await sleep(i ? 1500 : 700); if ((await body()).includes(name)) return true; } return false; };
const INP = "input:visible:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=number]):not([placeholder*=earch]), textarea:visible";

async function walkPolicy(name) {   // Monitoring alert policy: condition step -> notifications -> name -> Create Policy
  for (let i = 0; i < 8; i++) {
    for (const [lab, val] of [["Condition name", "rt condition"], ["Alert policy name", name]]) {
      const f = page.locator(`input[placeholder="${lab}"]:visible, input[aria-label="${lab}"]:visible`).first();
      if (await f.count()) await f.fill(val);
    }
    const fin = vis("button", /^\s*Create Policy/i);
    if (await fin.count()) { await fin.first().click({ timeout: 8000 }); await sleep(3000); return; }
    await vis("button", /^\s*Continue/i).first().click({ timeout: 8000 }); await sleep(900);
  }
  throw new Error("policy stepper never reached Create Policy");
}
async function uiCreate(svc, name) {
  await go(SVC[svc].ui[1]);
  if (SVC[svc].walk) return walkPolicy(name);
  const s = SVC[svc];
  if (s.pre) await s.pre(page);
  for (const [pred, val] of s.fills || []) {
    const h = await page.evaluateHandle((src) => [...document.querySelectorAll("input,textarea")].find((e) => new Function("e", "return " + src)(e)) || null, pred);
    const el = h.asElement(); if (el) await el.fill(val.replace("$N", name));
  }
  const seq = (s.seq || []).map((v) => v.replace("$N", name));
  let left = s.fills ? 0 : (s.seq ? seq.length : (s.nfill || 1)), k = 0; const els = page.locator(INP);
  for (let i = 0; i < await els.count() && left > 0; i++) { const e = els.nth(i); const v = await e.inputValue().catch(() => "x"); if (!v) { await e.fill(s.seq ? seq[k++] : name).catch(() => {}); left--; } }
  for (let i = 0; i < 8; i++) { const nx = vis("button", /^\s*next\b/i); if (await nx.count() === 0) break; await nx.last().click(); await sleep(500); }
  await vis("button", /^\s*(create|add|launch|store|save|finish|done)\b/i).last().click({ timeout: 8000 }); await sleep(3000);
}
const DEL = /^\s*(permanently )?(delete|terminate|remove)/i;
async function confirmDelete(name) {
  const dlg = page.locator("[role=dialog]:visible, .MuiDialog-root:visible").last();
  if (await dlg.count()) {   // a confirm modal: type the name when it asks, then press its Delete
    const word = ((await dlg.innerText().catch(() => "")).match(/type\s+["\u201c]?([A-Za-z0-9_-]+)["\u201d]?/i) || [])[1] || name;
    const ins = dlg.locator("input:visible:not([type=radio]):not([type=checkbox])");
    for (let i = 0; i < await ins.count(); i++) { const e = ins.nth(i); if (!(await e.inputValue().catch(() => "x"))) { await e.fill(word).catch(() => {}); break; } }
    await dlg.locator("button", { hasText: DEL }).last().click({ timeout: 8000 });
  }
  await sleep(3000);
}
async function uiDelete(svc, name) {
  await go(SVC[svc].ui[0]);
  const row = page.locator("tr", { hasText: name }).first();
  if (SVC[svc].delBtn) { await page.locator(SVC[svc].delBtn(name)).first().click({ timeout: 8000 }); await sleep(800); await confirmDelete(name); return; }
  const sel = row.locator("input[type=checkbox], input[type=radio]");
  if (await sel.count()) await sel.first().check({ force: true, timeout: 8000 });
  else { await row.locator("a").first().click({ timeout: 8000 }); await sleep(2500); }
  const direct = vis("button, a", DEL);
  if (await direct.count()) await direct.first().click({ timeout: 8000 });
  else { await vis("button", /^\s*(more )?actions\b/i).first().click({ timeout: 8000 }); await sleep(400); await vis("[role=menuitem], li, a, span", DEL).first().click({ timeout: 8000 }); }
  await sleep(1000);
  await confirmDelete(name);
  await sleep(3000);
}

if (ONLY.includes("apigateway") || ONLY.includes("apigateway-apis")) {
  await rest("POST", `/v1/projects/${P}/locations/global/apis?apiId=${AG.api}`, { displayName: "rt api" });
  await rest("POST", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs?apiConfigId=${AG.cfg}`, { openapiDocuments: [{ document: { path: "o.yaml", contents: Buffer.from(AG_SPEC).toString("base64") } }] });
}
if (ONLY.includes("apigateway-keys")) {   // keyString reveal in the UI = the native keyString; delete through the UI refuses the key at the gateway
  const kid = "rtk" + Date.now().toString(36).slice(-5);
  try {
    await rest("POST", `/v2/projects/${P}/locations/global/keys?keyId=${kid}`, { displayName: "rt key" });
    await go("apigateway/keys");
    await page.locator(`button[aria-label="Show key string of ${kid}"]`).click({ timeout: 8000 }); await sleep(800);
    const ui = await page.locator(`[data-testid="keystring-${kid}"]`).innerText();
    const nat = await rest("GET", `/v2/projects/${P}/locations/global/keys/${kid}/keyString`);
    check("apigateway-keys", "UI 'Show key' displays the native keyString", !!ui && ui === nat.body?.keyString, `ui=${ui} native=${JSON.stringify(nat.body)}`);
    await page.locator(`button[aria-label="Delete key ${kid}"]`).click({ timeout: 8000 }); await sleep(600); await confirmDelete(kid);
    const g = await rest("GET", `/v2/projects/${P}/locations/global/keys/${kid}`);
    check("apigateway-keys", "UI delete key -> native 404", g.status === 404, `${g.status}`);
  } catch (e) { check("apigateway-keys", "keyString reveal / delete", false, String(e).split("\n")[0]); }
}
if (ONLY.includes("eventarc")) {
  await rest("POST", `/storage/v1/b?project=${P}`, { name: EA.bucket });
  await rest("POST", `/v2/projects/${P}/locations/${R}/services?serviceId=${EA.svc}`, { template: { containers: [{ image: "us-docker.pkg.dev/cloudrun/container/hello" }] } });
}
if (ONLY.includes("iam")) {   // the real console derives the Service account ID live from the name until the ID is edited
  try {
    await go("iam-admin/serviceaccounts/create");
    await page.getByLabel("Service account name").first().fill("Round Trip Svc");
    const v1 = await page.getByLabel("Service account ID").first().inputValue();
    await page.getByLabel("Service account ID").first().fill("my-own-id-1");
    await page.getByLabel("Service account name").first().fill("Another Name");
    const v2 = await page.getByLabel("Service account ID").first().inputValue();
    check("iam", "Service account ID is derived from the name, until edited", v1 === "round-trip-svc" && v2 === "my-own-id-1", `derived="${v1}" after-manual-edit="${v2}"`);
  } catch (e) { check("iam", "Service account ID is derived from the name, until edited", false, String(e).split("\n")[0]); }
}
for (const svc of ONLY) {
  if (!SVC[svc]) { const why = SKIP[`${svc}:*`] || "not covered"; skipped.push(svc); console.log(`[SKIP] ${svc} :: ${why}`); results.push({ service: svc, step: "skip", ok: null, detail: why }); continue; }
  const s = SVC[svc], a = "rta" + Date.now().toString(36).slice(-5), b = "rtb" + Date.now().toString(36).slice(-5); let aOk = false;
  try { await uiCreate(svc, a); let g = await nget(s, a); for (let i = 0; i < 6 && g.status !== 200; i++) { await sleep(1500); g = await nget(s, a); } aOk = g.status === 200; check(svc, "A UI create -> native GET sees it", aOk, `${g.status} ${JSON.stringify(g.body)}`); }
  catch (e) { check(svc, "A UI create -> native GET sees it", false, String(e).split("\n")[0]); }
  const stepD = async () => {
  if (!aOk) { check(svc, "D UI delete -> native 404", false, "not run: A failed"); return; }
  if (s.noUiDelete) { console.log(`[SKIP] ${svc}: D UI delete -> native 404 :: ${s.noUiDelete}`); skipped.push(svc + ":D"); try { await ndel(s, a); } catch (_) {} return; }
  try { await uiDelete(svc, a); const g = await nget(s, a); check(svc, "D UI delete -> native 404", g.status === 404, `${g.status}`); }
  catch (e) { check(svc, "D UI delete -> native 404", false, process.env.DEBUG ? String(e).slice(0, 900) : String(e).split("\n")[0]); }
  try { await ndel(s, a); } catch (_) {}
  };
  // `serial`: the appliance admits one VM at a time (Mesh memory budget), so UI-delete A before native-creating B.
  if (s.serial) await stepD();
  try { const [m, u, bd] = s.create(b); const c = await rest(m, u, bd); if (c.status >= 300) throw new Error(`native create ${c.status} ${JSON.stringify(c.body)}`); check(svc, "B native create -> UI lists it", await listed(svc, b), "native created, UI list lacks it"); }
  catch (e) { check(svc, "B native create -> UI lists it", false, String(e).split("\n")[0]); }
  if (s.noDelete) { console.log(`[SKIP] ${svc}: C/D delete both ways :: the real cloud has no delete for this resource`); continue; }
  try { const d = await ndel(s, b); if (d.status >= 300) throw new Error(`native delete ${d.status} ${JSON.stringify(d.body)}`); check(svc, "C native delete -> UI drops it", !(await listed(svc, b, false)), "UI still lists it"); }
  catch (e) { check(svc, "C native delete -> UI drops it", false, String(e).split("\n")[0]); }
  if (!s.serial) await stepD();
}
if (ONLY.includes("apigateway-apis")) {   // gateway detail: invoke URLs, config policy, and the Try-it panel through the real gateway data plane
  const gid = "rtt" + Date.now().toString(36).slice(-5), cid = "rtp" + Date.now().toString(36).slice(-5), kid = "rtq" + Date.now().toString(36).slice(-5);
  const spec = `swagger: "2.0"
info:
  title: rt-try
  version: "1"
securityDefinitions:
  api_key:
    type: apiKey
    name: key
    in: query
x-google-management:
  metrics:
    - name: reads
      displayName: Reads
      valueType: INT64
      metricKind: DELTA
  quota:
    limits:
      - name: reads-per-min
        metric: reads
        unit: 1/min/{project}
        values:
          STANDARD: 2
x-google-backend:
  address: https://backend.rt.test
paths:
  /open:
    get:
      operationId: open
      responses:
        "200":
          description: ok
  /secure:
    get:
      operationId: secure
      security:
        - api_key: []
      x-google-quota:
        metricCosts:
          reads: 1
      responses:
        "200":
          description: ok
`;
  const tryIt = async (route, key) => {
    await page.getByRole("combobox", { name: "Route" }).click(); await page.getByRole("option", { name: new RegExp(route.replace("/", "\\/")) }).click();
    await page.getByRole("textbox", { name: "API key", exact: true }).fill(key || "");
    await page.getByRole("button", { name: /^Send request/ }).click();
    await page.locator('[data-testid="tryit-status"]').waitFor({ timeout: 10000 });
    return { status: await page.locator('[data-testid="tryit-status"]').innerText(), body: await page.locator('[data-testid="tryit-body"]').innerText() };
  };
  try {
    const cc = await rest("POST", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs?apiConfigId=${cid}`, { openapiDocuments: [{ document: { path: "o.yaml", contents: Buffer.from(spec).toString("base64") } }] });
    if (cc.status >= 300) throw new Error(`config create ${cc.status} ${JSON.stringify(cc.body)}`);
    await rest("POST", `/v2/projects/${P}/locations/global/keys?keyId=${kid}`, {});
    const keyString = (await rest("GET", `/v2/projects/${P}/locations/global/keys/${kid}/keyString`)).body?.keyString;
    await rest("POST", `/v1/projects/${P}/locations/${R}/gateways?gatewayId=${gid}`, { apiConfig: `projects/${P}/locations/global/apis/${AG.api}/configs/${cid}` });
    await go(`apigateway/gateways/${R}/${gid}`);
    const t = await body();
    const val = (lab) => page.locator(`input[aria-label^="${lab}"]`).first().inputValue();
    const hostU = await val("Host-style"), pathU = await val("Path-style"), curl = await val("curl");
    check("apigateway", "gateway detail shows host-style and path-style invoke URLs and a curl", hostU.includes(".gateway.dev") && pathU.endsWith(`/gcpgw/${gid}`) && curl.startsWith("curl ") && curl.includes(`/gcpgw/${gid}`), `${hostU} | ${pathU} | ${curl}`);
    check("apigateway", "gateway detail shows the config's security scheme and quota limit parsed from the document", t.includes("api_key") && t.includes("API key in query") && t.includes("reads-per-min") && t.includes("STANDARD: 2"), t.slice(0, 300));
    const open = await tryIt("/open");
    const nopen = NH ? await NH.wire(`/gcpgw/${gid}/open`) : await fetch(`${WIRE}/gcpgw/${gid}/open`);
    check("apigateway", "Try-it on an open route shows the gateway's real answer (same status as the native call)", open.status === `HTTP ${nopen.status}`, `${open.status} native=${nopen.status}`);
    if (!SIM && !process.env.BASE && !NANO) {
      check("apigateway", "Try-it reaches the local backend through the gateway (200 + backend body)", open.status === "HTTP 200" && open.body.includes('"hit"') && open.body.includes("/open"), `${open.status} ${open.body.slice(0, 120)}`);
    } else console.log("[SKIP] apigateway: Try-it backend reach :: needs the spawned dev server (loopback backend override)");
    const noKey = await tryIt("/secure", "");
    check("apigateway", "Try-it without a key on a keyed route -> 401", noKey.status === "HTTP 401", `${noKey.status} ${noKey.body.slice(0, 120)}`);
    const badKey = await tryIt("/secure", "AIzaNotARealKey");
    check("apigateway", "Try-it with a wrong key -> 400 API key not valid", badKey.status === "HTTP 400" && /API key not valid/.test(badKey.body), `${badKey.status} ${badKey.body.slice(0, 120)}`);
    const good1 = await tryIt("/secure", keyString), good2 = await tryIt("/secure", keyString), over = await tryIt("/secure", keyString);
    check("apigateway", "Try-it with the key created through the API Keys API passes, then quota (2/min) -> 429", good1.status !== "HTTP 401" && good1.status !== "HTTP 400" && good2.status !== "HTTP 429" && over.status === "HTTP 429",
      `${good1.status} ${good2.status} ${over.status}`);
    const nat = NH ? await NH.wire(`/gcpgw/${gid}/secure?key=${keyString}`) : await fetch(`${WIRE}/gcpgw/${gid}/secure?key=${keyString}`);
    check("apigateway", "native call via /gcpgw/ is over quota too (shared counter)", nat.status === 429, `${nat.status}`);
  } catch (e) { check("apigateway", "gateway invoke URLs / policy / Try-it", false, String(e).split("\n")[0]); }
  await rest("DELETE", `/v1/projects/${P}/locations/${R}/gateways/${gid}`); await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs/${cid}`);
  await rest("DELETE", `/v2/projects/${P}/locations/global/keys/${kid}`);
}
if (ONLY.includes("apigateway-apis")) {   // API config create (OpenAPI 2.0) / routes / in-use refusal, through the console
  const gid = "rtg" + Date.now().toString(36).slice(-5), cid = "rtc" + Date.now().toString(36).slice(-5);
  try {
    await go(`apigateway/apis/${AG.api}`);
    await vis("button", /^\s*Create API config/i).first().click({ timeout: 8000 }); await sleep(700);
    const dlg = page.locator("[role=dialog]:visible").last();
    await dlg.locator('input[aria-label="Config ID"]').fill(cid);
    await dlg.locator("button", { hasText: /^\s*create\s*$/i }).last().click({ timeout: 8000 }); await sleep(2500);
    const g = await rest("GET", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs/${cid}`);
    check("apigateway", "UI create API config (OpenAPI 2.0 sample) -> native GET sees it, routes derived", g.status === 200 && (g.body?.routes || []).some((r) => r.path === "/hello"), JSON.stringify(g.body).slice(0, 200));
    await rest("POST", `/v1/projects/${P}/locations/${R}/gateways?gatewayId=${gid}`, { apiConfig: `projects/${P}/locations/global/apis/${AG.api}/configs/${cid}` });
    await go(`apigateway/gateways/${R}/${gid}`);
    const t = await body();
    check("apigateway", "gateway detail shows hostname, config and the routes the config defines", t.includes(".gateway.dev") && t.includes(cid) && t.includes("/hello"), t.slice(0, 220));
    const d = await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs/${cid}`);
    check("apigateway", "native delete of a config served by a gateway is refused (FAILED_PRECONDITION)", d.status === 400 && /in use by gateway/.test(JSON.stringify(d.body)), `${d.status} ${JSON.stringify(d.body).slice(0, 160)}`);
    await rest("DELETE", `/v1/projects/${P}/locations/${R}/gateways/${gid}`);
    const d2 = await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs/${cid}`);
    check("apigateway", "after the gateway is gone the config deletes", d2.status === 200, `${d2.status}`);
    const bad = await rest("POST", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs?apiConfigId=badcfg`, { openapiDocuments: [{ document: { contents: Buffer.from("swagger: '3.0'").toString("base64") } }] });
    check("apigateway", "invalid OpenAPI document -> 400 with a meaningful message", bad.status === 400 && /OpenAPI 2.0/.test(JSON.stringify(bad.body)), `${bad.status} ${JSON.stringify(bad.body).slice(0, 160)}`);
  } catch (e) { check("apigateway", "api config / gateway detail", false, String(e).split("\n")[0]); }
  await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${AG.api}/configs/${AG.cfg}`); await rest("DELETE", `/v1/projects/${P}/locations/global/apis/${AG.api}`);
}
if (ONLY.includes("eventarc")) {   // trigger detail page renders what the API holds, and a real storage event is delivered
  const n = "rtd" + Date.now().toString(36).slice(-5);
  try {
    const [m, u, bd] = SVC.eventarc.create(n); await rest(m, u, bd);
    await go(`eventarc/triggers/${R}/${n}`);
    const t = await body();
    check("eventarc", "detail page shows event type, bucket filter and destination", t.includes("storage.object.v1.finalized") && t.includes(EA.bucket) && t.includes(EA.svc), t.slice(0, 200));
    if (NH) await NH.wire(`/upload/storage/v1/b/${EA.bucket}/o?uploadType=media&name=hello.txt`, { method: "POST", headers: { "content-type": "text/plain" }, body: "hi" });
    else await fetch(`${WIRE}/upload/storage/v1/b/${EA.bucket}/o?uploadType=media&name=hello.txt`, { method: "POST", headers: { "content-type": "text/plain" }, body: "hi" });
    await sleep(1500);
    const dl = await rest("GET", `/v1/projects/${P}/locations/${R}/triggers/${n}/deliveries`);
    check("eventarc", "object upload fires the trigger (delivery recorded natively)", ((dl.body?.delivered || 0) + (dl.body?.failed || 0)) >= 1 || (dl.body?.deliveries || []).length >= 1, JSON.stringify(dl.body).slice(0, 200));
    await go(`eventarc/triggers/${R}/${n}`);
    check("eventarc", "UI detail lists the delivery", /Deliveries \((\d+) delivered, (\d+) retrying, (\d+) dead-lettered, (\d+) failed\)/.test(await body()) && !/Deliveries \(0 delivered, 0 retrying, 0 dead-lettered, 0 failed\)/.test(await body()), (await body()).slice(-300));
    await ndel(SVC.eventarc, n);
  } catch (e) { check("eventarc", "trigger detail / delivery", false, String(e).split("\n")[0]); }
}
await browser.close(); BACKEND.srv.close(); if (dev) dev.kill(); if (NH) NH.server.close();
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ cloud: "gcp", console: "v4", base: BASE, project: P, results }, null, 1));
const done = results.filter((r) => r.ok !== null), pass = done.filter((r) => r.ok).length;
console.log(`RESULT ${pass} passed, ${done.length - pass} failed, ${skipped.length} skipped (not driven)`);
process.exit(done.length && pass === done.length ? 0 : 1);
