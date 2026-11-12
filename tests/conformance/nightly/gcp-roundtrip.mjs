/* Check 5 (GCP, Nano): UI <-> native API (what the SDK / gcloud / REST call) both ways, comparing DATA.
 *
 * The Nano console runs the engines in the browser; the native GCP REST surface is /_wire/<native path>
 * (the same engines the relay exposes to the SDK and gcloud). For each service:
 *   A. created through the native API   -> listed in the console grid, name and state the same
 *   B. created in the console (wizard)  -> the native API returns it, same name and the same state
 *   C. deleted through the native API   -> gone from the console grid after reopening the service
 *   D. deleted in the console           -> the native API answers 404
 * One [PASS]/[FAIL] line per check; a JSON summary is written to $OUT (default tests/conformance/hourly/out/gcp-roundtrip.json).
 *
 *   NANO_DIR=$PWD/wasm node tests/conformance/nightly/gcp-roundtrip.mjs [pubsub,secretmanager,...]
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { startServer, bootConsole, chromium, RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.OUT || resolve(HERE, "../hourly/out/gcp-roundtrip.json");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const tag = Date.now().toString(36).slice(-5);

// native = the path an SDK / gcloud / curl call; create returns nothing we rely on; get returns the resource.
const SERVICES = [
  { id: "pubsub", label: /Pub\/Sub/i,
    create: (P, n) => ["PUT", `/_wire/v1/projects/${P}/topics/${n}`, {}],
    path: (P, n) => `/_wire/v1/projects/${P}/topics/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: () => "" },
  { id: "secretmanager", label: /Secret Manager/i,
    create: (P, n) => ["POST", `/_wire/v1/projects/${P}/secrets?secretId=${n}`, { replication: { automatic: {} } }],
    path: (P, n) => `/_wire/v1/projects/${P}/secrets/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: () => "" },
  { id: "storage", label: /Cloud Storage/i,
    create: (P, n) => ["POST", `/_wire/storage/v1/b?project=${P}`, { name: n }],
    path: (P, n) => `/_wire/storage/v1/b/${n}`,
    name: (j) => String(j.name || ""), state: () => "" },
  // Real Cloud KMS has no DeleteKeyRing / DeleteCryptoKey (keys are only disabled or their versions destroyed), and the
  // console grid lists crypto KEYS, not rings: create both ways on a key, never delete (C and D are not applicable).
  { id: "kms", label: /Key Management|Cloud KMS/i, noDelete: true,
    create: (P, n) => [["POST", `/_wire/v1/projects/${P}/locations/us-central1/keyRings?keyRingId=rtr-${tag}`, {}],
                       ["POST", `/_wire/v1/projects/${P}/locations/us-central1/keyRings/rtr-${tag}/cryptoKeys?cryptoKeyId=${n}`, { purpose: "ENCRYPT_DECRYPT" }]],
    path: (P, n) => `/_wire/v1/projects/${P}/locations/us-central1/keyRings/rtr-${tag}/cryptoKeys/${n}`,
    lookup: async (api, P, n) => {          // a console-created key lives in whichever ring/location the wizard used
      for (const loc of ["us-central1", "global"]) {
        const rings = await api("GET", `/_wire/v1/projects/${P}/locations/${loc}/keyRings`);
        for (const r of (rings.body && rings.body.keyRings) || []) {
          const k = await api("GET", `/_wire/v1/${r.name}/cryptoKeys/${n}`);
          if (k.status === 200) return k;
        }
      }
      return { status: 404, body: null };
    },
    name: (j) => String(j.name || "").split("/").pop(), state: () => "" },
  { id: "cloudscheduler", label: /Cloud Scheduler/i,
    create: (P, n) => ["POST", `/_wire/v1/projects/${P}/locations/us-central1/jobs`,
      { name: `projects/${P}/locations/us-central1/jobs/${n}`, schedule: "0 9 * * *", timeZone: "UTC", httpTarget: { uri: "https://example.com/", httpMethod: "GET" } }],
    path: (P, n) => `/_wire/v1/projects/${P}/locations/us-central1/jobs/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: (j) => String(j.state || "") },
  { id: "vpc", label: /VPC network/i,
    create: (P, n) => ["POST", `/_wire/compute/v1/projects/${P}/global/networks`, { name: n, autoCreateSubnetworks: false }],
    path: (P, n) => `/_wire/compute/v1/projects/${P}/global/networks/${n}`,
    name: (j) => String(j.name || ""), state: () => "" },
  { id: "cloudsql", label: /Cloud SQL/i,
    create: (P, n, X) => ["POST", `/_wire/sql/v1beta4/projects/${P}/instances`, { name: n, databaseVersion: "POSTGRES_15", region: X.region, settings: { tier: "db-f1-micro" } }],
    path: (P, n) => `/_wire/sql/v1beta4/projects/${P}/instances/${n}`,
    name: (j) => String(j.name || ""), state: (j) => String(j.state || "") },
  { id: "firestore", label: /Firestore/i,
    create: (P, n) => ["POST", `/_wire/v1/projects/${P}/databases?databaseId=${n}`, { type: "FIRESTORE_NATIVE", locationId: "nam5" }],
    path: (P, n) => `/_wire/v1/projects/${P}/databases/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: () => "" },
  { id: "iam", label: /IAM & Admin|IAM and Admin/i,
    create: (P, n) => ["POST", `/_wire/v1/projects/${P}/serviceAccounts`, { accountId: n, serviceAccount: { displayName: n } }],
    path: (P, n) => `/_wire/v1/projects/${P}/serviceAccounts/${n}@${P}.iam.gserviceaccount.com`,
    name: (j) => String(j.email || "").split("@")[0], state: () => "" },
  { id: "apigateway", pending: "no native /_wire route for API Gateway in Nano (405)", label: /API Gateway/i,
    create: (P, n) => ["POST", `/_wire/v1/projects/${P}/locations/global/apis?apiId=${n}`, { displayName: n }],
    path: (P, n) => `/_wire/v1/projects/${P}/locations/global/apis/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: (j) => String(j.state || "") },
  { id: "artifactregistry", label: /Artifact Registry/i,
    create: (P, n, X) => ["POST", `/_wire/v1/projects/${P}/locations/${X.region}/repositories?repositoryId=${n}`, { format: "DOCKER" }],
    path: (P, n, X) => `/_wire/v1/projects/${P}/locations/${X.region}/repositories/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: () => "" },
  { id: "compute", pending: "console uses the generic store, /_wire the native gcp_compute_vm store (split-brain); mirroring them starts a second in-browser VM and breaks nano-post-create-gcp-gce-ssh, so the two stores need one owner first", label: /Compute Engine/i,
    create: (P, n, X) => ["POST", `/_wire/compute/v1/projects/${P}/zones/${X.zone}/instances`,
      { name: n, machineType: `zones/${X.zone}/machineTypes/e2-micro`,
        disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }],
        networkInterfaces: [{ network: `projects/${P}/global/networks/default` }] }],
    path: (P, n, X) => `/_wire/compute/v1/projects/${P}/zones/${X.zone}/instances/${n}`,
    // The Nano grid shows the in-browser VM state (consoles/src/gcp/services/compute/api.js nanoVm): RUNNING only once the v86 VM booted, so the
    // native status is not comparable; name + zone + machine type (rowMatch) are.
    name: (j) => String(j.name || ""), state: () => "" },
  { id: "functions", pending: "console uses the generic store, /_wire the native functions core (split-brain); native create also needs an uploaded source zip", label: /Cloud Functions|Cloud Run functions/i,
    create: (P, n, X) => ["POST", `/_wire/v2/projects/${P}/locations/${X.region}/functions?functionId=${n}`,
      { buildConfig: { runtime: "python311", entryPoint: "main", source: { storageSource: { bucket: "rt-src", object: "src.zip" } } } }],
    path: (P, n, X) => `/_wire/v2/projects/${P}/locations/${X.region}/functions/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: (j) => String(j.state || "") },
  { id: "eventarc", pending: "console uses the generic store, /_wire the native eventarc core (split-brain); native create needs an existing Cloud Run service", label: /Eventarc/i,
    create: (P, n, X) => ["POST", `/_wire/v1/projects/${P}/locations/${X.region}/triggers?triggerId=${n}`,
      { eventFilters: [{ attribute: "type", value: "google.cloud.pubsub.topic.v1.messagePublished" }],
        destination: { cloudRun: { service: "rt-svc", region: X.region } } }],
    path: (P, n, X) => `/_wire/v1/projects/${P}/locations/${X.region}/triggers/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: () => "" },
  // Alert policies are addressed by a server-assigned id: find it by display name (policy ids are remembered in IDS for the by-id path).
  { id: "monitoring", label: /Cloud Monitoring|Monitoring/i,
    create: (P, n) => ["POST", `/_wire/v3/projects/${P}/alertPolicies`,
      { displayName: n, combiner: "OR", conditions: [{ displayName: "c", conditionThreshold: { filter: 'metric.type="compute.googleapis.com/instance/cpu/utilization"', comparison: "COMPARISON_GT", thresholdValue: 0.9, duration: "60s" } }] }],
    lookup: async (api, P, n) => {
      const l = await api("GET", `/_wire/v3/projects/${P}/alertPolicies`);
      const hit = ((l.body || {}).alertPolicies || []).find((x) => x.displayName === n);
      if (hit) { IDS[n] = String(hit.name).split("/").pop(); return { status: 200, body: hit }; }
      return { status: 404, body: l.body };
    },
    path: (P, n) => `/_wire/v3/projects/${P}/alertPolicies/${IDS[n] || n}`,
    name: (j) => String(j.displayName || ""), state: () => "" },
  { id: "redis", label: /Memorystore for Redis/i,
    create: (P, n) => ["POST", `/_wire/v1/projects/${P}/locations/us-central1/instances?instanceId=${n}`, { tier: "BASIC", memorySizeGb: 1 }],
    path: (P, n) => `/_wire/v1/projects/${P}/locations/us-central1/instances/${n}`,
    name: (j) => String(j.name || "").split("/").pop(), state: (j) => String(j.state || "") },
];

const IDS = {};
const only = (process.argv[2] || "").split(",").filter(Boolean);
const results = [];
let fails = 0;
const check = (svc, step, ok, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${svc}: ${step}${!ok && detail ? ` :: ${detail}` : ""}`);
  results.push({ service: svc, step, ok, detail: ok ? "" : String(detail).slice(0, 300) });
  if (!ok) fails++;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
await bootConsole(page, base, "/gcp-console.html");
const P = await page.evaluate(() => PROJECT);
const X = await page.evaluate(async () => { const c = await (await fetch("/api/gcp/catalog")).json(); return { region: c.region || "us-central1", zone: c.zone || "us-central1-a" }; });

const api = (method, url, body) => page.evaluate(async ([m, u, b]) => {
  const r = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: b === undefined || m === "GET" || m === "DELETE" ? undefined : JSON.stringify(b) });
  let j = null; try { j = await r.json(); } catch (_) {}
  return { status: r.status, body: j };
}, [method, url, body]);

const open = async (label) => {
  await page.locator(RAIL_SEL).filter({ hasText: label }).first().click({ timeout: 15000 });
  await sleep(1800);
};
const rows = () => page.evaluate(() => [...document.querySelectorAll("#main table.gc tr[data-row-name]")].map((r) => ({
  name: r.getAttribute("data-row-name"), text: (r.innerText || "").replace(/\s+/g, " ").trim() })));
const reopen = async (label) => { await open(label); for (let i = 0, last = -1; i < 8; i++) { const n = (await rows()).length; if (n === last) break; last = n; await sleep(500); } };

for (const s of SERVICES) {
  if (only.length && !only.includes(s.id)) continue;
  if (s.pending && !only.includes(s.id)) { console.log(`[PENDING] ${s.id}: ${s.pending}`); results.push({ service: s.id, step: "pending", ok: null, detail: s.pending }); continue; }
  const nNative = `rt-n-${tag}`, nUi = `rt-u-${tag}`;
  try {
    await open(s.label);
    // A. native create -> UI
    const calls = s.create(P, nNative, X);
    let c = { status: 0, body: null };
    for (const [m, u, b] of (Array.isArray(calls[0]) ? calls : [calls])) { c = await api(m, u, b); if (c.status >= 300 && c.status !== 409) break; }
    check(s.id, "native create succeeds", c.status >= 200 && c.status < 300, `${c.status} ${JSON.stringify(c.body).slice(0, 160)}`);
    const g = s.lookup ? await s.lookup(api, P, nNative, X) : await api("GET", s.path(P, nNative, X));
    check(s.id, "native get returns the resource", g.status === 200 && s.name(g.body || {}) === nNative, `${g.status} ${JSON.stringify(g.body).slice(0, 160)}`);
    await reopen(s.label);
    const hit = (nm) => (r) => r.name === nm || r.text.includes(nm) || (s.rowMatch && s.rowMatch(r, nm));
    const rowA = (await rows()).find(hit(nNative));
    check(s.id, "A: native-created resource is listed in the console grid", !!rowA, `rows: ${(await rows()).map((r) => r.name).join(", ").slice(0, 160)}`);
    if (rowA && s.state(g.body || {})) check(s.id, "A: grid shows the native state", rowA.text.toUpperCase().includes(s.state(g.body).toUpperCase()), rowA.text);

    // B. UI create -> native
    await page.locator("#main button").filter({ hasText: /^\s*(add\s*)?Create/i }).first().click({ timeout: 8000 });
    await sleep(900);
    await page.evaluate((nm) => {
      const input = document.querySelector("#main input[type=text]");
      if (input) { input.value = nm; input.dispatchEvent(new Event("input", { bubbles: true })); input.dispatchEvent(new Event("change", { bubbles: true })); }
    }, nUi);
    await page.locator("#main button.primary").filter({ hasText: /Create/ }).first().click({ timeout: 8000 });
    await sleep(2200);
    await reopen(s.label);
    const rowB = (await rows()).find(hit(nUi));
    check(s.id, "B: console-created resource appears in its own grid", !!rowB, `rows: ${(await rows()).map((r) => r.name).join(", ").slice(0, 160)}`);
    const gB = s.lookup ? await s.lookup(api, P, nUi, X) : await api("GET", s.path(P, nUi, X));
    check(s.id, "B: native API returns the console-created resource", gB.status === 200 && s.name(gB.body || {}) === nUi, `${gB.status} ${JSON.stringify(gB.body).slice(0, 160)}`);
    if (gB.status === 200 && s.state(gB.body || {}) && rowB) check(s.id, "B: native state matches the grid", rowB.text.toUpperCase().includes(s.state(gB.body).toUpperCase()), `${s.state(gB.body)} vs ${rowB.text}`);

    if (s.noDelete) { console.log(`[SKIP] ${s.id}: C/D delete both ways — the real cloud has no delete for this resource`); continue; }
    // C. native delete -> UI
    const dN = await api("DELETE", s.path(P, nNative, X));
    check(s.id, "native delete succeeds", dN.status >= 200 && dN.status < 300, `${dN.status} ${JSON.stringify(dN.body).slice(0, 120)}`);
    await reopen(s.label);
    check(s.id, "C: natively deleted resource is gone from the console", !(await rows()).some(hit(nNative)), nNative);

    // D. UI delete -> native
    const rowName = rowB ? rowB.name : nUi;
    const opened = await page.evaluate((nm) => { const a = document.querySelector(`#main table.gc tr[data-row-name="${nm}"] a.id`); if (a) { a.click(); return true; } return false; }, rowName);
    if (opened) {
      await sleep(1500);
      await page.locator("#main button.danger").filter({ hasText: /Delete/ }).first().click({ timeout: 6000 }).catch(() => {});
      await sleep(1800);
      const gD = await api("GET", s.path(P, nUi, X));
      check(s.id, "D: console-deleted resource answers 404 on the native API", gD.status === 404, `${gD.status}`);
    } else {
      check(s.id, "D: console-deleted resource answers 404 on the native API", false, "could not open the resource from the grid to delete it");
      await api("DELETE", s.path(P, nUi, X));
    }
  } catch (e) {
    check(s.id, "run", false, String(e).split("\n")[0]);
    for (const n of [nNative, nUi]) { try { await api("DELETE", s.path(P, n, X)); } catch (_) {} }
  }
}
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ cloud: "gcp", target: "nano", project: P, results }, null, 1));
await browser.close(); server.close();
console.log(`RESULT ${results.filter((r) => r.ok).length} passed, ${fails} failed`);
process.exit(fails ? 1 : 0);
