/* Smoke: Cosmos DB Scale page shows RU consumption from measured data-plane requests.
 *   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-azure-cosmosscale.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `cs-rg-${n}`, ACC = `csacc${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body, headers = {}) => pg.evaluate(async ([m, url, body, headers]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json", ...headers }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); let j = null; try { j = t ? JSON.parse(t) : null; } catch {} return { status: r.status, body: j };
}, [m, url, body, headers]);
const arm = (m, path, body, v = "2024-05-15") => call(m, `${WIRE}/subscriptions/${SUB}${path}?api-version=${v}`, body);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
const ready = async () => { if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 }); };
/* Re-open the current page. Nano keeps request telemetry (OTLP spans, request counters) in the in-page recorder only - it does
 * not survive a document reload - so on Nano re-navigate inside the SPA instead of reloading. */
const refresh = async () => { if (process.env.NANO) { const u = pg.url(); await pg.goto(UI + "#/"); await pg.waitForTimeout(300); await pg.goto(u); } else await refresh(); };
await ready();
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${ACC}`, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "East US", failoverPriority: 0 }] } });
await pg.goto(`${UI}#/cosmos/${RG}/${ACC}/scale`); await pg.waitForTimeout(1500);
ok("idle account: honest empty state", (await pg.getByTestId("scale-empty").count()) === 1);
// data-plane traffic with the documentdb header so the wire routes it to the Cosmos core
const dp = (m, path, body, extra = {}) => call(m, `${WIRE}${path}`, body, { "x-ms-version": "2018-12-31", "x-ms-documentdb-partitionkey": '["a"]', ...extra });
await dp("POST", "/dbs", { id: "d1" }); await dp("POST", "/dbs/d1/colls", { id: "c1", partitionKey: { paths: ["/pk"], kind: "Hash" } });
for (let i = 0; i < 3; i++) await dp("POST", "/dbs/d1/colls/c1/docs", { id: "doc" + i, pk: "a" });
await refresh(); await pg.waitForTimeout(2000);
const req = Number((await pg.getByTestId("scale-requests").innerText()).trim());
ok("requests counted from the measured wire", req >= 3, String(req));
ok("modelled RUs > 0", Number((await pg.getByTestId("scale-ru").innerText()).trim()) > 0);
ok("not a not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
