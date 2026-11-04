/* Smoke for the AZ-07 network-config sweep: App Config + Cognitive Services private endpoint connections, vnet Network manager,
 * App Service networking (VNet integration, access restrictions, hybrid connections), Deployment Center Local Git / container,
 * AKS + Container Apps networking. Drives the UI and cross-checks over the native ARM wire.
 *   BASE=http://127.0.0.1:9047 node consoles/tests/smoke-azure-netcfg.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9047";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-netcfg";
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
  const base = `/resourceGroups/${RG}/providers`;
  const NV = armv("2023-11-01"), WV = armv("2023-12-01");
  const V = `vnet${n}`;
  const vid = `/subscriptions/${SUB}${base}/Microsoft.Network/virtualNetworks/${V}`;
  const subnet = (name, prefix, extra = {}) => ({ name, properties: { addressPrefix: prefix, ...extra } });
  await NV("PUT", `${base}/Microsoft.Network/virtualNetworks/${V}`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.7.0.0/16"] }, subnets: [
    subnet("default", "10.7.0.0/24"), subnet("integ", "10.7.1.0/26", { delegations: [{ name: "d", properties: { serviceName: "Microsoft.Web/serverFarms" } }] }),
    subnet("aca", "10.7.2.0/23")] } });

  // ── App Configuration + Cognitive Services: manual connection from Microsoft.Network, approve in the target blade ──
  const AC = `ac-${n}-store`;
  await armv("2023-03-01")("PUT", `${base}/Microsoft.AppConfiguration/configurationStores/${AC}`, { location: "eastus", sku: { name: "standard" } });
  const CSN = `cs${n}`;
  await armv("2023-05-01")("PUT", `${base}/Microsoft.CognitiveServices/accounts/${CSN}`, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: {} });
  for (const [target, group, route, getv, pe] of [
    [`/subscriptions/${SUB}${base}/Microsoft.AppConfiguration/configurationStores/${AC}`, "configurationStores", `#/appconfiguration/${RG}/${AC}/networking`, "2023-03-01", `peac${n}`],
    [`/subscriptions/${SUB}${base}/Microsoft.CognitiveServices/accounts/${CSN}`, "account", `#/cognitiveservices/${RG}/${CSN}/networking`, "2023-05-01", `pecs${n}`]]) {
    await NV("PUT", `${base}/Microsoft.Network/privateEndpoints/${pe}`, { location: "eastus", properties: { subnet: { id: `${vid}/subnets/default` },
      manualPrivateLinkServiceConnections: [{ name: "c", properties: { privateLinkServiceId: target, groupIds: [group], requestMessage: "pls" } }] } });
    await page.goto(UI + route);
    if (group === "account") await page.getByRole("tab", { name: "Private endpoint connections" }).click();
    await page.locator("tr", { hasText: pe }).waitFor({ timeout: 15000 });
    check(`${group}: target lists the Pending connection`, /Pending/.test(await page.locator("tr", { hasText: pe }).innerText()));
    await page.getByRole("button", { name: new RegExp(`Approve ${pe}`) }).click();
    await page.locator("tr", { hasText: pe }).getByRole("cell", { name: "Approved", exact: true }).waitFor({ timeout: 10000 });
    const e = json(await NV("GET", `${base}/Microsoft.Network/privateEndpoints/${pe}`));
    check(`${group}: UI approval flows back to the endpoint`, e.properties?.manualPrivateLinkServiceConnections?.[0]?.properties?.privateLinkServiceConnectionState?.status === "Approved");
    await noNS(`${group} networking`);
  }
  await page.goto(UI + "#/appconfiguration/create");
  await page.getByRole("tab", { name: "Networking", exact: true }).click();
  await page.getByLabel("Add a private endpoint").check();
  check("App Configuration wizard offers a real private endpoint section", await page.getByLabel("Private endpoint target sub-resource").isVisible());

  // ── vnet Network manager ──
  await page.goto(UI + `#/vnets/${RG}/${V}/networkmanager`);
  await page.getByRole("button", { name: "Create network manager" }).click();
  await page.getByLabel("Network manager name").fill(`nm${n}`);
  await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
  await page.locator("tr", { hasText: `nm${n}` }).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: "Add to network group" }).click();
  await page.getByLabel("Network manager", { exact: true }).selectOption({ label: `nm${n}` });
  await page.getByLabel("Network group name").fill("g1");
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();
  await page.locator("tr", { hasText: `nm${n}` }).getByRole("cell", { name: "g1", exact: true }).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: "Add connectivity configuration" }).click();
  await page.getByLabel("Network manager", { exact: true }).selectOption({ label: `nm${n}` });
  await page.getByLabel("Configuration name").fill("mesh1");
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();
  await page.locator("tr", { hasText: "mesh1 (Mesh)" }).waitFor({ timeout: 15000 });
  const cfg = json(await armv("2024-05-01")("GET", `${base}/Microsoft.Network/networkManagers/nm${n}/connectivityConfigurations/mesh1`));
  check("connectivity configuration stored over ARM", cfg.properties?.connectivityTopology === "Mesh");
  await noNS("vnet Network manager");

  // ── App Service networking ──
  const WS = `${base}/Microsoft.Web`;
  await WV("PUT", `${WS}/serverfarms/plan${n}`, { location: "eastus", sku: { name: "B1" } });
  await WV("PUT", `${WS}/sites/wapp${n}`, { location: "eastus", kind: "app,linux", properties: { serverFarmId: `/subscriptions/${SUB}${WS}/serverfarms/plan${n}` } });
  await page.goto(UI + `#/appservices/${RG}/wapp${n}/networking`);
  await page.getByLabel("Integration subnet").selectOption({ label: `${V}/integ` });
  await page.getByRole("button", { name: "Add virtual network integration" }).click();
  await page.getByLabel("Integrated subnet").waitFor({ timeout: 10000 });
  const nc = json(await WV("GET", `${WS}/sites/wapp${n}/networkConfig/virtualNetwork`));
  check("VNet integration stored over ARM", (nc.properties?.subnetResourceId || "").endsWith("/subnets/integ"));
  await page.getByRole("tab", { name: "Access restrictions" }).click();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Rule name").fill("office");
  await page.getByLabel("Rule source").fill("203.0.113.0/24");
  await page.getByRole("dialog").getByRole("button", { name: "Add rule", exact: true }).click();
  await page.locator("tr", { hasText: "office" }).waitFor({ timeout: 10000 });
  await page.locator("tr", { hasText: "Deny all" }).waitFor({ timeout: 10000 });
  const wc = json(await WV("GET", `${WS}/sites/wapp${n}/config/web`));
  check("access restriction + implicit Deny all tail stored", wc.properties?.ipSecurityRestrictions?.length === 2 && wc.properties?.ipSecurityRestrictionsDefaultAction === "Deny");
  await page.getByRole("tab", { name: "Hybrid connections" }).click();
  await page.getByRole("button", { name: "Add hybrid connection" }).click();
  await page.getByLabel("Relay namespace").fill("relay1");
  await page.getByLabel("Hybrid connection name").fill("sqlhc");
  await page.getByLabel("Endpoint host").fill("db.corp.local");
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();
  await page.locator("tr", { hasText: "sqlhc" }).waitFor({ timeout: 10000 });
  await noNS("App Service networking");

  // ── Deployment Center: Local Git, Azure Repos, container ──
  await page.goto(UI + `#/appservices/${RG}/wapp${n}/deploymentcenter`);
  await page.getByLabel("Source", { exact: true }).selectOption("local");
  await page.getByLabel("Git clone URI").waitFor();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.waitForFunction(async ([u]) => (await (await fetch(u)).json()).properties?.scmType === "LocalGit", [`${WIRE}/subscriptions/${SUB}${WS}/sites/wapp${n}/config/web?api-version=2023-12-01`], { timeout: 10000 });
  check("Local Git enabled over ARM", true);
  await page.getByLabel("Source", { exact: true }).selectOption("azrepos");
  await page.getByLabel("Repository", { exact: true }).fill("https://dev.azure.com/acme/shop/_git/shop");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.waitForFunction(async ([u]) => (await (await fetch(u)).json()).properties?.scmType === "VSTSRM", [`${WIRE}/subscriptions/${SUB}${WS}/sites/wapp${n}/config/web?api-version=2023-12-01`], { timeout: 10000 });
  check("Azure Repos source sets scmType VSTSRM", true);
  await page.getByLabel("Source", { exact: true }).selectOption("container");
  await page.getByLabel("Image and tag").fill("myreg.azurecr.io/shop/app:v1");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.waitForFunction(async ([u]) => (await (await fetch(u)).json()).properties?.linuxFxVersion === "DOCKER|myreg.azurecr.io/shop/app:v1", [`${WIRE}/subscriptions/${SUB}${WS}/sites/wapp${n}/config/web?api-version=2023-12-01`], { timeout: 10000 });
  check("Container registry source stored (linuxFxVersion DOCKER|...)", true);
  await noNS("Deployment Center");

  // ── AKS create wizard networking + blade ──
  await page.goto(UI + "#/aks/create");
  await page.getByRole("tab", { name: "Networking", exact: true }).click();
  check("AKS wizard has service CIDR / outbound type", await page.getByLabel("Service CIDR").isVisible() && await page.getByLabel("Outbound type").isVisible());
  await armv("2024-02-01")("PUT", `${base}/Microsoft.ContainerService/managedClusters/aks${n}`, { location: "eastus", properties: { dnsPrefix: `aks${n}`, agentPoolProfiles: [{ name: "np", count: 1, vmSize: "Standard_DS2_v2", mode: "System" }],
    networkProfile: { networkPlugin: "azure", networkPluginMode: "overlay", podCidr: "192.168.0.0/16" } } });
  await page.goto(UI + `#/aks/${RG}/aks${n}/networking`);
  await page.getByText("Service CIDR").waitFor({ timeout: 10000 });
  check("AKS Networking page shows the derived defaults", (await page.locator("body").innerText()).includes("10.0.0.10"));
  await noNS("AKS networking");

  // ── Container Apps environment in a custom VNet ──
  await armv("2024-03-01")("PUT", `${base}/Microsoft.App/managedEnvironments/cae${n}`, { location: "eastus", properties: { vnetConfiguration: { infrastructureSubnetId: `${vid}/subnets/aca`, internal: false } } });
  await page.goto(UI + `#/containerapps/environments/${RG}/cae${n}/networking`);
  await page.getByText(`${vid}/subnets/aca`, { exact: false }).waitFor({ timeout: 10000 });
  await page.goto(UI + "#/containerapps/environments/create");
  await page.getByRole("tab", { name: "Networking", exact: true }).click();
  await page.getByLabel("Use your own virtual network").check();
  check("Container Apps wizard offers the infrastructure subnet", await page.getByLabel("Infrastructure subnet").isVisible());
  await noNS("Container Apps networking");

  // ── vnet wizard advertised prefixes ──
  await page.goto(UI + "#/vnets/create");
  await page.getByRole("tab", { name: "Address space", exact: true }).click();
  check("vnet wizard has the advertised prefixes field", await page.getByLabel("Advertised address prefixes").first().isVisible().catch(() => false));
  await shot("netcfg-done");

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
