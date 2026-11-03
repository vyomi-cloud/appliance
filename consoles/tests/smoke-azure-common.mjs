/* Smoke for the shared Azure blades (Export template, ...) against a running /_wire backend.
 *   BASE=http://127.0.0.1:9140 UI_PATH=/v4/azure/ node consoles/tests/smoke-azure-common.mjs
 *   BASE=http://127.0.0.1:8840 UI_PATH=/nano/v4/azure/ WIRE_PATH=/nano/_wire ...   (Nano) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); } catch { pw = require(process.env.PW); }
const BASE = process.env.BASE || "http://127.0.0.1:9140";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "azc-rg";
const n = Date.now() % 100000;
const ZONE = `azc${n}.com`;
let fails = 0;
const ok = (c, m) => { console.log(`${c ? "PASS" : "FAIL"} ${m}`); if (!c) fails++; };
let page;
// ARM calls run inside the page so the Nano service worker (which serves /_wire) sees them too.
const arm = (method, path, body, v = "2021-04-01") => page.evaluate(async ([u, method, body]) => {
  const r = await fetch(u, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, text: await r.text() };
}, [`${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, method, body]);

const browser = await pw.chromium.launch();
page = await (await browser.newContext({ viewport: { width: 1500, height: 950 } })).newPage();
await page.goto(UI, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(Number(process.env.BOOT_MS || 2000));
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" });
ok((await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/dnszones/${ZONE}`, { location: "global", tags: { env: "dev" }, properties: { zoneType: "Public" } }, "2018-05-01")).status < 300, "zone created over ARM");

// Export template (ARM / Bicep / Terraform)
await page.goto(`${UI}#/dns/${RG}/${ZONE}/exporttemplate`);
const ta = page.locator('[data-testid="export-text"]');
await ta.waitFor({ timeout: 20000 });
await page.waitForFunction(() => document.querySelector('[data-testid="export-text"]')?.value.includes("dnszones"), null, { timeout: 15000 });
ok((await ta.inputValue()).includes(ZONE), "ARM tab shows the zone template");
await page.getByRole("tab", { name: "Bicep" }).click();
ok((await ta.inputValue()).includes("resource ") && (await ta.inputValue()).includes("Microsoft.Network/dnszones@"), "Bicep tab is real Bicep");
await page.getByRole("tab", { name: "Terraform" }).click();
ok((await ta.inputValue()).includes('resource "azapi_resource"'), "Terraform tab is real HCL");
ok(!(await page.content()).includes("isn't backed by a Vyomi backend"), "no Not-simulated panel on export");

await browser.close();
console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
