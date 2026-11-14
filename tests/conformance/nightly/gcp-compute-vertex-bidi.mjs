/* GCP Compute (deep) + Vertex AI end-to-end bi-directional checks: the real v4 console (consoles/src/gcp) in Playwright <-> the native Google REST surface
 * the SDKs / gcloud / curl use. Against a real appliance (a Mesh Codespace through `vyomi-tunnel forward`) when SIM_URL is set, else a local dev_server.
 *
 *   SIM_URL=http://127.0.0.1:19000 node tests/conformance/nightly/gcp-compute-vertex-bidi.mjs      (ONLY=compute,vertex  PROJECT=vyomi-project  OUT=...)
 *
 * Compute : instance lifecycle both ways (native stop -> UI Stopped, UI Start -> native RUNNING, ...), instance detail fields, disks (UI+native create/delete),
 *           snapshots / instance templates / health checks / machine images (native -> UI list, native delete -> UI drops).
 * Vertex  : per collection  A UI create -> native list  B native create -> UI list  C native delete -> UI drops  D UI delete -> native gone;
 *           plus a job's state and a deployed model seen identically on both sides, and a Studio generate vs native generateContent.
 * Anything the driver cannot do is printed as [SKIP] with the reason and never counted as a pass. */
import { chromium, sleep } from "../../../wasm/ui-tests/lib.mjs";
import { nanoStart } from "./lib/nano-gcp.mjs";
const NANO = !!process.env.NANO;   // NANO=1: genuine Nano (in-browser engines, wasm/ bundle) instead of dev_server
let NH = null;
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import net from "node:net";
import http from "node:http";

const HERE = dirname(fileURLToPath(import.meta.url));
const SIM = (process.env.SIM_URL || "").replace(/\/$/, "");
const P = process.env.PROJECT || (SIM ? "vyomi-project" : "nano-project");
const L = "us-central1", Z = "us-central1-a";
const OUT = process.env.OUT || resolve(HERE, "../hourly/out/gcp-compute-vertex-bidi.json");
const ONLY = (process.env.ONLY || "compute,vertex").split(",");
const freePort = () => new Promise((res) => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });

let dev = null, BASE = process.env.BASE || "";
if (!BASE && !NANO) {
  const port = await freePort();
  dev = spawn(process.env.PY || "python3", [resolve(HERE, "../../../consoles/dev_server.py"), "--port", String(port), "--tier", "max", "--primary", "gcp"], { stdio: "ignore", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
  BASE = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/v4/gcp/")).ok) break; } catch (_) {} await sleep(500); }
}
if (SIM) {   // console bundle from BASE, but its /_wire calls go to the real appliance
  const origin = BASE;
  const proxy = http.createServer(async (rq, rs) => {
    const chunks = []; for await (const c of rq) chunks.push(c);
    const wire = rq.url.startsWith("/_wire/");
    try {
      const r = await fetch(wire ? SIM + rq.url.slice(6) : origin + rq.url, { method: rq.method, headers: { "content-type": rq.headers["content-type"] || "application/json" }, body: ["GET", "HEAD"].includes(rq.method) ? undefined : Buffer.concat(chunks) });
      const h = {}; r.headers.forEach((v, k) => { if (!["content-encoding", "content-length", "transfer-encoding", "connection"].includes(k)) h[k] = v; });
      rs.writeHead(r.status, h); rs.end(Buffer.from(await r.arrayBuffer()));
    } catch (e) { rs.writeHead(502); rs.end(String(e)); }
  });
  await new Promise((res) => proxy.listen(0, "127.0.0.1", res));
  BASE = `http://127.0.0.1:${proxy.address().port}`;
}
let UI = BASE + "/v4/gcp/index.html";
const WIRE = SIM || BASE + "/_wire";

const rest = async (method, path, body) => {
  if (NH) return NH.rest(method, path, body);
  const r = await fetch(WIRE + path, { method, headers: { "content-type": "application/json" }, body: body === undefined || method === "GET" || method === "DELETE" ? undefined : JSON.stringify(body) });
  let j = null; try { j = await r.json(); } catch (_) {}
  return { status: r.status, body: j };
};
const tag = () => Date.now().toString(36).slice(-5);

const browser = await chromium.launch();
if (NANO) { NH = await nanoStart(browser, P); UI = NH.base + "/v4/gcp/index.html"; BASE = NH.base; }
const ctx = NH ? NH.ctx : await browser.newContext({ viewport: { width: 1500, height: 1100 } });
await ctx.addInitScript((p) => { try { localStorage.setItem("vyomi.v4.gcp.project", p); } catch (_) {} }, P);
const page = await ctx.newPage();
const results = []; let skipped = 0;
const check = (grp, step, ok, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${grp}: ${step}${ok ? "" : " :: " + String(extra).slice(0, 260)}`); results.push({ service: grp, step, ok, detail: ok ? "" : String(extra).slice(0, 320) }); };
const skip = (grp, step, why) => { skipped++; console.log(`[SKIP] ${grp}: ${step} :: ${why}`); results.push({ service: grp, step, ok: null, detail: why }); };
const vis = (sel, re) => page.locator(sel, { hasText: re }).filter({ visible: true });
const go = async (route) => { await page.goto(`${UI}#/${route}`); await page.reload(); await sleep(2500); };
const body = () => page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
const until = async (fn, ms = 20000) => { const t = Date.now(); for (;;) { try { const v = await fn(); if (v) return v; } catch (_) {} if (Date.now() - t > ms) return false; await sleep(700); } };
const DEL = /^\s*(permanently )?(delete|terminate|remove)/i;
const row = (name) => page.locator("tr", { hasText: name }).first();

async function confirmDialog(name) {
  await sleep(800);
  const dlg = page.locator("[role=dialog]:visible, .MuiDialog-root:visible").last();
  if (!(await dlg.count())) return;
  const word = ((await dlg.innerText().catch(() => "")).match(/type\s+["“]?([A-Za-z0-9_-]+)["”]?/i) || [])[1] || name;
  const ins = dlg.locator("input:visible:not([type=radio]):not([type=checkbox])");
  for (let i = 0; i < await ins.count(); i++) { const e = ins.nth(i); if (!(await e.inputValue().catch(() => "x"))) { await e.fill(word).catch(() => {}); break; } }
  await dlg.locator("button", { hasText: DEL }).last().click({ timeout: 8000 });
  await sleep(2500);
}

/* ───────────────────────────── Compute ───────────────────────────── */
const ZP = `/compute/v1/projects/${P}/zones/${Z}`, GP = `/compute/v1/projects/${P}/global`;
const waitOp = async (r) => { if (r.body && r.body.name && r.body.status && r.body.status !== "DONE") await sleep(1500); return r; };
const inst = (n) => rest("GET", `${ZP}/instances/${n}`);
const statusIs = (n, st) => until(async () => (await inst(n)).body?.status === st, 30000);
const chipOf = async (n) => { await go("compute/instances"); await sleep(600); return (await row(n).innerText().catch(() => "")).replace(/\s+/g, " "); };
async function selectRow(n) { const sel = row(n).locator("input[type=checkbox], input[type=radio]"); await sel.first().check({ force: true, timeout: 8000 }); }

async function compute() {
  const G = "compute";
  const n = "bdi" + tag();
  const c = await rest("POST", `${ZP}/instances`, { name: n, machineType: `zones/${Z}/machineTypes/e2-micro`, labels: { team: "bidi", env: "test" },
    disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }], networkInterfaces: [{ network: `projects/${P}/global/networks/default` }] });
  if (c.status >= 300) { check(G, "native create instance (e2-micro)", false, `${c.status} ${JSON.stringify(c.body)}`); return; }
  check(G, "native create instance -> status RUNNING", await statusIs(n, "RUNNING"), JSON.stringify((await inst(n)).body?.status));
  await go("compute/instances");
  const t = await row(n).innerText().catch(() => "");
  check(G, "instance appears in UI list with zone + running state", /us-central1-a/.test(t) && /running/i.test(t), t.replace(/\s+/g, " "));

  // detail page fields (UI renders what the API returns)
  await go(`compute/instances/${Z}/${n}`);
  const d = await body();
  check(G, "UI detail shows machine type, zone and the labels set over the API", /e2-micro/.test(d) && /us-central1-a/.test(d) && /bidi/.test(d), d.slice(0, 200));

  // lifecycle: native stop -> UI Stopped
  await rest("POST", `${ZP}/instances/${n}/stop`); await waitOp({});
  check(G, "native stop -> API status TERMINATED", await statusIs(n, "TERMINATED"));
  const ch1 = await chipOf(n);
  check(G, "native stop -> UI shows Stopped", /stopped|terminated/i.test(ch1), ch1);

  // UI Start -> native RUNNING
  try { await selectRow(n); await vis("button", /^\s*Start/i).first().click({ timeout: 8000 }); await sleep(1200); await confirmDialog(n); check(G, "UI Start -> native status RUNNING", await statusIs(n, "RUNNING"), JSON.stringify((await inst(n)).body?.status)); }
  catch (e) { check(G, "UI Start -> native status RUNNING", false, String(e).split("\n")[0]); }

  // UI Stop -> native TERMINATED
  try { await go("compute/instances"); await selectRow(n); await vis("button", /^\s*Stop\b/i).first().click({ timeout: 8000 }); await sleep(1200); await confirmDialog(n); check(G, "UI Stop -> native status TERMINATED", await statusIs(n, "TERMINATED"), JSON.stringify((await inst(n)).body?.status)); }
  catch (e) { check(G, "UI Stop -> native status TERMINATED", false, String(e).split("\n")[0]); }

  // native start -> UI Running
  await rest("POST", `${ZP}/instances/${n}/start`); await statusIs(n, "RUNNING");
  const ch2 = await chipOf(n);
  check(G, "native start -> UI shows Running", /running/i.test(ch2), ch2);

  // label change over the API (setLabels) shows in the UI detail
  const cur = (await inst(n)).body;
  await rest("POST", `${ZP}/instances/${n}/setLabels`, { labels: { team: "bidi", env: "prod2" }, labelFingerprint: cur?.labelFingerprint });
  await go(`compute/instances/${Z}/${n}`);
  check(G, "native setLabels -> UI detail shows the new label value", /prod2/.test(await body()), (await body()).slice(0, 160));

  // native delete -> UI drops
  await rest("DELETE", `${ZP}/instances/${n}`);
  await until(async () => (await inst(n)).status === 404, 40000);
  await go("compute/instances");
  check(G, "native delete instance -> UI list drops it", !(await body()).includes(n), "still listed");

  // disks: UI create <-> native
  const da = "bdd" + tag(), db = "bde" + tag();
  try {
    await go("compute/disks/create");
    await page.getByLabel("Name", { exact: true }).first().fill(da);
    await vis("button", /^\s*create\b/i).last().click({ timeout: 8000 }); await sleep(3000);
    const g = await rest("GET", `${ZP}/disks/${da}`);
    check(G, "UI create disk -> native GET sees it", g.status === 200, `${g.status} ${JSON.stringify(g.body)}`);
  } catch (e) { check(G, "UI create disk -> native GET sees it", false, String(e).split("\n")[0]); }
  const cd = await rest("POST", `${ZP}/disks`, { name: db, sizeGb: "10", type: `zones/${Z}/diskTypes/pd-standard` });
  await go("compute/disks");
  check(G, "native create disk -> UI lists it", cd.status < 300 && (await body()).includes(db), `${cd.status}`);
  await rest("DELETE", `${ZP}/disks/${db}`); await sleep(1500);
  await go("compute/disks");
  check(G, "native delete disk -> UI drops it", !(await body()).includes(db), "still listed");
  try {
    await go("compute/disks"); await selectRow(da); await vis("button", /^\s*Delete\b/i).first().click({ timeout: 8000 }); await confirmDialog(da);
    check(G, "UI delete disk -> native 404", (await rest("GET", `${ZP}/disks/${da}`)).status === 404);
  } catch (e) { check(G, "UI delete disk -> native 404", false, String(e).split("\n")[0]); }
  await rest("DELETE", `${ZP}/disks/${da}`);

  // other compute collections: native create -> UI list, native delete -> UI drops
  const sd = "bds" + tag(); await rest("POST", `${ZP}/disks`, { name: sd, sizeGb: "10" });
  const OTHERS = [
    ["snapshot", "compute/snapshots", `${GP}/snapshots`, null, async () => rest("POST", `${ZP}/disks/${sd}/createSnapshot`, { name: "bdsn" + tag() }), true],
    ["instance template", "compute/instance-templates", `${GP}/instanceTemplates`, (nm) => ({ name: nm, properties: { machineType: "e2-micro", disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }], networkInterfaces: [{ network: `projects/${P}/global/networks/default` }] } })],
    ["health check", "compute/health-checks", `${GP}/healthChecks`, (nm) => ({ name: nm, type: "HTTP", httpHealthCheck: { port: 80, requestPath: "/" }, checkIntervalSec: 10, timeoutSec: 5 })],
  ];
  for (const [label, route, coll, mk, special, snap] of OTHERS) {
    const nm = "bdo" + tag() + label.slice(0, 2);
    let rname = nm;
    if (special) { const r = await special(); const t = r.body?.targetLink || ""; rname = t.split("/").pop() || nm; if (r.status >= 300) { check(G, `native create ${label} -> UI lists it`, false, `${r.status} ${JSON.stringify(r.body)}`); continue; } await sleep(2000); }
    else { const r = await rest("POST", coll, mk(nm)); if (r.status >= 300) { check(G, `native create ${label} -> UI lists it`, false, `${r.status} ${JSON.stringify(r.body)}`); continue; } await sleep(1500); }
    await go(route);
    check(G, `native create ${label} -> UI lists it`, (await body()).includes(rname), `UI list lacks ${rname}`);
    await rest("DELETE", `${coll}/${rname}`); await sleep(2000);
    await go(route);
    check(G, `native delete ${label} -> UI drops it`, !(await body()).includes(rname), "still listed");
  }
  await rest("DELETE", `${ZP}/disks/${sd}`);
}

/* ───────────────────────────── Vertex AI ───────────────────────────── */
const VP = `/v1/projects/${P}/locations/${L}`;
const vlist = async (coll, v2) => { const r = await rest("GET", v2 ? `/v2/projects/${P}/locations/${Z}/${coll}` : `${VP}/${coll}`); return Object.values(r.body || {}).find(Array.isArray) || []; };
const vfind = async (coll, n, v2) => { const x = (await vlist(coll, v2)).find((y) => y.displayName === n || String(y.name).split("/").pop() === n); return x ? { ...x, name: fix(x.name) } : x; };
// Resource names must carry the project the request used. A build that hands back another project id (`nano-project`) makes every follow-up
// call with that name a 403, so it is checked explicitly (once) and the name is mapped back so the rest of the matrix still runs.
let nameLeak = null;
const fix = (nm) => { const m = /^projects\/([^/]+)\//.exec(nm || ""); if (m && m[1] !== P) { nameLeak = nameLeak || `${nm} (request project is ${P})`; return nm.replace(/^projects\/[^/]+/, `projects/${P}`); } return nm; };
const IMG = "us-docker.pkg.dev/vertex-ai/training/scikit-learn-cpu.1-0:latest";
const jobPool = [{ machineSpec: { machineType: "n1-standard-4" }, replicaCount: "1", containerSpec: { imageUri: IMG } }];
// route, coll, UI create button, name-input label, native create(name)->[path, body], idKey collections use the id as the name, v2 = notebooks
const VX = [
  { k: "endpoints", route: "vertex-ai/endpoints", btn: /^create endpoint/i, label: "Name", create: (n) => [`${VP}/endpoints`, { displayName: n }] },
  { k: "datasets", route: "vertex-ai/datasets", btn: /^create dataset/i, label: "Name", create: (n) => [`${VP}/datasets`, { displayName: n, metadataSchemaUri: "gs://google-cloud-aiplatform/schema/dataset/metadata/image_1.0.0.yaml" }] },
  { k: "models", route: "vertex-ai/models", btn: /^import model/i, label: "Name", create: (n) => [`${VP}/models:upload`, { model: { displayName: n, artifactUri: "gs://my-bucket/model/", containerSpec: { imageUri: "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-0:latest" } } }] },
  { k: "trainingPipelines", route: "vertex-ai/training", btn: /^create training pipeline/i, label: "Name", create: (n) => [`${VP}/trainingPipelines`, { displayName: n, trainingTaskDefinition: "gs://google-cloud-aiplatform/schema/trainingjob/definition/custom_task_1.0.0.yaml", trainingTaskInputs: { workerPoolSpecs: jobPool }, modelToUpload: { displayName: n + "-model" } }] },
  { k: "customJobs", route: "vertex-ai/training?tab=custom", btn: /^create custom job/i, label: "Name", create: (n) => [`${VP}/customJobs`, { displayName: n, jobSpec: { workerPoolSpecs: jobPool } }] },
  { k: "pipelineJobs", route: "vertex-ai/pipelines", btn: /^create run/i, label: "Name", create: (n) => [`${VP}/pipelineJobs`, { displayName: n, templateUri: "gs://my-bucket/pipeline.json", runtimeConfig: { gcsOutputDirectory: "gs://my-bucket/p" } }] },
  { k: "indexes", route: "vertex-ai/vector-search", btn: /^create index$/i, label: "Name", create: (n) => [`${VP}/indexes`, { displayName: n, indexUpdateMethod: "STREAM_UPDATE", metadata: { config: { dimensions: 128, distanceMeasureType: "COSINE_DISTANCE", approximateNeighborsCount: 10, algorithmConfig: { treeAhConfig: {} } } } }] },
  { k: "notebookRuntimeTemplates", route: "vertex-ai/workbench?tab=templates", btn: /^create runtime template/i, label: "Name", create: (n) => [`${VP}/notebookRuntimeTemplates`, { displayName: n, machineSpec: { machineType: "e2-standard-4" } }] },
];
async function listedUI(route, n) { await go(route); return until(async () => (await body()).includes(n), 9000); }
async function uiCreateV(x, n) {
  await go(x.route);
  await vis("button", x.btn).first().click({ timeout: 8000 }); await sleep(800);
  const dlg = page.locator("[role=dialog]:visible").last();
  await dlg.locator(`input[aria-label="${x.label}"]`).first().fill(n);
  await dlg.locator("button", { hasText: /^\s*create\s*$/i }).last().click({ timeout: 8000 }); await sleep(2500);
}
async function uiDeleteV(x, n) {
  await go(x.route);
  await page.locator(`button[aria-label="Actions for ${n}"]`).first().click({ timeout: 8000 }); await sleep(400);
  await page.locator("[role=menuitem]", { hasText: /^Delete$/ }).first().click({ timeout: 8000 }); await confirmDialog(n);
}
async function vertex() {
  const G = "vertex";
  for (const x of VX) {
    const g = `${G}:${x.k}`, a = "bda" + tag(), b = "bdb" + tag();
    try { await uiCreateV(x, a); const f = await until(() => vfind(x.k, a), 8000); check(g, "A UI create -> native list sees it", !!f, "native list lacks it"); }
    catch (e) { check(g, "A UI create -> native list sees it", false, String(e).split("\n")[0]); }
    try { const [p, bd] = x.create(b); const r = await rest("POST", p, bd); if (r.status >= 300) throw new Error(`native create ${r.status} ${JSON.stringify(r.body)}`); await until(() => vfind(x.k, b), 8000); check(g, "B native create -> UI lists it", await listedUI(x.route, b), "UI list lacks it"); }
    catch (e) { check(g, "B native create -> UI lists it", false, String(e).split("\n")[0]); }
    try { const f = await vfind(x.k, b); if (!f) throw new Error("not created natively"); const r = await rest("DELETE", `/v1/${f.name}`); if (r.status >= 300) throw new Error(`native delete ${r.status} ${JSON.stringify(r.body)}`); await sleep(1500); check(g, "C native delete -> UI drops it", !(await listedUI(x.route, b)), "UI still lists it"); }
    catch (e) { check(g, "C native delete -> UI drops it", false, String(e).split("\n")[0]); }
    try { await uiDeleteV(x, a); const gone = await until(async () => !(await vfind(x.k, a)), 8000); check(g, "D UI delete -> native gone", gone, "native list still has it"); }
    catch (e) { check(g, "D UI delete -> native gone", false, String(e).split("\n")[0]); }
    const left = await vfind(x.k, a); if (left) await rest("DELETE", `/v1/${left.name}`);
  }

  // Workbench instance (notebooks v2, zonal, id-named)
  {
    const g = `${G}:workbench-instances`, a = "bda" + tag(), b = "bdb" + tag(), mk = (n) => [`/v2/projects/${P}/locations/${Z}/instances?instanceId=${n}`, { gceSetup: { machineType: "e2-standard-4" } }];
    try { await go("vertex-ai/workbench"); await vis("button", /^create notebook instance/i).first().click({ timeout: 8000 }); await sleep(800);
      const dlg = page.locator("[role=dialog]:visible").last(); await dlg.locator('input[aria-label="Instance name"]').fill(a); await dlg.locator("button", { hasText: /^\s*create\s*$/i }).last().click(); await sleep(2500);
      check(g, "A UI create -> native list sees it", !!(await until(() => vfind("instances", a, true), 8000)), "native list lacks it"); } catch (e) { check(g, "A UI create -> native list sees it", false, String(e).split("\n")[0]); }
    try { const [p, bd] = mk(b); const r = await rest("POST", p, bd); if (r.status >= 300) throw new Error(`native create ${r.status} ${JSON.stringify(r.body)}`); await until(() => vfind("instances", b, true), 8000); check(g, "B native create -> UI lists it", await listedUI("vertex-ai/workbench", b), "UI list lacks it"); } catch (e) { check(g, "B native create -> UI lists it", false, String(e).split("\n")[0]); }
    try { const f = await vfind("instances", b, true); const r = await rest("DELETE", `/v2/${f.name}`); if (r.status >= 300) throw new Error(`native delete ${r.status}`); await sleep(1500); check(g, "C native delete -> UI drops it", !(await listedUI("vertex-ai/workbench", b)), "UI still lists it"); } catch (e) { check(g, "C native delete -> UI drops it", false, String(e).split("\n")[0]); }
    try { await uiDeleteV({ route: "vertex-ai/workbench" }, a); check(g, "D UI delete -> native gone", !!(await until(async () => !(await vfind("instances", a, true)), 8000)), "native list still has it"); } catch (e) { check(g, "D UI delete -> native gone", false, String(e).split("\n")[0]); }
    const left = await vfind("instances", a, true); if (left) await rest("DELETE", `/v2/${left.name}`);
  }

  // Job state: a custom job created over the API reaches the same terminal state in the console as the API reports
  {
    const g = `${G}:job-state`, n = "bdj" + tag();
    const r = await rest("POST", `${VP}/customJobs`, { displayName: n, jobSpec: { workerPoolSpecs: jobPool } });
    const name = fix(r.body?.response?.name || (r.body?.name || "").split("/operations/")[0]);
    if (!name) check(g, "native custom job created", false, `${r.status} ${JSON.stringify(r.body)}`);
    else {
      const fin = await until(async () => /SUCCEEDED|FAILED/.test((await rest("GET", `/v1/${name}`)).body?.state || ""), 60000);
      const st = (await rest("GET", `/v1/${name}`)).body?.state || "";
      check(g, "native job advances to a terminal state", !!fin, st);
      await go("vertex-ai/training?tab=custom"); const t = (await row(n).innerText().catch(() => "")).replace(/\s+/g, " ");
      const word = st.replace(/^JOB_STATE_/, "").toLowerCase();
      check(g, "UI row shows the same state as the API", !!word && t.toLowerCase().includes(word), `api=${st} ui="${t}"`);
      await rest("DELETE", `/v1/${name}`);
    }
  }

  // Deployed model: native deployModel -> UI endpoint detail shows it; native undeploy -> UI drops it
  {
    const g = `${G}:deploy`, en = "bde" + tag(), mn = "bdm" + tag();
    const m = await rest("POST", `${VP}/models:upload`, { model: { displayName: mn, artifactUri: "gs://my-bucket/model/", containerSpec: { imageUri: "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-0:latest" } } });
    const e = await rest("POST", `${VP}/endpoints`, { displayName: en });
    await sleep(1500);
    const mf = await vfind("models", mn), ef = await vfind("endpoints", en);
    if (!mf || !ef) check(g, "native model + endpoint created", false, `${m.status}/${e.status}`);
    else {
      const dp = await rest("POST", `/v1/${ef.name}:deployModel`, { deployedModel: { model: mf.name, displayName: "dm1", dedicatedResources: { minReplicaCount: 1, machineSpec: { machineType: "n1-standard-4" } } } });
      check(g, "native deployModel accepted", dp.status < 300, `${dp.status} ${JSON.stringify(dp.body)}`);
      await sleep(1500);
      const [loc, id] = [ef.name.split("/")[3], ef.name.split("/").pop()];
      await go(`vertex-ai/endpoints/${loc}/${id}`);
      check(g, "UI endpoint detail shows the deployed model", (await body()).includes("dm1") && (await body()).includes("n1-standard-4"), (await body()).slice(0, 220));
      const dep = (await rest("GET", `/v1/${ef.name}`)).body?.deployedModels?.[0]?.id;
      if (dep) { await rest("POST", `/v1/${ef.name}:undeployModel`, { deployedModelId: dep }); await sleep(1500); await go(`vertex-ai/endpoints/${loc}/${id}`); check(g, "native undeployModel -> UI detail no longer shows it", !(await body()).includes("dm1"), "still shown"); }
    }
    for (const f of [ef, mf]) if (f) await rest("DELETE", `/v1/${f.name}`);
  }

  check(`${G}:names`, "resource names returned by the API use the request's project id", nameLeak === null, nameLeak || "");

  // Inference: Studio generate vs native generateContent (needs a model runner: Mesh AI pack / local LLM)
  {
    const g = `${G}:inference`;
    const gm = await rest("GET", "/v1/publishers/-/models");
    const av = (gm.body?.publisherModels || []).find((m) => m.vyomiAvailability?.available);
    if (!av) skip(g, "Studio generate vs native generateContent", `no model runner up (vyomiAvailability: ${[...new Set((gm.body?.publisherModels || []).map((m) => m.vyomiAvailability?.state))].join(",")})`);
    else {
      const mid = av.name.split("/").pop(), pub = av.name.split("/")[1];
      const n = await rest("POST", `${VP}/publishers/${pub}/models/${mid}:generateContent`, { contents: [{ role: "user", parts: [{ text: "Reply with the single word: pong" }] }], generationConfig: { maxOutputTokens: 16 } });
      const txt = n.body?.candidates?.[0]?.content?.parts?.[0]?.text;
      if (n.status === 503 && /not reachable|Mesh/i.test(JSON.stringify(n.body))) { skip(g, "Studio generate vs native generateContent", "no LLM runtime behind this simulator (needs a Mesh runner / local LLM)"); return; }
      if (n.status === 503 && /No local LLM backend/i.test(JSON.stringify(n.body))) { skip(g, "Studio generate vs native generateContent", `catalog advertises ${mid} as available but this substrate has no LLM backend (503 "No local LLM backend is available on this substrate"); needs the Mesh AI pack / in-browser model. Product note: the publisher-model catalog reports available:true while generateContent is 503`); return; }
      check(g, `native generateContent (${mid}) returns text`, n.status === 200 && !!txt, `${n.status} ${JSON.stringify(n.body).slice(0, 160)}`);
      const c = await rest("POST", `${VP}/publishers/${pub}/models/${mid}:countTokens`, { contents: [{ role: "user", parts: [{ text: "hello world" }] }] });
      check(g, "native countTokens returns totalTokens", c.status === 200 && Number(c.body?.totalTokens) > 0, `${c.status} ${JSON.stringify(c.body)}`);
      try { await go("vertex-ai/studio"); await page.getByRole("combobox", { name: /^Model/ }).first().click(); await page.getByRole("option", { name: new RegExp(mid.replace(/\./g, "\\.")) }).first().click();
        await page.getByLabel("Prompt", { exact: true }).first().fill("Reply with the single word: pong");
        await vis("button", /^\s*Submit\b/i).first().click({ timeout: 8000 }); const ok = await until(async () => /pong/i.test(await body()), 60000);
        check(g, "UI Studio generate returns the model's reply", !!ok, (await body()).slice(-200)); } catch (e) { check(g, "UI Studio generate returns the model's reply", false, String(e).split("\n")[0]); }
    }
  }
}

for (const grp of ONLY) {
  try { if (grp === "compute") await compute(); else if (grp === "vertex") await vertex(); }
  catch (e) { check(grp, "harness ran to completion", false, String(e).split("\n").slice(0, 2).join(" ")); }
}
await browser.close(); if (dev) dev.kill(); if (NH) NH.server.close();
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ cloud: "gcp", console: "v4", base: SIM || BASE, project: P, results }, null, 1));
const done = results.filter((r) => r.ok !== null), pass = done.filter((r) => r.ok).length;
console.log(`RESULT ${pass} passed, ${done.length - pass} failed, ${skipped} skipped`);
process.exit(done.length && pass === done.length ? 0 : 1);
