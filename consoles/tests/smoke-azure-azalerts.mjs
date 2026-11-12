/* Defender alert detail page: status updates, history, remediation over native ARM.
 *   PW=... BASE=http://127.0.0.1:9082 node consoles/tests/smoke-azure-azalerts.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9082";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `alrt-rg${n}`, SA = `alrtsa${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
const sa = `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`;
await arm("PUT", sa, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { allowBlobPublicAccess: false } }, "2023-01-01");
await arm("PUT", "/providers/Microsoft.Security/pricings/StorageAccounts", { properties: { pricingTier: "Standard" } }, "2023-01-01");
await arm("PATCH", sa, { properties: { allowBlobPublicAccess: true } }, "2023-01-01");

await page.goto(UI + "#/defender/alerts");
await page.getByRole("link", { name: "Storage was opened to anonymous access" }).first().click();
await page.getByText("Remediation steps").waitFor({ timeout: 15000 });
check("detail page shows the alert type", await page.getByText("VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED").count() > 0);
await page.getByRole("button", { name: "Set in progress" }).click();
await page.getByRole("cell", { name: "InProgress", exact: true }).waitFor({ timeout: 10000 });
check("history records the in-progress change", await page.getByRole("cell", { name: "inprogress", exact: true }).count() === 1);
await page.getByRole("button", { name: /Take action/ }).click();
await page.getByText("Remediation applied", { exact: true }).first().waitFor({ timeout: 10000 });
const acct = json(await arm("GET", sa, null, "2023-01-01"));
check("remediation turned public blob access off on the account", acct.properties?.allowBlobPublicAccess === false);
check("alert is Resolved", await page.getByText("Resolved", { exact: true }).count() > 0);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
