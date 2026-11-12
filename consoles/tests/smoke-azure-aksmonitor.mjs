/* AKS Monitor settings: Container Insights / Managed Prometheus / Grafana toggles create + remove real DCRs.
 *   BASE=http://127.0.0.1:9103 node consoles/tests/smoke-azure-aksmonitor.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9103";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await page.goto(UI);
await page.waitForTimeout(1500);
const S = "00000000-0000-0000-0000-cloudlearn01";
const put = (p, b) => page.evaluate(async ([u, p, b]) => { const r = await fetch(u + p, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) }); return r.status; }, [WIRE, p, b]);
await put(`/subscriptions/${S}/resourcegroups/am-rg?api-version=2021-04-01`, { location: "eastus" });
const c = await put(`/subscriptions/${S}/resourceGroups/am-rg/providers/Microsoft.ContainerService/managedClusters/aksm?api-version=2024-09-02-preview`, { location: "eastus", properties: { dnsPrefix: "aksm" } });
check("seed cluster", c < 300, c);
const rows = () => page.getByRole("table", { name: "Data collection rules" }).innerText();
await page.goto(`${UI}#/aks/am-rg/aksm/monitorsettings`);
await page.getByLabel("Enable Managed Prometheus").waitFor({ timeout: 20000 });
await page.getByLabel("Enable Managed Prometheus").check();
await page.getByLabel("Enable Managed Grafana").check();
await page.getByRole("button", { name: "Apply" }).click();
await page.getByTestId("mon-grafana").waitFor({ timeout: 15000 });
await page.waitForTimeout(800);
let t = await rows();
check("Prometheus + Grafana: DCR created and linked", /MSProm-eastus-aksm/.test(t) && /ContainerInsightsMetricsExtension/.test(t) && /DefaultAzureMonitorWorkspace-eastus/.test(t), t.replace(/\s+/g, " "));
check("Grafana workspace shown", /DefaultGrafana-eastus/.test(await page.getByTestId("mon-grafana").innerText()));
await page.getByLabel("Enable Container Insights").check();
await page.getByRole("button", { name: "Apply" }).click();
await page.waitForFunction(() => /MSCI-eastus-aksm/.test(document.body.innerText), null, { timeout: 15000 });
t = await rows();
check("Container Insights: DCR to a (new) Log Analytics workspace", /MSCI-eastus-aksm/.test(t) && /DefaultWorkspace-eastus/.test(t) && /MSProm-eastus-aksm/.test(t), t.replace(/\s+/g, " "));
await page.getByLabel("Enable Container Insights").uncheck();
await page.getByLabel("Enable Managed Prometheus").uncheck();
await page.getByRole("button", { name: "Apply" }).click();
await page.waitForFunction(() => /No data collection rules are associated/.test(document.body.innerText), null, { timeout: 15000 });
check("toggling off removes the DCRs", true);
await page.goto(`${UI}#/aks/create`);
await page.getByRole("tab", { name: "Monitoring" }).click();
await page.getByLabel("Log Analytics workspace").waitFor({ timeout: 15000 });
check("create wizard offers a Log Analytics workspace", true);
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
