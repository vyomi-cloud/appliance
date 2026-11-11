/* GCP v4 console (consoles/src/gcp -> /v4/gcp/) UI <-> native REST bi-directional round-trip.
 * UI = the v4 console in Playwright; "SDK/CLI/API" = the real Google REST surface on the SAME wire (/_wire).
 *   A UI create -> native GET sees it   B native create -> UI lists it   C native delete -> UI drops it   D UI delete -> native 404
 * Env: BASE (default http://127.0.0.1:9310 = `python3 consoles/dev_server.py --port 9310`, or an appliance), UI_PATH (/v4/gcp/index.html),
 *      WIRE_PATH (/_wire), PROJECT (nano-project), ONLY=vpc,storage,..., OUT (json report).
 * Honest SKIPs are printed with their reason and never counted as PASS. */
import { chromium, sleep } from "../../../wasm/ui-tests/lib.mjs";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import net from "node:net";

const HERE = dirname(fileURLToPath(import.meta.url));
// BASE unset -> start `consoles/dev_server.py` (the same router the appliance and Nano use) on a free port for this run.
let dev = null;
const freePort = () => new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
let BASE = process.env.BASE || "";
if (!BASE) {
  const port = await freePort();
  dev = spawn(process.env.PY || "python3", [resolve(HERE, "../../../consoles/dev_server.py"), "--port", String(port)], { stdio: "ignore", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/v4/gcp/")).ok) break; } catch (_) {} await new Promise((r) => setTimeout(r, 500)); }
}
const UI = BASE + (process.env.UI_PATH || "/v4/gcp/index.html");
const WIRE = BASE + (process.env.WIRE_PATH || "/_wire");
const P = process.env.PROJECT || "nano-project";
const R = "us-central1", Z = "us-central1-a";
const OUT = process.env.OUT || resolve(HERE, "../hourly/out/gcp-v4-roundtrip.json");

const rest = async (method, path, body) => {
  const r = await fetch(WIRE + path, { method, headers: { "content-type": "application/json" }, body: body === undefined || method === "GET" || method === "DELETE" ? undefined : JSON.stringify(body) });
  let j = null; try { j = await r.json(); } catch (_) {}
  return { status: r.status, body: j };
};

// Each service: ui = [list route, create route|null]; create(n) -> [method, path, body]; get(n) -> path; del(n) -> path.
const SVC = {
  vpc: { ui: ["networking/networks/list", "networking/networks/add"],
    create: (n) => ["POST", `/compute/v1/projects/${P}/global/networks`, { name: n, autoCreateSubnetworks: false }],
    get: (n) => `/compute/v1/projects/${P}/global/networks/${n}`, del: (n) => `/compute/v1/projects/${P}/global/networks/${n}` },
  compute: { fills: [["/^instance-\\d/.test(e.value)", "$N"]], ui: ["compute/instances", "compute/instances/create"],
    create: (n) => ["POST", `/compute/v1/projects/${P}/zones/${Z}/instances`, { name: n, machineType: `zones/${Z}/machineTypes/e2-micro`,
      disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }],
      networkInterfaces: [{ network: `projects/${P}/global/networks/default` }] }],
    get: (n) => `/compute/v1/projects/${P}/zones/${Z}/instances/${n}`, del: (n) => `/compute/v1/projects/${P}/zones/${Z}/instances/${n}` },
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
  cloudscheduler: { seq: ["$N", "rt job", "* * * * *", "https://example.com/handler"], ui: ["cloudscheduler/jobs", "cloudscheduler/jobs/new"],
    create: (n) => ["POST", `/v1/projects/${P}/locations/${R}/jobs`, { name: `projects/${P}/locations/${R}/jobs/${n}`, schedule: "* * * * *", timeZone: "UTC", httpTarget: { uri: "https://example.com/", httpMethod: "GET" } }],
    get: (n) => `/v1/projects/${P}/locations/${R}/jobs/${n}`, del: (n) => `/v1/projects/${P}/locations/${R}/jobs/${n}` },
};
const SKIP = {
  "kubernetes:*": "GKE is tier-gated (Pro/Max); the dev stack has no k3s",
  "monitoring:*": "alert policies are addressed by server-assigned ids; the v4 create form is multi-step (not automated yet)",
  "functions:*": "the v4 'functions' console IS Cloud Run (see run), not the Cloud Functions API",
  "eventarc:*": "no v4 Eventarc console service exists",
  "apigateway:*": "no v4 API Gateway console service exists",
};
const ONLY = (process.env.ONLY || [...Object.keys(SVC), "kubernetes", "monitoring", "functions", "eventarc", "apigateway"].join(",")).split(",");

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
page.on("dialog", (d) => d.accept("delete").catch(() => {}));
const results = [], skipped = [];
const check = (svc, step, ok, extra = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${svc}: ${step}${ok ? "" : " :: " + String(extra).slice(0, 220)}`);
  results.push({ service: svc, step, ok, detail: ok ? "" : String(extra).slice(0, 300) });
};
const vis = (sel, re) => page.locator(sel, { hasText: re }).filter({ visible: true });
const go = async (route) => { await page.goto(`${UI}#/${route}`); await page.reload(); await sleep(2500); };
const body = () => page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
const listed = async (svc, name) => { await go(SVC[svc].ui[0]); await sleep(700); return (await body()).includes(name); };
const INP = "input:visible:not([type=radio]):not([type=checkbox]):not([type=file]):not([type=number]):not([placeholder*=earch]), textarea:visible";

async function uiCreate(svc, name) {
  await go(SVC[svc].ui[1]);
  const s = SVC[svc];
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
async function uiDelete(svc, name) {
  await go(SVC[svc].ui[0]);
  const row = page.locator("tr", { hasText: name }).first();
  const sel = row.locator("input[type=checkbox], input[type=radio]");
  if (await sel.count()) await sel.first().check({ force: true, timeout: 8000 });
  else { await row.locator("a").first().click({ timeout: 8000 }); await sleep(2500); }
  const DEL = /^\s*(permanently )?(delete|terminate|remove)/i;
  const direct = vis("button, a", DEL);
  if (await direct.count()) await direct.first().click({ timeout: 8000 });
  else { await vis("button", /^\s*(more )?actions\b/i).first().click({ timeout: 8000 }); await sleep(400); await vis("[role=menuitem], li, a, span", DEL).first().click({ timeout: 8000 }); }
  await sleep(1000);
  const dlg = page.locator("[role=dialog]:visible, .MuiDialog-root:visible").last();
  if (await dlg.count()) {   // a confirm modal: type the name when it asks, then press its Delete
    const word = ((await dlg.innerText().catch(() => "")).match(/type\s+["\u201c]?([A-Za-z0-9_-]+)["\u201d]?/i) || [])[1] || name;
    const ins = dlg.locator("input:visible:not([type=radio]):not([type=checkbox])");
    for (let i = 0; i < await ins.count(); i++) { const e = ins.nth(i); if (!(await e.inputValue().catch(() => "x"))) { await e.fill(word).catch(() => {}); break; } }
    await dlg.locator("button", { hasText: DEL }).last().click({ timeout: 8000 });
  }
  await sleep(3000);
}

for (const svc of ONLY) {
  if (!SVC[svc]) { const why = SKIP[`${svc}:*`] || "not covered"; skipped.push(svc); console.log(`[SKIP] ${svc} :: ${why}`); results.push({ service: svc, step: "skip", ok: null, detail: why }); continue; }
  const s = SVC[svc], a = "rta" + Date.now().toString(36).slice(-5), b = "rtb" + Date.now().toString(36).slice(-5); let aOk = false;
  try { await uiCreate(svc, a); const g = await rest("GET", s.get(a)); aOk = g.status === 200; check(svc, "A UI create -> native GET sees it", aOk, `${g.status} ${JSON.stringify(g.body)}`); }
  catch (e) { check(svc, "A UI create -> native GET sees it", false, String(e).split("\n")[0]); }
  try { const [m, u, bd] = s.create(b); const c = await rest(m, u, bd); if (c.status >= 300) throw new Error(`native create ${c.status} ${JSON.stringify(c.body)}`); check(svc, "B native create -> UI lists it", await listed(svc, b), "native created, UI list lacks it"); }
  catch (e) { check(svc, "B native create -> UI lists it", false, String(e).split("\n")[0]); }
  if (s.noDelete) { console.log(`[SKIP] ${svc}: C/D delete both ways :: the real cloud has no delete for this resource`); continue; }
  try { const d = await rest("DELETE", s.del(b)); if (d.status >= 300) throw new Error(`native delete ${d.status} ${JSON.stringify(d.body)}`); check(svc, "C native delete -> UI drops it", !(await listed(svc, b)), "UI still lists it"); }
  catch (e) { check(svc, "C native delete -> UI drops it", false, String(e).split("\n")[0]); }
  if (!aOk) { check(svc, "D UI delete -> native 404", false, "not run: A failed"); continue; }
  try { await uiDelete(svc, a); const g = await rest("GET", s.get(a)); check(svc, "D UI delete -> native 404", g.status === 404, `${g.status}`); }
  catch (e) { check(svc, "D UI delete -> native 404", false, process.env.DEBUG ? String(e).slice(0, 900) : String(e).split("\n")[0]); }
  try { await rest("DELETE", s.del(a)); } catch (_) {}
}
await browser.close(); if (dev) dev.kill();
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ cloud: "gcp", console: "v4", base: BASE, project: P, results }, null, 1));
const done = results.filter((r) => r.ok !== null), pass = done.filter((r) => r.ok).length;
console.log(`RESULT ${pass} passed, ${done.length - pass} failed, ${skipped.length} skipped (not driven)`);
process.exit(done.length && pass === done.length ? 0 : 1);
