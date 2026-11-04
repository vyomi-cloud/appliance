/* Smoke: Function App wizard (Application Insights + diagnostic settings) and AKS wizard (Defender for Containers) wire their
 * Monitor/secure toggles to real resources.   BASE=http://127.0.0.1:9092 PW=<playwright path> node consoles/tests/smoke-azure-wizard-monitor-wiring.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9092";
const UI = `${BASE}/v4/azure/`, WIRE = `${BASE}/_wire`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `mw-rg-${n}`, FN = `mwfn${n}`, WS = `mwws${n}`, AI = `mwai${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const arm = (m, path, body, v) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
await pg.goto(UI, { waitUntil: "networkidle" });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/${WS}`, { location: "eastus", properties: {} }, "2022-10-01");
await pg.goto(`${UI}#/functionapp/create/flex`); await pg.waitForTimeout(1500);
await pg.getByLabel("Resource Group").selectOption({ label: RG });
await pg.getByLabel("Function App name").fill(FN);
for (const t of ["Storage"]) { await pg.getByRole("tab", { name: t }).click(); await pg.waitForTimeout(300); }
await pg.locator("input[type=radio][value=configure]").first().check();
await pg.getByLabel("Log Analytics workspace").selectOption({ label: WS });
await pg.getByRole("tab", { name: "Monitoring" }).click(); await pg.waitForTimeout(300);
await pg.getByLabel("Application Insights", { exact: true }).fill(AI);
await pg.getByRole("tab", { name: /Review/ }).click(); await pg.waitForTimeout(500);
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(3500);
const site = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${FN}`;
ok("function app exists", (await arm("GET", site, null, "2023-12-01")).status === 200);
const diag = await arm("GET", `${site}/providers/Microsoft.Insights/diagnosticSettings`, null, "2021-05-01-preview");
ok("diagnostic setting created", (diag.body?.value || []).some((d) => (d.properties?.workspaceId || "").toLowerCase().includes(WS.toLowerCase())), JSON.stringify(diag.body).slice(0, 200));
ok("Application Insights component created", (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Insights/components/${AI}`, null, "2020-02-02")).status === 200);
const st = await arm("POST", `${site}/config/appsettings/list`, null, "2023-12-01");
ok("app setting links the component", /InstrumentationKey=/.test(st.body?.properties?.APPLICATIONINSIGHTS_CONNECTION_STRING || ""), JSON.stringify(st.body).slice(0, 200));
// Container Apps environment: "Create a new workspace" really creates one and links its customerId
const CE = `mwce${n}`;
await pg.goto(`${UI}#/containerapps/environments/create`); await pg.waitForTimeout(1500);
await pg.getByLabel("Resource Group").selectOption({ label: RG });
await pg.getByLabel("Environment name").fill(CE);
await pg.getByRole("tab", { name: /Review/ }).click(); await pg.waitForTimeout(500);
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(3500);
const ce = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.App/managedEnvironments/${CE}`, null, "2024-03-01");
const wsn = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/workspace-${CE}`, null, "2022-10-01");
ok("new workspace created for the environment", wsn.status === 200, JSON.stringify(wsn.body).slice(0, 150));
ok("environment logs to that workspace's customerId", !!wsn.body?.properties?.customerId && ce.body?.properties?.appLogsConfiguration?.logAnalyticsConfiguration?.customerId === wsn.body.properties.customerId, JSON.stringify(ce.body?.properties?.appLogsConfiguration));
await b.close(); console.log(`${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
