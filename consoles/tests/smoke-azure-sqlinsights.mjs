/* Smoke: SQL Query Performance Insight / Performance overview / Auditing from measured statement timings.
 *   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-azure-sqlinsights.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `qpi-rg-${n}`, SRV = `qpisrv${n}`, DB = `qpidb${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body, ver) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, url, body]);
const arm = (m, path, body, v = "2023-08-01") => call(m, `${WIRE}/subscriptions/${SUB}${path}?api-version=${v}`, body);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
const ready = async () => { if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 }); };
/* Re-open the current page. Nano keeps request telemetry (OTLP spans, request counters) in the in-page recorder only - it does
 * not survive a document reload - so on Nano re-navigate inside the SPA instead of reloading. */
const refresh = async () => { if (process.env.NANO) { const u = pg.url(); await pg.goto(UI + "#/"); await pg.waitForTimeout(300); await pg.goto(u); } else await refresh(); };
await ready();
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}`, { location: "eastus", properties: { administratorLogin: "a", administratorLoginPassword: "Passw0rd!x1" } });
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/databases/${DB}`, { location: "eastus", sku: { name: "Basic" } });
const go = async (panel) => { await pg.goto(`${UI}#/sql/${RG}/${SRV}/${DB}/${panel}`); await pg.waitForTimeout(1500); };
await go("queryperfinsight");
ok("QPI idle -> honest empty state", (await pg.getByTestId("qpi-empty").count()) === 1);
const q = (sql) => call("POST", `${WIRE}/azure-sql/servers/${SRV}/databases/${DB}/query`, { sql });
await call("PUT", `${WIRE}/azure-sql/servers/${SRV}`, {}); await call("PUT", `${WIRE}/azure-sql/servers/${SRV}/databases/${DB}`, {});
await q("CREATE TABLE t(id INTEGER, v TEXT)");
for (let i = 0; i < 4; i++) await q(`INSERT INTO t VALUES (${i}, 'a${i}')`);
await q("SELECT * FROM t WHERE id = 2");
await go("queryperfinsight"); await refresh(); await pg.waitForTimeout(1500);
const rc = await pg.getByTestId("qpi-row").count(), tx = await pg.locator("table[aria-label=\"Top queries\"]").innerText();
ok("QPI lists grouped queries (4 inserts = one row)", rc === 3 && tx.includes("INSERT INTO t VALUES (?, ?)"), rc + " " + tx.slice(0, 400));
ok("QPI not a not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
await go("perfoverview");
ok("overview counts 6 statements", (await pg.getByTestId("po-statements").innerText()).trim() === "6");
await go("auditing");
ok("auditing shows audit records", (await pg.getByTestId("audit-row").count()) === 6);
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
