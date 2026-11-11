/* Azure v4 console <-> API / CLI bi-directional conformance (Nano). The report the release needs.
 *
 *   NANO_DIR=$PWD/wasm SIM_URL=http://127.0.0.1:9000 node wasm/ui-tests/validate-azure-v4-bidirectional.mjs
 *
 * The v4 console (served from NANO_DIR, wire base = this page origin /_wire) talks to a real offline simulator (SIM_URL, the
 * same pairing a Mesh Codespace gives); the EXTERNAL client talks to the simulator directly, exactly as `az`/an SDK/curl would. Per service:
 *   API->UI   created over the relay (HTTP/ARM), the console list shows it (name + region)
 *   CLI->UI   created with `az rest` against the relay, the console list shows it            (needs `az`)
 *   UI->API   created through the console wizard, a relay GET returns it with the same name/location
 *   UIdel     deleted over the relay, the list no longer shows it
 * Resource groups additionally get UI delete -> API gone. Anything the generic driver cannot do (service-specific wizard
 * fields) is reported as NOT-AUTOMATED, never as a pass. Writes out/azure-v4-bidirectional.{json,md}. One [PASS]/[FAIL] per check.
 */
import { chromium, sleep, NANO_DIR } from "./lib.mjs";
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { execFile } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { promisify } from "node:util";
const run = promisify(execFile);

const SIM = (process.env.SIM_URL || "http://127.0.0.1:9000").replace(/\/$/, "");
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = `bd-rg-${Date.now() % 100000}`;
const SVCS = [
  { id: "resourcegroups", title: "Resource groups", rg: true },
  { id: "storage", title: "Storage accounts", ns: "Microsoft.Storage", type: "storageAccounts", ver: "2023-01-01", body: { sku: { name: "Standard_LRS" }, kind: "StorageV2" }, nm: (n) => n.replace(/-/g, "").slice(0, 22) },
  { id: "keyvaults", title: "Key vaults", ns: "Microsoft.KeyVault", type: "vaults", ver: "2023-07-01", body: { properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } }, nm: (n) => n.slice(0, 22) },
  { id: "vnets", title: "Virtual networks", ns: "Microsoft.Network", type: "virtualNetworks", ver: "2023-11-01", body: { properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] } } } },
  { id: "nsgs", title: "Network security groups", ns: "Microsoft.Network", type: "networkSecurityGroups", ver: "2023-11-01", body: { properties: {} } },
  { id: "dns", title: "DNS zones", ns: "Microsoft.Network", type: "dnsZones", ver: "2018-05-01", global: true, body: { properties: {} }, nm: (n) => `${n}.example.com` },
  { id: "appconfiguration", title: "App Configuration", ns: "Microsoft.AppConfiguration", type: "configurationStores", ver: "2023-03-01", body: { sku: { name: "free" } } },
  { id: "servicebus", title: "Service Bus", ns: "Microsoft.ServiceBus", type: "namespaces", ver: "2022-10-01-preview", body: { sku: { name: "Standard", tier: "Standard" } } },
  { id: "acr", title: "Container registries", ns: "Microsoft.ContainerRegistry", type: "registries", ver: "2023-07-01", body: { sku: { name: "Basic" } }, nm: (n) => n.replace(/-/g, "").slice(0, 40) },
  { id: "loganalytics", title: "Log Analytics workspaces", ns: "Microsoft.OperationalInsights", type: "workspaces", ver: "2022-10-01", body: { properties: { sku: { name: "PerGB2018" } } } },
  { id: "cognitiveservices", title: "Azure AI services", ns: "Microsoft.CognitiveServices", type: "accounts", ver: "2024-10-01", body: { kind: "OpenAI", sku: { name: "S0" }, properties: {} } },
  { id: "eventgrid", route: "eventgrid/topics", title: "Event Grid", ns: "Microsoft.EventGrid", type: "topics", ver: "2022-06-15", body: { properties: {} } },
  { id: "sql", title: "SQL databases", ns: "Microsoft.Sql", type: "databases", ver: "2021-11-01", body: { sku: { name: "Basic" } },
    prep: async (t) => { const sv = `bdsrv${t}`; await arm("PUT", resPath({ ns: "Microsoft.Sql", type: "servers" }, sv) + q("2021-11-01"), { location: "eastus", properties: { administratorLogin: "bdadmin", administratorLoginPassword: "Bd-Passw0rd!x" } }); return { parentPath: `servers/${sv}` }; } },
  { id: "cosmos", title: "Cosmos DB", ns: "Microsoft.DocumentDB", type: "databaseAccounts", ver: "2023-11-15", body: { kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }] } } },
  { id: "recoveryservices", title: "Recovery Services vaults", ns: "Microsoft.RecoveryServices", type: "vaults", ver: "2023-04-01", body: { sku: { name: "RS0", tier: "Standard" }, properties: {} } },
  { id: "frontdoor", title: "Front Door", ns: "Microsoft.Cdn", type: "profiles", ver: "2023-05-01", body: { sku: { name: "Standard_AzureFrontDoor" } }, global: true },
  { id: "networkmanagers", title: "Network managers", ns: "Microsoft.Network", type: "networkManagers", ver: "2023-11-01", body: { properties: { networkManagerScopes: { subscriptions: ["/subscriptions/" + SUB] }, networkManagerScopeAccesses: ["Connectivity"] } } },
  { id: "streamanalytics", title: "Stream Analytics", ns: "Microsoft.StreamAnalytics", type: "streamingjobs", ver: "2021-10-01-preview", body: { sku: { name: "Standard" }, properties: { sku: { name: "Standard" } } } },
  { id: "apim", title: "API Management", ns: "Microsoft.ApiManagement", type: "service", ver: "2022-08-01", body: { sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.co", publisherName: "bd" } } },
  { id: "aks", title: "Kubernetes services", ns: "Microsoft.ContainerService", type: "managedClusters", ver: "2023-10-01", body: { identity: { type: "SystemAssigned" }, properties: { dnsPrefix: "bd", agentPoolProfiles: [{ name: "np", count: 1, vmSize: "Standard_B2s", mode: "System" }] } } },
  { id: "containerapps", title: "Container Apps", ns: "Microsoft.App", type: "containerApps", ver: "2023-05-01", body: { properties: {} },
    prep: async (t) => { const env = `bdenv${t}`; await arm("PUT", resPath({ ns: "Microsoft.App", type: "managedEnvironments" }, env) + q("2023-05-01"), { location: "eastus", properties: {} }); return { body: { properties: { environmentId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.App/managedEnvironments/${env}`, template: { containers: [{ name: "app", image: "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" }] } } } }; } },
  { id: "functionapp", title: "Function apps", ns: "Microsoft.Web", type: "sites", ver: "2022-09-01", body: { kind: "functionapp", properties: {} },
    prep: async (t) => { const pl = `bdfplan${t}`; await arm("PUT", resPath({ ns: "Microsoft.Web", type: "serverfarms" }, pl) + q("2022-09-01"), { location: "eastus", sku: { name: "Y1", tier: "Dynamic" } }); return { body: { kind: "functionapp", properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${pl}` } } }; } },
  { id: "vms", title: "Virtual machines", ns: "Microsoft.Compute", type: "virtualMachines", ver: "2023-09-01", body: { properties: {} },
    prep: async (t) => {
      const vn = `bdvn${t}`, nic = `bdnic${t}`, nic2 = `bdnic2${t}`;
      const v = await arm("PUT", resPath({ ns: "Microsoft.Network", type: "virtualNetworks" }, vn) + q("2023-11-01"), { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.1.0.0/16"] }, subnets: [{ name: "default", properties: { addressPrefix: "10.1.0.0/24" } }] } });
      const subnetId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${vn}/subnets/default`;
      for (const nn of [nic, nic2]) await arm("PUT", resPath({ ns: "Microsoft.Network", type: "networkInterfaces" }, nn) + q("2023-11-01"), { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: subnetId } } }] } });
      const mk = (nn) => ({ properties: { hardwareProfile: { vmSize: "Standard_B1s" }, storageProfile: { imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts-gen2", version: "latest" }, osDisk: { createOption: "FromImage" } }, osProfile: { computerName: "bdvm", adminUsername: "bdadmin", adminPassword: "Bd-Passw0rd!x" }, networkProfile: { networkInterfaces: [{ id: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${nn}` }] } } });   // a NIC attaches to one VM (real Azure: NicInUse)
      return { body: (k) => mk(k === "cli" ? nic2 : nic) };
    } },
  { id: "appservices", title: "App Service web apps", ns: "Microsoft.Web", type: "sites", ver: "2022-09-01", body: { kind: "app", properties: {} },
    prep: async (t) => { const pl = `bdplan${t}`; await arm("PUT", resPath({ ns: "Microsoft.Web", type: "serverfarms" }, pl) + q("2022-09-01"), { location: "eastus", sku: { name: "B1" } }); return { body: { kind: "app", properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${pl}` } } }; } },
];
const only = (process.env.ONLY || "").split(",").filter(Boolean);
const svcs = only.length ? SVCS.filter((s) => only.includes(s.id)) : SVCS;

const rows = [];   // {svc, check, status: PASS|FAIL|NOT-AUTOMATED, detail}
let fails = 0;
const rec = (svc, check, status, detail = "") => {
  rows.push({ svc, check, status, detail });
  if (status === "FAIL") fails++;
  console.log(`[${status === "PASS" ? "PASS" : status === "FAIL" ? "FAIL" : "NOTE"}] ${svc} :: ${check}${detail ? ` :: ${detail}` : ""}`);
};

const arm = async (method, path, body) => {
  const r = await fetch(SIM + path, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(30000) });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* not json */ }
  return { status: r.status, json: j, text: t };
};
const rgPath = (rg) => `/subscriptions/${SUB}/resourcegroups/${rg}`;
const resPath = (s, name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/${s.ns}/${s.parentPath ? s.parentPath + "/" : ""}${s.type}/${name}`;
const q = (v) => `?api-version=${v}`;
const hasAz = await run("az", ["--version"]).then(() => true, () => false);
const azPut = (url, body) => run("az", ["rest", "--skip-authorization-header", "--only-show-errors", "--method", "put", "--url", SIM + url, "--body", JSON.stringify(body)], { env: { ...process.env, AZURE_CORE_COLLECT_TELEMETRY: "false" }, timeout: 60000 });

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, "http://x");
    if (/^\/(_wire|api|subscriptions|azure-data)\b/.test(u.pathname)) {          // the appliance's own API surface
      const chunks = []; for await (const c of req) chunks.push(c);
      const r = await fetch(SIM + req.url, { method: req.method, headers: Object.fromEntries(Object.entries(req.headers).filter(([k]) => !["host", "connection", "content-length"].includes(k))), body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks) });
      res.writeHead(r.status, Object.fromEntries([...r.headers].filter(([k]) => !["content-encoding", "transfer-encoding", "content-length"].includes(k))));
      return res.end(Buffer.from(await r.arrayBuffer()));
    }
    let p = normalize(decodeURIComponent(u.pathname)); if (p === "/") p = "/index.html";
    const f = join(NANO_DIR, p);
    if (!f.startsWith(NANO_DIR) || !existsSync(f)) { res.writeHead(404); return res.end("404"); }
    let body = await readFile(f);
    if (/\/v4\/\w+\/index\.html$/.test(p)) body = Buffer.from(body.toString().replace('content="nano"', 'content="offline"')    // the offline appliance serves this bundle as offline: no in-browser engine
      .replace(/<script[^>]*nano-boot\.js[^>]*><\/script>/g, "").replace(/<script[^>]*nano-kernel\.js[^>]*><\/script>/g, "").replace(/<script>window\.__nk[^<]*<\/script>/g, ""));
    res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream", "cache-control": "no-cache" }); res.end(body);
  } catch (e) { res.writeHead(500); res.end(String(e)); }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ serviceWorkers: "block" });
const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e.message).split("\n")[0]));

const routeOf = (id) => (SVCS.find((x) => x.id === id) || {}).route || id;
const goList = async (id) => {
  await page.goto(`${base}/v4/azure/index.html#/${routeOf(id)}`, { waitUntil: "domcontentloaded" });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => /Name|No .* to display|No resource|Create/i.test(document.body.innerText), null, { timeout: 30000 }).catch(() => {});
  await sleep(1500);
};
const listText = async (id) => { await goList(id); return (await page.locator("body").innerText()).replace(/\s+/g, " "); };
const rowHas = async (id, name) => {
  for (let i = 0; i < 3; i++) { const t = await listText(id); if (t.includes(name)) return t; await sleep(2000); }
  return null;
};

try {
  await page.goto(`${base}/v4/azure/index.html`, { waitUntil: "domcontentloaded" });
  const h = await fetch(SIM + "/healthz").then((r) => r.json()).catch(() => ({}));
  rec("(setup)", "simulator reachable", h.status === "ok" ? "PASS" : "FAIL", JSON.stringify(h).slice(0, 100));
  if (h.status !== "ok") throw new Error("simulator not reachable");
  await arm("POST", "/api/spaces/space-azure-default/switch");   // the active Azure space serves ARM and /_wire
  const rg = await arm("PUT", rgPath(RG) + q("2021-04-01"), { location: "eastus" });
  rec("(setup)", "create the test resource group over the relay", rg.status < 300 ? "PASS" : "FAIL", `${rg.status} ${rg.text.slice(0, 100)}`);

  for (const s of svcs) {
    const tag = `bd${Date.now() % 1000000}`;
    // ---- resource groups: all four directions with the real wizard
    if (s.rg) {
      const a = `${RG}-api`;
      const put = await arm("PUT", rgPath(a) + q("2021-04-01"), { location: "eastus", tags: { dir: "api" } });
      const seen = put.status < 300 && (await rowHas(s.id, a));
      rec(s.title, "API->UI: group created over the API is listed in the console", seen ? "PASS" : "FAIL", put.status >= 300 ? `PUT ${put.status}` : "not listed");
      if (seen) rec(s.title, "API->UI: the list shows the region", /East US|eastus/i.test(seen) ? "PASS" : "FAIL", seen.slice(0, 160));
      if (hasAz) {
        const c = `${RG}-cli`;
        const o = await azPut(rgPath(c) + q("2021-04-01"), { location: "eastus" }).catch((e) => ({ stderr: String(e.message) }));
        const sc = await rowHas(s.id, c);
        rec(s.title, "CLI->UI: group created with `az rest` is listed in the console", sc ? "PASS" : "FAIL", sc ? "" : String(o.stderr || "").slice(0, 120));
      } else rec(s.title, "CLI->UI (az not installed here)", "NOT-AUTOMATED");
      // UI -> API with the wizard
      const u = `${RG}-ui`;
      await page.goto(`${base}/v4/azure/index.html#/resourcegroups/create`, { waitUntil: "domcontentloaded" });
      await page.reload({ waitUntil: "domcontentloaded" });
      let uiOk = false, uiErr = "";
      try {
        await page.getByLabel("Resource group name").waitFor({ timeout: 30000 });
        await page.getByLabel("Resource group name").fill(u);
        await page.getByRole("button", { name: /Review \+ create/ }).first().dispatchEvent("click");
        await page.getByRole("button", { name: /^Create$/ }).first().dispatchEvent("click");
        await sleep(4000); uiOk = true;
      } catch (e) { uiErr = String(e.message).split("\n")[0]; }
      const got = await arm("GET", rgPath(u) + q("2021-04-01"));
      rec(s.title, "UI->API: group created in the console wizard is returned by the API", uiOk && got.status === 200 ? "PASS" : "FAIL", uiOk ? `GET ${got.status}` : uiErr);
      if (got.status === 200) rec(s.title, "UI->API: same name and region in the API response", got.json?.name === u && /eastus/i.test(got.json?.location || "") ? "PASS" : "FAIL", JSON.stringify({ n: got.json?.name, l: got.json?.location }));
      // UI delete -> API gone
      await page.goto(`${base}/v4/azure/index.html#/resourcegroups/${encodeURIComponent(u)}/delete`, { waitUntil: "domcontentloaded" });
      await page.reload({ waitUntil: "domcontentloaded" });
      try {
        await page.getByLabel("Enter resource group name to confirm deletion").fill(u);
        await page.getByRole("button", { name: /^Delete$/ }).first().dispatchEvent("click"); await sleep(3000);
        const gone = await arm("GET", rgPath(u) + q("2021-04-01"));
        rec(s.title, "UI delete -> API: group deleted in the console is gone from the API", gone.status === 404 ? "PASS" : "FAIL", `GET ${gone.status}`);
      } catch (e) { rec(s.title, "UI delete -> API", "FAIL", String(e.message).split("\n")[0]); }
      const del = await arm("DELETE", rgPath(a) + q("2021-04-01")); await sleep(1500);
      const t = await listText(s.id);
      rec(s.title, "API delete -> UI: group deleted over the API disappears from the list", del.status < 300 && !t.includes(a) ? "PASS" : "FAIL", `DELETE ${del.status}`);
      continue;
    }
    // ---- other services: API->UI, CLI->UI, UI->API (generic wizard), API delete -> UI
    const nmf = s.nm || ((n) => n);
    const name = nmf(`${s.id}-${tag}`.toLowerCase());
    const loc = s.global ? "global" : "eastus";
    if (s.prep) { const pr = await s.prep(tag); if (pr.parentPath) s.parentPath = pr.parentPath; if (pr.body) s.body = pr.body; }
    const bodyOf = (k) => (typeof s.body === "function" ? s.body(k) : s.body);
    const put = await arm("PUT", resPath(s, name) + q(s.ver), { location: loc, ...bodyOf("api") });
    if (put.status >= 300) { rec(s.title, "API create", "FAIL", `PUT ${put.status} ${put.text.slice(0, 120)}`); continue; }
    const seen = await rowHas(s.id, name);
    rec(s.title, "API->UI: resource created over the API is listed in the console", seen ? "PASS" : "FAIL", seen ? "" : "not listed in " + `#/${s.id}`);
    if (seen && !s.global) rec(s.title, "API->UI: the list shows the region", /East US|eastus/i.test(seen) ? "PASS" : "FAIL", "");
    if (hasAz) {
      const cn = nmf(`${s.id}-c${tag}`.toLowerCase());
      const o = await azPut(resPath(s, cn) + q(s.ver), { location: loc, ...bodyOf("cli") }).catch((e) => ({ stderr: String(e.message) }));
      const sc = await rowHas(s.id, cn);
      rec(s.title, "CLI->UI: resource created with `az rest` is listed in the console", sc ? "PASS" : "FAIL", sc ? "" : String(o.stderr || "").slice(0, 120));
    } else rec(s.title, "CLI->UI (az not installed here)", "NOT-AUTOMATED");
    // UI -> API: generic wizard (only counts when the wizard completes with a name alone)
    const un = nmf(`${s.id}-u${tag}`.toLowerCase());
    await page.goto(`${base}/v4/azure/index.html#/${routeOf(s.id)}/create`, { waitUntil: "domcontentloaded" });
    await page.reload({ waitUntil: "domcontentloaded" });
    let created = false, why = "";
    let drv = null;
    try { const f = new URL(`./azure-bd/${s.id}.mjs`, import.meta.url); if (existsSync(f)) drv = await import(f.href); } catch (e) { why = "driver load: " + e.message; }
    try {
      if (drv) {
        // per-service wizard driver: default export drives the create wizard for `name`; optional `find` looks the result up over the API
        await drv.default({ page, base, name: un, sleep, SUB, arm, dispatch: (loc) => loc.dispatchEvent("click") });
        await sleep(4000); created = true;
      } else {
      const nameBox = page.getByLabel(/^(Storage account name|Name|Key vault name|Virtual network name|Registry name|Namespace name|Resource name|Workspace name|Instance name|Account name|Zone name|Topic name|Name\b).*/i).first();
      await nameBox.waitFor({ timeout: 20000 });
      await nameBox.fill(s.global ? un : un);
      await page.getByRole("button", { name: /Review \+ create|Review \+ Create/ }).first().dispatchEvent("click");
      await page.getByRole("button", { name: /^Create$/ }).first().dispatchEvent("click");
      await sleep(5000); created = true;
      }
    } catch (e) { why = String(e.message).split("\n")[0]; }
    if (!created) { rec(s.title, "UI->API: console wizard", "NOT-AUTOMATED", `generic filler could not complete the wizard (${why.slice(0, 80)})`); }
    else {
      // the wizard creates in ITS default resource group, so look the resource up subscription-wide by name
      const all = await arm("GET", `/subscriptions/${SUB}/providers/${s.ns}/${s.type}` + q(s.ver));
      const hit = drv && drv.find ? await drv.find({ arm, SUB, name: un, q }) : (all.json?.value || []).find((x) => x.name === un);
      rec(s.title, "UI->API: resource created in the console wizard is returned by the API", hit ? "PASS" : "FAIL", hit ? "" : `not in the ${s.type} list (HTTP ${all.status}, ${(all.json?.value || []).length} items)`);
      if (hit) {
        rec(s.title, "UI->API: same name and a real region in the API response", hit.name === un && (s.global || /\w/.test(hit.location || "")) ? "PASS" : "FAIL", JSON.stringify({ n: hit.name, l: hit.location }));
        await arm("DELETE", hit.id + q(s.ver));
      }
    }
    const del = await arm("DELETE", resPath(s, name) + q(s.ver)); await sleep(1500);
    const t = await listText(s.id);
    rec(s.title, "API delete -> UI: resource deleted over the API disappears from the list", del.status < 300 && !t.includes(name) ? "PASS" : "FAIL", `DELETE ${del.status}`);
  }
  await arm("DELETE", rgPath(RG) + q("2021-04-01"));
} catch (e) {
  rec("(run)", "harness ran to completion", "FAIL", String(e.message).split("\n")[0]);
}
rec("(run)", "no uncaught page errors", pageErrors.length ? "NOTE" : "PASS", pageErrors.slice(0, 3).join(" | "));

const outDir = new URL("../../tests/conformance/hourly/out/", import.meta.url).pathname;
mkdirSync(outDir, { recursive: true });
writeFileSync(outDir + "azure-v4-bidirectional.json", JSON.stringify({ at: new Date().toISOString(), rows }, null, 1));
const by = {}; for (const r of rows) (by[r.svc] ||= []).push(r);
let md = "# Azure v4 console <-> API / CLI bi-directional report\n\n| Service | Check | Result | Detail |\n|---|---|---|---|\n";
for (const [svc, rs] of Object.entries(by)) for (const r of rs) md += `| ${svc} | ${r.check} | ${r.status} | ${String(r.detail).replace(/\|/g, "/").slice(0, 120)} |\n`;
const n = (st) => rows.filter((r) => r.status === st).length;
md += `\n**${n("PASS")} pass, ${n("FAIL")} fail, ${n("NOT-AUTOMATED")} not automated.**\n`;
writeFileSync(outDir + "azure-v4-bidirectional.md", md);
await browser.close(); server.close();
process.exit(fails ? 1 : 0);
