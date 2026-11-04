/* Smoke: per-function Metrics + live Log stream on the Function detail blade, fed by the REAL invocation log;
 * and per-resource Key Vault metrics fed by the observability recorder.
 *   BASE=http://127.0.0.1:9069 node consoles/tests/smoke-azure-fnmetrics.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9069";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `fnm-rg-${n}`, FN = `fnm${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const arm = (m, path, body, v = "2023-12-01") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
const site = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${FN}`;
await arm("PUT", site, { location: "eastus", kind: "functionapp", properties: {} });
await arm("PUT", `${site}/functions/good`, { properties: { files: { "__init__.py": "def main(req):\n    return {'ok': 1}" } } });
await arm("PUT", `${site}/functions/bad`, { properties: { files: { "__init__.py": "def main(req):\n    raise ValueError('boom')" } } });
for (let i = 0; i < 3; i++) await arm("POST", `${site}/functions/good/invoke`, { method: "GET" });
await arm("POST", `${site}/functions/bad/invoke`, { method: "GET" });
await pg.goto(`${UI}#/functionapp/${RG}/${FN}/functions/good`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Metrics" }).click(); await pg.waitForTimeout(800);
ok("per-function metrics: only this function's 3 runs", (await pg.getByTestId("fn-m-count").innerText()).trim() === "3");
ok("metrics tab is not a not-simulated panel", (await pg.locator("[data-vyomi-not-simulated]").count()) === 0);
await pg.getByRole("tab", { name: "Logs" }).click(); await pg.waitForTimeout(800);
const log = await pg.getByTestId("fn-logstream").innerText();
ok("log stream shows good, hides bad", log.includes("Functions.good") && !log.includes("Functions.bad"), log.slice(0, 120));
await arm("POST", `${site}/functions/good/invoke`, { method: "GET" });
await pg.waitForTimeout(3800);
ok("log stream picks up a new run live", ((await pg.getByTestId("fn-logstream").innerText()).match(/Functions\.good/g) || []).length === 4);
// Key Vault request metrics from the recorder
const KV = `fnmkv${n}`, kvId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`;
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`, { location: "eastus", properties: { tenantId: "x", sku: { family: "A", name: "standard" } } }, "2023-07-01");
const defs = (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}/providers/Microsoft.Insights/metricDefinitions`, null, "2018-01-01")).body.value.map((d) => d.name.value);
ok("KV defs: ActivityOperations + request metrics", defs.includes("ActivityOperations") && defs.includes("ServiceApiHit") && defs.includes("SuccessE2ELatency"), defs.join());
console.log(`${pass} passed, ${fail} failed`);
await b.close(); process.exit(fail ? 1 : 0);
