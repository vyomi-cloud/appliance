/* End-to-end smoke of the Azure lens against a running /_wire backend (dev_server.py, the
 * offline appliance, or Nano). Drives the UI like a user and cross-checks state over the
 * NATIVE Azure wire (ARM control plane + Blob REST data plane — what azure-* SDKs and the az
 * CLI see). Screenshots → $OUT (default ./smoke-out-azure).
 *
 *   BASE=http://127.0.0.1:8740 UI_PATH=/v4/azure/ node consoles/tests/smoke-azure.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

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
const APP = `vysmokeapp${n}`;      // app service created through the UI
const APP2 = `vywireapp${n}`;      // app service created over the wire (CLI → UI direction)
const EGT = `vyegtopic${n}`;       // Event Grid topic created through the UI
const EGT2 = `vyegwire${n}`;       // Event Grid topic created over the wire
const ES = `vyeges${n}`;           // event subscription created over the wire
const LOCK = `vyeglock${n}`;       // management lock created through the UI
const RGUI = `vyrg${n}`;           // resource group created through the UI
const RGWIRE = `vyrgwire${n}`;     // resource group created over the wire (CLI → UI direction)
const RGLOCK = `vyrglock${n}`;     // resource-group-scoped lock created through the UI
const APIM = `vyapim${n}`;         // API Management service created through the UI
const APIM2 = `vyapimwire${n}`;    // API Management service created over the wire
const AKS = `vysmokeaks${n}`;      // AKS cluster created through the UI
const AKS2 = `vywireaks${n}`;      // AKS cluster created over the wire
const POOL = `pool${n}`;           // node pool created through the UI (AKS pool names are short: <=12 chars)
const SUBNAME = `Vyomi Smoke Subscription ${n}`;  // subscription renamed through the UI
const SUBLOCK = `vysublock${n}`;   // subscription-scoped lock created through the UI
const SUBRG = `vysubrg${n}`;       // resource group created over the wire (shown in the Subscription's Resource groups panel)
const SUBSA = `vysubsa${n}`;       // storage account created over the wire, inside SUBRG (shown in the Subscription's Resources panel)
const SUBDEP = `vysubdep${n}`;     // subscription-scoped deployment created over the wire
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;

// Native-wire cross-checks run INSIDE the page (same origin): on Nano only the service worker
// answers /_wire, and it only sees requests from pages it controls.
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => {
  const r = await fetch(u, i);
  return { status: r.status, text: await r.text() };
}, [WIRE + path, init]);
const arm = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2023-05-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armWeb = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2023-12-01`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const armAks = (method, path, body) => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=2024-09-02-preview`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const blobHdr = (acct) => ({ "x-ms-version": "2021-12-02", authorization: `SharedKey ${acct}:c21va2U=` });
const blob = (method, acct, path, { query = "", headers = {}, body } = {}) => wire(`/${acct}${path}${query}`, { method, headers: { ...blobHdr(acct), ...headers }, body });

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Native 404s (e.g. a deleted resource's GET) are expected answers, not page errors.
page.on("console", (m) => m.type() === "error" && !/status of 404/.test(m.text()) && errors.push(m.text()));
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

  // ── Delete through Overview → gone over ARM ────────────────────────────────────────────
  await page.goto(UI + `#/functionapp/${FARG}/${FA}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FA);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
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
  await page.getByRole("link", { name: APP2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  // The grid drops the row as soon as it starts reloading; on Nano the DELETE may still be in flight.
  let gone2 = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP2}`);
  for (let i = 0; i < 20 && gone2.status !== 404; i++) {
    await page.waitForTimeout(500);
    gone2 = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP2}`);
  }
  check("UI delete app service → ARM GET 404", gone2.status === 404, `HTTP ${gone2.status}`);
  // ── Key vault created through the wizard → visible over native ARM ─────────────────────
  const kvWire = (path, method = "GET", body) => wire(`${path}${path.includes("?") ? "&" : "?"}api-version=7.4`,
    { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
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
  await page.goto(UI + "#/vms");
  await page.getByRole("link", { name: /in the classic Vyomi console/ }).first().waitFor({ timeout: 10000 }).catch(() => {});
  check("service without a v4 module → NotSimulated + classic link",
    await page.locator("[data-vyomi-not-simulated]").first().isVisible() && await page.getByRole("link", { name: /in the classic Vyomi console/ }).first().isVisible());
  await shot("15-vms-not-simulated");
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
  await page.getByRole("toolbar", { name: "Locks commands" }).getByRole("button", { name: "Add" }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(LOCK);
  await page.getByRole("button", { name: "OK" }).click();
  await page.getByText(LOCK).first().waitFor({ timeout: 10000 });
  const lockGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT}/providers/Microsoft.Authorization/locks/${LOCK}`);
  check("UI add lock → visible over native ARM (extension resource)", lockGet.status === 200, `HTTP ${lockGet.status}`);

  // ── Resource created over the wire → visible in the UI (CLI → UI) ──────────────────────
  const egput = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/topics/${EGT2}`, { location: "eastus" });
  check("ARM PUT Event Grid topic over wire", egput.status === 200 || egput.status === 201, `HTTP ${egput.status}`);
  await page.goto(UI + "#/eventgrid/topics");
  await page.getByRole("link", { name: EGT2, exact: true }).waitFor({ timeout: 10000 });
  check("wire-created topic shown in browse grid", true);
  await shot("21-eventgrid-topics");

  // ── Delete through the topic overview → gone over ARM ──────────────────────────────────
  await page.goto(UI + `#/eventgrid/topics/${RG}/${EGT}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(EGT);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
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

  // ── Lock created in the UI, scoped to the resource group itself → visible over ARM ──────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(RGLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByText(RGLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const rgLockGet = await arm("GET", `/resourceGroups/${RGUI}/providers/Microsoft.Authorization/locks/${RGLOCK}`);
  check("UI add resource-group-scoped lock → visible over native ARM", rgLockGet.status === 200, `HTTP ${rgLockGet.status}`);

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
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText("smoke-api", { exact: true }).waitFor({ timeout: 10000 });
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
  await page.getByText(APIMLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const apimLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ApiManagement/service/${APIM}/providers/Microsoft.Authorization/locks/${APIMLOCK}?api-version=2020-05-01`);
  check("UI create lock → visible over native ARM (extension resource)", apimLockGet.status === 200, `HTTP ${apimLockGet.status}`);
  await shot("28-apim-locks");

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
  await page.getByRole("button", { name: "Send messages", exact: true }).click();
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
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
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
  check("Run command executes the real (honestly simulated) round-trip", runOut.includes("Vyomi does not run a real kubelet"), runOut.slice(0, 80));
  await shot("27-aks-run-command");

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

  // ── Lock created in the UI → visible over the native ARM wire ─────────────────────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const AKSLOCK = `smoke-akslock-${n}`;
  await page.getByLabel("Lock name", { exact: true }).fill(AKSLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
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
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByText(ALERT, { exact: true }).waitFor({ state: "detached", timeout: 10000 });
  const alertGone = await armMonitor("GET", `/resourceGroups/${MON_RG}/providers/Microsoft.Insights/metricAlerts/${ALERT}`);
  check("UI delete alert rule → ARM GET 404", alertGone.status === 404, `HTTP ${alertGone.status}`);
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
  await page.getByText(SQLLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const sqlLockGet = await wire(`/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/databases/${DB}/providers/Microsoft.Authorization/locks/${SQLLOCK}?api-version=2020-05-01`);
  check("UI create lock on SQL database → visible over native ARM", sqlLockGet.status === 200, `HTTP ${sqlLockGet.status}`);
  await shot("28-sql-locks");

  // ── Database deleted through the overview → gone over ARM ──────────────────────────────
  await page.goto(UI + `#/sql/${RG}/${SRV}/${DB}`);
  await page.getByRole("toolbar", { name: "Overview commands" }).getByRole("button", { name: "Delete" }).click();
  await page.getByLabel("Confirm deletion").fill(DB);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
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

  // ── Lock created on the NSG through the UI → visible over the native ARM wire ──────────
  await openPanel("Locks");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Lock name", { exact: true }).fill(NSGLOCK);
  await page.getByRole("dialog").getByRole("button", { name: "OK" }).click();
  await page.getByText(NSGLOCK, { exact: true }).waitFor({ timeout: 10000 });
  const nsgLockGet = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG}/providers/Microsoft.Authorization/locks/${NSGLOCK}`);
  check("UI create lock on NSG → visible over native ARM", nsgLockGet.status === 200, `HTTP ${nsgLockGet.status}`);
  await shot("26-nsg-locks");

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
  await page.getByRole("link", { name: NSG2, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  let nsgGone = { status: 0 };
  for (let i = 0; i < 20 && nsgGone.status !== 404; i++) {
    nsgGone = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${NSG2}`);
    if (nsgGone.status !== 404) await page.waitForTimeout(500);
  }
  check("UI delete NSG → ARM GET 404", nsgGone.status === 404, `HTTP ${nsgGone.status}`);

  // ── Subscriptions: the one simulated subscription, renamed through the UI → visible over ARM ──
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

  // ── Create a subscription (renames the one simulated subscription, the honest Vyomi gap) ──
  await page.goto(UI + "#/subscriptions/create");
  await page.getByLabel("Subscription name", { exact: true }).fill(`${SUBNAME}-2`);
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByText("Validation passed").waitFor({ timeout: 5000 });
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: `${SUBNAME}-2`, exact: true }).waitFor({ timeout: 10000 });
  const subscriptionGot2 = await arm("GET", "");
  check("UI create-subscription wizard → renames the one simulated subscription over ARM", JSON.parse(subscriptionGot2.text).displayName === `${SUBNAME}-2`, subscriptionGot2.text);
} catch (e) {
  check("smoke run", false, e.message.split("\n")[0]);
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
