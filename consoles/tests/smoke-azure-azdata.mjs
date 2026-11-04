/* Smoke: Tasks blades (App Service + AKS) and the APIM gateway (Test the gateway -> Analytics, Capacity gauge).
 *   BASE=http://127.0.0.1:9085 node consoles/tests/smoke-azure-azdata.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9085";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vyaz-rg${n}`;
let page; let fails = 0;
const check = (name, ok, d = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + d : ""}`); };
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2023-05-01-preview") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(UI, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
  const P = (ns, t, name) => `/resourceGroups/${RG}/providers/Microsoft.${ns}/${t}/${name}`;
  // ── Tasks on a web app
  const W = `vyapp${n}`;
  await arm("PUT", P("Web", "serverfarms", "plan1"), { location: "eastus", sku: { name: "B1" } }, "2023-01-01");
  await arm("PUT", P("Web", "sites", W), { location: "eastus", properties: { serverFarmId: `/subscriptions/${SUB}${P("Web", "serverfarms", "plan1")}` } }, "2023-01-01");
  await page.goto(UI + `#/appservices/${RG}/${W}/tasks`);
  await page.getByRole("button", { name: /Create task from Restart the web app/ }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("link", { name: `task-webapp-restart-${W}`.slice(0, 80) }).waitFor({ timeout: 10000 });
  check("task created from template and listed", true);
  await page.getByRole("button", { name: "Run now" }).click();
  await page.getByText("Succeeded").first().waitFor({ timeout: 10000 }).then(() => check("Run now -> Succeeded run in history", true), () => check("Run now -> Succeeded run in history", false));
  const runs = json(await arm("GET", P("Logic", "workflows", `task-webapp-restart-${W}`.slice(0, 80)) + "/runs", null, "2019-05-01"));
  check("run really recorded over ARM", runs.value?.[0]?.properties?.vyomiActions?.Restart_site?.response?.statusCode === 200);
  check("no Not-simulated panel on Tasks", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  // ── APIM gateway
  const A = `vyapim${n}`;
  await arm("PUT", P("ApiManagement", "service", A), { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.c", publisherName: "x" } });
  await arm("PUT", P("ApiManagement", "service", A) + "/apis/echo", { properties: { displayName: "Echo", path: "echo", serviceUrl: "http://127.0.0.1:9/none" } });
  await arm("PUT", P("ApiManagement", "service", A) + "/apis/echo/operations/mock", { properties: { displayName: "mock", method: "GET", urlTemplate: "/mock" } });
  await arm("PUT", P("ApiManagement", "service", A) + "/apis/echo/policies/policy", { properties: { format: "xml", value: '<policies><inbound><base /><mock-response status-code="200" content-type="application/json" /></inbound><backend><base /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>' } });
  const key = json(await arm("POST", P("ApiManagement", "service", A) + "/subscriptions/master/listSecrets")).primaryKey;
  const noKey = await wire(`/azure-data/apim/${A}/echo/mock`);
  check("gateway rejects a call without a key (401)", noKey.status === 401);
  const ok = await wire(`/azure-data/apim/${A}/echo/mock`, { headers: { "Ocp-Apim-Subscription-Key": key } });
  check("gateway serves the mock-response with a key (200)", ok.status === 200);
  await page.goto(UI + `#/apim/${RG}/${A}/analytics`);
  await page.getByRole("heading", { name: "Requests by API" }).waitFor({ timeout: 15000 });
  check("Analytics shows the real gateway requests", (await page.getByText("echo", { exact: true }).count()) >= 1);
  await page.goto(UI + `#/apim/${RG}/${A}`);
  await page.getByRole("tab", { name: "Capacity" }).click();
  await page.getByRole("meter", { name: "Gateway capacity" }).waitFor({ timeout: 10000 }).then(() => check("Capacity gauge rendered from real requests", true), () => check("Capacity gauge rendered from real requests", false));
  check("no Not-simulated panel on Capacity", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
} catch (e) { fails++; console.log("FAIL exception - " + e.message); }
if (errors.length) { fails++; console.log("FAIL page errors - " + errors.slice(0, 3).join(" | ")); }
await browser.close();
process.exit(fails ? 1 : 0);
