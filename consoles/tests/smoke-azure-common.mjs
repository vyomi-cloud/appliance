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

// Activity log (shared): real events for a vnet, edit columns, server-side filters
const VN = `azcvn${n}`;
ok((await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VN}`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.7.0.0/16"] } } }, "2023-04-01")).status < 300, "vnet created over ARM");
await page.goto(`${UI}#/vnets/${RG}/${VN}/activitylog`);
await page.getByRole("table", { name: "Activity log" }).waitFor({ timeout: 20000 });
await page.waitForFunction((v) => document.body.innerText.includes("virtualNetworks/write"), VN, { timeout: 15000 });
ok(true, "activity log lists the vnet write event");
await page.getByRole("button", { name: "Edit columns" }).click();
await page.getByRole("checkbox", { name: "Severity" }).check();
await page.getByRole("button", { name: "OK" }).click();
ok((await page.locator("table.vy-grid th", { hasText: "Severity" }).count()) === 1, "Edit columns adds the Severity column");
await page.getByLabel("Status", { exact: true }).selectOption("Failed");
await page.waitForFunction(() => document.body.innerText.includes("No events to display"), null, { timeout: 10000 });
ok(true, "status filter is applied server-side");
await page.getByRole("button", { name: "Reset filters" }).click();
await page.waitForFunction(() => document.body.innerText.includes("virtualNetworks/write"), null, { timeout: 10000 });
ok(true, "Reset filters restores the events");

// RBAC extras (shared): Classic administrators (real list), Deny assignments, My access
await page.goto(`${UI}#/vnets/${RG}/${VN}/iam`);
await page.getByRole("tab", { name: "Classic administrators" }).waitFor({ timeout: 20000 });
await page.getByRole("tab", { name: "Classic administrators" }).click();
await page.waitForFunction(() => document.body.innerText.includes("admin@vyomi.local"), null, { timeout: 15000 });
ok(true, "Classic administrators lists the account administrator (real ARM read)");
await page.getByRole("tab", { name: "Deny assignments" }).click();
await page.waitForTimeout(800);
ok(!(await page.content()).includes("isn't backed by a Vyomi backend"), "Deny assignments is a real grid, not a Not-simulated panel");
await page.getByRole("tab", { name: "Check access" }).click();
await page.getByRole("button", { name: "View my access" }).click();
await page.waitForFunction(() => document.body.innerText.includes("Role assignments covering this resource"), null, { timeout: 15000 });
ok(true, "My access evaluates the signed-in principal with checkAccess");

// Resource health + Advisor + Diagnostic settings + Resource visualizer (shared)
const KV = `azckv${n}`;
ok((await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`, { location: "eastus", properties: { tenantId: "t", sku: { family: "A", name: "standard" } } }, "2023-02-01")).status < 300, "key vault created over ARM");
await page.goto(`${UI}#/keyvaults/${RG}/${KV}/resourcehealth`);
await page.waitForFunction(() => document.body.innerText.includes("Available"), null, { timeout: 20000 });
ok(true, "Resource health shows the real Available state");
await page.goto(`${UI}#/keyvaults/${RG}/${KV}`);
await page.getByRole("tab", { name: "Recommendations" }).click();
await page.waitForFunction(() => document.body.innerText.includes("Purge protection should be enabled"), null, { timeout: 20000 });
ok(true, "Advisor shows a real Key Vault recommendation on the Overview tab");
await page.getByRole("button", { name: "Dismiss" }).first().click();
await page.waitForFunction(() => document.body.innerText.includes("No active recommendations"), null, { timeout: 15000 });
ok(true, "Dismiss persists a real Advisor suppression");
await page.goto(`${UI}#/keyvaults/${RG}/${KV}/diagnosticsettings`);
await page.getByRole("button", { name: /Create|Add/ }).first().waitFor({ timeout: 20000 });
ok(!(await page.content()).includes("isn't backed by a Vyomi backend"), "Diagnostic settings is a real blade");
await page.goto(`${UI}#/resourcegroups/${RG}/resourcevisualizer`);
await page.locator('[data-testid="viz-node"]').first().waitFor({ timeout: 20000 });
ok((await page.locator('[data-testid="viz-node"]').count()) >= 3, "Resource visualizer draws the group's resources");

// Grid tools (shared BrowseGrid): Open query (Resource Graph) + Assign tags (real ARM PATCH)
await page.goto(`${UI}#/vnets`);
await page.getByRole("button", { name: "Open query" }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "Open query" }).click();
await page.getByRole("button", { name: "Run query" }).click();
await page.getByRole("table", { name: "Query results" }).waitFor({ timeout: 15000 });
await page.waitForFunction((v) => document.querySelector('[aria-label="Query results"]')?.innerText.includes(v), VN, { timeout: 10000 });
ok(true, "Open query returns the vnet from real Resource Graph");
await page.getByRole("button", { name: "Close" }).first().click();
await page.getByText(VN).first().waitFor({ timeout: 10000 });
await page.locator("tbody").getByRole("row").filter({ hasText: VN }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Assign tags" }).click();
await page.getByLabel("Tag name 1").fill("owner");
await page.getByLabel("Tag value 1").fill("azc");
await page.getByRole("button", { name: "Apply" }).click();
await page.waitForTimeout(1500);
const got = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VN}`, null, "2023-04-01");
ok(JSON.parse(got.text).tags?.owner === "azc", "Assign tags merged the tag onto the vnet over ARM");

await browser.close();
console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
