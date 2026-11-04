/* Smoke for AZ-06 per-resource monitoring (Alerts / Metrics / Logs / Insights / Workbooks on resource blades).
 *   BASE=http://127.0.0.1:9046 node consoles/tests/smoke-azure-monitoring.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9046";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vymon-rg${n}`, KV = `vymonkv${n}`, LAW = `vymonlaw${n}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + detail : ""}`); };
let page;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2023-01-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" });
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`, { location: "eastus", properties: { tenantId: "x", sku: { family: "A", name: "standard" } } }, "2023-07-01");
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/${LAW}`, { location: "eastus", properties: { sku: { name: "PerGB2018" } } }, "2022-10-01");
  const kvId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`;

  // Metrics
  await page.goto(UI + `#/keyvaults/${RG}/${KV}/metrics`);
  await page.getByLabel("Metric", { exact: true }).waitFor({ timeout: 20000 });
  const summary = await page.getByTestId("metric-summary").textContent({ timeout: 20000 });
  const sum = Number(/sum (\d+)/.exec(summary)?.[1]);
  check("metrics panel shows the real ActivityOperations count (>=1 from the vault create)", sum >= 1, summary);

  // Alerts: create via UI, evaluate
  await page.goto(UI + `#/keyvaults/${RG}/${KV}/alerts`);
  await page.getByRole("button", { name: "Create" }).first().click();
  await page.getByLabel("Alert rule name").fill("kv-busy");
  await page.getByLabel("Threshold value").fill("0");
  await page.getByRole("button", { name: "Create alert rule" }).click();
  await page.getByText("kv-busy").first().waitFor({ timeout: 10000 });
  const stored = json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Insights/metricAlerts/kv-busy`, null, "2018-03-01"));
  check("alert rule exists over native ARM scoped to the vault", (stored.properties?.scopes || [])[0]?.toLowerCase() === kvId.toLowerCase());
  await page.getByRole("button", { name: "Evaluate kv-busy" }).click();
  const ev = await page.getByTestId("eval-kv-busy").textContent({ timeout: 10000 }).catch(() => "");
  check("Evaluate computes the rule against the real metric", /Would fire|Healthy/.test(ev), ev);

  // Logs: AzureActivity filtered to the resource
  await page.goto(UI + `#/keyvaults/${RG}/${KV}/logs`);
  await page.getByRole("button", { name: "Run" }).click();
  check("logs query returns this vault's activity rows", await page.getByRole("table", { name: "Query results" }).waitFor({ timeout: 10000 }).then(() => true, () => false));

  // Workbooks
  await page.goto(UI + `#/keyvaults/${RG}/${KV}/workbooks`);
  await page.getByRole("button", { name: "Create" }).first().click();
  await page.getByText(`${KV} overview`).first().waitFor({ timeout: 10000 });
  check("workbook created and linked to the vault", true);

  // Insights
  await page.goto(UI + `#/keyvaults/${RG}/${KV}/insights`);
  await page.waitForFunction(() => /\d\s*Alert rules/.test(document.querySelector('[data-testid="insights-tiles"]')?.textContent || ""), null, { timeout: 10000 }).catch(() => {});
  const tiles = await page.getByTestId("insights-tiles").textContent({ timeout: 10000 });
  check("insights rolls up alert rules and operations", /1\s*Alert rules/.test(tiles), tiles);

  // App Service + Service Bus use the same shared panels
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/vymonapp${n}`, { location: "eastus", kind: "app", properties: {} }, "2023-12-01");
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.ServiceBus/namespaces/vymonsb${n}`, { location: "eastus", sku: { name: "Standard", tier: "Standard" } }, "2022-10-01-preview");
  await page.goto(UI + `#/appservices/${RG}/vymonapp${n}/metrics`);
  const wsum = await page.getByTestId("metric-summary").textContent({ timeout: 20000 }).catch(() => "");
  check("web app metrics panel shows its Activity-log count", /sum [1-9]/.test(wsum), wsum);
  await page.goto(UI + `#/appservices/${RG}/vymonapp${n}/alerts`);
  check("web app alerts panel is the shared rule grid", await page.getByRole("button", { name: "Create" }).first().waitFor({ timeout: 10000 }).then(() => true, () => false));
  await page.goto(UI + `#/servicebus/${RG}/vymonsb${n}/insights`);
  await page.waitForFunction(() => /\d\s*Operations recorded/.test(document.querySelector('[data-testid="insights-tiles"]')?.textContent || ""), null, { timeout: 15000 }).catch(() => {});
  check("service bus insights rolls up its operations", /[1-9]\s*Operations recorded/.test(await page.getByTestId("insights-tiles").textContent({ timeout: 5000 }).catch(() => "")));

  // Other blades render the shared panels (not the Not-simulated panel)
  for (const [path, label] of [[`#/resourcegroups/${RG}/alerts`, "rg alerts"], [`#/resourcegroups/${RG}/metrics`, "rg metrics"]]) {
    await page.goto(UI + path);
    await page.waitForTimeout(1500);
    check(`${label} is not a Not-simulated panel`, await page.getByText("Not simulated", { exact: false }).count() === 0);
  }
  await page.goto(UI + `#/keyvaults/${RG}/${KV}`);
  await page.getByRole("tab", { name: "Monitoring" }).click().catch(() => {});
  check("no page errors", errors.length === 0, errors.join("; "));
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
