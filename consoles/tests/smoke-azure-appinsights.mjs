/* Smoke: App Service Application Insights - create a real component, post OTLP spans, see requests/failures/events.
 *   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-azure-appinsights.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `ai-rg-${n}`, APP = `aiapp${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, url, body]);
const arm = (m, path, body, v = "2023-12-01") => call(m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`, { location: "eastus", properties: { siteConfig: {} } });
await pg.goto(`${UI}#/appservices/${RG}/${APP}/appinsights`); await pg.waitForTimeout(1500);
ok("not linked -> offers to turn on", (await pg.getByRole("button", { name: "Turn on Application Insights" }).count()) === 1);
await pg.getByRole("button", { name: "Turn on Application Insights" }).click(); await pg.waitForTimeout(2000);
ok("linked component shown", (await pg.getByTestId("ai-linked").count()) === 1);
const comps = (await arm("GET", `/providers/Microsoft.Insights/components`, null, "2020-02-02")).body.value;
ok("real Microsoft.Insights/components over ARM", comps.some((c) => c.name === `${APP}-ai` && c.properties.InstrumentationKey));
const settings = (await arm("POST", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}/config/appsettings/list`)).body?.properties || {};
ok("connection string app setting set", /InstrumentationKey=/.test(settings.APPLICATIONINSIGHTS_CONNECTION_STRING || ""), JSON.stringify(settings).slice(0, 100));
const now = Date.now() * 1e6;
const span = (name, kind, code, sid, extra = {}) => ({ traceId: "ab".repeat(16), spanId: sid, name, kind, startTimeUnixNano: String(now - 8e6), endTimeUnixNano: String(now), status: { code }, ...extra });
await call("POST", `${WIRE}/_obs/v1/traces`, { resourceSpans: [{ resource: { attributes: [{ key: "service.name", value: { stringValue: APP } }] }, scopeSpans: [{ spans: [
  span("GET /", 2, 0, "11".repeat(8)), span("POST /pay", 2, 2, "22".repeat(8), { events: [{ name: "cart.checkout", timeUnixNano: String(now) }] }), span("SELECT orders", 3, 0, "33".repeat(8))] }] }] });
await pg.reload(); await pg.waitForTimeout(2000);
ok("overview counts 2 requests / 1 failed", (await pg.getByTestId("ai-requests").innerText()).trim() === "2" && (await pg.getByTestId("ai-failed").innerText()).trim() === "1");
await pg.getByRole("tab", { name: "Failures" }).click(); await pg.waitForTimeout(500);
ok("failures lists the failed request", (await pg.getByTestId("ai-fail-row").count()) === 1);
await pg.getByRole("tab", { name: "Events" }).click(); await pg.waitForTimeout(500);
ok("events lists custom span event", (await pg.getByTestId("ai-ev-row").count()) === 1);
await pg.getByRole("tab", { name: "Dependencies" }).click(); await pg.waitForTimeout(500);
ok("dependency listed", (await pg.getByTestId("ai-dep-row").count()) === 1);
ok("not a not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
console.log(`${pass} passed, ${fail} failed`); await b.close(); process.exit(fail ? 1 : 0);
