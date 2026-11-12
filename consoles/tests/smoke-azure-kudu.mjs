/* Smoke: App Service Console / Advanced Tools / App Service Editor / Process explorer / Log stream / Extensions and the
 * Diagnose-and-solve blades (AKS, APIM, App Configuration, Cognitive Services, App Service), driven through the UI and
 * verified over the native ARM wire.   BASE=http://127.0.0.1:9081 node consoles/tests/smoke-azure-kudu.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9081";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `kudu-rg-${n}`, APP = `kudu${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const arm = (m, path, body, v = "2023-12-01") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const prov = (ns, t, name) => `/resourceGroups/${RG}/providers/${ns}/${t}/${name}`;
const site = prov("Microsoft.Web", "sites", APP);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
ok("create app", [200, 201].includes((await arm("PUT", site, { location: "eastus", kind: "app", properties: {} })).status));
await arm("PUT", `${site}/config/appsettings`, { properties: { GREETING: "hello-kudu" } });
const go = async (panel, base = `appservices/${RG}/${APP}`) => { await pg.goto(`${UI}#/`); await pg.waitForTimeout(200); await pg.goto(`${UI}#/${base}/${panel}`); await pg.waitForTimeout(1500); };
const NS = async () => await pg.locator("[data-vyomi-not-simulated]").count();

// Console
await go("console");
ok("console is not a not-simulated panel", (await NS()) === 0);
const input = pg.getByLabel("Console input");
const type = async (c) => { await input.fill(c); await input.press("Enter"); await pg.waitForTimeout(700); };
await type("printenv GREETING");
ok("console shows app setting", (await pg.locator("[data-testid=kudu-console]").innerText()).includes("hello-kudu"));
await type("echo from-ui > /home/site/wwwroot/ui.txt");
ok("console write is a real file over the wire", (await arm("GET", `${site}/kudu/api/vfs/site/wwwroot/ui.txt`)).body?.content === "from-ui\n");
await type("nosuchcmd");
ok("unknown command errors", (await pg.locator("[data-testid=kudu-console]").innerText()).includes("command not found"));

// App Service Editor
await go("appeditor");
ok("editor lists wwwroot with the console-written file", (await pg.locator("[data-testid=editor-tree]").innerText()).includes("ui.txt"));
await pg.locator("[data-testid=editor-tree] a", { hasText: "ui.txt" }).click(); await pg.waitForTimeout(600);
ok("editor loads content", (await pg.getByLabel("File editor").inputValue()) === "from-ui\n");
await pg.getByLabel("File editor").fill("edited-in-ui\n");
await pg.getByRole("button", { name: "Save", exact: true }).click(); await pg.waitForTimeout(800);
ok("editor save persisted over the wire", (await arm("GET", `${site}/kudu/api/vfs/site/wwwroot/ui.txt`)).body?.content === "edited-in-ui\n");

// Process explorer
await go("processexplorer");
ok("process explorer shows worker + scm", /w3wp\.exe|gunicorn|dotnet/.test(await pg.content()) && (await pg.content()).includes("worker") && (await NS()) === 0);

// Log stream
await go("logstream");
await pg.waitForTimeout(2500);
ok("log stream tails real lines", (await pg.locator("[data-testid=log-stream]").innerText()).includes("[kudu] command"), await pg.locator("[data-testid=log-stream]").innerText());

// Extensions
await go("extensions");
await pg.getByRole("tab", { name: "Gallery" }).click(); await pg.waitForTimeout(800);
await pg.locator("tr", { hasText: "Diagnostics as a Service" }).getByRole("button", { name: "Add" }).click(); await pg.waitForTimeout(800);
ok("extension installed over the wire", (await arm("GET", `${site}/kudu/api/siteextensions?scope=installed`)).body.value.some((e) => e.id === "DaaS"));
await pg.getByRole("tab", { name: "Installed extensions" }).click(); await pg.waitForTimeout(800);
ok("installed tab lists it", (await pg.content()).includes("Diagnostics as a Service"));

// Advanced tools
await go("advancedtools");
ok("advanced tools environment", (await pg.content()).includes("Operating system") && (await NS()) === 0);
await pg.getByRole("tab", { name: "Settings" }).click(); await pg.waitForTimeout(500);
await pg.getByLabel("Kudu setting name").fill("SCM_TRACE_LEVEL"); await pg.getByLabel("Kudu setting value").fill("Verbose");
await pg.getByRole("button", { name: "Save", exact: true }).click(); await pg.waitForTimeout(800);
ok("kudu setting persisted", (await arm("GET", `${site}/kudu/api/settings`)).body.SCM_TRACE_LEVEL === "Verbose");

// Diagnose blades
await arm("PUT", prov("Microsoft.ContainerService", "managedClusters", `kaks${n}`), { location: "eastus", properties: { kubernetesVersion: "1.20.0", agentPoolProfiles: [{ name: "np", count: 1 }] } });
await arm("PUT", prov("Microsoft.ApiManagement", "service", `kapim${n}`), { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "x" } });
await arm("PUT", prov("Microsoft.AppConfiguration", "configurationStores", `kcfg${n}`), { location: "eastus", sku: { name: "Free" } });
await arm("PUT", prov("Microsoft.CognitiveServices", "accounts", `kcog${n}`), { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: {} });
const diag = async (label, base, detector, status) => {
  await go("diagnose", base);
  const row = pg.locator(`tr[data-detector="${detector}"]`);
  ok(`${label}: diagnose is real (not a not-simulated panel)`, (await NS()) === 0 && (await row.count()) === 1);
  ok(`${label}: ${detector} = ${status}`, (await row.getAttribute("data-status")) === status);
};
await diag("web app", `appservices/${RG}/${APP}`, "https", "Warning");
await arm("PATCH", site, { properties: { httpsOnly: true } });
await diag("web app after fix", `appservices/${RG}/${APP}`, "https", "Healthy");
await diag("aks", `aks/${RG}/kaks${n}`, "k8s-version", "Warning");
await arm("PATCH", prov("Microsoft.ContainerService", "managedClusters", `kaks${n}`), { properties: { agentPoolProfiles: [{ name: "np", count: 0 }] } });
await diag("aks after scale to 0", `aks/${RG}/kaks${n}`, "nodepools", "Critical");
await diag("apim", `apim/${RG}/kapim${n}`, "sku-sla", "Warning");
await diag("app configuration", `appconfiguration/${RG}/kcfg${n}`, "soft-delete", "Info");
await diag("cognitive services", `cognitiveservices/${RG}/kcog${n}`, "deployments", "Warning");

// Events (preview)
await go("events");
ok("events panel is real", (await NS()) === 0 && (await pg.getByLabel("Add event subscription").count()) === 1);
await pg.getByLabel("Test event type").selectOption("Microsoft.Web.AppUpdated");
await pg.getByLabel("Send test event").click(); await pg.waitForTimeout(800);
ok("send test event reports a result", (await pg.content()).includes("Test event sent") || (await pg.content()).includes("raised"));

// Create wizard: secure unique default hostname + Database + Application Insights
const WA = `wiz${n}`;
await pg.goto(`${UI}#/appservices/create`); await pg.waitForTimeout(1500);
await pg.getByLabel("Resource Group").first().selectOption(RG).catch(() => {});
await pg.getByLabel("Name", { exact: true }).fill(WA);
await pg.getByLabel("Secure unique default hostname on.").check();
ok("wizard previews the hashed hostname", (await pg.getByTestId("default-hostname").innerText()).includes("-<hash>.eastus-01.azurewebsites.net"));
await pg.getByRole("tab", { name: "Database" }).click(); await pg.waitForTimeout(300);
ok("wizard database tab is real", (await NS()) === 0);
await pg.getByLabel("Create a database").check();
await pg.getByLabel("Database server name").fill(`wizsql${n}`); await pg.getByLabel("Database name", { exact: true }).fill("appdb");
await pg.getByLabel("Database admin password").fill("S3cure-Passw0rd!");
await pg.getByRole("tab", { name: "Monitor + secure" }).click(); await pg.waitForTimeout(300);
await pg.getByRole("radio", { name: "Yes" }).first().check();
ok("wizard application insights panel is real", (await NS()) === 0 && (await pg.getByLabel("Application Insights name").count()) === 1);
await pg.getByRole("button", { name: "Review + create" }).click();
await pg.getByText("Validation passed").waitFor({ timeout: 5000 });
await pg.getByRole("button", { name: "Create", exact: true }).click();
// Poll for the real result instead of a fixed sleep: the wizard creates the site + SQL server/db + App Insights, which is slow under load.
const wizDbPath = `${prov("Microsoft.Sql", "servers", `wizsql${n}`)}/databases/appdb`;
for (let i = 0; i < 60; i++) {
  const s1 = (await arm("GET", prov("Microsoft.Web", "sites", WA))).status, s2 = (await arm("GET", wizDbPath, null, "2023-08-01")).status;
  if (s1 === 200 && s2 === 200) break;
  await pg.waitForTimeout(1000);
}
const wsite = (await arm("GET", prov("Microsoft.Web", "sites", WA))).body;
ok("wizard site has the secure hostname", /^wiz\d+-[a-z0-9]{16,}\.eastus-01\.azurewebsites\.net$/.test(wsite?.properties?.defaultHostName || ""), wsite?.properties?.defaultHostName);
ok("wizard created the SQL database", (await arm("GET", `${prov("Microsoft.Sql", "servers", `wizsql${n}`)}/databases/appdb`, null, "2023-08-01")).status === 200);
const wcs = (await arm("GET", `${prov("Microsoft.Web", "sites", WA)}/config/connectionstrings`)).body?.properties || {};
ok("wizard wrote the connection string to the app", wcs.appdb?.type === "SQLAzure" && wcs.appdb.value.includes(`wizsql${n}.database.windows.net`), JSON.stringify(wcs));
const wst = (await arm("GET", `${prov("Microsoft.Web", "sites", WA)}/config/appsettings`)).body?.properties || {};
ok("wizard linked Application Insights", !!wst.APPLICATIONINSIGHTS_CONNECTION_STRING && !!wst.APPINSIGHTS_INSTRUMENTATIONKEY, JSON.stringify(Object.keys(wst)));

console.log(`\n${pass} passed, ${fail} failed`);
await b.close();
process.exit(fail ? 1 : 0);
