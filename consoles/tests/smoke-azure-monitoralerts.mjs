/* Azure Monitor alerts end to end: a metric alert and a log-search alert are RAISED by real evaluation, the action group's
 * webhook receives a real HTTP POST, the Alerts blade shows/changes them, processing rules + DCR Resources + KQL are real.
 *   PW=/path/to/playwright BASE=http://127.0.0.1:8741 node consoles/tests/smoke-azure-monitoralerts.mjs   (fresh dev server) */
import { createRequire } from "node:module";
import http from "node:http";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8741";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `mal-rg${n}`, SA = `malsa${n}`, AG = `malag${n}`, WS = `malws${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const hits = [];
const srv = http.createServer((q, r) => { let b = ""; q.on("data", (c) => (b += c)); q.on("end", () => { try { hits.push(JSON.parse(b)); } catch { /* ignore */ } r.end("ok"); }); });
await new Promise((res) => srv.listen(0, "127.0.0.1", res));
const HOOK = `http://127.0.0.1:${srv.address().port}/hook`;
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: "networkidle" });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
const rgp = `/resourceGroups/${RG}/providers`;
const ag = json(await arm("PUT", `${rgp}/Microsoft.Insights/actionGroups/${AG}`, { location: "Global", properties: { groupShortName: "mal", enabled: true, webhookReceivers: [{ name: "hook", serviceUri: HOOK, useCommonAlertSchema: true }] } }, "2023-01-01"));
const sa = `${rgp}/Microsoft.Storage/storageAccounts/${SA}`;
await arm("PUT", sa, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: {} }, "2023-01-01");
await arm("PUT", `${rgp}/Microsoft.Insights/metricAlerts/ops${n}`, { location: "global", properties: { severity: 1, enabled: true, scopes: [`/subscriptions/${SUB}${sa}`], evaluationFrequency: "PT1M", windowSize: "PT5M",
  criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [{ name: "c1", metricName: "ActivityOperations", operator: "GreaterThan", timeAggregation: "Total", threshold: 0 }] }, actions: [{ actionGroupId: ag.id }] } }, "2018-03-01");
const ws = `${rgp}/Microsoft.OperationalInsights/workspaces/${WS}`;
await arm("PUT", ws, { location: "eastus", properties: {} }, "2022-10-01");
await wire(`/subscriptions/${SUB}${ws}/api/logs?api-version=2022-10-01&logType=App`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify([{ level: "Error", ms: 900 }, { level: "Error", ms: 700 }, { level: "Info", ms: 5 }]) });
await arm("PUT", `${rgp}/Microsoft.Insights/scheduledQueryRules/errs${n}`, { location: "eastus", properties: { severity: 2, enabled: true, scopes: [`/subscriptions/${SUB}${ws}`], evaluationFrequency: "PT5M", windowSize: "PT15M",
  criteria: { allOf: [{ query: "App_CL | where level_s == 'Error'", timeAggregation: "Count", operator: "GreaterThan", threshold: 1 }] }, actions: { actionGroups: [ag.id] } } }, "2023-03-15-preview");

await page.goto(UI + "#/monitor/alerts");
await page.getByRole("tab", { name: "Alerts", exact: true }).waitFor({ timeout: 20000 });
await page.getByRole("cell", { name: `ops${n}`, exact: true }).waitFor({ timeout: 20000 });
check("metric alert RAISED by real evaluation shows in the Alerts blade", await page.getByRole("cell", { name: `ops${n}`, exact: true }).count() > 0);
check("log-search alert RAISED by the real KQL engine shows too", await page.getByRole("cell", { name: `errs${n}`, exact: true }).count() > 0);
check("summary counts the real alerts (>= 2)", Number((await page.locator(".vy-kv", { hasText: "Total alerts" }).innerText()).replace(/\D/g, "")) >= 2);
check("action group webhook RECEIVED real HTTP POSTs", hits.length >= 2 && hits.every((h) => h.schemaId === "azureMonitorCommonAlertSchema"), JSON.stringify(hits.map((h) => h.data?.essentials?.alertRule)));
// change user response through the UI
await page.getByRole("row", { name: new RegExp(`ops${n}`) }).getByRole("checkbox").check();
await page.getByRole("button", { name: /Change user response: Acknowledged/ }).click();
await page.getByRole("cell", { name: "Acknowledged" }).first().waitFor({ timeout: 10000 });
const alerts = json(await arm("GET", "/providers/Microsoft.AlertsManagement/alerts", null, "2019-03-01")).value || [];
check("UI user-response change persisted in the backend", alerts.some((a) => a.properties.essentials.alertRule.includes(`ops${n}`) && a.properties.essentials.alertState === "Acknowledged"));
// timeline
await page.getByRole("tab", { name: "View as timeline" }).click();
await page.getByText("Alert fired (monitor condition Fired, state New)").first().waitFor({ timeout: 10000 });
check("timeline shows real alert history", await page.getByText(/webhook .*delivered/).count() > 0);
// processing rule via UI
await page.getByRole("tab", { name: "Alert processing rules" }).click();
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByLabel("Rule name").fill(`mute${n}`);
await page.getByLabel("Resource group").fill(RG);
await page.getByRole("button", { name: "Create", exact: true }).last().click();
await page.getByRole("cell", { name: `mute${n}`, exact: true }).waitFor({ timeout: 10000 });
check("alert processing rule created from the UI exists over ARM", json(await arm("GET", `${rgp}/Microsoft.AlertsManagement/actionRules/mute${n}`, null, "2021-08-08")).properties?.actions?.[0]?.actionType === "RemoveAllActionGroups");
// DCR resources
const dcr = `${rgp}/Microsoft.Insights/dataCollectionRules/dcr${n}`;
await arm("PUT", dcr, { location: "eastus", properties: { destinations: { logAnalytics: [{ name: "d1", workspaceResourceId: `/subscriptions/${SUB}${ws}` }] }, dataFlows: [{ streams: ["Microsoft-Event"], destinations: ["d1"] }], dataSources: {} } }, "2023-03-11");
await arm("PUT", `${sa}/providers/Microsoft.Insights/dataCollectionRuleAssociations/assoc${n}`, { properties: { dataCollectionRuleId: `/subscriptions/${SUB}${dcr}` } }, "2023-03-11");
await page.goto(UI + "#/monitor/datacollectionrules");
await page.getByRole("tab", { name: "Resources" }).click();
await page.getByRole("cell", { name: SA, exact: true }).waitFor({ timeout: 15000 });
check("DCR Resources tab lists the real association", await page.getByRole("cell", { name: `assoc${n}`, exact: true }).count() > 0);
// KQL via Logs blade
await page.goto(UI + "#/monitor/logs");
await page.getByLabel("KQL query").fill("App_CL | summarize n=count() by level_s | order by n desc");
await page.getByRole("button", { name: "Run", exact: true }).click();
await page.getByRole("cell", { name: "Error", exact: true }).waitFor({ timeout: 10000 });
check("Logs blade runs summarize/by/order over ingested rows", await page.getByRole("cell", { name: "Info", exact: true }).count() > 0);
// Change analysis group by
await page.goto(UI + "#/monitor/changeanalysis");
await page.getByLabel("Group by").selectOption("type");
await page.getByRole("columnheader", { name: "Changes" }).waitFor({ timeout: 10000 });
check("Change analysis group-by renders grouped counts", await page.getByRole("cell", { name: "Microsoft.Storage/storageAccounts", exact: true }).count() > 0);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close(); srv.close();
process.exit(bad ? 1 : 0);
