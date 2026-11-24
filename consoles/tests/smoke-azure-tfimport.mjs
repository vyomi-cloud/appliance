/* Azure export -> Terraform (azurerm) -> import -> deploy round trip, driven through the real console + ARM wire.
 *   BASE=http://127.0.0.1:8761 UI_PATH=/nano/v4/azure/ WIRE_PATH=/nano/_wire NANO=1 node consoles/tests/smoke-azure-tfimport.mjs
 *   (appliance) BASE=http://127.0.0.1:9140 UI_PATH=/v4/azure/ WIRE_PATH=/_wire node consoles/tests/smoke-azure-tfimport.mjs
 * Env: SHOTS=<dir> to keep screenshots, CHROME_BIN=<path> to use an installed Chrome instead of Playwright's bundle. */
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); } catch { pw = require(process.env.PW); }
const BASE = process.env.BASE || "http://127.0.0.1:9140";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SHOTS = process.env.SHOTS || "";
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 1000000;
const A = `tfa${n}`, B = `tfb${n}`;
const S = (x) => `${x}${String(n).slice(-5)}`;                 // globally unique names
const names = { st: S("stvy"), kv: S("kvvy"), sb: S("sbvy"), sql: S("sqlvy"), acr: S("acrvy"), web: S("webvy"), law: S("lawvy"), cos: S("cosvy") };
let fails = 0;
const ok = (c, m) => { console.log(`${c ? "PASS" : "FAIL"} ${m}`); if (!c) fails++; };
let page;
const arm = (method, path, body, v = "2021-04-01") => page.evaluate(async ([u, method, body]) => {
  const r = await fetch(u, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, text: await r.text() };
}, [`${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, method, body]);
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` }); };

const launch = { headless: true };
if (process.env.CHROME_BIN) launch.executablePath = process.env.CHROME_BIN;
const browser = await pw.chromium.launch(launch);
page = await (await browser.newContext({ viewport: { width: 1500, height: 1000 } })).newPage();
page.on("pageerror", (e) => console.log("pageerror", String(e).slice(0, 200)));
await page.goto(UI, { waitUntil: "domcontentloaded" });
for (let i = 0; i < 90; i++) { try { if ((await arm("PUT", `/resourcegroups/${A}`, { location: "eastus" })).status < 300) break; } catch {} await page.waitForTimeout(1000); }

const R = `/resourceGroups/${A}/providers`;
const make = [
  ["Microsoft.ManagedIdentity/userAssignedIdentities/uami1", "2023-01-31", { location: "eastus" }],
  ["Microsoft.Network/networkSecurityGroups/nsg1", "2023-05-01", { location: "eastus", properties: { securityRules: [{ name: "allow-ssh", properties: { priority: 100, direction: "Inbound", access: "Allow", protocol: "Tcp", sourcePortRange: "*", destinationPortRange: "22", sourceAddressPrefix: "10.0.0.0/8", destinationAddressPrefix: "*" } }] } }],
  ["Microsoft.Network/virtualNetworks/vnet1", "2023-05-01", { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] }, subnets: [{ name: "app", properties: { addressPrefix: "10.0.1.0/24", networkSecurityGroup: { id: `/subscriptions/${SUB}${R}/Microsoft.Network/networkSecurityGroups/nsg1` } } }, { name: "data", properties: { addressPrefix: "10.0.2.0/24" } }] } }],
  ["Microsoft.Network/publicIPAddresses/pip1", "2023-05-01", { location: "eastus", sku: { name: "Standard" }, properties: { publicIPAllocationMethod: "Static" } }],
  [`Microsoft.Storage/storageAccounts/${names.st}`, "2023-01-01", { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { minimumTlsVersion: "TLS1_2", supportsHttpsTrafficOnly: true } }],
  [`Microsoft.KeyVault/vaults/${names.kv}`, "2023-02-01", { location: "eastus", properties: { tenantId: "11111111-1111-1111-1111-111111111111", sku: { family: "A", name: "standard" }, enableRbacAuthorization: true, enableSoftDelete: true, softDeleteRetentionInDays: 7 } }],
  [`Microsoft.OperationalInsights/workspaces/${names.law}`, "2022-10-01", { location: "eastus", properties: { sku: { name: "PerGB2018" }, retentionInDays: 30 } }],
  [`Microsoft.ServiceBus/namespaces/${names.sb}`, "2022-10-01-preview", { location: "eastus", sku: { name: "Standard", tier: "Standard" } }],
  [`Microsoft.ServiceBus/namespaces/${names.sb}/queues/orders`, "2022-10-01-preview", { properties: { maxDeliveryCount: 5, lockDuration: "PT1M" } }],
  [`Microsoft.ServiceBus/namespaces/${names.sb}/topics/events`, "2022-10-01-preview", { properties: { defaultMessageTimeToLive: "P1D" } }],
  [`Microsoft.Sql/servers/${names.sql}`, "2022-05-01-preview", { location: "eastus", properties: { administratorLogin: "sqladmin", administratorLoginPassword: "S3cret-Pass-123!", version: "12.0" } }],
  [`Microsoft.Sql/servers/${names.sql}/databases/appdb`, "2022-05-01-preview", { location: "eastus", sku: { name: "S0", tier: "Standard" }, properties: { collation: "SQL_Latin1_General_CP1_CI_AS", maxSizeBytes: 2147483648 } }],
  [`Microsoft.DocumentDB/databaseAccounts/${names.cos}`, "2023-04-15", { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }], consistencyPolicy: { defaultConsistencyLevel: "Session" } } }],
  ["Microsoft.Web/serverfarms/plan1", "2022-09-01", { location: "eastus", kind: "linux", sku: { name: "B1", tier: "Basic" }, properties: { reserved: true } }],
  [`Microsoft.Web/sites/${names.web}`, "2022-09-01", { location: "eastus", kind: "app,linux", properties: { serverFarmId: `/subscriptions/${SUB}${R}/Microsoft.Web/serverfarms/plan1`, httpsOnly: true, siteConfig: { linuxFxVersion: "NODE|18-lts", alwaysOn: true } } }],
  [`Microsoft.ContainerRegistry/registries/${names.acr}`, "2023-07-01", { location: "eastus", sku: { name: "Basic" }, properties: { adminUserEnabled: false } }],
  [`Microsoft.Network/dnszones/${A}.example.com`, "2018-05-01", { location: "global" }],
  [`Microsoft.Network/dnszones/${A}.example.com/A/www`, "2018-05-01", { properties: { TTL: 300, ARecords: [{ ipv4Address: "10.1.2.3" }] } }],
  [`Microsoft.Network/dnszones/${A}.example.com/CNAME/blog`, "2018-05-01", { properties: { TTL: 300, CNAMERecord: { cname: `www.${A}.example.com` } } }],
];
let created = 0;
for (const [rel, v, body] of make) {
  const r = await arm("PUT", `${R}/${rel}`, body, v);
  if (r.status < 300) created++; else console.log("create failed", rel, r.status, r.text.slice(0, 160));
}
ok(created === make.length, `${created}/${make.length} resources created over the real ARM wire in ${A}`);

// ── Export template page of the resource group ──
await page.goto(`${UI}#/resourcegroups/${A}/exporttemplate`);
const ta = page.locator('[data-testid="export-text"]');
await ta.waitFor({ timeout: 30000 });
await page.waitForFunction(() => /virtualNetworks/.test(document.querySelector('[data-testid="export-text"]')?.value || ""), null, { timeout: 30000 });
const arm_text = await ta.inputValue();
ok(/resourceId\('Microsoft\.Network\/networkSecurityGroups'/.test(arm_text) && arm_text.includes('"dependsOn"'), "ARM tab: resourceId() cross-references + dependsOn");
await shot("01-export-arm");
await page.getByRole("tab", { name: "Bicep" }).click();
ok((await ta.inputValue()).includes("id: nsg1.id"), "Bicep tab: symbolic reference (nsg1.id)");
await page.getByRole("tab", { name: "Terraform" }).click();
const tf = await ta.inputValue();
await shot("02-export-terraform");
for (const t of ["azurerm_resource_group", "azurerm_virtual_network", "azurerm_subnet", "azurerm_network_security_group", "azurerm_public_ip", "azurerm_storage_account", "azurerm_key_vault",
  "azurerm_mssql_server", "azurerm_mssql_database", "azurerm_cosmosdb_account", "azurerm_servicebus_namespace", "azurerm_servicebus_queue", "azurerm_servicebus_topic", "azurerm_service_plan",
  "azurerm_linux_web_app", "azurerm_container_registry", "azurerm_dns_zone", "azurerm_dns_a_record", "azurerm_dns_cname_record", "azurerm_log_analytics_workspace", "azurerm_user_assigned_identity"]) {
  ok(tf.includes(`resource "${t}"`), `Terraform has ${t}`);
}
ok(!tf.includes("azapi_resource"), "no azapi fallback needed for these types");
ok(tf.includes("azurerm_virtual_network.vnet1.name") && tf.includes("azurerm_mssql_server.") && tf.includes("var.") && !tf.includes("S3cret"), "cross-references; secrets are variables");
writeFileSync(`${SHOTS || "/tmp"}/export-a.tf`, tf);

// ── Import that Terraform into a fresh resource group through Deployments > Deploy template ──
ok((await arm("PUT", `/resourcegroups/${B}`, { location: "eastus" })).status < 300, `fresh resource group ${B}`);
const renamed = Object.values(names).reduce((t, nm) => t.replace(new RegExp(`(\\bname\\s+=\\s+)"${nm}"`, "g"), `$1"${nm}b"`), tf)
  .replace(new RegExp(`(\\bname\\s+=\\s+)"${A}\\.example\\.com"`, "g"), `$1"${B}.example.com"`).split(`www.${A}.example.com`).join(`www.${B}.example.com`)
  .replace(/(variable "resource_group_name" \{[^}]*default\s+= )"[^"]+"/, `$1"${B}"`);
writeFileSync(`${SHOTS || "/tmp"}/import-b.tf`, renamed);
await page.goto(`${UI}#/resourcegroups/${B}/deployments`);
await page.getByTestId("deploy-template-open").waitFor({ timeout: 30000 });
await shot("03-deployments-before");
await page.getByTestId("deploy-template-open").click();
await page.getByRole("tab", { name: /Import Terraform/ }).click();
// drop the .tf through the file input (same handler as drag-and-drop)
await page.getByTestId("deploy-file").setInputFiles({ name: "main.tf", mimeType: "text/plain", buffer: Buffer.from(renamed) });
await page.waitForFunction(() => document.querySelector('[data-testid="deploy-text"]')?.value.includes("azurerm_virtual_network"), null, { timeout: 10000 });
await page.getByTestId("deploy-load").click();
await page.getByTestId("tf-report").waitFor({ timeout: 30000 });
const report = await page.getByTestId("tf-report").innerText();
ok(/Converted \d+ Terraform resource/.test(report), `import report: ${report.split("\n")[0]}`);
await shot("04-import-converted");
await page.getByLabel(new RegExp("^Parameter .*administrator_login_password")).fill("Pw-12345!x");
await page.getByLabel("Deployment name", { exact: true }).fill("tf-import");
await page.getByTestId("deploy-whatif").click();
await page.getByTestId("whatif-result").waitFor({ timeout: 30000 });
const wi = await page.getByTestId("whatif-result").innerText();
ok(/Create/.test(wi) && !/Modify|Delete/.test(wi), "what-if lists Create for every resource (nothing to modify/delete in a fresh group)");
await shot("05-whatif");
await page.getByTestId("deploy-go").click();
await page.waitForFunction(() => !document.querySelector('[data-testid="deploy-go"]'), null, { timeout: 90000 }).catch(() => {});
await page.waitForTimeout(1500);
const err = await page.getByTestId("deploy-error").count() ? await page.getByTestId("deploy-error").innerText() : "";
ok(!err, `deployment succeeded${err ? ": " + err : ""}`);
await shot("06-deployments-after");
const res = JSON.parse((await arm("GET", `/resourceGroups/${B}/resources`, null)).text).value || [];
ok(res.length >= 20, `${res.length} resources exist in ${B} after the import`);
const dep = JSON.parse((await arm("GET", `/resourceGroups/${B}/providers/Microsoft.Resources/deployments/tf-import`, null)).text);
ok(dep.properties?.provisioningState === "Succeeded", `deployment tf-import is ${dep.properties?.provisioningState}`);

// ── Second export round-trips equal modulo names ──
await page.goto(`${UI}#/resourcegroups/${B}/exporttemplate`);
await page.waitForFunction(() => /virtualNetworks/.test(document.querySelector('[data-testid="export-text"]')?.value || ""), null, { timeout: 30000 });
await page.getByRole("tab", { name: "Terraform" }).click();
const tf2 = await ta.inputValue();
await shot("07-export-after-import");
const back = Object.values(names).reduce((t, nm) => t.split(`${nm}b`).join(nm), tf2).split(B).join(A);   // names only
writeFileSync(`${SHOTS || "/tmp"}/export-b.tf`, tf2);
ok(back === tf, "second Terraform export equals the first modulo names");
if (back !== tf) { const a = tf.split("\n"), b = back.split("\n"); for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) { console.log("first diff line", i, JSON.stringify(a[i]), JSON.stringify(b[i])); break; } }

// ── ARM JSON deploy with a dependsOn-ordered template, then what-if modify ──
await page.goto(`${UI}#/resourcegroups/${B}/deployments`);
await page.getByTestId("deploy-template-open").click();
const tpl = { $schema: "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#", contentVersion: "1.0.0.0", parameters: { prefix: { type: "string", defaultValue: "arm" } },
  resources: [
    { type: "Microsoft.Network/virtualNetworks/subnets", apiVersion: "2023-05-01", name: "[concat(parameters('prefix'), '-vnet/a')]", dependsOn: ["[resourceId('Microsoft.Network/virtualNetworks', concat(parameters('prefix'), '-vnet'))]"], properties: { addressPrefix: "10.9.1.0/24" } },
    { type: "Microsoft.Network/virtualNetworks", apiVersion: "2023-05-01", name: "[concat(parameters('prefix'), '-vnet')]", location: "[resourceGroup().location]", properties: { addressSpace: { addressPrefixes: ["10.9.0.0/16"] } } }] };
await page.getByTestId("deploy-text").fill(JSON.stringify(tpl, null, 2));
await page.getByTestId("deploy-load").click();
await page.getByLabel("Deployment name", { exact: true }).fill("arm-json");
await page.getByTestId("deploy-whatif").click();
await page.getByTestId("whatif-result").waitFor({ timeout: 30000 });
ok((await page.getByTestId("whatif-result").locator("tr[data-change=Create]").count()) === 2, "ARM JSON what-if: 2 creates (subnet declared before its vnet, ordered by dependsOn)");
await page.getByTestId("deploy-go").click();
await page.waitForFunction(() => !document.querySelector('[data-testid="deploy-go"]'), null, { timeout: 60000 }).catch(() => {});
const sn = await arm("GET", `/resourceGroups/${B}/providers/Microsoft.Network/virtualNetworks/arm-vnet/subnets/a`, null, "2023-05-01");
ok(sn.status === 200, "ARM JSON deployment created the subnet after its vnet (dependsOn ordering)");
await browser.close();
console.log(fails ? `\n${fails} FAILED` : "\nALL PASSED");
process.exit(fails ? 1 : 0);
