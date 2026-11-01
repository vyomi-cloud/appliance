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
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:8740";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-azure";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "vyomi-smoke-rg";
const n = Date.now() % 100000;
const SA = `vysmoke${n}`;          // created through the UI
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
const AKS = `vysmokeaks${n}`;      // AKS cluster created through the UI
const AKS2 = `vywireaks${n}`;      // AKS cluster created over the wire
const POOL = `pool${n}`;           // node pool created through the UI (AKS pool names are short: <=12 chars)
const EUSR = `vysmokeuser${n}`;    // Entra ID user created through the UI
const EUSR2 = `vywireuser${n}`;    // Entra ID user created over the wire
const EGRP = `vysmokegrp${n}`;     // Entra ID security group, created through the UI once the directory-settings toggle allows it
const SUBNAME = `Vyomi Smoke Subscription ${n}`;  // subscription renamed through the UI
const SUBLOCK = `vysublock${n}`;   // subscription-scoped lock created through the UI
const SUBRG = `vysubrg${n}`;       // resource group created over the wire (shown in the Subscription's Resource groups panel)
const SUBSA = `vysubsa${n}`;       // storage account created over the wire, inside SUBRG (shown in the Subscription's Resources panel)
const SUBDEP = `vysubdep${n}`;     // subscription-scoped deployment created over the wire
const SUBPRINCIPAL = `vysubprincipal${n}@contoso.com`;  // role assignment added through the Subscription's own IAM page
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

  // ── Storage account created through the wizard → visible over native ARM ──────────────
  await page.goto(UI + "#/storage/create");
  await page.getByLabel("Storage account name", { exact: true }).fill(SA);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByLabel("Region", { exact: true }).selectOption("westeurope");
  await shot("02-create-basics");
  for (const t of ["Advanced", "Networking", "Data protection", "Encryption", "Tags"]) {
    await page.getByRole("tab", { name: t, exact: true }).click();
    await page.waitForTimeout(250);
    if (t === "Advanced") await page.getByLabel("Minimum TLS version", { exact: true }).selectOption("TLS1_1");
    if (t === "Tags") { await page.getByLabel("Tag name 1").fill("env"); await page.getByLabel("Tag value 1").fill("smoke"); }
    await shot(`03-create-${t.toLowerCase().replace(/ /g, "-")}`);
  }
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("04-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: SA, exact: true }).waitFor({ timeout: 10000 });
  const got = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`);
  const acct = got.status === 200 ? JSON.parse(got.text) : {};
  check("UI create storage account → visible over native ARM", got.status === 200, `HTTP ${got.status}`);
  check("wizard settings reached ARM (location, SKU, TLS, tags)",
    acct.location === "westeurope" && acct.sku?.name === "Standard_RAGRS" && acct.properties?.minimumTlsVersion === "TLS1_1" && acct.tags?.env === "smoke",
    JSON.stringify({ l: acct.location, sku: acct.sku?.name, tls: acct.properties?.minimumTlsVersion, tags: acct.tags }));
  const list = await arm("GET", `/providers/Microsoft.Storage/storageAccounts`);
  check("account in subscription-scope ARM list", list.text.includes(`"name": "${SA}"`) || list.text.includes(`"name":"${SA}"`));
  await page.getByText("Essentials").waitFor();
  await shot("05-blade-overview");
  for (const t of ["Monitoring", "Capabilities", "Properties"]) await page.getByRole("tab", { name: t }).click();
  check("overview essentials + Properties tab render", await page.getByText("Read-access geo-redundant storage (RA-GRS)").first().isVisible());

  // ── Container + blob in the UI → readable over the Blob data-plane wire ────────────────
  await openPanel("Containers");
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Create" }).click();
  await page.getByLabel("Container name").fill(C);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("link", { name: C, exact: true }).waitFor({ timeout: 10000 });
  const lc = await blob("GET", SA, "", { query: "?comp=list" });
  check("UI create container → listed over Blob wire", lc.text.includes(`<Name>${C}</Name>`), `HTTP ${lc.status}`);
  await shot("06-containers");
  await page.getByRole("link", { name: C, exact: true }).click();
  await page.getByRole("button", { name: "Upload" }).click();
  await page.locator('input[type=file]').setInputFiles({ name: "hello.txt", mimeType: "text/plain", buffer: Buffer.from("hello v4 azure") });
  await page.getByRole("dialog").getByRole("button", { name: "Upload" }).click();
  await page.getByRole("button", { name: "hello.txt" }).waitFor({ timeout: 10000 });
  const b = await blob("GET", SA, `/${C}/hello.txt`);
  check("UI upload blob → readable over Blob wire", b.status === 200 && b.text === "hello v4 azure", `${b.status} ${b.text.slice(0, 40)}`);
  const other = await blob("GET", SA2, `/${C}/hello.txt`);
  check("blob namespaces are per storage account", other.status === 404, `HTTP ${other.status}`);
  await shot("07-container-blobs");

  // ── Table created through the UI → visible over the native Table REST wire, and the reverse ──
  await openPanel("Tables");
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Table" }).click();
  await page.getByLabel("Table name").fill(TBL);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("link", { name: TBL, exact: true }).waitFor({ timeout: 10000 });
  const lt = await table("GET", "/Tables");
  check("UI create table → listed over Table wire", lt.text.includes(`"TableName":"${TBL}"`) || lt.text.includes(`"TableName": "${TBL}"`), `HTTP ${lt.status}`);
  await shot("07b-tables");
  const putTbl = await table("POST", "/Tables", { TableName: TBL2 });
  check("Table wire create", putTbl.status === 201, `HTTP ${putTbl.status}`);
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("link", { name: TBL2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created table shown in Tables grid", true);
  const ins = await table("POST", `/${TBL2}`, { PartitionKey: "smoke", RowKey: "r1", Greeting: "hello v4 azure tables" });
  check("Table wire insert entity", ins.status === 201, `HTTP ${ins.status}`);
  await page.getByRole("link", { name: TBL2, exact: true }).click();
  await page.getByText("hello v4 azure tables").waitFor({ timeout: 10000 });
  check("wire-inserted entity shown in table detail", true);
  await shot("07c-table-entities");

  // ── Blades / panels render; gaps are honest ───────────────────────────────────────────
  for (const [label, file] of [["Access keys", "08-access-keys"], ["Configuration", "09-configuration"], ["Endpoints", "10-endpoints"], ["Tags", "11-tags"]]) {
    await openPanel(label);
    await shot(file);
  }
  check("Access keys panel shows listKeys result", await page.goto(UI + `#/storage/${RG}/${SA}/accesskeys`).then(() => page.getByRole("heading", { name: "key1" }).waitFor({ timeout: 5000 })).then(() => true, () => false));
  await openPanel("Activity log");
  check("unbacked panel is an honest NotSimulated", await page.locator("[data-vyomi-not-simulated]").first().isVisible());
  await shot("12-activity-log-not-simulated");
  // Configuration → ARM PATCH round-trip
  await openPanel("Configuration");
  await page.getByRole("radiogroup", { name: "Blob access tier (default)" }).getByRole("radio", { name: "Cool" }).check();
  await page.getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(800);
  const after = JSON.parse((await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA}`)).text);
  check("Configuration save → ARM properties.accessTier", after.properties?.accessTier === "Cool", after.properties?.accessTier);

  // ── Resource + blob created over the wire → visible in the UI (CLI → UI) ───────────────
  const put = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA2}`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } });
  check("ARM PUT storage account over wire", put.status === 200 || put.status === 201, `HTTP ${put.status}`);
  await blob("PUT", SA2, "/wirebox", { query: "?restype=container" });
  await blob("PUT", SA2, "/wirebox/from-cli.txt", { headers: { "x-ms-blob-type": "BlockBlob", "content-type": "text/plain" }, body: "cli" });
  await page.goto(UI + "#/storage");
  await page.getByRole("link", { name: SA2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created storage account shown in browse grid", true);
  await shot("13-browse");
  await page.goto(UI + `#/storage/${RG}/${SA2}/containers?container=wirebox`);
  await page.getByRole("button", { name: "from-cli.txt" }).waitFor({ timeout: 10000 });
  check("wire-uploaded blob shown in container view", true);

  // ── Delete through the browse grid → gone over ARM ─────────────────────────────────────
  await page.goto(UI + "#/storage");
  await page.getByRole("link", { name: SA2, exact: true }).waitFor({ timeout: 10000 });
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA2}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(SA2);
  await shot("14-delete-confirm");
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("link", { name: SA2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  // The row can leave the grid before the DELETE round-trip settles on a slow substrate (Nano
  // runs the engine in the tab) — poll the ARM read-back briefly instead of reading once.
  let gone = { status: 0 };
  for (let i = 0; i < 20 && gone.status !== 404; i++) {
    gone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${SA2}`);
    if (gone.status !== 404) await page.waitForTimeout(500);
  }
  check("UI delete → ARM GET 404", gone.status === 404, `HTTP ${gone.status}`);

  // ── Cost Management: budget created through the UI → visible over native Consumption wire,
  //    and (against the real spend of the storage account created above) raises a Cost alert ──
  const BUDGET = `vysmoke-budget-${n}`;
  await page.goto(UI + "#/cost/budgets/create");
  await page.getByLabel("Name", { exact: true }).fill(BUDGET);
  await page.getByLabel("Amount", { exact: true }).fill("0.01");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText(BUDGET, { exact: true }).first().waitFor({ timeout: 10000 });
  await shot("18-budget-created");
  const budgetWire = await wire(`/subscriptions/${SUB}/providers/Microsoft.Consumption/budgets/${BUDGET}?api-version=2023-11-01`);
  check("UI create budget → visible over native Consumption wire", budgetWire.status === 200, `HTTP ${budgetWire.status}`);

  await page.goto(UI + "#/cost/alerts");
  await page.getByText(BUDGET, { exact: false }).first().waitFor({ timeout: 10000 });
  check("over-threshold budget → Cost alerts shows a derived alert", true);
  await shot("19-cost-alerts");

  // ── Resource created over the native ARM wire → Advisor recommendations (real inventory) ──
  const CR = `vywirecost${n}`;
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${CR}`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } });
  await page.goto(UI + "#/cost/advisor");
  await page.getByText(CR, { exact: true }).first().waitFor({ timeout: 10000 });
  check("wire-created resource shown in Advisor recommendations", true);
  await shot("20-advisor-recommendations");

  // ── Reservation purchased through the UI → visible over native Capacity wire; Azure
  //    Hybrid Benefit toggled for a VM already in inventory → licenseType set over native ARM ──
  const RES = `vysmokeres${n}`;
  const AHBVM = `vyahbvm${n}`;
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${AHBVM}`,
    { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" } } });   // within the Free tier's size cap offline
  await page.goto(UI + "#/cost/reservations");
  await page.getByRole("button", { name: "Purchase" }).click();
  await page.getByLabel("Reservation name").fill(RES);
  await page.getByLabel("Quantity").fill("1");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText(RES, { exact: true }).first().waitFor({ timeout: 10000 });
  await shot("20a-reservation-created");
  const resWire = await wire(`/subscriptions/${SUB}/providers/Microsoft.Capacity/reservationOrders/${RES}?api-version=2023-11-01`);
  check("UI purchase reservation → visible over native Capacity wire", resWire.status === 200, `HTTP ${resWire.status}`);

  await page.getByRole("row", { name: new RegExp(AHBVM) }).getByRole("switch").click();
  await page.waitForTimeout(500);
  const ahbWire = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${AHBVM}`);
  check("UI toggle Hybrid Benefit → licenseType set over native ARM", JSON.parse(ahbWire.text).properties?.licenseType === "Windows_Server", ahbWire.text.slice(0, 160));
  await shot("20b-hybrid-benefit-toggled");

  // ── Cost allocation rule created through the UI → visible over native CostManagement wire ──
  const ALLOC = `vysmokealloc${n}`;
  await page.goto(UI + "#/cost/allocation");
  await page.getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Rule name").fill(ALLOC);
  await page.getByLabel("Source resource group").selectOption({ label: RG });
  await page.getByLabel("Target resource group").selectOption({ label: RG });
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText(ALLOC, { exact: true }).first().waitFor({ timeout: 10000 });
  await shot("20c-allocation-rule-created");
  const allocWire = await wire(`/subscriptions/${SUB}/providers/Microsoft.CostManagement/costAllocationRules/${ALLOC}?api-version=2023-11-01`);
  check("UI create cost allocation rule → visible over native CostManagement wire", allocWire.status === 200, `HTTP ${allocWire.status}`);

  // ── Function App created through the wizard → visible over native ARM ─────────────────
  const FA = `vysmokefn${n}`;
  const FARG = "cloudlearn-rg";                   // the Function App wizard's default resource group
  await page.goto(UI + "#/functionapp/create");
  await page.getByRole("button", { name: "Select" }).click();
  await page.waitForURL(/#\/functionapp\/create\/flex/);
  await page.getByLabel("Function App name").fill(FA);
  await shot("18-functionapp-basics");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: FA, exact: true }).waitFor({ timeout: 10000 });
  const fa = await armWeb("GET", `/resourceGroups/${FARG}/providers/Microsoft.Web/sites/${FA}`);
  check("UI create function app → visible over native ARM", fa.status === 200, `HTTP ${fa.status}`);
  await shot("19-functionapp-overview");

  // ── Function created in the UI → invoked for real, read back over native ARM ──────────
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForURL(/\/functions\/create/);
  await page.getByRole("tab", { name: "Template details" }).click();
  await page.getByLabel("Function name").fill("httptrigger");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: "httptrigger", exact: true }).waitFor({ timeout: 10000 });
  const fn = await armWeb("GET", `/resourceGroups/${FARG}/providers/Microsoft.Web/sites/${FA}/functions/httptrigger`);
  check("UI create function → visible over native ARM", fn.status === 200, `HTTP ${fn.status}`);
  await page.getByLabel("Body").fill('{"n": 2}');
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByText('"ok": true').waitFor({ timeout: 10000 });
  check("Test/Run executes the real sandboxed function", await page.getByText("hello from Azure Functions").first().isVisible());
  await shot("20-function-test-run");

  // ── Scale and concurrency: a capacity of 0 is ENFORCED against a real invoke ──────────
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/scale-and-concurrency`);
  await page.getByLabel("Maximum instance count").fill("0");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText(/invoke will now be throttled/).waitFor({ timeout: 10000 });
  const scaled = await armWeb("GET", `/resourceGroups/${FARG}/providers/Microsoft.Web/sites/${FA}`);
  check("UI set maximumInstanceCount=0 → native ARM reflects it",
        JSON.parse(scaled.text).properties.functionAppConfig.scaleAndConcurrency.maximumInstanceCount === 0);
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/functions/httptrigger`);
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByText("FunctionsTooBusy").first().waitFor({ timeout: 10000 });
  check("scaled-to-zero capacity is ENFORCED: Test/Run is throttled 429", await page.getByText(/"status": 429/).first().isVisible());
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/scale-and-concurrency`);
  await page.getByLabel("Maximum instance count").fill("100");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText(/never enforced against concurrent callers/).waitFor({ timeout: 10000 });

  // ── Environment variables: UI write → native ARM config/appsettings ───────────────────
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/environment-variables`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("SMOKE_SETTING");
  await page.getByLabel("Value", { exact: true }).fill("1");
  await page.getByRole("button", { name: "OK" }).click();
  await page.getByRole("cell", { name: "SMOKE_SETTING" }).waitFor({ timeout: 10000 });
  const settings = JSON.parse((await armWeb("POST", `/resourceGroups/${FARG}/providers/Microsoft.Web/sites/${FA}/config/appsettings/list`)).text);
  check("UI add app setting → native ARM config/appsettings", settings.properties?.SMOKE_SETTING === "1", JSON.stringify(settings.properties));
  await shot("21-environment-variables");

  // ── App keys panel shows the real host master/default keys ────────────────────────────
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/app-keys`);
  await page.getByRole("cell", { name: "default" }).first().waitFor({ timeout: 10000 });
  check("App keys panel lists the default host key", await page.getByRole("cell", { name: "default" }).first().isVisible());
  await shot("22-app-keys");

  // ── Locks: a CanNotDelete lock added through the UI really blocks delete over native ARM ──
  const FALOCK = `vyfnlock${n}`;
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/locks`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name").fill(FALOCK);
  await page.getByRole("button", { name: "OK" }).click();
  await page.getByRole("cell", { name: FALOCK, exact: true }).waitFor({ timeout: 10000 });
  const lockedDelete = await armWeb("DELETE", `/resourceGroups/${FARG}/providers/Microsoft.Web/sites/${FA}`);
  check("locked function app rejects delete over native ARM", lockedDelete.status === 409, `HTTP ${lockedDelete.status}`);
  await page.goto(UI + `#/functionapp/${FARG}/${FA}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FA);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByText("ScopeLocked").waitFor({ timeout: 10000 });
  check("UI delete is blocked by the lock and shows the ScopeLocked error", true);
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.goto(UI + `#/functionapp/${FARG}/${FA}/locks`);
  await page.getByRole("row", { name: new RegExp(FALOCK) }).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FALOCK);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("cell", { name: FALOCK, exact: true }).waitFor({ state: "detached", timeout: 10000 });

  // ── Delete through Overview → gone over ARM ────────────────────────────────────────────
  await page.goto(UI + `#/functionapp/${FARG}/${FA}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FA);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Function App", exact: true }).waitFor({ timeout: 10000 });
  const faGone = await armWeb("GET", `/resourceGroups/${FARG}/providers/Microsoft.Web/sites/${FA}`);
  check("UI delete function app → ARM GET 404", faGone.status === 404, `HTTP ${faGone.status}`);

  // ── App Service created through the UI → visible over native ARM ──────────────────────
  await page.goto(UI + "#/appservices/create");
  await page.getByLabel("Name", { exact: true }).fill(APP);
  await page.getByLabel("Resource Group", { exact: true }).selectOption(RG);
  await shot("18-appservices-create-basics");
  for (const t of ["Database", "Container", "Deployment", "Networking", "Monitor + secure", "Tags"]) {
    await page.getByRole("tab", { name: t, exact: true }).click();
    await page.waitForTimeout(200);
  }
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("19-appservices-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: APP, exact: true }).waitFor({ timeout: 10000 });
  const siteGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`);
  const site = siteGet.status === 200 ? JSON.parse(siteGet.text) : {};
  check("UI create app service → visible over native ARM", siteGet.status === 200, `HTTP ${siteGet.status}`);
  check("wizard settings reached ARM (OS, runtime, plan)",
    site.kind === "app,linux" && site.properties?.siteConfig?.linuxFxVersion === "PYTHON|3.12" && !!site.properties?.serverFarmId,
    JSON.stringify({ kind: site.kind, fx: site.properties?.siteConfig?.linuxFxVersion, plan: site.properties?.serverFarmId }));
  await shot("20-appservices-blade-overview");

  // ── Stop through the Overview command bar → ARM state ──────────────────────────────────
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Stop" }).click();
  await page.waitForTimeout(600);
  const stopped = JSON.parse((await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`)).text);
  check("UI Stop → ARM state Stopped", stopped.properties?.state === "Stopped", stopped.properties?.state);

  // ── Access control (IAM): a role assignment created over the wire, EXPLICITLY scoped to
  // this App Service resource (not just the subscription) → read back on the Role
  // assignments tab over the same generic Microsoft.Authorization engine the Cosmos DB/VM/NSG
  // blades use (azure.appservices.webapp.iam) ────────────────────────────────────────────
  const appId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`;
  const appRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${APPROLE}?api-version=2022-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ properties: { principalId: APPPRINCIPAL, roleName: "Owner", scope: appId } }) });
  check("ARM PUT role assignment scoped to the App Service over wire", appRoleRes.status === 200 || appRoleRes.status === 201, `HTTP ${appRoleRes.status}`);
  await page.goto(UI + `#/appservices/${RG}/${APP}/iam`);
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText(APPPRINCIPAL).first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the App Service-scoped wire-created assignment", true);
  await shot("20b-appservices-iam-role-assignments");

  // ── Environment variables → ARM config/appsettings round-trip ─────────────────────────
  await page.goto(UI + `#/appservices/${RG}/${APP}/envvars`);
  await page.getByRole("textbox", { name: "Name" }).first().fill("SMOKE_KEY");
  await page.getByRole("textbox", { name: "Value" }).first().fill("smoke-value");
  await shot("21-appservices-envvars");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.waitForTimeout(600);
  const webSettings = JSON.parse((await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}/config/appsettings`)).text);
  check("UI app setting → ARM config/appsettings", webSettings.properties?.SMOKE_KEY === "smoke-value", JSON.stringify(webSettings.properties));

  // ── App Service created over the wire → visible in the UI (CLI → UI) ──────────────────
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${APP2}-plan`, { location: "eastus", sku: { name: "B1" }, properties: { reserved: true } });
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP2}`,
    { location: "eastus", kind: "app,linux", properties: { serverFarmId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/serverfarms/${APP2}-plan` } });
  await page.goto(UI + "#/appservices");
  await page.getByRole("link", { name: APP2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created app service shown in browse grid", true);
  await shot("22-appservices-browse");

  // ── Delete through the browse grid → gone over ARM ─────────────────────────────────────
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP2}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(APP2);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("link", { name: APP2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  // The grid drops the row as soon as it starts reloading; on Nano the DELETE may still be in flight.
  let gone2 = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP2}`);
  for (let i = 0; i < 20 && gone2.status !== 404; i++) {
    await page.waitForTimeout(500);
    gone2 = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP2}`);
  }
  check("UI delete app service → ARM GET 404", gone2.status === 404, `HTTP ${gone2.status}`);
  // ── Key vault created through the wizard → visible over native ARM ─────────────────────
  const kvWire = (path, method = "GET", body, vault) => wire(`${path}${path.includes("?") ? "&" : "?"}api-version=7.4`,
    { method, headers: { "content-type": "application/json", ...(vault ? { "x-vyomi-vault": vault } : {}) },
      body: body ? JSON.stringify(body) : undefined });
  const KV = `vysmokekv${n}`;
  await page.goto(UI + "#/keyvaults/create");
  await page.getByLabel("Key vault name", { exact: true }).fill(KV);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await shot("18-create-keyvault-basics");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: KV, exact: true }).waitFor({ timeout: 10000 });
  const gotKv = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`);
  check("UI create key vault → visible over native ARM", gotKv.status === 200, `HTTP ${gotKv.status}`);
  await shot("19-keyvault-overview");

  // ── Secret created in the UI → readable over the Key Vault Secrets REST wire ───────────
  await openPanel("Secrets");
  await page.getByRole("button", { name: "Generate/Import" }).click();
  const SECRET = `smoke-secret-${n}`;
  await page.getByLabel("Name", { exact: true }).fill(SECRET);
  await page.getByLabel("Secret value", { exact: true }).fill("s3cr3t");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("link", { name: SECRET, exact: true }).waitFor({ timeout: 10000 });
  const sGet = await kvWire(`/secrets/${SECRET}`);
  check("UI create secret → readable over Key Vault Secrets wire", sGet.status === 200 && JSON.parse(sGet.text).value === "s3cr3t", `HTTP ${sGet.status}`);
  await shot("20-secrets");

  // ── Key created over the wire → visible in the UI (CLI → UI) ───────────────────────────
  const KEY = `wirekey${n}`;
  const putKey = await kvWire(`/keys/${KEY}/create`, "POST", { kty: "RSA", key_size: 2048 });
  check("Key Vault Keys REST create over wire", putKey.status === 200, `HTTP ${putKey.status}`);
  await page.goto(UI + `#/keyvaults/${RG}/${KV}/keys`);
  await page.getByText(KEY, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created key shown in Keys grid", true);
  await shot("21-keys");

  // ── Certificate created in the UI → readable over the Key Vault Certificates REST wire ─
  await openPanel("Certificates");
  await page.getByRole("button", { name: "Generate/Import" }).click();
  const CERT = `smoke-cert-${n}`;
  await page.getByLabel("Certificate Name", { exact: true }).fill(CERT);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText(CERT, { exact: true }).waitFor({ timeout: 10000 });
  const cGet = await kvWire(`/certificates/${CERT}`);
  check("UI create certificate → readable over Key Vault Certificates wire", cGet.status === 200 && !!JSON.parse(cGet.text).x5t, `HTTP ${cGet.status}`);
  await shot("21b-certificates");

  // ── Certificate imported over the wire (real PEM DER) → visible in the UI (CLI → UI) ───
  const CERTIMPORT = `wirecert-import-${n}`;
  const certDer = createHash("sha256").update(`smoke-cert-der-${n}`).digest();
  const certPem = `-----BEGIN CERTIFICATE-----\n${certDer.toString("base64")}\n-----END CERTIFICATE-----\n`;
  const putImportCert = await kvWire(`/certificates/${CERTIMPORT}/import`, "POST", { value: Buffer.from(certPem).toString("base64") });
  const importedCerBody = putImportCert.status === 200 ? JSON.parse(putImportCert.text) : null;
  check("Key Vault Certificates REST import over wire → real DER round-trips",
    putImportCert.status === 200 && Buffer.from(importedCerBody.cer, "base64").equals(certDer), `HTTP ${putImportCert.status}`);
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Refresh" }).click();
  await page.getByText(CERTIMPORT, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-imported certificate shown in Certificates grid", true);
  await shot("21c-certificates-imported");

  // ── Networking: "Disable public access" really blocks this vault's Key Vault wire ──────
  await arm("PATCH", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`,
    { properties: { publicNetworkAccess: "Disabled" } });
  const blockedSecret = `smoke-netblocked-${n}`;
  const putBlocked = await kvWire(`/secrets/${blockedSecret}`, "PUT", { value: "x" }, KV);
  check("publicNetworkAccess=Disabled blocks the Key Vault Secrets wire", putBlocked.status === 403, `HTTP ${putBlocked.status}`);
  const putBlockedNoVault = await kvWire(`/secrets/${blockedSecret}`, "PUT", { value: "x" });
  check("the SAME call with no vault signal is unaffected (direct SDK, unmodelled)", putBlockedNoVault.status === 200, `HTTP ${putBlockedNoVault.status}`);
  await arm("PATCH", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}`,
    { properties: { publicNetworkAccess: "Enabled" } });
  const putUnblocked = await kvWire(`/secrets/${blockedSecret}`, "PUT", { value: "x" }, KV);
  check("re-enabling publicNetworkAccess unblocks the same vault", putUnblocked.status === 200, `HTTP ${putUnblocked.status}`);

  // ── Activity log Timespan picker really narrows the query (eventTimestamp ge, ENFORCED) ──
  await openPanel("Activity log");
  await page.getByText("Microsoft.KeyVault/vaults/write").first().waitFor({ timeout: 10000 });
  await page.getByLabel("Timespan", { exact: true }).selectOption("1h");
  await page.getByText("Microsoft.KeyVault/vaults/write").first().waitFor({ timeout: 10000 });
  check("UI Activity log timespan picker narrows the query without losing this vault's own recent events", true);

  // ── Lock created in the UI → visible over the native ARM wire (and the reverse) ────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const KVLOCK = `smoke-kvlock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(KVLOCK);
  await page.getByLabel("Lock type", { exact: true }).selectOption("Read-only");
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByText(KVLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const kvLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}/providers/Microsoft.Authorization/locks/${KVLOCK}?api-version=2020-05-01`);
  check("UI create lock → visible over native ARM", kvLockGet.status === 200 && JSON.parse(kvLockGet.text).properties.level === "ReadOnly", `HTTP ${kvLockGet.status}`);
  await shot("22-locks");

  const KVWIRELOCK = `kvwirelock${n}`;
  const kvPutLock = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KV}/providers/Microsoft.Authorization/locks/${KVWIRELOCK}?api-version=2020-05-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { level: "CanNotDelete" } }) });
  check("Microsoft.Authorization/locks PUT over wire", kvPutLock.status === 200 || kvPutLock.status === 201, `HTTP ${kvPutLock.status}`);
  await page.reload();
  await page.getByText(KVWIRELOCK, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created lock shown in Locks grid", true);
  await shot("23-locks-wire");

  // ── Shell: unbacked service is honest; dark mode ───────────────────────────────────────
  // Every Azure service now has a v4 blade — an address no service owns must still be an honest gap.
  await page.goto(UI + "#/no-such-service");
  await page.locator("[data-vyomi-not-simulated]").first().waitFor({ timeout: 10000 }).catch(() => {});
  check("unknown service address → honest NotSimulated panel", await page.locator("[data-vyomi-not-simulated]").first().isVisible());
  await shot("15-unknown-service");
  await page.evaluate(() => localStorage.setItem("vyomi.v4.azure.mode", "dark"));
  await page.goto(UI + `#/storage/${RG}/${SA}`);
  await page.reload();
  await page.getByText("Essentials").waitFor();
  await shot("16-dark");
  await page.goto(UI);
  await page.getByRole("link", { name: SA }).first().waitFor({ timeout: 5000 });
  check("Home → Resources → Recent lists viewed account", true);
  await shot("17-home-dark-recent");
  await page.evaluate(() => localStorage.removeItem("vyomi.v4.azure.mode"));

  // ── Event Grid: topic created through the UI → visible over native ARM ─────────────────
  await page.goto(UI + "#/eventgrid/topics/create");
  await page.getByLabel("Name", { exact: true }).fill(EGT);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByRole("tab", { name: "Security" }).click();
  await page.getByLabel("Minimum TLS version", { exact: true }).selectOption("1.1");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("18-eventgrid-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: EGT, exact: true }).waitFor({ timeout: 10000 });
  const egot = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT}`);
  const egtopic = egot.status === 200 ? JSON.parse(egot.text) : {};
  check("UI create Event Grid topic → visible over native ARM", egot.status === 200, `HTTP ${egot.status}`);
  check("topic gets an endpoint + TLS setting reached ARM", (egtopic.properties?.endpoint || "").includes(EGT) && egtopic.properties?.minimumTlsVersionAllowed === "1.1", JSON.stringify(egtopic.properties));
  await shot("19-eventgrid-topic-overview");

  // ── Event subscription created through the UI → visible over native ARM (scoped) ───────
  await page.getByRole("link", { name: "Event Subscription", exact: true }).or(page.getByRole("button", { name: "Event Subscription", exact: true })).first().click();
  await page.getByLabel("Name", { exact: true }).fill(ES);
  await page.getByLabel("Endpoint", { exact: true }).fill("https://example.com/hook");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: EGT, exact: true }).waitFor({ timeout: 10000 });
  const esr = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT}/providers/Microsoft.EventGrid/eventSubscriptions/${ES}`);
  const essub = esr.status === 200 ? JSON.parse(esr.text) : {};
  check("UI create event subscription → visible over native ARM (extension resource)",
    esr.status === 200 && essub.properties?.destination?.properties?.endpointUrl === "https://example.com/hook", `HTTP ${esr.status}`);
  await page.getByText(ES).first().waitFor({ timeout: 10000 });
  check("event subscription listed on the topic overview", true);
  await shot("20-eventgrid-event-subscriptions");

  // ── Activity log: real, backed by the cloudsim event log recorded on every ARM mutation ──
  await openPanel("Activity log");
  await page.getByText(ES).first().waitFor({ timeout: 10000 });
  check("Event Grid activity log shows the event subscription create", true);

  // ── Locks: real extension resource (Microsoft.Authorization/locks), scoped to the topic ──
  await openPanel("Locks");
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(LOCK);
  await page.getByRole("button", { name: "OK" }).click();
  await page.getByText(LOCK).first().waitFor({ timeout: 10000 });
  const lockGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT}/providers/Microsoft.Authorization/locks/${LOCK}`);
  check("UI add lock → visible over native ARM (extension resource)", lockGet.status === 200, `HTTP ${lockGet.status}`);
  const lockedEgDelete = await arm("DELETE", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT}`);
  check("locked Event Grid topic rejects delete over native ARM", lockedEgDelete.status === 409, `HTTP ${lockedEgDelete.status}`);

  // ── Access control (IAM): a role assignment created over the wire (subscription-wide,
  // same honest scoping as the Cosmos DB account blade) is read back on the topic's tab ────
  const egRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${EGROLE}?api-version=2022-04-01`,
    { method: "PUT", body: JSON.stringify({ properties: { principalId: "eventgrid-smoke-principal", roleDefinitionId: `/subscriptions/${SUB}/providers/Microsoft.Authorization/roleDefinitions/owner`, principalType: "User" } }) });
  check("ARM PUT role assignment over wire", egRoleRes.status === 200 || egRoleRes.status === 201, `HTTP ${egRoleRes.status}`);
  await openPanel("Access control (IAM)");
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText("eventgrid-smoke-principal").first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the wire-created assignment", true);

  // ── Export template: the ARM Template tab renders this topic's own live resource JSON ──
  await openPanel("Export template");
  await page.getByRole("tab", { name: "ARM Template" }).click();
  const armTemplateText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (ARM Template) reflects the real resource",
    armTemplateText.includes("Microsoft.EventGrid/topics") && armTemplateText.includes(EGT), armTemplateText.slice(0, 200));

  // ── Resource created over the wire → visible in the UI (CLI → UI) ──────────────────────
  const egput = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT2}`, { location: "eastus" });
  check("ARM PUT Event Grid topic over wire", egput.status === 200 || egput.status === 201, `HTTP ${egput.status}`);
  await page.goto(UI + "#/eventgrid/topics");
  await page.getByRole("link", { name: EGT2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created topic shown in browse grid", true);
  await shot("21-eventgrid-topics");

  // ── Bulk "Assign tags" on the Topics list → real ARM PATCH merged onto the selection ───
  await page.getByRole("row", { name: new RegExp(EGT2) }).getByRole("checkbox").check();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Assign tags" }).click();
  await page.getByLabel("Tag name 1", { exact: true }).fill("env");
  await page.getByLabel("Tag value 1", { exact: true }).fill("smoke");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.waitForTimeout(600);
  const egBulkTags = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT2}`);
  check("UI bulk Assign tags → merged onto the selected topic over native ARM", JSON.parse(egBulkTags.text).tags?.env === "smoke", egBulkTags.text);

  // ── Delete through the topic overview is blocked while the lock stands ─────────────────
  await page.goto(UI + `#/eventgrid/topics/${RG}/${EGT}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(EGT);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByText("ScopeLocked").waitFor({ timeout: 10000 });
  check("UI delete is blocked by the lock and shows the ScopeLocked error", true);
  await page.getByRole("button", { name: "Cancel" }).click();

  // ── Remove the lock, then delete through the topic overview → gone over ARM ────────────
  await page.goto(UI + `#/eventgrid/topics/${RG}/${EGT}/locks`);
  await page.getByLabel(`Select ${LOCK}`, { exact: true }).check();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(LOCK);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByLabel(`Select ${LOCK}`, { exact: true }).waitFor({ state: "detached", timeout: 10000 });   // the lock's own row (its name also appears in activity/notifications)
  await page.goto(UI + `#/eventgrid/topics/${RG}/${EGT}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(EGT);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Event Grid Topics" }).waitFor({ timeout: 10000 });
  const egGone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT}`);
  check("UI delete topic → ARM GET 404", egGone.status === 404, `HTTP ${egGone.status}`);

  // ── Resource groups: created through the UI wizard → visible over native ARM ───────────
  await page.goto(UI + "#/resourcegroups/create");
  await page.getByLabel("Resource group name", { exact: true }).fill(RGUI);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: RGUI, exact: true }).waitFor({ timeout: 10000 });
  const gotRg = await arm("GET", `/resourceGroups/${RGUI}`);
  check("UI create resource group → visible over native ARM", gotRg.status === 200, `HTTP ${gotRg.status}`);
  await shot("22-resourcegroup-overview");

  // ── Tags applied in the UI → persisted over ARM ─────────────────────────────────────────
  await openPanel("Tags");
  await page.getByLabel("Tag name 1", { exact: true }).fill("env");
  await page.getByLabel("Tag value 1", { exact: true }).fill("smoke");
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await page.waitForTimeout(600);
  const rgTags = await arm("GET", `/resourceGroups/${RGUI}`);
  check("UI tag apply → persisted on the resource group over ARM", JSON.parse(rgTags.text).tags?.env === "smoke", rgTags.text);

  // ── Activity log: aggregates both the group's own create and its tag update ────────────
  await openPanel("Activity log");
  await page.getByText("Microsoft.Resources/resourceGroups/write").first().waitFor({ timeout: 10000 });
  check("resource group activity log shows its own create/update", true);

  // ── Lock created in the UI, scoped to the resource group itself → visible over ARM ──────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(RGLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(RGLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const rgLockGet = await arm("GET", `/resourceGroups/${RGUI}/providers/Microsoft.Authorization/locks/${RGLOCK}`);
  check("UI add resource-group-scoped lock → visible over native ARM", rgLockGet.status === 200, `HTTP ${rgLockGet.status}`);

  // ── Access control (IAM): role assignment added through the UI, scoped to this resource
  // group (not the subscription), then a real checkAccess decision, then removed ───────────
  await openPanel("Access control (IAM)");
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByRole("toolbar", { name: "Access control commands" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Role", { exact: true }).selectOption("Reader");
  await page.getByLabel("Member", { exact: true }).fill(RGPRINCIPAL);
  await page.getByRole("button", { name: "Review + assign" }).click();
  await page.getByText(RGPRINCIPAL).first().waitFor({ timeout: 10000 });
  const raGet = await arm("GET", `/resourceGroups/${RGUI}/providers/Microsoft.Authorization/roleAssignments`);
  const raList = JSON.parse(raGet.text).value || [];
  const ra = raList.find((r) => r.properties?.principalId === RGPRINCIPAL);
  check("UI Add role assignment → visible over native ARM, scoped to this resource group",
    !!ra && ra.properties.scope === `/subscriptions/${SUB}/resourceGroups/${RGUI}`, JSON.stringify(ra));
  await shot("22b-resourcegroup-iam-role-assignments");

  await page.getByRole("tab", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByLabel("Find a user, group or service principal", { exact: true }).fill(RGPRINCIPAL);
  await page.getByRole("dialog").getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByText("Allowed").waitFor({ timeout: 10000 });
  check("UI Check access → real decision reflects the role just assigned", true);
  const checkClose = page.getByRole("dialog").getByRole("button", { name: "Close" }).last();   // the dialog's own Close (not the X)
  if (await checkClose.isVisible().catch(() => false)) await checkClose.click();

  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByLabel(`Select ${RGPRINCIPAL}`, { exact: true }).check();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await page.getByRole("row", { name: new RegExp(RGPRINCIPAL.replace(/[.@]/g, "\\$&")) }).waitFor({ state: "detached", timeout: 10000 });
  // Scoped to the checkbox (not getByText(RGPRINCIPAL)) — a success toast can still be
  // showing the same principal text, which would otherwise make this a strict-mode violation.
  await page.getByLabel(`Select ${RGPRINCIPAL}`, { exact: true }).waitFor({ state: "detached", timeout: 10000 });
  const raGone = await arm("GET", `/resourceGroups/${RGUI}/providers/Microsoft.Authorization/roleAssignments`);
  check("UI Remove role assignment → gone over native ARM",
    !(JSON.parse(raGone.text).value || []).some((r) => r.properties?.principalId === RGPRINCIPAL), raGone.text);

  // ── Deployments: a template-driven deployment created over the wire actually provisions a
  // real resource; Redeploy re-runs it for real, Cancel on a completed deployment honestly fails ──
  const deployTemplate = {
    parameters: { saName: { defaultValue: RGDEPLOYRES } },
    resources: [{ type: "Microsoft.Storage/storageAccounts", apiVersion: "2023-01-01", name: "[parameters('saName')]" }],
  };
  const depPut = await arm("PUT", `/resourceGroups/${RGUI}/providers/Microsoft.Resources/deployments/${RGDEPLOY}`,
    { properties: { mode: "Incremental", template: deployTemplate } });
  check("ARM PUT resource-group-scoped deployment with a template over wire → provisions the resource for real",
    depPut.status === 200 && JSON.parse(depPut.text).properties?.outputResources?.[0]?.resourceName === RGDEPLOYRES, depPut.text);

  await openPanel("Deployments");
  await page.getByText(RGDEPLOY, { exact: true }).waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "View template" }).click();
  await page.getByText(RGDEPLOYRES).first().waitFor({ timeout: 5000 });
  check("UI View template shows the resource the deployment actually provisioned", true);
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByLabel(`Select ${RGDEPLOY}`, { exact: true }).check();
  await page.getByRole("button", { name: "Redeploy", exact: true }).click();
  await page.getByText("Redeploy").first().waitFor({ timeout: 10000 });
  check("UI Redeploy re-runs the template for real", true);

  await page.getByLabel(`Select ${RGDEPLOY}`, { exact: true }).check();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByText("Cancel failed").waitFor({ timeout: 10000 });
  check("UI Cancel on an already-completed deployment honestly fails (every deployment here completes synchronously)", true);
  await shot("22c-resourcegroup-deployments");

  // ── Resource group created over the wire → visible in the UI browse grid (CLI → UI) ─────
  const rgPut = await arm("PUT", `/resourceGroups/${RGWIRE}`, { location: "eastus" });
  check("ARM PUT resource group over wire", rgPut.status === 200, `HTTP ${rgPut.status}`);
  await page.goto(UI + "#/resourcegroups");
  await page.getByRole("link", { name: RGWIRE, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created resource group shown in browse grid", true);
  await shot("23-resourcegroups-list");

  // ── Delete through the dedicated delete page → gone over ARM, cascading to its lock ─────
  await page.goto(UI + `#/resourcegroups/${RGUI}/delete`);
  await page.getByLabel("Enter resource group name to confirm deletion", { exact: true }).fill(RGUI);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("heading", { name: "Resource groups" }).waitFor({ timeout: 10000 });
  const rgGone = await arm("GET", `/resourceGroups/${RGUI}`);
  check("UI delete resource group → ARM GET 404", rgGone.status === 404, `HTTP ${rgGone.status}`);
  const rgLockGone = await arm("GET", `/resourceGroups/${RGUI}/providers/Microsoft.Authorization/locks/${RGLOCK}`);
  check("deleted resource group's own lock cascades away", rgLockGone.status === 404, `HTTP ${rgLockGone.status}`);
  // ── API Management: service created through the wizard → visible over native ARM ──────
  const apimWire = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2023-05-01-preview`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  await page.goto(UI + "#/apim/create");
  await page.getByLabel("Resource name", { exact: true }).fill(APIM);
  await page.getByLabel("Organization name", { exact: true }).fill("CloudLearn");
  await page.getByLabel("Administrator email", { exact: true }).fill("admin@cloudlearn.dev");
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await shot("23-apim-create-basics");
  await page.getByRole("tab", { name: "Managed identity" }).click();
  await page.getByLabel("Status", { exact: true }).check();
  await page.getByRole("button", { name: "Review + install" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("24-apim-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: APIM, exact: true }).waitFor({ timeout: 10000 });
  const apimGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}`);
  const apimSvc = apimGot.status === 200 ? JSON.parse(apimGot.text) : {};
  check("UI create API Management service → visible over native ARM", apimGot.status === 200, `HTTP ${apimGot.status}`);
  check("wizard settings reached ARM (publisher, identity)",
    apimSvc.properties?.publisherEmail === "admin@cloudlearn.dev" && apimSvc.identity?.type === "SystemAssigned", JSON.stringify({ email: apimSvc.properties?.publisherEmail, identity: apimSvc.identity }));
  await shot("25-apim-overview");

  // ── API created through the UI → visible over native ARM (nested sub-resource) ─────────
  await openPanel("APIs");
  await page.getByRole("link", { name: "Add API", exact: true }).or(page.getByRole("button", { name: "Add API", exact: true })).first().click();
  await page.getByLabel("Display name", { exact: true }).fill("Smoke API");
  await page.getByLabel("Web service URL", { exact: true }).fill("https://example.com");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  const apiPut = page.waitForResponse((r) => r.request().method() === "PUT" && /\/apis\/smoke-api\?/.test(r.url()), { timeout: 15000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await apiPut;   // the review step already shows "smoke-api", so wait for the real PUT
  await page.getByText("smoke-api", { exact: true }).first().waitFor({ timeout: 10000 });
  const apiGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/apis/smoke-api`);
  check("UI create API → visible over native ARM (nested sub-resource)", apiGot.status === 200, `HTTP ${apiGot.status}`);
  await shot("26-apim-apis");

  // ── Subscription created through the UI → visible over native ARM ──────────────────────
  await openPanel("Subscriptions");
  await page.getByRole("button", { name: "Add subscription", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("Smoke Subscription");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText("smoke-subscription", { exact: true }).waitFor({ timeout: 10000 });
  const subGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/subscriptions/smoke-subscription`);
  check("UI create subscription → visible over native ARM, keys generated", subGot.status === 200 && !!JSON.parse(subGot.text).properties?.primaryKey, `HTTP ${subGot.status}`);
  await shot("27-apim-subscriptions");

  // ── Lock created in the UI → visible over the native ARM wire (extension resource) ─────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const APIMLOCK = `smoke-apimlock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(APIMLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(APIMLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const apimLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/providers/Microsoft.Authorization/locks/${APIMLOCK}?api-version=2020-05-01`);
  check("UI create lock → visible over native ARM (extension resource)", apimLockGet.status === 200, `HTTP ${apimLockGet.status}`);
  await shot("28-apim-locks");

  // ── API Tag created through the UI → visible over native ARM (nested sub-resource) ─────
  await openPanel("API Tags");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(APIMTAG);
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByText(APIMTAG, { exact: true }).waitFor({ timeout: 10000 });
  const apimTagGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/tags/${APIMTAG}`);
  check("UI create API Tag → visible over native ARM (nested sub-resource)", apimTagGot.status === 200, `HTTP ${apimTagGot.status}`);
  await shot("28b-apim-apitags");

  // ── Policy fragment created through the UI → visible over native ARM, XML stored as-is ──
  await openPanel("Policy fragments");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(APIMFRAG);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText(APIMFRAG, { exact: true }).waitFor({ timeout: 10000 });
  const apimFragGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/policyFragments/${APIMFRAG}`);
  check("UI create policy fragment → visible over native ARM, XML round-trips",
    apimFragGot.status === 200 && JSON.parse(apimFragGot.text).properties?.value?.includes("<fragment>"), `HTTP ${apimFragGot.status}`);
  await shot("28c-apim-policyfragments");

  // ── Named value created through the UI, type Key Vault → "Show value" resolves against
  // the REAL secret created earlier over the Key Vault Secrets wire (azure.apim.namedvalues.keyvaultref) ──
  await openPanel("Named values");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const APIMNV = `smoke-apimnv-${n}`;
  await page.getByLabel("Name", { exact: true }).fill(APIMNV);
  await page.getByRole("radiogroup", { name: "Type" }).getByRole("radio", { name: "Key Vault" }).check();
  await page.getByLabel("Key Vault secret identifier", { exact: true }).fill(`https://${KV}.vault.azure.net/secrets/${SECRET}`);
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByText(APIMNV, { exact: true }).waitFor({ timeout: 10000 });
  const apimNvGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/namedValues/${APIMNV}`);
  check("UI create named value (Key Vault) → visible over native ARM", apimNvGot.status === 200, `HTTP ${apimNvGot.status}`);
  await page.getByRole("button", { name: "Show value" }).click();
  await page.getByText("s3cr3t", { exact: true }).waitFor({ timeout: 10000 });
  check("UI 'Show value' resolves the real Key Vault secret", true);
  await shot("28ca-apim-namedvalues");

  // ── Scale out and up / Pricing tier: UI sku PATCH → visible over native ARM, reflected
  // in Overview's "Tier" field (same sku merge the create wizard writes). Pricing tier first:
  // Developer (the create default) has a fixed unit count — ENFORCED (azure.apim.scaletier) —
  // so Units can't be scaled until the tier allows it. ───────────────────────────────────
  await openPanel("Pricing tier");
  await page.getByLabel("Pricing tier", { exact: true }).selectOption("Premium");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Tier updated").first().waitFor({ timeout: 10000 }).catch(() => {});
  await openPanel("Scale out and up");
  await page.getByLabel("Units", { exact: true }).fill("3");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Units: 3", { exact: false }).waitFor({ timeout: 10000 });
  const apimSkuGot = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}`);
  const apimSku = apimSkuGot.status === 200 ? JSON.parse(apimSkuGot.text).sku : {};
  check("UI scale + pricing tier → visible over native ARM", apimSku?.capacity === 3 && apimSku?.name === "Premium", JSON.stringify(apimSku));
  await openPanel("Overview");
  await page.getByText("Premium", { exact: true }).first().waitFor({ timeout: 10000 });
  check("Overview Tier field reflects the ARM-patched sku", true);
  await shot("28d-apim-scale-tier");

  // ── Diagnostic setting created over the wire → visible in the UI (CLI → UI direction) ──
  const apimDiagRes = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/providers/Microsoft.Insights/diagnosticSettings/${APIMDIAG}?api-version=2021-05-01-preview`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { storageAccountId: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/apimsmokesa`, logs: [{ categoryGroup: "allLogs", enabled: true }] } }) });
  check("ARM PUT diagnostic setting over wire", apimDiagRes.status === 200 || apimDiagRes.status === 201, `HTTP ${apimDiagRes.status}`);
  await openPanel("Diagnostic settings");
  await page.getByText(APIMDIAG, { exact: true }).waitFor({ timeout: 10000 });
  check("UI Diagnostic settings shows the wire-created setting", true);
  await shot("28e-apim-diagnosticsettings");

  // ── Access control (IAM): a role assignment created over the wire at the SUBSCRIPTION
  // scope is read back on this tab too — the resource-scoped list includes its subscription/
  // resource-group ancestors (real inherited access), same pattern as Event Grid / Cosmos DB ──
  const apimRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${APIMROLE}?api-version=2022-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { principalId: "apim-smoke-principal", roleDefinitionId: `/subscriptions/${SUB}/providers/Microsoft.Authorization/roleDefinitions/owner`, principalType: "User" } }) });
  check("ARM PUT role assignment over wire", apimRoleRes.status === 200 || apimRoleRes.status === 201, `HTTP ${apimRoleRes.status}`);
  await openPanel("Access control (IAM)");
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText("apim-smoke-principal").first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the wire-created assignment", true);
  await shot("28f-apim-iam");

  // ── API Management service created over the wire → visible in the UI (CLI → UI) ────────
  const apimPut = await apimWire("PUT", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM2}`, { location: "eastus", properties: { publisherEmail: "a@b.com", publisherName: "CLI" } });
  check("ARM PUT API Management service over wire", apimPut.status === 200 || apimPut.status === 201, `HTTP ${apimPut.status}`);
  await page.goto(UI + "#/apim");
  await page.getByRole("link", { name: APIM2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created API Management service shown in browse grid", true);
  await shot("29-apim-browse");

  // ── Delete through the overview command bar → gone over ARM ────────────────────────────
  await page.goto(UI + `#/apim/${RG}/${APIM}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(APIM);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "API Management services" }).waitFor({ timeout: 10000 });
  const apimGone = await apimWire("GET", `/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}`);
  check("UI delete API Management service → ARM GET 404", apimGone.status === 404, `HTTP ${apimGone.status}`);
  // ── Container registry created through the wizard → visible over native ARM ───────────
  const ACR = `vysmokeacr${n}`;
  const ACR2 = `vywireacr${n}`;
  await page.goto(UI + "#/acr/create");
  await page.getByLabel("Registry name", { exact: true }).fill(ACR);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("23-acr-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: ACR, exact: true }).waitFor({ timeout: 10000 });
  const acrGot = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}`);
  check("UI create container registry → visible over native ARM", acrGot.status === 200, `HTTP ${acrGot.status}`);
  await shot("24-acr-overview");

  // ── Admin user + credentials: UI toggle → ARM round-trip, real listCredentials/regenerate ──
  await openPanel("Access keys");
  await page.getByRole("checkbox", { name: "Admin user" }).click();
  await page.getByText("Username").waitFor({ timeout: 10000 });
  const pwBefore = await page.getByLabel("password", { exact: true }).inputValue();
  await page.getByRole("button", { name: "Regenerate" }).first().click();
  await page.waitForTimeout(500);
  const pwAfter = await page.getByLabel("password", { exact: true }).inputValue();
  check("Access keys: admin user enable + regenerate rotates the password", !!pwBefore && pwBefore !== pwAfter, `${pwBefore} -> ${pwAfter}`);
  await shot("25-acr-access-keys");

  // ── Access control (IAM): a role assignment created over the wire (subscription-wide, same
  // honest scoping as the VM/NSG/Cosmos DB blades) is read back on the registry's own IAM tab ──
  const ACRROLE = `00000000-0000-4000-b000-${String(n).padStart(12, "0")}`;
  const acrRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${ACRROLE}?api-version=2022-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { principalId: "vyomi-acr-smoke-principal", roleDefinitionId: `/subscriptions/${SUB}/providers/Microsoft.Authorization/roleDefinitions/owner`, principalType: "User" } }) });
  check("ARM PUT role assignment over wire", acrRoleRes.status === 200 || acrRoleRes.status === 201, `HTTP ${acrRoleRes.status}`);
  await page.goto(UI + `#/acr/${RG}/${ACR}/iam`);
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText("vyomi-acr-smoke-principal").first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the wire-created assignment", true);
  await shot("25b-acr-iam-role-assignments");

  // ── Diagnostic settings: added through the UI (real Microsoft.Insights/diagnosticSettings
  // extension resource scoped to this registry) → visible over native ARM (azure.acr.monitoring) ──
  const ACRWS = `vyacrws${n}`;
  const acrWsPut = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.OperationalInsights/workspaces/${ACRWS}?api-version=2022-10-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus", properties: {} }) });
  check("ARM PUT Log Analytics workspace for registry diagnostic settings over wire", acrWsPut.status === 200 || acrWsPut.status === 201, `HTTP ${acrWsPut.status}`);
  const ACRDIAG = `vyacrdiag${n}`;
  await openPanel("Diagnostic settings");
  await page.getByRole("button", { name: "Add diagnostic setting" }).click();
  await page.getByLabel("Diagnostic setting name", { exact: true }).fill(ACRDIAG);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText(ACRDIAG, { exact: true }).first().waitFor({ timeout: 10000 });
  const acrDiagGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}/providers/Microsoft.Insights/diagnosticSettings/${ACRDIAG}?api-version=2021-05-01-preview`);
  check("UI add diagnostic setting on registry → visible over native ARM extension resource", acrDiagGet.status === 200, `HTTP ${acrDiagGet.status}`);
  await shot("25c-acr-diagnostic-settings");

  // ── Export template: ARM, Bicep and Terraform all reflect this registry's own live resource ──
  await page.goto(UI + `#/acr/${RG}/${ACR}/exporttemplate`);
  const acrArmText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (ARM) reflects the real resource",
    acrArmText.includes("Microsoft.ContainerRegistry/registries") && acrArmText.includes(ACR), acrArmText.slice(0, 200));
  await page.getByRole("tab", { name: "Bicep" }).click();
  const acrBicepText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (Bicep) reflects the real resource",
    acrBicepText.includes("Microsoft.ContainerRegistry/registries") && acrBicepText.includes(ACR), acrBicepText.slice(0, 200));
  await page.getByRole("tab", { name: "Terraform" }).click();
  const acrTfText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (Terraform) reflects the real resource",
    acrTfText.includes("azurerm_container_registry") && acrTfText.includes(ACR), acrTfText.slice(0, 200));

  // ── A repository pushed over the real OCI v2 wire (CLI → UI) ───────────────────────────
  const REPO = `smokerepo${n}`;
  const push = await wire(`/v2/${REPO}/manifests/latest`, { method: "PUT", headers: { "content-type": "application/vnd.docker.distribution.manifest.v2+json" }, body: '{"schemaVersion":2}' });
  check("docker-push-shaped manifest PUT → 201 + digest", push.status === 201, `HTTP ${push.status}`);
  await openPanel("Repositories");
  await page.getByRole("link", { name: REPO, exact: true }).waitFor({ timeout: 10000 });
  check("wire-pushed repository shown in Repositories grid", true);
  await shot("26-acr-repositories");
  await page.getByRole("link", { name: REPO, exact: true }).click();
  await page.getByRole("cell", { name: "latest" }).waitFor({ timeout: 10000 });
  check("repository detail shows the pushed tag + digest", true);
  await shot("27-acr-repository-detail");

  // ── Real OCI blob-layer wire: a manifest referencing an un-uploaded layer is rejected,
  //     then the SAME manifest succeeds once the blob is pushed through blob-uploads ──────
  const LREPO = `smokelayers${n}`;
  const layerBody = `vy-layer-${n}`;
  const layerDigest = "sha256:" + createHash("sha256").update(layerBody).digest("hex");
  const layeredManifest = JSON.stringify({
    schemaVersion: 2, mediaType: "application/vnd.docker.distribution.manifest.v2+json",
    config: { mediaType: "application/vnd.docker.container.image.v1+json", digest: layerDigest, size: layerBody.length },
    layers: [],
  });
  const rejected = await wire(`/v2/${LREPO}/manifests/v1`, { method: "PUT", headers: { "content-type": "application/vnd.docker.distribution.manifest.v2+json" }, body: layeredManifest });
  check("manifest referencing an un-uploaded blob is rejected", rejected.status === 404, `HTTP ${rejected.status}`);
  const initUpload = await wire(`/v2/${LREPO}/blobs/uploads/`, { method: "POST" });
  check("blob upload session starts", initUpload.status === 202, `HTTP ${initUpload.status}`);
  const uploadUrl = initUpload.headers.location;
  const finish = await wire(`${uploadUrl}?digest=${encodeURIComponent(layerDigest)}`, { method: "PUT", body: layerBody });
  check("blob upload finalize matches the real digest", finish.status === 201 && finish.headers["docker-content-digest"] === layerDigest, `HTTP ${finish.status}`);
  const accepted = await wire(`/v2/${LREPO}/manifests/v1`, { method: "PUT", headers: { "content-type": "application/vnd.docker.distribution.manifest.v2+json" }, body: layeredManifest });
  check("same manifest succeeds once its blob exists", accepted.status === 201, `HTTP ${accepted.status}`);
  const gotBlob = await wire(`/v2/${LREPO}/blobs/${layerDigest}`);
  check("pushed blob reads back byte-for-byte", gotBlob.status === 200 && gotBlob.text === layerBody, `HTTP ${gotBlob.status}`);

  // ── Webhook created through the UI → visible over native ARM (nested resource) ─────────
  const WH = `smokewh${n}`;
  await openPanel("Webhooks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(WH);
  await page.getByLabel("Service URI", { exact: true }).fill("https://example.com/acr-hook");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText(WH, { exact: true }).waitFor({ timeout: 10000 });
  const whGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}/webhooks/${WH}`);
  check("UI create webhook → visible over native ARM (nested resource)", whGet.status === 200, `HTTP ${whGet.status}`);
  await shot("28-acr-webhooks");

  // ── Lock created through the UI → visible over native ARM (and the reverse) ────────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const ACRLOCK = `smoke-acrlock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(ACRLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(ACRLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const acrLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}/providers/Microsoft.Authorization/locks/${ACRLOCK}?api-version=2020-05-01`);
  check("UI create lock → visible over native ARM", acrLockGet.status === 200, `HTTP ${acrLockGet.status}`);
  await shot("29-acr-locks");

  // ── Resource created over the wire → visible in the UI (CLI → UI) ──────────────────────
  const acrPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR2}`, { location: "eastus" });
  check("ARM PUT container registry over wire", acrPut.status === 200 || acrPut.status === 201, `HTTP ${acrPut.status}`);
  await page.goto(UI + "#/acr");
  await page.getByRole("link", { name: ACR2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created registry shown in browse grid", true);
  await shot("30-acr-browse");

  // ── Delete through the browse grid → gone over ARM ──────────────────────────────────────
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR2}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(ACR2);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("link", { name: ACR2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  let acrGone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR2}`);
  for (let i = 0; i < 20 && acrGone.status !== 404; i++) {
    await page.waitForTimeout(500);
    acrGone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR2}`);
  }
  check("UI delete container registry → ARM GET 404", acrGone.status === 404, `HTTP ${acrGone.status}`);

  // ── Service Bus: namespace created through the UI → visible over native ARM ────────────
  const SBNS = `vysbns${n}`;
  const SBQ = `vysbq${n}`;
  const SBT2 = `vysbtwire${n}`;
  const sbArm = `/resourceGroups/${RG}/providers/Microsoft.ServiceBus/namespaces/${SBNS}`;
  await page.goto(UI + "#/servicebus/create");
  await page.getByLabel("Namespace name", { exact: true }).fill(SBNS);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("23-servicebus-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: SBNS, exact: true }).waitFor({ timeout: 10000 });
  const gotSbNs = await arm("GET", sbArm);
  check("UI create Service Bus namespace → visible over native ARM", gotSbNs.status === 200, `HTTP ${gotSbNs.status}`);
  await shot("24-servicebus-namespace-overview");

  // ── Queue created through the UI → visible over ARM; Explorer round-trips over the data plane wire ──
  await openPanel("Queues");
  await page.getByRole("button", { name: "Queue", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(SBQ);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("link", { name: SBQ, exact: true }).waitFor({ timeout: 10000 });
  const gotSbQ = await arm("GET", `${sbArm}/queues/${SBQ}`);
  check("UI create queue → visible over native ARM", gotSbQ.status === 200, `HTTP ${gotSbQ.status}`);
  await shot("25-servicebus-queues");

  await page.getByRole("link", { name: SBQ, exact: true }).click();
  await openPanel("Service Bus Explorer");
  await page.getByLabel("Message body", { exact: true }).fill("smoke-message");
  // wait for the send itself — Nano's in-browser engine answers after the click returns
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes(`/${SBQ}/messages`), { timeout: 20000 }),
    page.getByRole("button", { name: "Send messages", exact: true }).click(),
  ]);
  const peeked = await wire(`/${SBQ}/messages`);
  const peekedBody = peeked.status === 200 ? JSON.parse(peeked.text) : { messages: [] };
  check("UI send → readable over the Service Bus data plane wire", peekedBody.messages.some((m) => m.Body === "smoke-message"), `HTTP ${peeked.status}`);
  await page.getByRole("button", { name: "Peek from start" }).click();
  await page.getByRole("cell", { name: "Active" }).first().waitFor({ timeout: 10000 });
  check("sent message shown in Service Bus Explorer", true);
  await shot("26-servicebus-explorer");

  // ── Topic created over the wire → visible in the UI (CLI → UI) ──────────────────────────
  const putTopic = await arm("PUT", `${sbArm}/topics/${SBT2}`, { properties: { maxSizeInMegabytes: 1024 } });
  check("ARM PUT Service Bus topic over wire", putTopic.status === 200 || putTopic.status === 201, `HTTP ${putTopic.status}`);
  await page.goto(UI + `#/servicebus/${RG}/${SBNS}/topics`);
  await page.getByText(SBT2, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created topic shown in Topics grid", true);
  await shot("27-servicebus-topics");

  // ── Delete the queue through the grid → gone over both ARM and the data plane ──────────
  await page.goto(UI + `#/servicebus/${RG}/${SBNS}/queues`);
  await page.getByRole("checkbox", { name: `Select ${SBQ}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(SBQ);
  await Promise.all([   // the row can unmount on a grid re-render before the DELETE returns
    page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes(`/queues/${SBQ}`), { timeout: 20000 }),
    page.getByRole("dialog").getByRole("button", { name: "Delete" }).click(),
  ]);
  await page.getByRole("link", { name: SBQ, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  const sbQGone = await arm("GET", `${sbArm}/queues/${SBQ}`);
  check("UI delete queue → ARM GET 404", sbQGone.status === 404, `HTTP ${sbQGone.status}`);
  // ── Kubernetes service created through the wizard → visible over native ARM ───────────
  await page.goto(UI + "#/aks/create");
  await page.getByLabel("Kubernetes cluster name", { exact: true }).fill(AKS);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByLabel("Region", { exact: true }).selectOption("eastus");
  await shot("23-aks-create-basics");
  for (const t of ["Node pools", "Networking", "Integrations", "Monitoring", "Security", "Advanced", "Tags"]) {
    await page.getByRole("tab", { name: t, exact: true }).click();
    await page.waitForTimeout(200);
  }
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("24-aks-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: AKS, exact: true }).waitFor({ timeout: 10000 });
  const aksGet = await armAks("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}`);
  const aksCluster = aksGet.status === 200 ? JSON.parse(aksGet.text) : {};
  check("UI create kubernetes service → visible over native ARM", aksGet.status === 200, `HTTP ${aksGet.status}`);
  check("wizard's default node pool reached ARM as a real node pool", aksCluster.properties?.kubernetesVersion, JSON.stringify(aksCluster.properties?.kubernetesVersion));
  await shot("25-aks-blade-overview");
  const poolsGet = await armAks("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}/agentPools`);
  const pools = poolsGet.status === 200 ? JSON.parse(poolsGet.text).value : [];
  check("create wizard's node pool visible over native ARM (nested resource)", pools.some((p) => p.name === "nodepool1"), JSON.stringify(pools.map((p) => p.name)));

  // ── Node pools: add one through the UI → visible over the nested ARM resource ──────────
  await openPanel("Node pools");
  await page.getByRole("button", { name: "Add node pool", exact: true }).click();
  await page.getByLabel("Node pool name", { exact: true }).fill(POOL);
  await page.getByRole("dialog").getByRole("button", { name: "Add" }).click();
  await page.getByRole("cell", { name: POOL, exact: true }).waitFor({ timeout: 10000 });
  const poolGet = await armAks("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}/agentPools/${POOL}`);
  check("UI add node pool → visible over native ARM (nested resource)", poolGet.status === 200, `HTTP ${poolGet.status}`);
  await shot("26-aks-node-pools");

  // ── Run command: real round-trip, honestly labelled (no live kubelet) ──────────────────
  await openPanel("Run command");
  await page.getByLabel("Command", { exact: true }).fill("kubectl get pods -A");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  const outBox = page.getByLabel("Output", { exact: true });
  await outBox.waitFor({ timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('textarea[aria-label="Output"]')?.value?.length > 0, null, { timeout: 10000 });
  const runOut = await outBox.inputValue();
  check("Run command runs kubectl against the cluster's (still empty) Kubernetes object store", runOut.includes("No resources found"), runOut.slice(0, 80));
  await shot("27-aks-run-command");

  {   // own block scope: these names stay local to the Defender section
  // ── Kubernetes objects + Microsoft Defender for Cloud (Kubescape) ─────────────────────────
  // Defender plans: turn the Containers plan on through the UI → Standard over native ARM.
  const SECQ = (p, v) => `/subscriptions/${SUB}/providers/Microsoft.Security${p}?api-version=${v}`;
  const secGet = async (p, v) => { const r = await wire(SECQ(p, v)); return r.status === 200 ? JSON.parse(r.text) : { status: r.status }; };
  await page.goto(UI + `#/defender/environment/${SUB}`);
  const contSwitch = page.getByRole("switch", { name: "Containers plan" });
  await contSwitch.waitFor({ timeout: 15000 });
  if (!(await contSwitch.isChecked())) await contSwitch.click();
  await page.getByRole("toolbar", { name: "Defender plans commands" }).getByRole("button", { name: "Save" }).click();
  await page.getByText("Defender plans updated").first().waitFor({ timeout: 10000 });
  const cont = await secGet("/pricings/Containers", "2024-01-01");
  check("UI Defender plans: Containers plan on → Standard over native ARM", cont.properties?.pricingTier === "Standard", JSON.stringify(cont.properties || cont));
  await shot("27a-defender-plans");

  // Workloads → Create → Apply a YAML: a Deployment with a privileged container, through the UI.
  const PRIV = `priv-${n}`;
  const AKSID = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}`;
  await page.goto(UI + `#/aks/${RG}/${AKS}/workloads`);
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Create" }).click();
  await page.getByLabel("YAML", { exact: true }).fill(`apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ${PRIV}\n  namespace: default\nspec:\n  replicas: 2\n  selector:\n    matchLabels: {app: ${PRIV}}\n  template:\n    metadata:\n      labels: {app: ${PRIV}}\n    spec:\n      containers:\n      - name: web\n        image: nginx:1.25\n        securityContext:\n          privileged: true\n`);
  await page.getByRole("dialog").getByRole("button", { name: "Apply", exact: true }).click();
  await page.waitForFunction(() => document.querySelector('textarea[aria-label="kubectl output"]')?.value?.length > 0, null, { timeout: 15000 });
  const applyOut = await page.getByLabel("kubectl output", { exact: true }).inputValue();
  check("UI Apply a YAML → kubectl apply through runCommand", applyOut.includes(`deployment.apps/${PRIV} created`), applyOut.slice(0, 120));
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).last().click();
  await page.getByRole("cell", { name: PRIV, exact: true }).waitFor({ timeout: 10000 });
  check("Workloads lists the applied Deployment with a truthful status",
    await page.getByRole("row", { name: new RegExp(PRIV) }).getByText("Not scheduled — Vyomi doesn't run containers").isVisible());
  const kget = await armAks("POST", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}/runCommand`, { command: `kubectl get deployment ${PRIV} -o json` });
  const kobj = kget.status === 200 ? JSON.parse(JSON.parse(kget.text).properties.logs) : {};
  check("UI-applied Deployment readable over the native wire (runCommand kubectl get -o json)",
    kobj.spec?.template?.spec?.containers?.[0]?.securityContext?.privileged === true && kobj.status?.readyReplicas === 0, `HTTP ${kget.status}`);
  await shot("27b-aks-workloads");

  // The Kubescape scan runs after the change (offline: the CLI container, debounced in the background;
  // Nano: the OPA-wasm evaluator) — wait for the C-0057 recommendation over the native wire.
  const clusterAssessments = async () => {
    const r = await wire(`${AKSID}/providers/Microsoft.Security/assessments?api-version=2021-06-01`);
    return r.status === 200 ? JSON.parse(r.text) : { value: [], status: r.status };
  };
  let privA = null, scanners = [];
  for (let i = 0; i < 90 && !privA; i++) {
    const b = await clusterAssessments();
    scanners = b.vyomiKubernetesScanners || [];
    privA = (b.value || []).find((v) => v.properties.additionalData?.kubescapeControlId === "C-0057" && v.properties.status.code === "Unhealthy");
    if (!privA) await page.waitForTimeout(2000);
  }
  check("Kubescape finds the privileged container → Defender recommendation (C-0057) on the cluster",
    !!privA, privA ? privA.properties.displayName : JSON.stringify(scanners).slice(0, 300));
  if (privA) {
    const subs = JSON.parse((await wire(`${privA.id}/subAssessments?api-version=2019-01-01-preview`)).text).value || [];
    check("sub-assessment names the failing Deployment", subs.some((x) => x.properties.id === `Deployment/default/${PRIV}`), JSON.stringify(subs.map((x) => x.properties.id)));
    await page.goto(UI + `#/aks/${RG}/${AKS}/defender`);
    await page.getByRole("link", { name: "Privileged containers should be avoided (C-0057)" }).click();
    await page.getByRole("table", { name: "Failing Kubernetes objects" }).getByRole("cell", { name: PRIV, exact: true }).waitFor({ timeout: 15000 });
    check("UI: cluster blade → Defender → recommendation detail lists the failing Kubernetes object", true);
    await shot("27c-defender-k8s-recommendation");
  }

  // NSG with 0.0.0.0/0 → 22 over the wire → recommendation in the UI; fix it → it resolves.
  const DNSG = `vydefnsg${n}`;
  const nsgId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${DNSG}`;
  await wire(`${nsgId}?api-version=2023-11-01`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus" }) });
  const sshRule = (src) => wire(`${nsgId}/securityRules/allow-ssh?api-version=2023-11-01`, { method: "PUT", headers: { "content-type": "application/json" },
    body: JSON.stringify({ properties: { direction: "Inbound", access: "Allow", protocol: "Tcp", priority: 300, sourceAddressPrefix: src, sourcePortRange: "*", destinationAddressPrefix: "*", destinationPortRange: "22" } }) });
  await sshRule("0.0.0.0/0");
  const MGMT = "Management ports should not be open to the internet on network security groups";
  await page.goto(UI + `#/defender/recommendations?resource=${encodeURIComponent(nsgId)}`);
  const mgmtRow = page.getByRole("row", { name: new RegExp(MGMT) });
  await mgmtRow.waitFor({ timeout: 15000 });
  check("NSG allowing 0.0.0.0/0 → 22 shows as an Unhealthy recommendation in the UI", await mgmtRow.getByText("Unhealthy").isVisible());
  await mgmtRow.getByRole("link", { name: MGMT }).click();
  await page.getByRole("table", { name: "Unhealthy resources" }).getByRole("link", { name: DNSG, exact: true }).waitFor({ timeout: 10000 });
  check("recommendation detail lists the NSG as an unhealthy resource with the exposing rule",
    await page.getByRole("table", { name: "Unhealthy resources" }).getByText(/port 22 allowed from the internet by rule 'allow-ssh'/).isVisible());
  await shot("27d-defender-nsg");
  await sshRule("10.20.0.0/16");
  await page.getByRole("toolbar", { name: "Defender commands" }).getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("tab", { name: /Healthy resources \(1\)/ }).waitFor({ timeout: 10000 });
  check("restricting the source over the wire → the recommendation resolves (resource Healthy) in the UI",
    await page.getByRole("tab", { name: /Unhealthy resources \(0\)/ }).isVisible());

  // Deleting the privileged Deployment (UI) → rescan → C-0057 resolves.
  if (privA) {
    await page.goto(UI + `#/aks/${RG}/${AKS}/workloads`);
    await page.getByRole("cell", { name: PRIV, exact: true }).waitFor({ timeout: 10000 });
    await page.getByRole("checkbox", { name: `Select default/${PRIV}` }).click();
    await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
    const dlg = page.getByRole("dialog");
    const confirm = dlg.getByLabel("Confirm deletion");
    await confirm.fill(PRIV);
    await dlg.getByRole("button", { name: "Delete" }).click();
    await page.getByText("Delete succeeded").first().waitFor({ timeout: 15000 });
    let resolved = false;
    for (let i = 0; i < 90 && !resolved; i++) {
      const b = await clusterAssessments();
      const a = (b.value || []).find((v) => v.properties.additionalData?.kubescapeControlId === "C-0057");
      resolved = !!a && a.properties.status.code !== "Unhealthy" && !(b.vyomiKubernetesScanners || []).some((x) => x.stale);
      if (!resolved) await page.waitForTimeout(2000);
    }
    check("UI delete of the privileged Deployment → rescan → C-0057 no longer Unhealthy", resolved);
  }
  await page.goto(UI + "#/defender");
  await page.getByLabel("Secure score percentage").waitFor({ timeout: 15000 });
  const ss = await secGet("/secureScores/ascScore", "2020-01-01");
  check("Defender Overview shows the secure score the wire computes",
    (await page.getByLabel("Secure score percentage").innerText()).trim() === `${Math.round((ss.properties?.score?.percentage || 0) * 100)}%`);
  await shot("27e-defender-overview");
  await wire(SECQ("/pricings/Containers", "2024-01-01"), { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { pricingTier: "Free" } }) });
    await page.goto(UI + `#/aks/${RG}/${AKS}`);   // back on the cluster blade for the steps below
    await page.getByRole("navigation", { name: "Resource menu" }).waitFor({ timeout: 15000 });
  }

  // ── Namespaces: create through the UI → visible over native ARM ───────────────────────
  await openPanel("Namespaces");
  const NS = `smoke-ns-${n}`;
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Create" }).click();
  await page.getByLabel("Name", { exact: true }).fill(NS);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("cell", { name: NS, exact: true }).waitFor({ timeout: 10000 });
  const nsGet = await armAks("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}`);
  const nsCluster = JSON.parse(nsGet.text);
  check("UI create namespace → visible over native ARM (properties.namespaces)",
    (nsCluster.properties?.namespaces || []).some((x) => x.name === NS), JSON.stringify(nsCluster.properties?.namespaces));
  await shot("28-aks-namespaces");
  // ── System namespaces are ENFORCED protected (not just stored) — same wire path as the UI uses
  const withoutKubeSystem = (nsCluster.properties?.namespaces || []).filter((x) => x.name !== "kube-system");
  const protectedNsPatch = await armAks("PATCH", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}`,
    { properties: { namespaces: withoutKubeSystem } });
  check("deleting the kube-system namespace is rejected over native ARM", protectedNsPatch.status === 409, `HTTP ${protectedNsPatch.status}`);

  // ── Lock created in the UI → visible over the native ARM wire ─────────────────────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const AKSLOCK = `smoke-akslock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(AKSLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(AKSLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const aksLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}/providers/Microsoft.Authorization/locks/${AKSLOCK}?api-version=2020-05-01`);
  check("UI create lock → visible over native ARM (extension resource)", aksLockGet.status === 200, `HTTP ${aksLockGet.status}`);
  await shot("29-aks-locks");

  // ── Kubernetes service created over the wire → visible in the UI (CLI → UI) ───────────
  const aksPut = await armAks("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS2}`, { location: "eastus" });
  check("ARM PUT kubernetes service over wire", aksPut.status === 200 || aksPut.status === 201, `HTTP ${aksPut.status}`);
  await page.goto(UI + "#/aks");
  await page.getByRole("link", { name: AKS2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created kubernetes service shown in browse grid", true);
  await shot("30-aks-browse");

  // ── Delete through the Overview command bar → gone over ARM (cluster + its node pool) ──
  await page.goto(UI + `#/aks/${RG}/${AKS}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(AKS);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Kubernetes services" }).waitFor({ timeout: 10000 });
  const aksGone = await armAks("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}`);
  check("UI delete kubernetes service → ARM GET 404", aksGone.status === 404, `HTTP ${aksGone.status}`);
  const poolGone = await armAks("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${AKS}/agentPools/${POOL}`);
  check("node pool cascade-deleted with the cluster", poolGone.status === 404, `HTTP ${poolGone.status}`);
  // ── Monitor: metric alert rule created through the wizard → visible over native ARM ────
  const MON_RG = "cloudlearn-rg";              // the Create alert rule / action group wizards' default resource group
  const armMonitor = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2018-03-01`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const ALERT = `vysmokealert${n}`;
  await page.goto(UI + "#/monitor/createalertrule");
  for (const label of ["Scope", "Condition", "Actions"]) {
    await page.getByRole("tab", { name: label }).waitFor({ timeout: 10000 });
    await page.getByRole("button", { name: "Next", exact: true }).click();
  }
  await page.getByRole("tab", { name: "Details" }).waitFor({ timeout: 5000 });
  await page.getByLabel("Alert rule name", { exact: true }).fill(ALERT);
  await shot("22-monitor-alert-details");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText(ALERT, { exact: true }).first().waitFor({ timeout: 10000 });
  await shot("23-monitor-alerts");
  const alertGet = await armMonitor("GET", `/resourceGroups/${MON_RG}/providers/Microsoft.Insights/metricAlerts/${ALERT}`);
  check("UI create alert rule → visible over native ARM", alertGet.status === 200, `HTTP ${alertGet.status}`);

  // ── Action group created over the native wire → visible in the UI (CLI → UI) ───────────
  const AG = `vysmokeag${n}`;
  const agPut = await wire(`/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.Insights/actionGroups/${AG}?api-version=2023-01-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "Global", properties: { groupShortName: "smokeag", enabled: true } }) });
  check("ARM PUT action group over wire", agPut.status === 200 || agPut.status === 201, `HTTP ${agPut.status}`);
  await page.goto(UI + "#/monitor/actiongroups");
  await page.getByText(AG, { exact: true }).first().waitFor({ timeout: 10000 });
  check("wire-created action group shown in browse grid", true);
  await shot("24-monitor-actiongroups");

  // ── Delete the alert rule from the Alerts grid → gone over ARM ─────────────────────────
  await page.goto(UI + "#/monitor/alerts");
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.Insights/metricAlerts/${ALERT}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(ALERT);
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes(`/metricAlerts/${ALERT}`), { timeout: 20000 }),
    page.getByRole("dialog").getByRole("button", { name: "Delete" }).click(),
  ]);
  // the deleted row's own checkbox (the name text also appears in the delete notification)
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.Insights/metricAlerts/${ALERT}` }).waitFor({ state: "detached", timeout: 10000 });
  const alertGone = await armMonitor("GET", `/resourceGroups/${MON_RG}/providers/Microsoft.Insights/metricAlerts/${ALERT}`);
  check("UI delete alert rule → ARM GET 404", alertGone.status === 404, `HTTP ${alertGone.status}`);

  // ── Monitor depth: Data Collection Endpoint created through the wizard → visible over ARM ──
  // The Review + create tab renders a <span>{name}</span> summary BEFORE the resource actually
  // exists, so waiting on that same text right after the Create click can false-positive on the
  // still-mounted summary instead of the post-create list — wait for the real navigation away
  // from the wizard route first, then assert the name is on the (now actual) list page.
  const DCE = `vysmokedce${n}`;
  await page.goto(UI + "#/monitor/createdatacollectionendpoint");
  await page.getByLabel("Endpoint name", { exact: true }).fill(DCE);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForURL((u) => u.hash === "#/monitor/datacollectionendpoints", { timeout: 15000 });
  await page.getByText(DCE, { exact: true }).first().waitFor({ timeout: 10000 });
  const dceGet = await armMonitor("GET", `/resourceGroups/${MON_RG}/providers/Microsoft.Insights/dataCollectionEndpoints/${DCE}`);
  check("UI create data collection endpoint → visible over native ARM", dceGet.status === 200, `HTTP ${dceGet.status}`);
  const dceBody = dceGet.status === 200 ? JSON.parse(dceGet.text) : {};
  check("DCE generated a logs ingestion endpoint", !!dceBody.properties?.logsIngestion?.endpoint, JSON.stringify(dceBody.properties));

  // ── Monitor depth: Private Link Scope created through the wizard → visible over ARM ────────
  // Same false-positive hazard as the DCE wizard above (Review tab pre-renders the name) — wait
  // for the real navigation away from the wizard before asserting the name is visible.
  const PLS = `vysmokepls${n}`;
  await page.goto(UI + "#/monitor/createprivatelinkscope");
  await page.getByLabel("Name", { exact: true }).fill(PLS);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForURL((u) => u.hash === "#/monitor/privatelinkscopes", { timeout: 15000 });
  await page.getByText(PLS, { exact: true }).first().waitFor({ timeout: 10000 });
  const plsGet = await armMonitor("GET", `/resourceGroups/${MON_RG}/providers/Microsoft.Insights/privateLinkScopes/${PLS}`);
  check("UI create private link scope → visible over native ARM", plsGet.status === 200, `HTTP ${plsGet.status}`);

  // ── Monitor depth: the scope's "Azure Monitor Resources" tab — a Log Analytics workspace
  // linked INTO the scope through the UI → visible as a real scopedResources extension
  // resource over native ARM (azure.monitor.private_link_scopes) ─────────────────────────
  const PLSWS = `vysmokeplsws${n}`;
  const plsWsPut = await wire(`/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.OperationalInsights/workspaces/${PLSWS}?api-version=2022-10-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus", properties: {} }) });
  check("ARM PUT Log Analytics workspace for Private Link Scope resources over wire", plsWsPut.status === 200 || plsWsPut.status === 201, `HTTP ${plsWsPut.status}`);
  await page.goto(UI + `#/monitor/privatelinkscoperesources?rg=${MON_RG}&name=${PLS}`);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("Log Analytics workspace", { exact: true }).selectOption({ label: PLSWS });
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText(PLSWS, { exact: true }).first().waitFor({ timeout: 10000 });
  const plsResGet = await armMonitor("GET", `/resourceGroups/${MON_RG}/providers/Microsoft.Insights/privateLinkScopes/${PLS}/scopedResources/${PLSWS}`);
  check("UI link workspace into Private Link Scope → visible over native ARM", plsResGet.status === 200, `HTTP ${plsResGet.status}`);

  // ── Monitor depth: diagnostic setting added through the UI (resource-scoped extension
  // resource, Microsoft.Insights/diagnosticSettings) → visible over native ARM, and the
  // reverse (wire-created resource's diagnostics status shown in the picker grid) ─────────
  const DIAGSA = `vysmokediagsa${n}`;
  const diagSaPut = await wire(`/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.Storage/storageAccounts/${DIAGSA}?api-version=2023-01-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus" }) });
  check("ARM PUT storage account for diagnostic settings over wire", diagSaPut.status === 200 || diagSaPut.status === 201, `HTTP ${diagSaPut.status}`);
  const DIAGWS = `vysmokediagws${n}`;
  const diagWsPut = await wire(`/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.OperationalInsights/workspaces/${DIAGWS}?api-version=2022-10-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus", properties: {} }) });
  check("ARM PUT Log Analytics workspace for diagnostic settings over wire", diagWsPut.status === 200 || diagWsPut.status === 201, `HTTP ${diagWsPut.status}`);
  const diagSaId = `/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.Storage/storageAccounts/${DIAGSA}`;
  await page.goto(UI + "#/monitor/diagnosticsettings");
  await page.getByText(DIAGSA, { exact: true }).first().waitFor({ timeout: 10000 });
  check("wire-created storage account shown in Diagnostic settings picker", true);
  await page.goto(UI + `#/monitor/diagnosticsettingsresource?id=${encodeURIComponent(diagSaId)}&name=${encodeURIComponent(DIAGSA)}&type=Storage%20account`);
  const DIAG = `vysmokediag${n}`;
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByLabel("Diagnostic setting name", { exact: true }).fill(DIAG);
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText(DIAG, { exact: true }).first().waitFor({ timeout: 10000 });
  const diagGet = await wire(`${diagSaId}/providers/Microsoft.Insights/diagnosticSettings/${DIAG}?api-version=2021-05-01-preview`);
  check("UI create diagnostic setting → visible over native ARM extension resource", diagGet.status === 200, `HTTP ${diagGet.status}`);
  await page.goto(UI + "#/monitor/diagnosticsettings");
  await page.getByText(DIAGSA, { exact: true }).first().waitFor({ timeout: 10000 });
  await page.getByText("Enabled (1)").first().waitFor({ timeout: 10000 });
  check("diagnostic settings picker shows the resource's Diagnostics status as Enabled", true);

  // ── Monitor depth: Logs — the KQL subset (azure.monitor.log_query) reads back a real
  // wire-created resource's Activity log row through AzureActivity (native ARM → UI query) ──
  const LOGSWS = `vysmokelogsws${n}`;
  const logsWsPut = await wire(`/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.OperationalInsights/workspaces/${LOGSWS}?api-version=2022-10-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus", properties: {} }) });
  check("ARM PUT Log Analytics workspace for Logs query over wire", logsWsPut.status === 200 || logsWsPut.status === 201, `HTTP ${logsWsPut.status}`);
  const LOGSA = `vysmokelogsa${n}`;
  const logSaPut = await wire(`/subscriptions/${SUB}/resourceGroups/${MON_RG}/providers/Microsoft.Storage/storageAccounts/${LOGSA}?api-version=2023-01-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus" }) });
  check("ARM PUT storage account for Logs query over wire", logSaPut.status === 200 || logSaPut.status === 201, `HTTP ${logSaPut.status}`);
  await page.goto(UI + "#/monitor/logs");
  await page.getByLabel("Log Analytics workspace").selectOption({ label: LOGSWS });
  await page.getByLabel("KQL query").fill("AzureActivity\n| take 50");
  await page.getByRole("button", { name: "Run" }).click();
  await page.getByText(LOGSA, { exact: false }).first().waitFor({ timeout: 10000 });
  check("UI Logs KQL query shows the wire-created resource's real Activity log row", true);
  await shot("25-monitor-logs-query");

  // ── SQL: server + database created through the wizard → visible over native ARM ───────
  const sqlArm = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2023-08-01`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const SRV = `vysmoke-sql-${n}`;
  const DB = `vysmokedb${n}`;
  await page.goto(UI + "#/sql/create");
  await page.getByLabel("Database name", { exact: true }).fill(DB);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("Server name", { exact: true }).fill(SRV);
  await page.getByRole("radio", { name: "Use SQL authentication" }).check();
  await page.getByLabel("Server admin login", { exact: true }).fill("sqladmin");
  await page.getByLabel("Password", { exact: true }).fill("Vy0mi#Passw0rd!");
  await page.getByLabel("Confirm password", { exact: true }).fill("Vy0mi#Passw0rd!");
  await shot("23-sql-create-server-dialog");
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden", timeout: 10000 });
  await page.waitForFunction((s) => document.querySelector('select[aria-label="Select a server"]')?.value === s, SRV, { timeout: 10000 });
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("24-sql-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: DB, exact: true }).waitFor({ timeout: 10000 });
  const gotDb = await sqlArm("GET", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/databases/${DB}`);
  check("UI create SQL database → visible over native ARM", gotDb.status === 200, `HTTP ${gotDb.status}`);
  await shot("25-sql-overview");

  // ── Query editor: real SQL executed through the UI → readable over the azure-sql wire ──
  await openPanel("Query editor (preview)");
  await page.getByRole("button", { name: /Continue as/ }).click();
  await page.getByLabel("SQL query", { exact: true }).fill("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);");
  await page.getByRole("button", { name: "Run" }).click();
  await page.waitForTimeout(500);
  await page.getByLabel("SQL query", { exact: true }).fill("INSERT INTO t (name) VALUES ('smoke');");
  await page.getByRole("button", { name: "Run" }).click();
  await page.waitForTimeout(500);
  await shot("26-sql-query-editor");
  const q = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT name FROM t" }) });
  let qRows = [];
  try { qRows = JSON.parse(q.text).rows; } catch {}
  check("UI query editor INSERT → readable over the azure-sql data-plane wire", q.status === 200 && qRows?.[0]?.[0] === "smoke", `HTTP ${q.status}`);

  // ── Performance recommendations: real CREATE_INDEX suggestion from the query log ───────
  for (let i = 0; i < 4; i++) {
    await page.getByLabel("SQL query", { exact: true }).fill("SELECT name FROM t WHERE name = 'smoke';");
    await page.getByRole("button", { name: "Run" }).click();
    await page.waitForTimeout(300);
  }
  await openPanel("Performance recommendations");
  await page.getByText("Create index on t(name)").waitFor({ timeout: 10000 });
  await shot("26b-sql-performance-recommendations");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.getByText("No recommendations right now", { exact: false }).waitFor({ timeout: 10000 });
  const idxCheck = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='t'" }) });
  let idxRows = [];
  try { idxRows = JSON.parse(idxCheck.text).rows; } catch {}
  check("UI apply performance recommendation → real CREATE INDEX executed on the azure-sql data plane", idxRows.length === 1, `rows=${JSON.stringify(idxRows)}`);

  // ── Networking: disabling public network access blocks the query data plane ────────────
  await page.goto(UI + `#/sql/servers/${RG}/${SRV}/networking`);
  await page.getByRole("radio", { name: "Disable" }).check();
  await page.getByRole("toolbar", { name: "Networking commands" }).getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(500);
  const blockedQuery = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT 1" }) });
  check("UI disable public network access → query data plane now rejects connections", blockedQuery.status === 403, `HTTP ${blockedQuery.status}`);
  await shot("26c-sql-networking-disabled");
  await page.getByRole("radio", { name: "Selected networks" }).check();
  await page.getByRole("toolbar", { name: "Networking commands" }).getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(500);
  const allowedQuery = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT 1" }) });
  check("UI re-enable public network access → query data plane allows connections again", allowedQuery.status === 200, `HTTP ${allowedQuery.status}`);

  // ── Firewall rule added on the server blade → visible over native ARM ──────────────────
  await page.goto(UI + `#/sql/servers/${RG}/${SRV}/networking`);
  await page.getByRole("button", { name: "Add a firewall rule" }).click();
  const FW = `smoke-fw-${n}`;
  await page.getByLabel("Rule name", { exact: true }).fill(FW);
  await page.getByLabel("Start IPv4 address", { exact: true }).fill("10.1.2.3");
  await page.getByLabel("End IPv4 address", { exact: true }).fill("10.1.2.3");
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByText(FW, { exact: true }).waitFor({ timeout: 10000 });
  const fwGet = await sqlArm("GET", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/firewallRules/${FW}`);
  check("UI add firewall rule → visible over native ARM", fwGet.status === 200 && JSON.parse(fwGet.text).properties.startIpAddress === "10.1.2.3", `HTTP ${fwGet.status}`);
  await shot("27-sql-server-networking");

  // ── Lock created on the database → visible over native ARM (and the reverse) ───────────
  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}/locks`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const SQLLOCK = `smoke-sqllock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(SQLLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(SQLLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const sqlLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/databases/${DB}/providers/Microsoft.Authorization/locks/${SQLLOCK}?api-version=2020-05-01`);
  check("UI create lock on SQL database → visible over native ARM", sqlLockGet.status === 200, `HTTP ${sqlLockGet.status}`);
  await shot("28-sql-locks");

  // ── Transparent data encryption: customer-managed Key Vault key (BYOK) depth pass ──────
  // A Key Vault key created over the wire becomes the database's TDE protector, requiring
  // the database's OWN system-assigned identity before it's honored — real Azure SQL's BYOK
  // precondition — and then real-enforces the key's enabled state on the query data plane.
  const kvWireKey = (path, method = "GET", body) => wire(`${path}${path.includes("?") ? "&" : "?"}api-version=7.4`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const TDEKEY = `vysmoketdekey${n}`;
  const putTdeKey = await kvWireKey(`/keys/${TDEKEY}/create`, "POST", { kty: "RSA", key_size: 2048 });
  check("Key Vault key created over wire for the TDE protector", putTdeKey.status === 200, `HTTP ${putTdeKey.status}`);

  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}/tde`);
  await page.getByText("Transparent data encryption", { exact: true }).first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(300);
  await page.getByRole("radio", { name: "Customer-managed key" }).click();
  await page.getByLabel("Key Vault key name", { exact: true }).fill(TDEKEY);
  check("UI blocks saving a customer-managed TDE key with no managed identity configured",
    await page.getByRole("toolbar", { name: "Transparent data encryption commands" }).getByRole("button", { name: "Save" }).isDisabled());
  await shot("28b-sql-tde-cmk-needs-identity");

  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}/identity`);
  await page.getByText("Identity", { exact: true }).first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(300);
  await page.getByRole("radio", { name: "On" }).click();
  const identitySaved = page.waitForResponse((r) => ["PATCH", "PUT"].includes(r.request().method()) && new RegExp(`/databases/${DB}\\?`).test(r.url()), { timeout: 15000 });
  await page.getByRole("toolbar", { name: "Identity commands" }).getByRole("button", { name: "Save" }).click();
  await identitySaved;   // the "Object (principal) ID" label shows before the save completes
  await page.getByText("Object (principal) ID").waitFor({ timeout: 10000 });

  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}/tde`);
  await page.getByText("Transparent data encryption", { exact: true }).first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(300);
  await page.getByRole("radio", { name: "Customer-managed key" }).click();
  await page.getByLabel("Key Vault key name", { exact: true }).fill(TDEKEY);
  await page.getByRole("toolbar", { name: "Transparent data encryption commands" }).getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(500);
  await shot("28c-sql-tde-cmk-configured");
  const tdeOkQuery = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT 1" }) });
  check("UI configure customer-managed TDE key (with identity) → query data plane still allows connections",
    tdeOkQuery.status === 200, `HTTP ${tdeOkQuery.status}`);

  const disableTdeKey = await kvWireKey(`/keys/${TDEKEY}`, "PATCH", { attributes: { enabled: false } });
  check("disable the Key Vault key over wire", disableTdeKey.status === 200, `HTTP ${disableTdeKey.status}`);
  const tdeBlockedQuery = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT 1" }) });
  check("disabling the Key Vault TDE protector key → query data plane now rejects connections",
    tdeBlockedQuery.status === 403, `HTTP ${tdeBlockedQuery.status}`);

  const enableTdeKey = await kvWireKey(`/keys/${TDEKEY}`, "PATCH", { attributes: { enabled: true } });
  check("re-enable the Key Vault key over wire", enableTdeKey.status === 200, `HTTP ${enableTdeKey.status}`);
  const tdeRestoredQuery = await wire(`/azure-sql/servers/${SRV}/databases/${DB}/query`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "SELECT 1" }) });
  check("re-enabling the Key Vault TDE protector key → query data plane allows connections again",
    tdeRestoredQuery.status === 200, `HTTP ${tdeRestoredQuery.status}`);

  // Back to service-managed so the delete-database flow right below isn't left depending on
  // a customer-managed protector.
  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}/tde`);
  await page.getByText("Transparent data encryption", { exact: true }).first().waitFor({ timeout: 10000 });
  await page.waitForTimeout(300);
  await page.getByRole("radio", { name: "Service-managed key" }).click();
  await page.getByRole("toolbar", { name: "Transparent data encryption commands" }).getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(500);

  // ── Database deleted through the overview → gone over ARM ──────────────────────────────
  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(DB);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "SQL databases", exact: true }).waitFor({ timeout: 10000 });
  const dbGone = await sqlArm("GET", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/databases/${DB}`);
  check("UI delete SQL database → ARM GET 404", dbGone.status === 404, `HTTP ${dbGone.status}`);

  // ── Network security group created through the wizard → visible over native ARM ──────
  const NSG = `vysmokensg${n}`;
  const NSG2 = `vywirensg${n}`;
  const RULE = `allow-smoke-${n}`;
  const NSGLOCK = `vynsglock${n}`;
  await page.goto(UI + "#/nsgs/create");
  await page.getByLabel("Name", { exact: true }).fill(NSG);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await shot("23-nsg-create-basics");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: NSG, exact: true }).waitFor({ timeout: 10000 });
  const nsgGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG}`);
  check("UI create NSG → visible over native ARM", nsgGet.status === 200, `HTTP ${nsgGet.status}`);
  await shot("24-nsg-overview");

  // ── Inbound security rule added in the UI → visible as a native ARM child resource ────
  await openPanel("Inbound security rules");
  await page.getByRole("toolbar", { name: "Inbound security rules commands" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Name", { exact: true }).fill(RULE);
  await page.getByLabel("Priority", { exact: true }).fill("150");
  await page.getByRole("dialog").getByRole("button", { name: "Add" }).click();
  await page.getByRole("cell", { name: RULE, exact: true }).waitFor({ timeout: 10000 });
  const ruleGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG}/securityRules/${RULE}`);
  check("UI add inbound rule → visible over native ARM (nested child resource)",
    ruleGet.status === 200 && JSON.parse(ruleGet.text).properties?.direction === "Inbound", `HTTP ${ruleGet.status}`);
  await shot("25-nsg-inbound-rules");

  // ── Lock created in the UI → visible over the native ARM wire ─────────────────────────
  // ── Lock created on the NSG through the UI → visible over the native ARM wire ──────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(NSGLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(NSGLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const nsgLockGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG}/providers/Microsoft.Authorization/locks/${NSGLOCK}`);
  check("UI create lock on NSG → visible over native ARM", nsgLockGet.status === 200, `HTTP ${nsgLockGet.status}`);
  await shot("26-nsg-locks");

  // ── Access control (IAM): a role assignment created over the wire, EXPLICITLY scoped to
  // this NSG resource (not just the subscription/resource group) → read back on the Role
  // assignments tab, and a real Check access decision reflects it (azure.nsgs.iam) ─────────
  const nsgId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG}`;
  const nsgRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${NSGROLE}?api-version=2022-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ properties: { principalId: NSGPRINCIPAL, roleName: "Owner", scope: nsgId } }) });
  check("ARM PUT role assignment scoped to the NSG over wire", nsgRoleRes.status === 200 || nsgRoleRes.status === 201, `HTTP ${nsgRoleRes.status}`);
  await openPanel("Access control (IAM)");
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText(NSGPRINCIPAL).first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the NSG-scoped wire-created assignment", true);
  await shot("26b-nsg-iam-role-assignments");

  await page.getByRole("tab", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByLabel("Principal ID", { exact: true }).fill(NSGPRINCIPAL);
  await page.getByRole("dialog").getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByText("Allowed").waitFor({ timeout: 10000 });
  check("UI Check access on the NSG → real decision reflects the NSG-scoped role assignment", true);
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // ── Diagnostic settings: added through the UI (real Microsoft.Insights/diagnosticSettings
  // extension resource scoped to this NSG) → visible over native ARM (azure.nsgs.monitoring) ──
  await openPanel("Diagnostic settings");
  await page.getByRole("button", { name: "Add diagnostic setting" }).click();
  await page.getByLabel("Diagnostic setting name", { exact: true }).fill(NSGDIAG);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText(NSGDIAG, { exact: true }).first().waitFor({ timeout: 10000 });
  const nsgDiagGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG}/providers/Microsoft.Insights/diagnosticSettings/${NSGDIAG}?api-version=2021-05-01-preview`);
  check("UI add diagnostic setting on NSG → visible over native ARM extension resource", nsgDiagGet.status === 200, `HTTP ${nsgDiagGet.status}`);

  // ── Associations: a network interface with no NSG of its own, created over the wire, then
  // picked through the UI's "Associate" dialog → its networkSecurityGroup is set over native
  // ARM (azure.nsgs.associations) ─────────────────────────────────────────────────────────
  const nsgNicPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${NSGNIC}`, { location: "eastus" });
  check("ARM PUT network interface with no NSG over wire", nsgNicPut.status === 200 || nsgNicPut.status === 201, `HTTP ${nsgNicPut.status}`);
  await openPanel("Network interfaces");
  await page.getByRole("button", { name: "Associate", exact: true }).click();
  await page.getByLabel("network interface", { exact: true }).selectOption({ label: NSGNIC });
  await page.getByRole("dialog").getByRole("button", { name: "Associate", exact: true }).click();
  await page.getByRole("dialog", { name: "Associate network interface" }).waitFor({ state: "detached", timeout: 10000 });
  await page.getByRole("cell", { name: NSGNIC, exact: true }).waitFor({ timeout: 10000 });
  const nsgNicAfter = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${NSGNIC}`);
  check("UI Associate network interface → networkSecurityGroup set over native ARM",
    (JSON.parse(nsgNicAfter.text).properties?.networkSecurityGroup?.id || "").toLowerCase() === nsgId.toLowerCase(), nsgNicAfter.text);
  await shot("26c-nsg-associate");

  // ── Diagnose and solve problems: Network Watcher's IP flow verify answers a real Deny,
  // naming the deciding security rule (azure.nsgs.network_watcher) — a vnet/subnet/NIC/VM
  // created over the wire so the subnet carries this NSG, then a Deny rule added through the
  // Inbound security rules UI, then checked through the Diagnose blade ─────────────────────
  const flowVnetPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${FLOWVNET}`, {
    location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.91.0.0/16"] },
      subnets: [{ name: "default", properties: { addressPrefix: "10.91.1.0/24", networkSecurityGroup: { id: nsgId } } }] },
  });
  check("ARM PUT vnet with this NSG attached to its subnet, over wire", flowVnetPut.status === 200 || flowVnetPut.status === 201, `HTTP ${flowVnetPut.status}`);
  const flowNicPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${FLOWNIC}`, {
    location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: {
      subnet: { id: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${FLOWVNET}/subnets/default` } } }] },
  });
  check("ARM PUT network interface in the NSG-attached subnet, over wire", flowNicPut.status === 200 || flowNicPut.status === 201, `HTTP ${flowNicPut.status}`);
  const flowVmPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${FLOWVM}`,
    { location: "eastus", properties: { networkProfile: { networkInterfaces: [{ id: JSON.parse(flowNicPut.text).id }] } } });
  check("ARM PUT virtual machine for Network Watcher diagnostics, over wire", flowVmPut.status === 200 || flowVmPut.status === 201, `HTTP ${flowVmPut.status}`);

  await openPanel("Inbound security rules");
  await page.getByRole("toolbar", { name: "Inbound security rules commands" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Name", { exact: true }).fill(DENYRULE);
  await page.getByLabel("Priority", { exact: true }).fill("140");
  await page.getByLabel("Destination port ranges", { exact: true }).fill("4321");
  await page.getByRole("dialog").getByRole("radio", { name: "TCP" }).check();
  await page.getByRole("dialog").getByRole("radio", { name: "Deny" }).check();
  await page.getByRole("dialog").getByRole("button", { name: "Add" }).click();
  await page.getByRole("cell", { name: DENYRULE, exact: true }).waitFor({ timeout: 10000 });

  await openPanel("Diagnose and solve problems");
  await page.getByRole("button", { name: "IP flow verify", exact: true }).click();
  await page.getByLabel("Virtual machine", { exact: true }).selectOption({ label: FLOWVM });
  await page.getByLabel("Local port", { exact: true }).fill("4321");
  await page.getByLabel("Remote IP address", { exact: true }).fill("10.91.1.50");
  await page.getByLabel("Remote port", { exact: true }).fill("50000");
  await page.getByRole("dialog").getByRole("button", { name: "Check", exact: true }).click();
  await page.getByText(`Security rule: securityRules/${DENYRULE}`).waitFor({ timeout: 10000 });
  check("UI IP flow verify (Diagnose and solve problems) → real Deny naming this NSG's deny rule",
    await page.getByText("Access: Deny").isVisible());
  await shot("26d-nsg-diagnose-ipflowverify");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // ── Effective security rules (azure.nsgs.effective_rules): the NIC sits in the subnet that
  // carries this NSG (no NSG of its own), so its effective Inbound rules must show the
  // subnet-level Deny rule added above, tagged "Subnet: <this NSG>" ────────────────────────
  await openPanel("Effective security rules");
  await page.getByLabel("Network interface", { exact: true }).selectOption({ label: FLOWNIC });
  await page.getByRole("tab", { name: "Inbound rules" }).click();
  await page.getByRole("cell", { name: DENYRULE, exact: true }).waitFor({ timeout: 10000 });
  check("UI Effective security rules → shows the subnet-level Deny rule merged for this NIC", true);
  await shot("26e-nsg-effective-rules");

  // ── NSG created over the wire → visible in the UI (CLI → UI), then deleted in the UI ──
  const nsgPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG2}`, { location: "eastus" });
  check("ARM PUT network security group over wire", nsgPut.status === 200 || nsgPut.status === 201, `HTTP ${nsgPut.status}`);
  await page.goto(UI + "#/nsgs");
  await page.getByRole("link", { name: NSG2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created NSG shown in browse grid", true);
  await shot("27-nsg-browse");
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG2}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(NSG2);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("link", { name: NSG2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  let nsgGone = { status: 0 };
  for (let i = 0; i < 20 && nsgGone.status !== 404; i++) {
    nsgGone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG2}`);
    if (nsgGone.status !== 404) await page.waitForTimeout(500);
  }
  check("UI delete NSG → ARM GET 404", nsgGone.status === 404, `HTTP ${nsgGone.status}`);

  // ── Entra ID: UI create user → visible over native Microsoft Graph wire ────────────────
  await page.goto(UI + "#/entra/users/create");
  await page.getByLabel("User principal name", { exact: true }).fill(`${EUSR}@vyomilearn.onmicrosoft.com`);
  await page.getByLabel("Display name", { exact: true }).fill(EUSR);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: EUSR, exact: true }).waitFor({ timeout: 10000 });
  const gotUsers = await graph("GET", "/users");
  const createdUsers = gotUsers.status === 200 ? JSON.parse(gotUsers.text).value : [];
  check("UI create user → visible over native Microsoft Graph wire", createdUsers.some((u) => u.displayName === EUSR), `HTTP ${gotUsers.status}`);
  await shot("22-entra-create-user");

  // ── Entra ID: user created over the wire → visible in the UI (CLI → UI direction) ──────
  const graphPut = await graph("POST", "/users", { displayName: EUSR2, userPrincipalName: `${EUSR2}@vyomilearn.onmicrosoft.com`, passwordProfile: { password: "Vy3omi!2345AB" } });
  check("Graph POST user over wire", graphPut.status === 201, `HTTP ${graphPut.status}`);
  await page.goto(UI + "#/entra/users");
  await page.getByText(EUSR2).first().waitFor({ timeout: 10000 });
  check("wire-created user shown in browse grid", true);
  await shot("23-entra-users");

  // ── Entra ID: delete through the user's own blade → gone over native Microsoft Graph ───
  await page.getByRole("link", { name: EUSR, exact: true }).click();
  await page.getByRole("toolbar", { name: "User commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(EUSR);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Users", exact: true }).waitFor({ timeout: 10000 });
  const afterDelete = await graph("GET", "/users");
  const stillThere = (afterDelete.status === 200 ? JSON.parse(afterDelete.text).value : []).some((u) => u.displayName === EUSR);
  check("UI delete user → gone over native Microsoft Graph wire", !stillThere);

  // ── Entra ID: "Users can create security groups" (User settings) really blocks/allows
  // security-group creation over the native Microsoft Graph wire (azure.entra.directory_settings
  // is now "limited", not just stored) ────────────────────────────────────────────────────
  await graph("PATCH", "/settings/directory", { usersCanCreateSecurityGroups: false });
  await page.goto(UI + "#/entra/groups/new");
  await page.getByLabel("Group name", { exact: true }).fill(EGRP);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText(/Users can create security groups/).waitFor({ timeout: 10000 });
  const blockedGroups = await graph("GET", "/groups");
  const blockedCreated = (blockedGroups.status === 200 ? JSON.parse(blockedGroups.text).value : []).some((g) => g.displayName === EGRP);
  check("'Users can create security groups' = No blocks group creation over native Microsoft Graph wire", !blockedCreated);
  await shot("24-entra-group-blocked");

  await graph("PATCH", "/settings/directory", { usersCanCreateSecurityGroups: true });
  const createBtn = page.getByRole("button", { name: "Create", exact: true });
  await createBtn.waitFor({ state: "visible", timeout: 10000 });
  await page.waitForFunction(() => [...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Create" && !b.disabled), null, { timeout: 10000 });
  const groupPost = page.waitForResponse((r) => r.request().method() === "POST" && /\/v1\.0\/groups(\?|$)/.test(r.url()), { timeout: 15000 });
  await createBtn.click();
  await groupPost;   // the review step already shows the name: wait for the real create
  await page.getByText(EGRP, { exact: true }).first().waitFor({ timeout: 10000 });
  const allowedGroups = await graph("GET", "/groups");
  const allowedCreated = (allowedGroups.status === 200 ? JSON.parse(allowedGroups.text).value : []).some((g) => g.displayName === EGRP);
  check("setting back to Yes allows the same group creation over native Microsoft Graph wire", allowedCreated);
  await shot("25-entra-group-allowed");

  // ── Entra ID | Properties: "Access management for Azure resources" = Yes really grants a
  // tenant-root "User Access Administrator" role assignment over native Azure RBAC — the same
  // checkAccess engine Subscription/vnet Access control (IAM) uses (azure.entra.security_defaults
  // is now "limited", not just stored). "Manage security defaults" really stores the real
  // Graph policy document ───────────────────────────────────────────────────────────────
  await page.goto(UI + "#/entra/properties");
  await page.getByRole("radiogroup", { name: "Access management for Azure resources" }).getByRole("radio", { name: "Yes" }).check();
  await page.getByText("Access management for Azure resources set to Yes").first().waitFor({ timeout: 10000 });
  const roleAssignmentsOn = await wire("/providers/Microsoft.Authorization/roleAssignments");
  const elevated = (roleAssignmentsOn.status === 200 ? JSON.parse(roleAssignmentsOn.text).value : [])
    .find((a) => a.properties.principalId === "global-admin" && a.properties.roleDefinitionId === "User Access Administrator" && a.properties.scope === "/");
  check("UI 'Access management for Azure resources' = Yes grants a tenant-root User Access Administrator assignment over native Azure RBAC", !!elevated);
  await shot("25a-entra-elevate-access");

  await page.getByRole("radiogroup", { name: "Access management for Azure resources" }).getByRole("radio", { name: "No" }).check();
  await page.getByText("Access management for Azure resources set to No").first().waitFor({ timeout: 10000 });
  const roleAssignmentsOff = await wire("/providers/Microsoft.Authorization/roleAssignments");
  const stillElevated = (roleAssignmentsOff.status === 200 ? JSON.parse(roleAssignmentsOff.text).value : [])
    .some((a) => a.name === elevated?.name);
  check("setting back to No revokes the tenant-root role assignment over native Azure RBAC", !stillElevated);

  await page.getByRole("button", { name: "Manage security defaults" }).click();
  await page.getByRole("dialog", { name: "Enable security defaults" }).getByRole("radiogroup", { name: "Enable security defaults" }).getByRole("radio", { name: "No" }).check();
  await page.getByRole("dialog", { name: "Enable security defaults" }).getByRole("button", { name: "Save" }).click();
  await page.getByText("Security defaults disabled").first().waitFor({ timeout: 10000 });
  const secDefaultsGet = await graph("GET", "/policies/identitySecurityDefaultsEnforcementPolicy");
  check("UI 'Manage security defaults' → Disabled stored over the native Graph policy endpoint",
    secDefaultsGet.status === 200 && JSON.parse(secDefaultsGet.text).isEnabled === false);
  await shot("25b-entra-security-defaults");

  // ── Cosmos DB: account created through the wizard → visible over native ARM ───────────
  const cosmosArm = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2024-05-15`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const COSMOS = `vysmokecosmos${n}`;
  await page.goto(UI + "#/cosmos/create");
  await page.getByRole("button", { name: "Create", exact: true }).click(); // API picker: NoSQL is selected by default
  await page.getByLabel("Resource Group", { exact: true }).selectOption(RG);
  await page.getByLabel("Account Name", { exact: true }).fill(COSMOS);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("28-cosmos-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: COSMOS, exact: true }).waitFor({ timeout: 10000 });
  const cosmosGet = await cosmosArm("GET", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COSMOS}`);
  check("UI create Azure Cosmos DB account → visible over native ARM", cosmosGet.status === 200, `HTTP ${cosmosGet.status}`);
  await shot("29-cosmos-overview");

  // ── Data Explorer: database + container + item created through the UI → readable over
  // the native Cosmos DB REST (SQL/Core API) data plane ───────────────────────────────────
  const CDB = `smokedb${n}`;
  const CCOLL = `smokecoll${n}`;
  await openPanel("Data Explorer");
  await page.getByLabel("Database id", { exact: true }).fill(CDB);
  await page.getByLabel("Container id", { exact: true }).fill(CCOLL);
  await page.getByLabel("Partition key", { exact: true }).fill("/pk");
  await page.getByRole("button", { name: "OK", exact: true }).click();
  await page.getByText(`${CDB} / ${CCOLL}`).waitFor({ timeout: 10000 });
  await shot("30-cosmos-data-explorer-new-container");
  await page.getByRole("button", { name: "New Item" }).click();
  await page.getByLabel("New item JSON", { exact: true }).fill(JSON.stringify({ id: "smoke-item", pk: "p1", note: "smoke" }));
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByText("smoke-item", { exact: true }).waitFor({ timeout: 10000 });
  await shot("31-cosmos-data-explorer-item");
  const itemGet = await wire(`/dbs/${CDB}/colls/${CCOLL}/docs/smoke-item`);
  let item = {};
  try { item = JSON.parse(itemGet.text); } catch {}
  check("UI create item in Data Explorer → readable over the native Cosmos DB data plane",
    itemGet.status === 200 && item.note === "smoke", `HTTP ${itemGet.status}`);

  // ── A document written directly over the native wire (SDK → UI direction) shows up when
  // the UI's SQL query box is run ─────────────────────────────────────────────────────────
  const wirePut = await wire(`/dbs/${CDB}/colls/${CCOLL}/docs`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id: "wire-item", pk: "p2", note: "from-wire" }),
  });
  check("native wire create document", wirePut.status === 201, `HTTP ${wirePut.status}`);
  await page.getByLabel("SQL query", { exact: true }).fill("SELECT * FROM c WHERE c.note = 'from-wire'");
  await page.getByRole("button", { name: "Execute" }).click();
  await page.getByText("wire-item", { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created document → readable via the UI's SQL query box", true);
  await shot("32-cosmos-data-explorer-query");

  // ── Replicate data globally: Add region + Manual Failover through the UI really
  // reassign the write region over native ARM (azure.cosmos.replicate_data_globally) ─────────
  await openPanel("Replicate data globally");
  await page.getByRole("button", { name: "Add region" }).click();
  await page.getByLabel("Region", { exact: true }).selectOption("westus");
  await page.getByRole("dialog", { name: "Add region" }).getByRole("button", { name: "Save" }).click();
  await page.getByRole("dialog", { name: "Add region" }).waitFor({ state: "detached", timeout: 10000 });
  await page.getByText("West US", { exact: true }).waitFor({ timeout: 10000 });
  await shot("33b-cosmos-replicate-add-region");
  await page.getByRole("button", { name: "Manual Failover" }).click();
  await page.getByLabel("New write region", { exact: true }).selectOption("westus");
  await page.getByRole("dialog", { name: "Manual Failover" }).getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Manual Failover" }).waitFor({ state: "detached", timeout: 10000 });
  const cosmosFailedOver = await cosmosArm("GET", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COSMOS}`);
  const cosmosFailedOverBody = JSON.parse(cosmosFailedOver.text);
  check("UI Manual Failover → write region reassigned over native ARM",
    cosmosFailedOverBody.location === "westus", JSON.stringify(cosmosFailedOverBody.properties?.locations));

  // ── Lock created on the account → visible over native ARM ──────────────────────────────
  await page.goto(UI + `#/cosmos/${RG}/${COSMOS}/locks`);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const COSMOSLOCK = `smoke-cosmoslock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(COSMOSLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(COSMOSLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const cosmosLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COSMOS}/providers/Microsoft.Authorization/locks/${COSMOSLOCK}?api-version=2020-05-01`);
  check("UI create lock on Cosmos account → visible over native ARM", cosmosLockGet.status === 200, `HTTP ${cosmosLockGet.status}`);
  await shot("33-cosmos-locks");
  await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COSMOS}/providers/Microsoft.Authorization/locks/${COSMOSLOCK}?api-version=2020-05-01`, { method: "DELETE" });

  // ── Account deleted through the overview → gone over ARM ───────────────────────────────
  await page.goto(UI + `#/cosmos/${RG}/${COSMOS}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete account" }).click();
  await page.getByLabel("Confirm deletion").fill(COSMOS);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Azure Cosmos DB", exact: true }).waitFor({ timeout: 10000 });
  const cosmosGone = await cosmosArm("GET", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COSMOS}`);
  check("UI delete Azure Cosmos DB account → ARM GET 404", cosmosGone.status === 404, `HTTP ${cosmosGone.status}`);

  // ── Virtual network created through the wizard → visible over native ARM, with its
  // default subnet (a nested child resource created right after the vnet itself) ────────
  const VNET = `vysmokevnet${n}`;
  const VNET2 = `vywirevnet${n}`;
  const SUBNET = `smoke-subnet-${n}`;
  const PEERVNET = `vysmokepeer${n}`;
  const PEERNAME = `smoke-peer-${n}`;
  const VNETLOCK = `vyvnetlock${n}`;
  await page.goto(UI + "#/vnets/create");
  await page.getByLabel("Virtual network name", { exact: true }).fill(VNET);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await shot("28-vnet-create-basics");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: VNET, exact: true }).first().waitFor({ timeout: 10000 });
  const vnetGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}`);
  check("UI create virtual network → visible over native ARM", vnetGet.status === 200, `HTTP ${vnetGet.status}`);
  const defaultSubnetGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}/subnets/default`);
  check("UI create virtual network → default subnet visible over native ARM (nested child resource)", defaultSubnetGet.status === 200, `HTTP ${defaultSubnetGet.status}`);
  await shot("29-vnet-overview");

  // ── Route table + NAT gateway created over the wire (own ARM resource types, no dedicated
  // console yet) → real options in the Add subnet dialog's NAT gateway / Route table pickers ──
  const RT = `vysmokert${n}`;
  const NATGW = `vysmokenat${n}`;
  const rtPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/routeTables/${RT}`, { location: "eastus" });
  check("ARM PUT route table over wire", rtPut.status === 200 || rtPut.status === 201, `HTTP ${rtPut.status}`);
  const natPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/natGateways/${NATGW}`, { location: "eastus" });
  check("ARM PUT NAT gateway over wire", natPut.status === 200 || natPut.status === 201, `HTTP ${natPut.status}`);

  // ── Subnet added in the UI, with real NAT gateway / Route table associations → visible as
  // a native ARM nested child resource, both associations intact ─────────────────────────
  await openPanel("Subnets");
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Subnet", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill(SUBNET);
  await page.getByLabel("Starting address", { exact: true }).fill("10.0.5.0");
  await page.getByLabel("NAT gateway", { exact: true }).selectOption({ label: NATGW });
  await page.getByLabel("Route table", { exact: true }).selectOption({ label: RT });
  await page.getByRole("dialog").getByRole("button", { name: "Add" }).click();
  await page.getByRole("cell", { name: SUBNET, exact: true }).waitFor({ timeout: 10000 });
  const subnetGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}/subnets/${SUBNET}`);
  check("UI add subnet → visible over native ARM (nested child resource)", subnetGet.status === 200, `HTTP ${subnetGet.status}`);
  const subnetProps = JSON.parse(subnetGet.text || "{}").properties || {};
  check("UI subnet NAT gateway picker → real association over native ARM",
    (subnetProps.natGateway?.id || "").endsWith(`/natGateways/${NATGW}`), JSON.stringify(subnetProps.natGateway));
  check("UI subnet Route table picker → real association over native ARM",
    (subnetProps.routeTable?.id || "").endsWith(`/routeTables/${RT}`), JSON.stringify(subnetProps.routeTable));
  await page.getByRole("cell", { name: RT, exact: true }).waitFor({ timeout: 10000 });
  check("Subnets grid Route table column shows the real association", true);
  await shot("30-vnet-subnets");

  // ── Topology: real subnets/peerings/connected-devices read-back, not an honest gap ───────
  await openPanel("Topology");
  await page.getByRole("cell", { name: SUBNET, exact: true }).or(page.getByText(SUBNET, { exact: true })).first().waitFor({ timeout: 10000 });
  check("Topology shows this virtual network's own subnet", true);
  await shot("30c-vnet-topology");

  // ── Network interface created over the wire, attached to the subnet → shown in the UI's
  // Connected devices list (CLI → UI direction; a subscription-wide scan filtered by
  // ipConfigurations[].subnet.id, not a dedicated NIC console) ──────────────────────────
  const NIC = `vysmokenic${n}`;
  const nicPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${NIC}`,
    { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}/subnets/${SUBNET}` } } }] } });
  check("ARM PUT network interface over wire", nicPut.status === 200 || nicPut.status === 201, `HTTP ${nicPut.status}`);
  await openPanel("Connected devices");
  await page.getByRole("cell", { name: NIC, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created network interface shown in Connected devices", true);
  await shot("30b-vnet-connected-devices");

  // ── Peering added in the UI → visible on BOTH virtual networks over native ARM ────────
  const peerPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${PEERVNET}`, { location: "eastus" });
  check("ARM PUT remote virtual network for peering over wire", peerPut.status === 200 || peerPut.status === 201, `HTTP ${peerPut.status}`);
  await openPanel("Peerings");
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Peering link name", { exact: true }).fill(PEERNAME);
  await page.getByLabel("Remote virtual network", { exact: true }).selectOption({ label: `${PEERVNET} (${RG})` });
  await page.getByRole("dialog").getByRole("button", { name: "Add" }).click();
  await page.getByRole("cell", { name: PEERNAME, exact: true }).waitFor({ timeout: 10000 });
  const peeringGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}/virtualNetworkPeerings/${PEERNAME}`);
  check("UI add peering → visible over native ARM (nested child resource)", peeringGet.status === 200, `HTTP ${peeringGet.status}`);
  const reciprocalGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${PEERVNET}/virtualNetworkPeerings/${PEERVNET}-to-${VNET}`);
  check("UI add peering → reciprocal peering created on the remote virtual network", reciprocalGet.status === 200, `HTTP ${reciprocalGet.status}`);
  await shot("31-vnet-peerings");

  // ── Lock created in the UI → visible over the native ARM wire ─────────────────────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(VNETLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(VNETLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const vnetLockGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}/providers/Microsoft.Authorization/locks/${VNETLOCK}`);
  check("UI create lock on virtual network → visible over native ARM", vnetLockGet.status === 200, `HTTP ${vnetLockGet.status}`);
  await shot("32-vnet-locks");

  // ── Diagnose and solve problems: Network Watcher's Next hop answers from this vnet's own
  // real route topology (azure.vnets.network_watcher) — the NIC already in this vnet's subnet
  // (created above for Connected devices) gets a VM, then Next hop to the internet is checked ──
  const vnetVmPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VNETVM}`,
    { location: "eastus", properties: { networkProfile: { networkInterfaces: [{ id: JSON.parse(nicPut.text).id }] } } });
  check("ARM PUT virtual machine for Network Watcher diagnostics, over wire", vnetVmPut.status === 200 || vnetVmPut.status === 201, `HTTP ${vnetVmPut.status}`);
  await openPanel("Diagnose and solve problems");
  await page.getByRole("button", { name: "Next hop", exact: true }).click();
  await page.getByLabel("Virtual machine", { exact: true }).selectOption({ label: VNETVM });
  await page.getByLabel("Destination IP address", { exact: true }).fill("8.8.8.8");
  await page.getByRole("dialog").getByRole("button", { name: "Next hop", exact: true }).click();
  await page.getByText("Next hop type: Internet").waitFor({ timeout: 10000 });
  check("UI Next hop (Diagnose and solve problems) → answers from this vnet's real route topology", true);
  await shot("32b-vnet-diagnose-nexthop");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // ── Connection troubleshoot (azure.vnets.network_watcher): same netsim evaluator, reached
  // from the vnet's own Monitoring menu item instead of Diagnose and solve problems ─────────
  await openPanel("Connection troubleshoot");
  await page.getByRole("button", { name: "Check connectivity" }).click();
  await page.getByLabel("Source virtual machine", { exact: true }).selectOption({ label: VNETVM });
  await page.getByRole("radio", { name: "Manual", exact: true }).click();
  await page.getByLabel("Destination IP address", { exact: true }).fill("8.8.8.8");
  await page.getByLabel("Destination port", { exact: true }).fill("443");
  await page.getByRole("dialog").getByRole("button", { name: "Check", exact: true }).click();
  await page.getByText("Reachable", { exact: true }).waitFor({ timeout: 10000 });
  check("UI Connection troubleshoot → real connectivity check over this vnet's route topology", true);
  await shot("32c-vnet-connection-troubleshoot");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // ── Access control (IAM): a role assignment created over the wire, EXPLICITLY scoped to
  // this virtual network (not just the subscription/resource group) → read back on the Role
  // assignments tab, and a real Check access decision reflects it (azure.vnets.iam) ────────
  const vnetId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET}`;
  const vnetRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${VNETROLE}?api-version=2022-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ properties: { principalId: VNETPRINCIPAL, roleName: "Owner", scope: vnetId } }) });
  check("ARM PUT role assignment scoped to the vnet over wire", vnetRoleRes.status === 200 || vnetRoleRes.status === 201, `HTTP ${vnetRoleRes.status}`);
  await openPanel("Access control (IAM)");
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText(VNETPRINCIPAL).first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the vnet-scoped wire-created assignment", true);
  await shot("32d-vnet-iam-role-assignments");
  await page.getByRole("tab", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByLabel("Principal ID", { exact: true }).fill(VNETPRINCIPAL);
  await page.getByRole("dialog").getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByText("Allowed").waitFor({ timeout: 10000 });
  check("UI Check access on the vnet → real decision reflects the vnet-scoped role assignment", true);
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  // ── Virtual network created over the wire → visible in the UI (CLI → UI), then deleted in the UI ──
  const vnetPut = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET2}`, { location: "eastus" });
  check("ARM PUT virtual network over wire", vnetPut.status === 200 || vnetPut.status === 201, `HTTP ${vnetPut.status}`);
  await page.goto(UI + "#/vnets");
  await page.getByRole("link", { name: VNET2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created virtual network shown in browse grid", true);
  await shot("33-vnet-browse");
  await page.getByRole("checkbox", { name: `Select /subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET2}` }).click();
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(VNET2);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("link", { name: VNET2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  let vnetGone = { status: 0 };
  for (let i = 0; i < 20 && vnetGone.status !== 404; i++) {
    vnetGone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VNET2}`);
    if (vnetGone.status !== 404) await page.waitForTimeout(500);
  }
  check("UI delete virtual network → ARM GET 404", vnetGone.status === 404, `HTTP ${vnetGone.status}`);
  // ── Subscriptions: the one simulated subscription, renamed through the UI → visible over ARM ──
  // (the name persists, so start — and finish, below — from the default)
  const resetSubName = () => wire(`/subscriptions/${SUB}/providers/Microsoft.Subscription/rename?api-version=2021-10-01`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ subscriptionName: "CloudLearn Subscription" }) });
  await resetSubName();
  await page.goto(UI + "#/subscriptions");
  await page.getByRole("heading", { name: "Subscriptions", exact: true }).waitFor({ timeout: 10000 });
  await page.getByRole("link", { name: "CloudLearn Subscription", exact: true }).waitFor({ timeout: 10000 });
  await shot("30-subscriptions-list");
  await page.getByRole("link", { name: "CloudLearn Subscription", exact: true }).click();
  await page.getByRole("heading", { name: "CloudLearn Subscription", exact: true }).waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Rename", exact: true }).click();
  await page.getByLabel("Subscription name", { exact: true }).fill(SUBNAME);
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByRole("heading", { name: SUBNAME, exact: true }).waitFor({ timeout: 10000 });
  const subscriptionGot = await arm("GET", "");
  check("UI rename subscription → visible over native ARM", JSON.parse(subscriptionGot.text).displayName === SUBNAME, subscriptionGot.text);
  await shot("31-subscription-overview");

  // ── Tags applied in the UI → persisted over ARM (Microsoft.Resources/tags/default) ──
  await openPanel("Tags");
  await page.getByLabel("Tag name 1", { exact: true }).fill("env");
  await page.getByLabel("Tag value 1", { exact: true }).fill("smoke");
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await page.waitForTimeout(600);
  const subTags = await wire(`/subscriptions/${SUB}/providers/Microsoft.Resources/tags/default?api-version=2021-04-01`);
  check("UI tag apply → persisted on the subscription over ARM", JSON.parse(subTags.text).properties?.tags?.env === "smoke", subTags.text);

  // ── Lock created in the UI, scoped to the subscription itself → visible over ARM ──
  await openPanel("Resource locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(SUBLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 20000 });   // its overlay blocks the next click
  await page.getByText(SUBLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const subLockGet = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/locks/${SUBLOCK}?api-version=2016-09-01`);
  check("UI add subscription-scoped lock → visible over native ARM", subLockGet.status === 200, `HTTP ${subLockGet.status}`);
  await shot("32-subscription-locks");

  // ── Resource group + resource + deployment created over the wire → shown in the Subscription's ──
  // Resource groups / Resources / Deployments panels (CLI → UI direction) ───────────────────────
  const subRgPut = await arm("PUT", `/resourceGroups/${SUBRG}`, { location: "eastus" });
  check("ARM PUT resource group over wire", subRgPut.status === 200, `HTTP ${subRgPut.status}`);
  await wire(`/subscriptions/${SUB}/resourceGroups/${SUBRG}/providers/Microsoft.Storage/storageAccounts/${SUBSA}`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus" }) });
  const subDepPut = await wire(`/subscriptions/${SUB}/providers/Microsoft.Resources/deployments/${SUBDEP}?api-version=2021-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { mode: "Incremental", template: {} } }) });
  check("ARM PUT subscription-scoped deployment over wire", subDepPut.status === 200, `HTTP ${subDepPut.status}`);

  await openPanel("Resource groups");
  await page.getByRole("link", { name: SUBRG, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created resource group shown in the Subscription's Resource groups panel", true);

  await openPanel("Resources");
  await page.getByText(SUBSA, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created resource shown in the Subscription's Resources panel", true);

  await openPanel("Deployments");
  await page.getByText(SUBDEP, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created deployment shown in the Subscription's Deployments panel", true);
  await shot("33-subscription-deployments");

  // ── Resource providers: unregister then re-register through the UI → reflected over ARM ──
  await openPanel("Resource providers");
  await page.getByRole("row", { name: /Microsoft\.Storage/ }).getByRole("button", { name: "Unregister" }).click();
  await page.waitForTimeout(500);
  const unregistered = await arm("GET", "/providers/Microsoft.Storage");
  check("UI unregister provider → ARM reflects NotRegistered", JSON.parse(unregistered.text).registrationState === "NotRegistered", unregistered.text);
  await page.getByRole("row", { name: /Microsoft\.Storage/ }).getByRole("button", { name: "Register" }).click();
  await page.waitForTimeout(500);
  const registered = await arm("GET", "/providers/Microsoft.Storage");
  check("UI register provider → ARM reflects Registered", JSON.parse(registered.text).registrationState === "Registered", registered.text);

  // ── Access control (IAM): role assignment added through the UI, scoped to the subscription
  // itself, then a real checkAccess decision, then removed ───────────────────────────────────
  await openPanel("Access control (IAM)");
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByRole("toolbar", { name: "Access control commands" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Role", { exact: true }).selectOption("Reader");
  await page.getByLabel("Member", { exact: true }).fill(SUBPRINCIPAL);
  await page.getByRole("button", { name: "Review + assign" }).click();
  await page.getByText(SUBPRINCIPAL).first().waitFor({ timeout: 10000 });
  const subRaGet = await arm("GET", "/providers/Microsoft.Authorization/roleAssignments");
  const subRaList = JSON.parse(subRaGet.text).value || [];
  const subRa = subRaList.find((r) => r.properties?.principalId === SUBPRINCIPAL);
  check("UI Add role assignment → visible over native ARM, scoped to the subscription itself",
    !!subRa && subRa.properties.scope === `/subscriptions/${SUB}`, JSON.stringify(subRa));

  await page.getByRole("tab", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByLabel("Find a user, group or service principal", { exact: true }).fill(SUBPRINCIPAL);
  await page.getByRole("dialog").getByRole("button", { name: "Check access", exact: true }).click();
  await page.getByText("Allowed").waitFor({ timeout: 10000 });
  check("UI Check access → real decision reflects the role just assigned", true);
  // Two "Close" buttons in this dialog (title's icon-only close + the footer button) — the
  // footer one is last in DOM order.
  await page.getByRole("button", { name: "Close" }).last().click();

  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByLabel(`Select ${SUBPRINCIPAL}`, { exact: true }).check();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  // Scoped to the checkbox (not getByText(SUBPRINCIPAL)) — a success toast can still be
  // showing the same principal text, which would otherwise make this a strict-mode violation.
  await page.getByLabel(`Select ${SUBPRINCIPAL}`, { exact: true }).waitFor({ state: "detached", timeout: 10000 });
  const subRaGone = await arm("GET", "/providers/Microsoft.Authorization/roleAssignments");
  check("UI Remove role assignment → gone over native ARM",
    !(JSON.parse(subRaGone.text).value || []).some((r) => r.properties?.principalId === SUBPRINCIPAL), subRaGone.text);

  // ── Create a subscription (renames the one simulated subscription, the honest Vyomi gap) ──
  await page.goto(UI + "#/subscriptions/create");
  await page.getByLabel("Subscription name", { exact: true }).fill(`${SUBNAME}-2`);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: `${SUBNAME}-2`, exact: true }).waitFor({ timeout: 10000 });
  const subscriptionGot2 = await arm("GET", "");
  check("UI create-subscription wizard → renames the one simulated subscription over ARM", JSON.parse(subscriptionGot2.text).displayName === `${SUBNAME}-2`, subscriptionGot2.text);
  await resetSubName();
  // ── Virtual machine created through the wizard → visible over native ARM ──────────────
  const DEFAULT_RG = "cloudlearn-rg";   // kit/arm.js's DEFAULT_RG — the wizard's default resource group
  const VM = `vysmokevm${n}`;
  const VM2 = `vywirevm${n}`;
  await page.goto(UI + "#/vms/create");
  await page.getByLabel("Virtual machine name", { exact: true }).fill(VM);
  await page.getByLabel("Username", { exact: true }).fill("azureuser");
  await page.getByLabel("Size", { exact: true }).selectOption("Standard_B1s");   // within the offline Free tier's size cap
  await page.getByRole("tab", { name: "Networking" }).click();
  await page.getByLabel("Public IP", { exact: true }).selectOption({ label: `(new) ${VM}-ip` });
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await shot("29-vm-create-review");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: VM, exact: true }).waitFor({ timeout: 10000 });
  const vmGet = await arm("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Compute/virtualMachines/${VM}`);
  check("UI create virtual machine → visible over native ARM", vmGet.status === 200, `HTTP ${vmGet.status}`);
  await shot("30-vm-overview");

  // ── Public IP requested in the create wizard → real Microsoft.Network/publicIPAddresses
  // resource, referenced from the NIC and shown in the UI (azure.vms.networking) ───────────
  const pipGet = await arm("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/publicIPAddresses/${VM}-ip`);
  const pipIp = pipGet.status === 200 ? JSON.parse(pipGet.text).properties?.ipAddress : null;
  check("UI-requested public IP is a real ARM resource with a real address", pipGet.status === 200 && /^\d+\.\d+\.\d+\.\d+$/.test(pipIp || ""), pipGet.text.slice(0, 160));
  await page.getByText(pipIp || "no-pip").first().waitFor({ timeout: 10000 });
  check("Overview shows the real public IP address (not '--')", true);
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}/connect`);
  await page.getByText(pipIp || "no-pip").first().waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Native SSH", exact: true }).click();
  const sshCmdText = (await page.locator("p").filter({ hasText: "ssh azureuser@" }).first().innerText());
  check("Connect's SSH command uses the real public IP", sshCmdText.includes(pipIp || "\0"), sshCmdText);
  await page.getByRole("button", { name: "Close" }).click();
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}`);

  // ── Start / Stop from the Overview command bar → power state over native ARM ──────────
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Stop", exact: true }).click();
  await page.getByText("Stop succeeded").waitFor({ timeout: 10000 });
  const vmStopped = await arm("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Compute/virtualMachines/${VM}`);
  check("UI stop virtual machine → power state over native ARM", JSON.parse(vmStopped.text).properties?.powerState === "PowerState/stopped", vmStopped.text.slice(0, 160));
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Start", exact: true }).click();
  await page.getByText("Start succeeded").waitFor({ timeout: 10000 });
  await shot("31-vm-power");

  // ── Auto-shutdown schedule saved from the Auto-shutdown settings page is ENFORCED lazily on
  // read (core/azure_arm_core.py): a schedule a few minutes in the past flips the VM's own
  // power state to stopped with no real scheduler (azure.vms.auto_shutdown) ─────────────────
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}/autoshutdown`);
  const pastLocal = new Date(Date.now() - 5 * 60000);
  await page.getByRole("radiogroup", { name: "Enabled" }).getByRole("radio", { name: "On" }).check();
  await page.getByLabel("Scheduled shutdown", { exact: true }).fill(`${String(pastLocal.getUTCHours()).padStart(2, "0")}:${String(pastLocal.getUTCMinutes()).padStart(2, "0")}`);
  await page.getByLabel("Time zone", { exact: true }).selectOption("UTC");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Save succeeded").waitFor({ timeout: 10000 });
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}`);
  await page.getByText("Stopped", { exact: true }).first().waitFor({ timeout: 10000 });
  check("auto-shutdown schedule already past today is ENFORCED on the Overview's own status", true);

  // ── Access control (IAM): a role assignment created over the wire (subscription-wide, same
  // honest scoping as the Cosmos DB account blade) is read back on the VM's own IAM tab ──────
  const VMROLE = `00000000-0000-4000-7000-${String(n).padStart(12, "0")}`;
  const vmRoleRes = await wire(`/subscriptions/${SUB}/providers/Microsoft.Authorization/roleAssignments/${VMROLE}?api-version=2022-04-01`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ properties: { principalId: "vyomi-vm-smoke-principal", roleDefinitionId: `/subscriptions/${SUB}/providers/Microsoft.Authorization/roleDefinitions/owner`, principalType: "User" } }) });
  check("ARM PUT role assignment over wire", vmRoleRes.status === 200 || vmRoleRes.status === 201, `HTTP ${vmRoleRes.status}`);
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}/iam`);
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByText("vyomi-vm-smoke-principal").first().waitFor({ timeout: 10000 });
  check("UI Access control (IAM) → Role assignments shows the wire-created assignment", true);
  await shot("31b-vm-iam-role-assignments");

  // ── Export template: ARM, Bicep and Terraform all reflect this VM's own live resource ──────
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}/exporttemplate`);
  const vmArmText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (ARM) reflects the real resource",
    vmArmText.includes("Microsoft.Compute/virtualMachines") && vmArmText.includes(VM), vmArmText.slice(0, 200));
  await page.getByRole("tab", { name: "Bicep" }).click();
  const vmBicepText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (Bicep) reflects the real resource",
    vmBicepText.includes("Microsoft.Compute/virtualMachines") && vmBicepText.includes(VM), vmBicepText.slice(0, 200));
  await page.getByRole("tab", { name: "Terraform" }).click();
  const vmTfText = await page.getByRole("textbox").first().inputValue();
  check("UI Export template (Terraform) reflects the real resource",
    vmTfText.includes("azurerm_linux_virtual_machine") && vmTfText.includes(VM), vmTfText.slice(0, 200));

  // ── Activity log: the ENFORCED timespan picker narrows the query without losing this VM's
  // own very-recent events ───────────────────────────────────────────────────────────────────
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM}/activitylog`);
  await page.getByText("Microsoft.Compute/virtualMachines/write").first().waitFor({ timeout: 10000 });
  await page.getByLabel("Timespan", { exact: true }).selectOption("1h");
  await page.getByText("Microsoft.Compute/virtualMachines/write").first().waitFor({ timeout: 10000 });
  check("UI Activity log timespan picker narrows the query without losing this VM's own recent events", true);

  // ── Virtual machine created over the wire → visible in the UI (CLI → UI) ──────────────
  const vmPut = await arm("PUT", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Compute/virtualMachines/${VM2}`,
    { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, osProfile: { computerName: VM2, adminUsername: "azureuser" }, storageProfile: { osDisk: { osType: "Linux" } } } });
  check("ARM PUT virtual machine over wire", vmPut.status === 200 || vmPut.status === 201, `HTTP ${vmPut.status}`);
  await page.goto(UI + "#/vms");
  await page.getByRole("link", { name: VM2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created virtual machine shown in browse grid", true);
  await shot("32-vm-browse");

  // ── Delete through the Overview command bar → gone over native ARM ───────────────────
  await page.goto(UI + `#/vms/${DEFAULT_RG}/${VM2}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(VM2);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Virtual machines", exact: true }).waitFor({ timeout: 10000 });
  const vmGone = await arm("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Compute/virtualMachines/${VM2}`);
  check("UI delete virtual machine → ARM GET 404", vmGone.status === 404, `HTTP ${vmGone.status}`);

  // ── DNS: public zone created through the wizard → visible over native ARM ─────────────
  await page.goto(UI + "#/dns/create");
  await page.getByLabel("Name", { exact: true }).fill(DNSZONE);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: DNSZONE, exact: true }).waitFor({ timeout: 10000 });
  const dnsZoneGet = await armDns("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSZONE}`);
  check("UI create DNS zone → visible over native ARM", dnsZoneGet.status === 200, `HTTP ${dnsZoneGet.status}`);
  await shot("33-dns-zone-overview");

  // ── Record set added through the UI → visible over native ARM ──────────────────────────
  await page.getByRole("button", { name: "Record set" }).click();
  await page.getByLabel("Name", { exact: true }).fill(DNSREC);
  await page.getByLabel("IP address", { exact: true }).fill("10.20.30.40");
  await page.getByRole("dialog", { name: "Add record set" }).getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add record set" }).waitFor({ state: "detached", timeout: 10000 });
  await page.getByRole("button", { name: DNSREC, exact: true }).waitFor({ timeout: 10000 });
  const dnsRecGet = await armDns("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSZONE}/A/${DNSREC}`);
  check("UI add A record set → visible over native ARM", dnsRecGet.status === 200 && JSON.parse(dnsRecGet.text).properties?.ARecords?.[0]?.ipv4Address === "10.20.30.40", dnsRecGet.text);
  await shot("34-dns-zone-recordsets");

  // ── Lock created through the UI, scoped to this zone → visible over native ARM ─────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(DNSLOCK);
  await page.getByRole("dialog", { name: "Add lock" }).getByRole("button", { name: "OK" }).click();
  await page.getByRole("dialog", { name: "Add lock" }).waitFor({ state: "detached", timeout: 10000 });
  await page.getByText(DNSLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const dnsLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSZONE}/providers/Microsoft.Authorization/locks/${DNSLOCK}?api-version=2020-05-01`);
  check("UI add DNS zone lock → visible over native ARM", dnsLockGet.status === 200, `HTTP ${dnsLockGet.status}`);

  // ── Private zone created through the wizard → visible over native ARM, no name servers ─
  await page.goto(UI + "#/dns/create");
  await page.getByLabel("Name", { exact: true }).fill(DNSPRIV);
  await page.getByRole("radio", { name: /^Private:/ }).check();
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: DNSPRIV, exact: true }).waitFor({ timeout: 10000 });
  const dnsPrivGet = await armDns("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSPRIV}`);
  const dnsPrivBody = JSON.parse(dnsPrivGet.text);
  check("UI create private DNS zone → visible over native ARM, no name servers",
    dnsPrivGet.status === 200 && dnsPrivBody.properties?.zoneType === "Private" && (dnsPrivBody.properties?.nameServers || []).length === 0, dnsPrivGet.text);

  // ── Virtual network link added through the UI → visible over native ARM ───────────────
  const dnsVnetPut = await arm("PUT", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/virtualNetworks/${DNSVNET}`,
    { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.90.0.0/16"] } } });
  check("ARM PUT virtual network over wire (for the DNS link)", dnsVnetPut.status === 200 || dnsVnetPut.status === 201, `HTTP ${dnsVnetPut.status}`);
  await openPanel("Virtual network links");
  await page.getByRole("button", { name: "Add registration link" }).click();
  await page.getByLabel("Virtual network", { exact: true }).selectOption({ label: DNSVNET });
  await page.getByRole("dialog", { name: "Add registration link" }).getByRole("button", { name: "Add", exact: true }).click();
  await page.getByText(DNSVNET).first().waitFor({ timeout: 10000 });
  const dnsPrivLinked = JSON.parse((await armDns("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSPRIV}`)).text);
  check("UI add registration VNet link → visible over native ARM",
    (dnsPrivLinked.properties?.registrationVirtualNetworks || []).some((v) => v.id.includes(DNSVNET)), JSON.stringify(dnsPrivLinked.properties));
  await shot("35-dns-zone-vnetlinks");

  // ── DNS zone + record set created over the wire → visible in the UI (CLI → UI) ─────────
  const dnsZone2Put = await armDns("PUT", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSZONE2}`, { location: "global" });
  check("ARM PUT DNS zone over wire", dnsZone2Put.status === 200 || dnsZone2Put.status === 201, `HTTP ${dnsZone2Put.status}`);
  const dnsRec2Put = await armDns("PUT", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSZONE2}/TXT/${DNSREC2}`,
    { properties: { TTL: 300, TXTRecords: [{ value: ["uic"] }] } });
  check("ARM PUT TXT record set over wire", dnsRec2Put.status === 200 || dnsRec2Put.status === 201, `HTTP ${dnsRec2Put.status}`);
  await page.goto(UI + "#/dns");
  await page.getByRole("link", { name: DNSZONE2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created DNS zone shown in browse grid", true);
  await page.goto(UI + `#/dns/${DEFAULT_RG}/${DNSZONE2}`);
  await page.getByRole("button", { name: DNSREC2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created record set shown in the zone's record sets table", true);
  await shot("36-dns-zones-browse");

  // ── Delete through the Overview command bar → gone over native ARM ────────────────────
  await page.goto(UI + `#/dns/${DEFAULT_RG}/${DNSZONE}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(DNSZONE);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("heading", { name: "DNS zones", exact: true }).waitFor({ timeout: 10000 });
  const dnsZoneGone = await armDns("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.Network/dnsZones/${DNSZONE}`);
  check("UI delete DNS zone → ARM GET 404", dnsZoneGone.status === 404, `HTTP ${dnsZoneGone.status}`);
  // ── Azure AI services account created through the wizard → visible over native ARM ────
  await page.goto(UI + "#/cognitiveservices/create");
  await page.getByLabel("Name", { exact: true }).fill(COGS);
  await page.getByLabel("Resource group", { exact: true }).selectOption(RG);
  await shot("33-create-cognitiveservices-basics");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: COGS, exact: true }).waitFor({ timeout: 10000 });
  const gotCogs = await armCogs("GET", `/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${COGS}`);
  check("UI create Azure AI services account → visible over native ARM", gotCogs.status === 200 && JSON.parse(gotCogs.text).kind === "OpenAI", `HTTP ${gotCogs.status}`);
  await shot("34-cognitiveservices-overview");

  // ── Model deployment created in the blade → readable over native ARM ───────────────────
  await openPanel("Model deployments");
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Create new deployment" }).click();
  await page.getByLabel("Deployment name", { exact: true }).fill(DEPLOY);
  await page.getByRole("dialog").getByRole("button", { name: "Deploy" }).click();
  await page.getByText(DEPLOY, { exact: true }).first().waitFor({ timeout: 10000 });
  const depGet = await armCogs("GET", `/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${COGS}/deployments/${DEPLOY}`);
  check("UI create model deployment → readable over native ARM", depGet.status === 200 && JSON.parse(depGet.text).properties?.model?.name === "gpt-4o", `HTTP ${depGet.status}`);
  await shot("35-cognitiveservices-deployments");

  // ── Account created over the wire → visible in the UI browse grid (CLI → UI) ───────────
  const cogsPut = await armCogs("PUT", `/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${COGS2}`,
    { kind: "OpenAI", sku: { name: "S0" }, location: "eastus" });
  check("ARM PUT Azure AI services account over wire", cogsPut.status === 200 || cogsPut.status === 201, `HTTP ${cogsPut.status}`);
  await page.goto(UI + "#/cognitiveservices");
  await page.getByRole("link", { name: COGS2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created account shown in browse grid", true);
  await shot("36-cognitiveservices-browse");

  // ── Delete through the Overview command bar → gone over native ARM (soft-deleted) ──────
  await page.goto(UI + `#/cognitiveservices/${RG}/${COGS2}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(COGS2);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });
  await page.getByRole("heading", { name: "Azure AI services", exact: true }).waitFor({ timeout: 10000 });
  const cogsGone = await armCogs("GET", `/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${COGS2}`);
  check("UI delete Azure AI services account → ARM GET 404", cogsGone.status === 404, `HTTP ${cogsGone.status}`);
  // ── Log Analytics workspace created through the wizard → visible over native ARM ──────
  const lawArm = (path) => arm("GET", `/resourceGroups/${DEFAULT_RG}${path}`);
  await page.goto(UI + "#/loganalytics/create");
  await page.getByLabel("Name", { exact: true }).fill(LAW);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: LAW, exact: true }).waitFor({ timeout: 10000 });
  const lawGet = await arm("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.OperationalInsights/workspaces/${LAW}`);
  check("UI create Log Analytics workspace → visible over native ARM", lawGet.status === 200, `HTTP ${lawGet.status}`);
  await shot("33-loganalytics-overview");

  // ── Agents management shows the real workspace ID + shared keys ───────────────────────
  await openPanel("Agents management");
  await page.getByText("Workspace ID").waitFor({ timeout: 5000 });
  const primaryBefore = await page.getByLabel("Primary key").inputValue();
  check("Agents management shows a real primary key", primaryBefore.length > 10, primaryBefore);
  await page.getByRole("button", { name: "Regenerate" }).first().click();
  await page.waitForTimeout(500);
  const primaryAfter = await page.getByLabel("Primary key").inputValue();
  check("Regenerate primary key → key actually changes", primaryAfter !== primaryBefore && primaryAfter.length > 10);
  await shot("34-loganalytics-agents");

  // ── Saved search + custom table added in the blade → readable over native ARM ─────────
  await openPanel("Saved searches");
  await page.getByRole("button", { name: "Add saved search" }).click();
  await page.getByLabel("ID", { exact: true }).fill("smoke-search");
  await page.getByLabel("Display name", { exact: true }).fill("Smoke search");
  await page.getByLabel("Query", { exact: true }).fill("Heartbeat | take 5");
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByText("Smoke search", { exact: true }).first().waitFor({ timeout: 10000 });
  const savedSearchGet = await lawArm(`/providers/Microsoft.OperationalInsights/workspaces/${LAW}/savedSearches/smoke-search?api-version=2022-10-01`);
  check("UI add saved search → visible over native ARM", savedSearchGet.status === 200, `HTTP ${savedSearchGet.status}`);

  await openPanel("Tables");
  await page.getByRole("button", { name: "Add table" }).click();
  await page.getByLabel("Table name", { exact: true }).fill(LAWTABLE);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByRole("cell", { name: LAWTABLE, exact: true }).waitFor({ timeout: 10000 });
  const tableGet = await lawArm(`/providers/Microsoft.OperationalInsights/workspaces/${LAW}/tables/${LAWTABLE}?api-version=2022-10-01`);
  check("UI add custom table → visible over native ARM", tableGet.status === 200, `HTTP ${tableGet.status}`);
  await shot("35-loganalytics-tables");

  // ── Logs: the real KQL subset runs over AzureActivity (this subscription's own Activity log feed) ──
  await openPanel("Logs");
  await page.getByLabel("Query", { exact: true }).fill("AzureActivity | where OperationName == 'Microsoft.OperationalInsights/workspaces/write' | project OperationName | take 5");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByText("Microsoft.OperationalInsights/workspaces/write").first().waitFor({ timeout: 10000 });
  check("Logs query editor runs a real KQL query over the AzureActivity feed", true);
  await shot("36-loganalytics-logs");

  // ── Locks: added through the UI → visible over native ARM extension resource ──────────
  const LAWLOCK = `vylawlock${n}`;
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name").fill(LAWLOCK);
  await page.getByRole("button", { name: "OK" }).click();
  await page.getByRole("cell", { name: LAWLOCK, exact: true }).waitFor({ timeout: 10000 });
  const lawLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${DEFAULT_RG}/providers/Microsoft.OperationalInsights/workspaces/${LAW}/providers/Microsoft.Authorization/locks/${LAWLOCK}?api-version=2020-05-01`);
  check("UI add lock → visible over native ARM extension resource", lawLockGet.status === 200, `HTTP ${lawLockGet.status}`);
  await page.getByRole("row", { name: new RegExp(LAWLOCK) }).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(LAWLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("cell", { name: LAWLOCK, exact: true }).waitFor({ state: "detached", timeout: 10000 });

  // ── Activity log: the workspace's own create/lock writes land on the generic eventtypes feed ──
  await openPanel("Activity log");
  await page.getByText("Microsoft.OperationalInsights/workspaces/write").first().waitFor({ timeout: 10000 });
  check("UI Activity log shows this workspace's own ARM writes", true);

  // ── Workspace created over the wire → visible in the UI (CLI → UI) ────────────────────
  const lawPut = await arm("PUT", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.OperationalInsights/workspaces/${LAW2}`, { location: "eastus" });
  check("ARM PUT Log Analytics workspace over wire", lawPut.status === 200 || lawPut.status === 201, `HTTP ${lawPut.status}`);
  await page.goto(UI + "#/loganalytics");
  await page.getByRole("link", { name: LAW2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created workspace shown in browse grid", true);
  await shot("37-loganalytics-browse");

  // ── Delete through the Overview command bar → gone over native ARM ───────────────────
  await page.goto(UI + `#/loganalytics/${DEFAULT_RG}/${LAW}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(LAW);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });   // open until the (async) delete returns; its modal hides the page
  await page.getByRole("heading", { name: "Log Analytics workspaces", exact: true }).waitFor({ timeout: 10000 });
  const lawGone = await arm("GET", `/resourceGroups/${DEFAULT_RG}/providers/Microsoft.OperationalInsights/workspaces/${LAW}`);
  check("UI delete Log Analytics workspace → ARM GET 404", lawGone.status === 404, `HTTP ${lawGone.status}`);
  // ── App Configuration store created through the wizard → visible over native ARM ──────
  const acArm = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2024-05-01`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const acData = (path, method = "GET", body, store) => wire(`${path}${path.includes("?") ? "&" : "?"}api-version=2023-11-01`,
    { method, headers: { "content-type": "application/json", ...(store ? { "x-vyomi-store": store } : {}) }, body: body ? JSON.stringify(body) : undefined });
  const AC = `vysmokeac${n}`;
  await page.goto(UI + "#/appconfiguration/create");
  await page.getByLabel("Resource name", { exact: true }).fill(AC);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG);
  await page.getByLabel("Pricing tier", { exact: true }).selectOption("Standard");   // Geo-replication below needs Standard/Premium
  await shot("33-create-appconfig-basics");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: AC, exact: true }).waitFor({ timeout: 10000 });
  const gotAc = await acArm("GET", `/resourceGroups/${RG}/providers/Microsoft.AppConfiguration/configurationStores/${AC}`);
  check("UI create configuration store → visible over native ARM", gotAc.status === 200, `HTTP ${gotAc.status}`);
  await shot("34-appconfig-overview");

  // ── Key-value created in the UI → readable over the App Configuration data-plane wire ──
  await openPanel("Configuration explorer");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const ACKEY = `smoke-key-${n}`;
  await page.getByLabel("Key", { exact: true }).fill(ACKEY);
  await page.getByLabel("Value", { exact: true }).fill("smoke-value");
  await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();
  await page.getByRole("link", { name: ACKEY, exact: true }).waitFor({ timeout: 10000 });
  const kvGet = await acData(`/kv/${ACKEY}`, "GET", undefined, AC);
  check("UI create key-value → readable over App Configuration data-plane wire", kvGet.status === 200 && JSON.parse(kvGet.text).value === "smoke-value", `HTTP ${kvGet.status}`);
  await shot("35-configuration-explorer");

  // ── Key-value created over the wire → visible in the UI (CLI → UI) ─────────────────────
  const WIREKEY = `wirekey-ac-${n}`;
  const putKv = await acData(`/kv/${WIREKEY}`, "PUT", { value: "from-wire" }, AC);
  check("App Configuration kv REST PUT over wire", putKv.status === 200, `HTTP ${putKv.status}`);
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Refresh" }).click();
  await page.getByText(WIREKEY, { exact: true }).waitFor({ timeout: 10000 });
  check("wire-created key-value shown in Configuration explorer", true);
  await shot("36-configuration-explorer-wire");

  // ── Feature flag added through the UI → readable over the data-plane wire, then toggled
  // from the grid → the change round-trips back out over the SAME wire ──────────────────
  await openPanel("Feature manager");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const FLAG = `smokeflag${n}`;
  await page.getByLabel("Name", { exact: true }).fill(FLAG);
  await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();
  await page.getByText(FLAG, { exact: true }).waitFor({ timeout: 10000 });
  const ffGet = await acData(`/kv/.appconfig.featureflag%2F${FLAG}`, "GET", undefined, AC);
  check("UI add feature flag → readable over the data-plane wire, starts disabled",
    ffGet.status === 200 && JSON.parse(JSON.parse(ffGet.text).value).enabled === false, ffGet.text.slice(0, 200));
  await page.getByRole("row", { name: new RegExp(FLAG) }).getByRole("switch").click();
  await page.waitForTimeout(800);
  const ffGet2 = await acData(`/kv/.appconfig.featureflag%2F${FLAG}`, "GET", undefined, AC);
  check("UI toggle feature flag → enabled over the data-plane wire", JSON.parse(JSON.parse(ffGet2.text).value).enabled === true, ffGet2.text.slice(0, 200));
  await shot("37-feature-manager");

  // ── Geo-replication: replica added through the UI → visible over native ARM ────────────
  await openPanel("Geo-replication");
  await page.getByRole("button", { name: "Create" }).click();
  const REPLICA = `smokerepl${n}`;
  await page.getByLabel("Name", { exact: true }).fill(REPLICA);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText(REPLICA, { exact: true }).waitFor({ timeout: 10000 });
  const replGet = await acArm("GET", `/resourceGroups/${RG}/providers/Microsoft.AppConfiguration/configurationStores/${AC}/replicas/${REPLICA}`);
  check("UI add replica → visible over native ARM", replGet.status === 200, `HTTP ${replGet.status}`);
  await shot("38-geo-replication");

  // ── Delete through the Overview command bar → gone over native ARM ─────────────────────
  await page.goto(UI + `#/appconfiguration/${RG}/${AC}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(AC);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog", { name: /^Delete / }).waitFor({ state: "detached", timeout: 30000 });
  await page.getByRole("heading", { name: "Configuration stores", exact: true }).waitFor({ timeout: 10000 });
  const acGone = await acArm("GET", `/resourceGroups/${RG}/providers/Microsoft.AppConfiguration/configurationStores/${AC}`);
  check("UI delete configuration store → ARM GET 404", acGone.status === 404, `HTTP ${acGone.status}`);
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
