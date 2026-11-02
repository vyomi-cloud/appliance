/* End-to-end smoke of the Azure lens against a running /_wire backend (dev_server.py, the
 * offline appliance, or Nano). Drives the UI like a user and cross-checks state over the
 * NATIVE Azure wire (ARM control plane + Blob REST data plane — what azure-* SDKs and the az
 * CLI see). Screenshots → $OUT (default ./smoke-out-azure).
 *
 *   BASE=http://127.0.0.1:8740 UI_PATH=/v4/azure/ node consoles/tests/smoke-azure.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";

const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); }
catch { pw = require("/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:8740";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-azure";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "vyomi-smoke-rg";
const n = Date.now() % 100000;
const SA = `vysmoke${n}`;          // created through the UI
const SAR = `vyrepl${n}`;        // object-replication destination account
const SA2 = `vywire${n}`;          // created over the wire (CLI → UI direction)
const C = `smoke-${n}`;
const TBL = `vysmoketbl${n}`;      // Table created through the UI
const TBL2 = `vywiretbl${n}`;      // Table created over the wire (CLI → UI direction)
const APP = `vysmokeapp${n}`;      // app service created through the UI
const APP2 = `vywireapp${n}`;      // app service created over the wire (CLI → UI direction)
const APPROLE = `00000000-0000-4000-b000-${String(n).padStart(12, "0")}`;  // role assignment GUID created over the wire, EXPLICITLY scoped to the App Service resource
const APPPRINCIPAL = `vyappprincipal${n}`;  // principal of the App Service-scoped role assignment above
const EGT = `vyegtopic${n}`;       // Event Grid topic created through the UI
const EGT2 = `vyegwire${n}`;       // Event Grid topic created over the wire
const ES = `vyeges${n}`;           // event subscription created over the wire
const LOCK = `vyeglock${n}`;       // management lock created through the UI
const EGROLE = `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;  // role assignment GUID created over the wire, read back on the topic's Access control (IAM) tab
const RGUI = `vyrg${n}`;           // resource group created through the UI
const RGWIRE = `vyrgwire${n}`;     // resource group created over the wire (CLI → UI direction)
const RGLOCK = `vyrglock${n}`;     // resource-group-scoped lock created through the UI
const RGPRINCIPAL = `vyrgprincipal${n}@contoso.com`;  // principal assigned a role through the resource group's IAM tab
const RGDEPLOY = `vyrgdeploy${n}`;  // resource-group-scoped deployment with a real template, created over the wire
const RGDEPLOYRES = `vyrgdeployres${n}`;  // storage account the deployment's template actually provisions
const APIM = `vyapim${n}`;         // API Management service created through the UI
const APIM2 = `vyapimwire${n}`;    // API Management service created over the wire
const APIMROLE = `00000000-0000-4000-9000-${String(n).padStart(12, "0")}`;  // role assignment GUID created over the wire, read back on the APIM service's Access control (IAM) tab
const APIMTAG = `vyapimtag${n}`;   // API Tag created through the UI
const APIMFRAG = `vyapimfrag${n}`; // Policy fragment created through the UI
const APIMDIAG = `vyapimdiag${n}`; // diagnostic setting created over the wire, read back in the UI (CLI → UI direction)
const APIMWS = `vyapimws${n}`;     // workspace created through the UI (wave-5b: azure.apim.workspaces)
const APIMCERT = `vyapimcert${n}`; // certificate created over the wire, read back in the UI (wave-5b: azure.apim.deployment)
const AKS = `vysmokeaks${n}`;      // AKS cluster created through the UI
const AKS2 = `vywireaks${n}`;      // AKS cluster created over the wire
const POOL = `pool${n}`;           // node pool created through the UI (AKS pool names are short: <=12 chars)
const EUSR = `vysmokeuser${n}`;    // Entra ID user created through the UI
const EUSR2 = `vywireuser${n}`;    // Entra ID user created over the wire
const EGRP = `vysmokegrp${n}`;     // Entra ID security group, created through the UI once the directory-settings toggle allows it
const EDEV = `vysmokedevice${n}`;  // device registered through a user's own "Devices" tab
const ESAPP = `vysigninapp${n}`;   // app registration whose real client secret signs in through oauth2/v2.0/token
const SUBNAME = `Vyomi Smoke Subscription ${n}`;  // subscription renamed through the UI
const SUBLOCK = `vysublock${n}`;   // subscription-scoped lock created through the UI
const SUBRG = `vysubrg${n}`;       // resource group created over the wire (shown in the Subscription's Resource groups panel)
const SUBSA = `vysubsa${n}`;       // storage account created over the wire, inside SUBRG (shown in the Subscription's Resources panel)
const SUBDEP = `vysubdep${n}`;     // subscription-scoped deployment created over the wire
const SUBPRINCIPAL = `vysubprincipal${n}@contoso.com`;  // role assignment added through the Subscription's own IAM page
const SUBPOLICY = `vysubpolicy${n}`;           // "Allowed locations" policy assignment created through the UI
const SUBPOLICYDENIED = `vysubpolicydenied${n}`;  // storage account PUT outside the allowed locations, expected to be denied
const NSGROLE = `00000000-0000-4000-a000-${String(n).padStart(12, "0")}`;  // role assignment GUID created over the wire, EXPLICITLY scoped to the NSG resource
const NSGPRINCIPAL = `vynsgprincipal${n}`;  // principal of the NSG-scoped role assignment above
const NSGDIAG = `vynsgdiag${n}`;   // diagnostic setting created through the NSG's own UI tab
const NSGNIC = `vynsgnic${n}`;     // network interface (no NSG yet) created over the wire, associated through the UI
const FLOWVNET = `vyflowvnet${n}`;  // vnet+subnet (NSG-attached) created over the wire for Network Watcher diagnostics
const FLOWNIC = `vyflownic${n}`;   // NIC in that subnet, created over the wire
const FLOWVM = `vyflowvm${n}`;     // VM pointed at that NIC — the target IP flow verify/Next hop diagnose
const DENYRULE = `deny-smoke-${n}`;  // inbound Deny rule the Diagnose and solve problems IP flow verify check must name
const VNETVM = `vysmokevnetvm${n}`;  // VM pointed at the vnet's own NIC, for the vnet's Diagnose and solve problems Next hop check
const VNETROLE = `00000000-0000-4000-c000-${String(n).padStart(12, "0")}`;  // role assignment GUID created over the wire, EXPLICITLY scoped to the vnet resource
const VNETPRINCIPAL = `vyvnetprincipal${n}`;  // principal of the vnet-scoped role assignment above
const DNSZONE = `vysmokedns${n}.com`;    // public DNS zone created through the UI wizard
const DNSZONE2 = `vywiredns${n}.com`;    // DNS zone created over the wire (CLI → UI direction)
const DNSREC = `dnsrec${n}`;             // A record set added through the UI
const DNSREC2 = `dnswirerec${n}`;        // A record set created over the wire (CLI → UI direction)
const DNSPRIV = `vysmokednspriv${n}.net`;  // private DNS zone created through the UI, for VNet links
const DNSVNET = `vysmokednsvnet${n}`;    // vnet linked to the private zone as a registration link
const DNSLOCK = `vysmokednslock${n}`;    // lock created through the UI, scoped to the DNS zone
const COGS = `vysmokecogs${n}`;    // Azure AI services account created through the UI
const COGS2 = `vywirecogs${n}`;    // Azure AI services account created over the wire (CLI → UI direction)
const DEPLOY = `vysmokedeploy${n}`;  // model deployment created through the UI, read back over ARM
const LAW = `vysmokelaw${n}`;       // Log Analytics workspace created through the UI
const LAW2 = `vywirelaw${n}`;       // Log Analytics workspace created over the wire (CLI → UI direction)
const LAWTABLE = `vysmoke${n}_CL`;  // custom table added in the blade
const CAE = `vysmokecae${n}`;      // Container Apps Environment created through the UI
const CA = `vysmokeca${n}`;        // Container App created through the UI
const CA2 = `vywireca${n}`;        // Container App created over the wire (CLI → UI direction)
const CAJ = `vysmokecaj${n}`;      // Container Apps Job created through the UI
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;

// Native-wire cross-checks run INSIDE the page (same origin): on Nano only the service worker
// answers /_wire, and it only sees requests from pages it controls.
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => {
  const r = await fetch(u, i);
  return { status: r.status, text: await r.text(), headers: Object.fromEntries(r.headers.entries()) };
}, [WIRE + path, init]);
const arm = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2023-05-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armWeb = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2023-12-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armAks = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2024-09-02-preview`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armDns = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2018-05-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armCogs = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2024-10-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armApp = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2024-03-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const graph = (method, path, body) => wire(`/v1.0${path}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const blobHdr = (acct) => ({ "x-ms-version": "2021-12-02", authorization: `SharedKey ${acct}:c21va2U=` });
const blob = (method, acct, path, { query = "", headers = {}, body } = {}) => wire(`/${acct}${path}${query}`, { method, headers: { ...blobHdr(acct), ...headers }, body });
const table = (method, path, body) => wire(path, { method, headers: { "content-type": "application/json", accept: "application/json;odata=nometadata" }, body: body !== undefined ? JSON.stringify(body) : undefined });

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Native 404s (e.g. a deleted resource's GET), 403s (e.g. a query against a server with public
// network access disabled, or a database whose TDE protector is unavailable) and 409s (e.g.
// deleting a locked resource) are expected answers, not page errors.
page.on("console", (m) => m.type() === "error" && !/status of (403|404|409)/.test(m.text()) && errors.push(m.text()));
const shot = (name) => page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
const openPanel = async (label) => { await page.getByRole("navigation", { name: "Resource menu" }).getByRole("link", { name: label, exact: true }).click(); await page.waitForTimeout(500); };

try {
  // Nano keeps fetching its in-browser runtime after load, so "networkidle" can take minutes
  // there; wait for the page, then (below) for the backend to be ready.
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });   // portal Home (no page title)
  check("home renders (Azure services + Resources)", await page.getByRole("heading", { name: "Azure services" }).isVisible() && await page.getByRole("tab", { name: "Recent" }).isVisible());
  check("page title is Vyomi branded", (await page.title()) === "Vyomi · Azure", await page.title());
  await shot("01-home");
  // fast
  // ── sweep-E: Export template Bicep/Terraform for App Service, Function App, AKS, Cosmos, Container Apps ──
  {
    const E = `vyexp${n}`;
    await armWeb("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${E}`, { location: "eastus", sku: { name: "B1" } });
    await armWeb("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${E}`, { location: "eastus", kind: "app", properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${E}` } });
    await armWeb("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${E}fn`, { location: "eastus", kind: "functionapp", properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${E}` } });
    await armAks("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${E}`, { location: "eastus" });
    await armApp("PUT", `/resourceGroups/${RG}/providers/Microsoft.App/containerApps/${E}`, { location: "eastus", properties: { template: { containers: [{ image: "nginx" }] } } });
    for (const [label, route, rtype] of [["App Service", `appservices/${RG}/${E}/exporttemplate`, "Microsoft.Web/sites@"], ["Function App", `functionapp/${RG}/${E}fn/export-template`, "Microsoft.Web/sites@"],
      ["AKS", `aks/${RG}/${E}/exporttemplate`, "Microsoft.ContainerService/managedClusters@"], ["Container App", `containerapps/${RG}/${E}/exporttemplate`, "Microsoft.App/containerApps@"]]) {
      await page.goto(UI + `#/${route}`);
      await page.getByRole("tab", { name: "Bicep" }).click();
      const bt = await page.getByTestId("export-bicep").innerText({ timeout: 10000 });
      check(`${label} Export template Bicep rendered from the live resource`, bt.includes(rtype) && bt.includes(`'${E}`), bt.slice(0, 80));
      await page.getByRole("tab", { name: "Terraform" }).click();
      const tt = await page.getByTestId("export-terraform").innerText({ timeout: 10000 });
      check(`${label} Export template Terraform (azapi) rendered`, tt.includes("azapi_resource") && tt.includes(rtype), tt.slice(0, 80));
    }
    // sweep-E-marker
  }
} catch (e) {
  const at = ((e.stack || "").match(/(?:smoke|dbg)-[a-z]+\.mjs:(\d+)/) || [])[1];   // the failing step's line
  check("smoke run", false, e.message.split("\n")[0] + (at ? ` (smoke line ${at})` : ""));
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
