/* Smoke: App Service operations panels (WebJobs, Service Connector, Certificates, Quotas,
 * Default documents, Health check, Clone, Autoscale, ...) driven through the UI and verified over
 * the native ARM wire.   BASE=http://127.0.0.1:9160 UI_PATH=/v4/azure/ node consoles/tests/smoke-azure-appops.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9160";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `appops-rg-${n}`, APP = `appops${n}`, STG = `appopsstg${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;  // wire calls run INSIDE the page (same origin) so Nano's service worker answers them
const arm = (m, path, body, v = "2023-12-01") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const site = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`;
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${STG}`, { location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2" }, "2023-01-01");
ok("create app over wire", [200, 201].includes((await arm("PUT", site, { location: "eastus", properties: { siteConfig: {} } })).status));
const go = async (panel) => { await pg.goto(`${UI}#/appservices/${RG}/${APP}/${panel}`); await pg.waitForTimeout(1200); };
const NS = async () => await pg.locator("[data-vyomi-not-simulated]").count();

await go("webjobs");
await pg.getByLabel("WebJob name").fill("job1");
await pg.getByLabel("WebJob script").fill("print('ran', 6*7)");
await pg.getByRole("button", { name: "Add", exact: true }).click(); await pg.waitForTimeout(800);
await pg.getByRole("button", { name: "Run job1" }).click(); await pg.waitForTimeout(800);
await pg.getByRole("button", { name: "Logs job1" }).click(); await pg.waitForTimeout(800);
ok("webjob output shown in UI", (await pg.content()).includes("ran 42"));
ok("webjob over wire", (await arm("GET", `${site}/triggeredwebjobs/job1/history`)).body.value[0].properties.output === "ran 42");
ok("webjobs not a not-simulated panel", (await NS()) === 0);

await go("serviceconnector");
await pg.getByLabel("Connection name").fill("tostg");
await pg.getByLabel("Target service").selectOption({ label: `${STG} (storageAccounts)` }); 
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1000);
const st = (await arm("GET", `${site}/config/appsettings`)).body.properties;
ok("service connector wrote app settings", st.AZURE_STORAGEBLOB_RESOURCEENDPOINT === `https://${STG}.blob.core.windows.net`, JSON.stringify(st));

await go("certificates");
await pg.getByLabel("Managed certificate domain").fill("www.example.com");
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1000);
ok("certificate listed", (await pg.content()).includes("www.example.com"));
ok("certificate over wire", (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/certificates`)).body.value.length === 1);

await go("quotas"); ok("quotas shows file system storage", (await pg.content()).includes("File System Storage"));

await go("configuration");
await pg.getByRole("tab", { name: "Default documents" }).click();
await pg.getByLabel("Default document 1").fill("home.html");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("default documents persisted", (await arm("GET", `${site}/config/web`)).body.properties.defaultDocuments[0] === "home.html");
await pg.getByRole("tab", { name: "Path mappings" }).click(); ok("path mappings panel real", (await NS()) === 0);
await pg.getByRole("tab", { name: "Error pages (preview)" }).click(); await pg.getByLabel("404 error page").fill("<h1>nope</h1>");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("error page persisted", (await arm("GET", `${site}/config/web`)).body.properties.errorPages?.["404"] === "<h1>nope</h1>");

await go("healthcheck"); await pg.getByLabel("Enable health check").check(); await pg.getByLabel("Health check path").fill("/healthz");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("health check path persisted", (await arm("GET", `${site}/config/web`)).body.properties.healthCheckPath === "/healthz");

await go("apidefinition"); await pg.getByLabel("API definition location").fill("https://x.test/swagger.json");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("api definition persisted", (await arm("GET", `${site}/config/web`)).body.properties.apiDefinition?.url === "https://x.test/swagger.json");

await go("authentication"); await pg.getByLabel("App Service authentication").click(); await pg.waitForTimeout(1000);
ok("auth enabled over wire", (await arm("GET", `${site}/config/authsettingsV2`)).body.properties.platform.enabled === true);

await go("scaleout"); await pg.getByLabel("Autoscale maximum").fill("5"); await pg.getByRole("button", { name: "Save autoscale" }).click(); await pg.waitForTimeout(1000);
const as = (await arm("GET", `/providers/Microsoft.Insights/autoscalesettings`, null, "2022-10-01")).body.value || [];
ok("autoscale setting stored", as.some((s) => s.properties.profiles[0].capacity.maximum === "5"), JSON.stringify(as).slice(0, 200));

await go("appserviceplan"); ok("plan page shows plan", (await pg.content()).includes("Pricing plan"));
await go("cloneapp"); await pg.getByRole("button", { name: "Clone", exact: true }).click(); await pg.waitForTimeout(2000);
ok("clone created over wire", (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}-clone`)).status === 200);
const c = (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}-clone/config/appsettings`)).body.properties;
ok("clone copied app settings", !!c.AZURE_STORAGEBLOB_RESOURCEENDPOINT);
// ── Function App: Service Connector, Integration editor, Invocations ──
const FN = `appopsfn${n}`, fsite = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${FN}`;
await arm("PUT", fsite, { location: "eastus", kind: "functionapp", properties: {} });
await arm("PUT", `${fsite}/functions/f1`, { properties: { files: { "__init__.py": "def main(req):\n    return {'ok': 1}" } } });
await arm("POST", `${fsite}/functions/f1/invoke`, { method: "GET" });
await pg.goto(`${UI}#/functionapp/${RG}/${FN}/functions/f1`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Invocations" }).click(); await pg.waitForTimeout(800);
ok("invocations tab lists the real run", (await pg.locator("table[aria-label=Invocations] tbody tr").count()) >= 1 && (await pg.content()).includes("Success"));
await pg.getByRole("tab", { name: "Integration" }).click(); await pg.waitForTimeout(500);
await pg.getByRole("button", { name: "Add output binding" }).click();
await pg.getByRole("button", { name: "Save", exact: true }).last().click(); await pg.waitForTimeout(1000);
ok("bindings persisted over wire", ((await arm("GET", `${fsite}/functions/f1`)).body.properties.config.bindings || []).length >= 3);
await pg.goto(`${UI}#/functionapp/${RG}/${FN}/service-connector`); await pg.waitForTimeout(1200);
await pg.getByLabel("Connection name").fill("tostg"); await pg.getByLabel("Target service").selectOption({ label: `${STG} (storageAccounts)` });
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1000);
ok("function service connector wrote app settings", !!(await arm("GET", `${fsite}/config/appsettings`)).body.properties.AZURE_STORAGEBLOB_RESOURCEENDPOINT);
for (const p of ["apimanagement", "webjobs", "certificates", "serviceconnector", "healthcheck", "authentication"]) { await go(p); }
await b.close(); console.log(`${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
