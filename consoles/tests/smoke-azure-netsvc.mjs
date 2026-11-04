/* Smoke for the AZ-07 sweep (private endpoints, Bastion, Azure Firewall, DDoS plans, NSG flow logs). Drives the UI and cross-checks over the native ARM wire.
 *   BASE=http://127.0.0.1:9047 node consoles/tests/smoke-azure-netsvc.mjs
 *   BASE=http://127.0.0.1:8850 NANO=1 UI_PATH=/nano/v4/azure/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-azure-netsvc.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9047";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-netsvc";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vynet-rg${n}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => {
  const r = await fetch(u, i); return { status: r.status, text: await r.text() };
}, [WIRE + path, init]);
const armv = (av) => (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const arm = armv("2023-01-01");
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (400|403|404|409)/.test(m.text()) && errors.push(m.text()));
const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
const until = async (fn, ms = 15000) => { const t0 = Date.now(); for (;;) { try { const v = await fn(); if (v) return v; } catch { /* retry */ } if (Date.now() - t0 > ms) return false; await page.waitForTimeout(300); } };
const noNS = async (label, allow = []) => {
  const left = (await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated") || ""))).filter((t) => !allow.some((a) => t.includes(a)));
  check(`${label}: no unexpected Not-simulated panel`, left.length === 0, left.join(" | ").slice(0, 160));
};

try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" });

    const net = (t) => `/resourceGroups/${RG}/providers/Microsoft.Network/${t}`;
  const NV = armv("2023-11-01");
  const V = `vnet${n}`;
  const vid = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${V}`;
  await NV("PUT", net(`virtualNetworks/${V}`), { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.7.0.0/16"] } } });
  await NV("PUT", net(`virtualNetworks/${V}/subnets/default`), { properties: { addressPrefix: "10.7.0.0/24" } });
  const SA = `vynsa${n}`;
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } });
  await NV("PUT", net("networkSecurityGroups/nsg" + n), { location: "eastus" });

  // ── Private endpoints: create in the UI, approve on the target over ARM ──
  await page.goto(UI + `#/vnets/${RG}/${V}/privateendpoints`);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("Private endpoint name").fill(`pe${n}`);
  await page.getByLabel("Target resource").selectOption({ label: `${SA} (storageAccounts)` });
  await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
  await page.locator("tr", { hasText: `pe${n}` }).waitFor({ timeout: 15000 });
  const peRow = await page.locator("tr", { hasText: `pe${n}` }).innerText();
  check("PE row shows Approved + privatelink FQDN", /Approved/.test(peRow) && peRow.includes(`${SA}.privatelink.blob.core.windows.net`), peRow.replace(/\s+/g, " ").slice(0, 120));
  const tgt = json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`));
  check("target storage lists the connection over ARM", (tgt.properties?.privateEndpointConnections || []).length === 1);
  await shot("private-endpoints");
  await noNS("vnet Private endpoints");

  // ── Bastion ──
  await page.goto(UI + `#/vnets/${RG}/${V}/bastion`);
  await page.getByRole("button", { name: "Deploy Bastion" }).click();
  await page.getByLabel("Bastion name").fill(`bst${n}`);
  await page.getByRole("dialog").getByRole("button", { name: "Deploy", exact: true }).click();
  await page.locator("tr", { hasText: `bst${n}` }).waitFor({ timeout: 15000 });
  const bh = json(await NV("GET", net(`bastionHosts/bst${n}`)));
  check("Bastion deployed with dnsName + AzureBastionSubnet created", /bastion\.azure\.com$/.test(bh.properties?.dnsName || "") && (json(await NV("GET", net(`virtualNetworks/${V}/subnets/AzureBastionSubnet`))).properties?.addressPrefix || "").endsWith("/26"));
  await noNS("vnet Bastion");

  // ── Firewall ──
  await page.goto(UI + `#/vnets/${RG}/${V}/firewall`);
  await page.getByRole("button", { name: "Deploy Firewall" }).click();
  await page.getByLabel("Firewall name").fill(`fw${n}`);
  await page.getByRole("dialog").getByRole("button", { name: "Deploy", exact: true }).click();
  await page.locator("tr", { hasText: `fw${n}` }).waitFor({ timeout: 15000 });
  const fw = json(await NV("GET", net(`azureFirewalls/fw${n}`)));
  check("Firewall has an allocated private IP in AzureFirewallSubnet", /^10\.7\./.test(fw.properties?.ipConfigurations?.[0]?.properties?.privateIPAddress || ""));
  await noNS("vnet Firewall");

  // ── DDoS ──
  await page.goto(UI + `#/vnets/${RG}/${V}/ddosprotection`);
  await page.getByLabel("New DDoS plan name").fill(`ddos${n}`);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("DDoS protection plan").selectOption({ label: `ddos${n}` });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Enabled", { exact: false }).first().waitFor({ timeout: 10000 });
  const plan = json(await NV("GET", net(`ddosProtectionPlans/ddos${n}`)));
  check("plan tracks the protected vnet", (plan.properties?.virtualNetworks || []).length === 1);
  await noNS("vnet DDoS");

  // ── Target-side Private endpoint connections tab (storage) ──
  await NV("PUT", net("privateEndpoints/pem" + n), { location: "eastus", properties: { subnet: { id: `${vid}/subnets/default` },
    manualPrivateLinkServiceConnections: [{ name: "c", properties: { privateLinkServiceId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`, groupIds: ["file"], requestMessage: "pls" } }] } });
  await page.goto(UI + `#/storage/${RG}/${SA}/networking`);
  await page.getByRole("tab", { name: "Private access" }).click();
  await page.locator("tr", { hasText: `pem${n}` }).waitFor({ timeout: 15000 });
  check("target tab lists the Pending manual connection", /Pending/.test(await page.locator("tr", { hasText: `pem${n}` }).innerText()));
  await page.getByRole("button", { name: new RegExp(`Approve pem${n}`) }).click();
  await page.locator("tr", { hasText: `pem${n}` }).getByRole("cell", { name: "Approved", exact: true }).waitFor({ timeout: 10000 });
  const pem = json(await NV("GET", net(`privateEndpoints/pem${n}`)));
  check("UI approval flows back to the endpoint", pem.properties?.manualPrivateLinkServiceConnections?.[0]?.properties?.privateLinkServiceConnectionState?.status === "Approved");
  await noNS("storage Private access", ["Exceptions", "Virtual networks"]);
  // wizard section
  await page.goto(UI + "#/keyvaults/create");
  await page.getByRole("tab", { name: "Networking", exact: true }).click();
  await page.getByLabel("Add a private endpoint").check();
  check("Key Vault wizard offers a real private endpoint section", await page.getByLabel("Private endpoint target sub-resource").isVisible());

  // ── Deployment Center (App Service) ──
  const WV = armv("2023-12-01");
  await WV("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/plan${n}`, { location: "eastus", sku: { name: "B1" } });
  await WV("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/wapp${n}`, { location: "eastus", kind: "app,linux", properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/plan${n}` } });
  await page.goto(UI + `#/appservices/${RG}/wapp${n}/deploymentcenter`);
  await page.getByLabel("Source", { exact: true }).selectOption("gh");
  await page.getByLabel("Repository", { exact: true }).fill("https://github.com/acme/shop");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByLabel("Generated GitHub workflow").waitFor({ timeout: 10000 });
  check("Deployment Center shows the generated workflow", (await page.getByLabel("Generated GitHub workflow").inputValue()).includes("azure/webapps-deploy@v3"));
  const sc = json(await WV("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/wapp${n}/config/web`));
  check("scmType = GitHubAction over ARM", sc.properties?.scmType === "GitHubAction");
  await page.getByRole("tab", { name: "FTPS credentials" }).click();
  await page.getByLabel("FTPS username").waitFor({ timeout: 10000 });
  check("FTPS username is $site", (await page.getByLabel("FTPS username").inputValue()) === `$wapp${n}`);
  await page.getByRole("tab", { name: "Logs" }).click();
  await noNS("App Service Deployment Center");

  // ── NSG flow logs ──
  await page.goto(UI + `#/nsgs/${RG}/nsg${n}/flowlogs`);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("Flow log name").fill(`fl${n}`);
  await page.getByLabel("Retention days").fill("30");
  await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
  await page.locator("tr", { hasText: `fl${n}` }).waitFor({ timeout: 15000 });
  const nws = json(await NV("GET", "/providers/Microsoft.Network/networkWatchers")).value || [];
  check("flow log stored under an auto-created network watcher", nws.length >= 1);
  await shot("nsg-flowlogs");
  await noNS("NSG flow logs");

} catch (e) {
  const at = ((e.stack || "").match(/smoke-[a-z-]+\.mjs:(\d+)/) || [])[1];
  check("smoke run", false, e.message.split("\n")[0] + (at ? ` (smoke line ${at})` : ""));
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
