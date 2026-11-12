/* Smoke for the Azure Monitor gap closure: Metrics Add filter / Apply splitting / Save to dashboard,
 * Azure Local clusters, SCOM managed instances (and no remaining "Not simulated" panel on Monitor).
 *   BASE=http://127.0.0.1:9331 node consoles/tests/smoke-azure-monitor-gaps.mjs   (NANO=1 UI_PATH=/nano/v4/azure/ WIRE_PATH=/nano/_wire for Nano) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9331";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vygap-rg${n}`, KV = `vygapkv${n}`, DASH = `vygapdash${n}`, LOC = `vyloc${n}`, SCOM = `vyscom${n}`;
let fails = 0;
const check = (name, ok, detail = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 700) : ""}`); };
let page;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2023-01-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(UI, { waitUntil: "domcontentloaded" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`, { location: "eastus", properties: { tenantId: "x", sku: { family: "A", name: "standard" } } }, "2023-07-01");
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`, { location: "eastus", tags: { a: "1" }, properties: { tenantId: "x", sku: { family: "A", name: "standard" } } }, "2023-07-01");
  const kvId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`;

  // ---- Metrics: dimensions over the wire (what an SDK / az monitor metrics list --filter sends)
  const defs = json(await wire(`${kvId}/providers/Microsoft.Insights/metricDefinitions?api-version=2018-01-01`));
  check("metric definition advertises OperationName + Status dimensions", (defs.value?.[0]?.dimensions || []).map((d) => d.value).join() === "OperationName,Status", defs.value?.[0]?.dimensions);
  const split = json(await wire(`${kvId}/providers/Microsoft.Insights/metrics?api-version=2018-01-01&metricnames=ActivityOperations&interval=PT1H&aggregation=Total&$filter=${encodeURIComponent("OperationName eq '*'")}`));
  const ts = split.value?.[0]?.timeseries || [];
  check("splitting by OperationName returns labelled series", ts.length >= 1 && ts.every((t) => t.metadatavalues?.[0]?.name?.value === "operationname"), JSON.stringify(ts.map((t) => t.metadatavalues)));

  // ---- Metrics UI
  await page.goto(UI + "#/monitor/metrics");
  await page.getByLabel("Metric", { exact: true }).waitFor({ timeout: 20000 });
  await page.waitForFunction(() => { const el = document.querySelector('select[aria-label="Metric"]'); return el && !el.disabled && el.options.length > 0; }, null, { timeout: 20000 });
  await page.getByLabel("Metric", { exact: true }).selectOption("ActivityOperations");
  check("Metrics page no longer declares a Not-simulated gap", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  await page.getByRole("button", { name: "Add filter" }).click();
  await page.getByRole("checkbox").first().waitFor({ timeout: 15000 });
  await page.getByRole("checkbox").first().check();
  await page.getByRole("button", { name: "Apply filter" }).click();
  check("Add filter shows a filter pill", await page.getByTestId("metric-filter-pill").first().waitFor({ timeout: 10000 }).then(() => true, () => false));
  await page.getByRole("button", { name: "Apply splitting" }).click();
  await page.getByLabel("Split by").selectOption("Status");
  check("Apply splitting shows a split pill", await page.getByTestId("metric-split-pill").waitFor({ timeout: 10000 }).then(() => true, () => false));
  await page.getByRole("button", { name: "Save to dashboard" }).click();
  await page.getByLabel("Dashboard name").fill(DASH);
  await page.getByLabel("Dashboard resource group").selectOption(RG).catch(() => {});
  await page.getByRole("button", { name: "Pin to dashboard" }).click();
  check("Save to dashboard reports success", /Saved 1 chart/.test(await page.getByTestId("metric-dashboard-msg").textContent({ timeout: 10000 }).catch(() => "")));
  const dash = json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Portal/dashboards/${DASH}`, null, "2022-12-01-preview"));
  const part = dash.properties?.lenses?.[0]?.parts?.[0];
  check("a real Microsoft.Portal/dashboards resource holds the chart part", !!part && JSON.stringify(part).includes("ActivityOperations") && JSON.stringify(part).includes("Microsoft.KeyVault/vaults/vygapkv") && JSON.stringify(part).includes("Status"), JSON.stringify(dash.properties).slice(0, 600));

  // ---- Azure Local
  await page.goto(UI + "#/monitor/insights-azurelocal");
  await page.getByRole("button", { name: /^Create/ }).first().click();
  await page.getByLabel("Cluster name").fill(LOC);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  check("Azure Local cluster appears in the grid", await page.getByText(LOC).first().waitFor({ timeout: 10000 }).then(() => true, () => false));
  const loc = json(await arm("GET", `/resourceGroups/cloudlearn-rg/providers/Microsoft.AzureStackHCI/clusters/${LOC}`, null, "2024-04-01"));
  check("cluster exists over native ARM with 2 declared nodes", loc.properties?.reportedProperties?.nodes?.length === 2 && loc.properties.status === "ConnectedRecently", JSON.stringify(loc).slice(0, 200));
  check("Azure Local page has no Not-simulated panel", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);

  // ---- SCOM managed instance
  await page.goto(UI + "#/monitor/scommanagedinstance");
  await page.getByRole("button", { name: /^Create/ }).first().click();
  await page.getByLabel("Instance name").fill(SCOM);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  check("SCOM instance appears in the grid", await page.getByText(SCOM).first().waitFor({ timeout: 10000 }).then(() => true, () => false));
  const sc = json(await arm("GET", `/resourceGroups/cloudlearn-rg/providers/Microsoft.Scom/managedInstances/${SCOM}`, null, "2023-07-07-preview"));
  check("SCOM instance exists over native ARM", sc.properties?.domainControllerProperties?.domainName === "corp.local", JSON.stringify(sc).slice(0, 200));
  check("SCOM page has no Not-simulated panel", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);

  // cleanup
  await arm("DELETE", `/resourceGroups/cloudlearn-rg/providers/Microsoft.AzureStackHCI/clusters/${LOC}`, null, "2024-04-01");
  await arm("DELETE", `/resourceGroups/cloudlearn-rg/providers/Microsoft.Scom/managedInstances/${SCOM}`, null, "2023-07-07-preview");
  await arm("DELETE", `/resourceGroups/${RG}/providers/Microsoft.Portal/dashboards/${DASH}`, null, "2022-12-01-preview");
  check("no uncaught page errors", errors.length === 0, errors.join(" | "));
} catch (e) { fails++; console.log("FAIL exception - " + e.message); }
await browser.close();
console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
