/* Smoke: APIM Overview > Capacity gauge reads the NATIVE Capacity metric (derived load estimate from real
 * gateway request counters). Idle reads 0%; real gateway traffic moves it; the honesty note is shown.
 *   BASE=http://127.0.0.1:9143 PW=<playwright> SHOT=/path/shot.png node consoles/tests/smoke-azure-apimcapacity.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9143";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `cap-rg-${n}`, SVC = `capapim${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const call = (m, url, body, headers = {}) => pg.evaluate(async ([m, url, body, headers]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json", ...headers }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); let j = null; try { j = t ? JSON.parse(t) : null; } catch {} return { status: r.status, body: j };
}, [m, url, body, headers]);
const arm = (m, path, body, v = "2023-05-01-preview") => call(m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
const svc = `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${SVC}`;
await arm("PUT", svc, { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "p" } });
await arm("PUT", `${svc}/apis/echo`, { properties: { displayName: "echo", path: "echo", protocols: ["https"], mockResponse: { hello: "world" } } });
await arm("PUT", `${svc}/subscriptions/s1`, { properties: { displayName: "s1", scope: `/subscriptions/${SUB}${svc}/apis`, primaryKey: "pk-smoke", secondaryKey: "sk-smoke" } });
const defs = (await arm("GET", `${svc}/providers/Microsoft.Insights/metricDefinitions`, null, "2018-01-01")).body.value.map((d) => d.name.value);
ok("metricDefinitions (native ARM) lists Capacity", defs.includes("Capacity"), defs.join());
await pg.goto(`${UI}#/apim/${RG}/${SVC}`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Capacity" }).click(); await pg.waitForTimeout(1500);
ok("capacity tab is not a not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
ok("idle: gauge reads 0.0%", (await pg.getByTestId("apim-capacity-value").textContent()).trim() === "0.0%");
const txt = await pg.getByTestId("apim-capacity").innerText();
ok("honest note: estimate from gateway request counters, not CPU", /estimate/i.test(txt) && /request counters/i.test(txt) && /not measured CPU/i.test(txt), txt.slice(0, 200));
let served = 0;
for (let i = 0; i < 300; i++) served += (await call("GET", `${WIRE}/azure-data/apim/${SVC}/echo/ping`, null, { "Ocp-Apim-Subscription-Key": "pk-smoke" })).status === 200 ? 1 : 0;
ok("gateway served 300 requests", served === 300, String(served));
const iso = (d) => d.toISOString().replace(/\.\d+Z$/, "Z");
const ts = `${iso(new Date(Date.now() - 600000))}/${iso(new Date(Date.now() + 60000))}`;
const m = await arm("GET", `${svc}/providers/Microsoft.Insights/metrics?metricnames=Capacity&aggregation=Maximum&interval=PT1M&timespan=${ts}`, null, "2018-01-01");
const mx = Math.max(...m.body.value[0].timeseries[0].data.map((p) => p.maximum));
ok("native metrics API reports Capacity > 0", mx > 0, JSON.stringify(m.body).slice(0, 200));
await pg.getByRole("button", { name: "Refresh" }).last().click(); await pg.waitForTimeout(1500);
const v = parseFloat(await pg.getByTestId("apim-capacity-value").textContent());
ok("gauge moved off 0 from the same native call", v > 0, String(v));
if (process.env.SHOT) await pg.screenshot({ path: process.env.SHOT });
console.log(`gauge=${v}% metricMax=${mx}`);
console.log(`${pass} passed, ${fail} failed`);
await b.close(); process.exit(fail ? 1 : 0);
