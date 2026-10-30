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
