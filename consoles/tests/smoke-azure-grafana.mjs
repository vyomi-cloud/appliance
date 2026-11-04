/* Smoke: Azure Managed Grafana workspace -> Prometheus-compatible data source (/_obs/prom) + built-in dashboard of real series.
 *   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-azure-grafana.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `graf-rg-${n}`, G = `graf${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); let j = null; try { j = t ? JSON.parse(t) : null; } catch {} return { status: r.status, body: j };
}, [m, url, body]);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1500, height: 1600 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
const arm = (m, p, body, v) => call(m, `${WIRE}/subscriptions/${SUB}${p}?api-version=${v}`, body);
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
const put = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Dashboard/grafana/${G}`, { location: "eastus", sku: { name: "Standard" }, identity: { type: "SystemAssigned" }, properties: { grafanaMajorVersion: "11" } }, "2023-09-01");
ok("create workspace", put.status < 300, JSON.stringify(put.body).slice(0, 150));
// generate measured traffic: a few ARM calls are recorded by the router
const s3 = (m, path) => pg.evaluate(async ([m, u]) => (await fetch(u, { method: m, headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0" } })).status, [m, `${WIRE}${path}`]);
await s3("PUT", `/grafbkt${n}`);
for (let i = 0; i < 6; i++) await s3("GET", `/grafbkt${n}`);
await pg.goto(`${UI}#/monitor/managedgrafana`); await pg.waitForTimeout(2000);
await pg.getByRole("button", { name: `Open ${G}` }).click(); await pg.waitForTimeout(1000);
ok("data source URL points at /_obs/prom", /\/_obs\/prom$/.test(await pg.getByTestId("graf-url").innerText()));
await pg.getByRole("button", { name: /Save & test/ }).click(); await pg.waitForTimeout(800);
ok("Save & test works", /working/.test(await pg.getByTestId("graf-status").innerText()));
await pg.waitForTimeout(2000);
ok("dashboard panels rendered", (await pg.locator("[data-testid^=graf-]").count()) >= 6);
await pg.getByRole("textbox", { name: "PromQL expression" }).fill('sum by (service) (vyomi_requests_total)');
await pg.getByRole("button", { name: "Run query" }).click(); await pg.waitForTimeout(800);
const rows = await pg.getByTestId("graf-explore").locator("tbody tr").count();
ok("Explore returns measured series", rows >= 1 && !(await pg.getByTestId("graf-explore").innerText()).includes("Empty result"), String(rows));
const bad = await pg.getByRole("textbox", { name: "PromQL expression" }).fill('sum(('); await pg.getByRole("button", { name: "Run query" }).click(); await pg.waitForTimeout(600);
ok("bad PromQL surfaces the Prometheus error", (await pg.getByTestId("graf-explore-error").count()) === 1);
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
