/* Smoke: App Service operations panels (WebJobs, Service Connector, Certificates, Quotas,
 * Default documents, Health check, Clone, Autoscale, ...) driven through the UI and verified over
 * the native ARM wire.   BASE=http://127.0.0.1:9160 UI_PATH=/v4/azure/ node consoles/tests/smoke-azure-appops.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9160";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `appops-rg-${n}`, APP = `appops${n}`, STG = `appopsstg${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;  // wire calls run INSIDE the page (same origin) so Nano's service worker answers them
const arm = (m, path, body, v = "2023-12-01") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const site = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}`;
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${STG}`, { location: "eastus", sku: { name: "Standard_LRS" }, kind: "StorageV2" }, "2023-01-01");
ok("create app over wire", [200, 201].includes((await arm("PUT", site, { location: "eastus", properties: { siteConfig: {} } })).status));
const go = async (panel) => { await pg.goto(`${UI}#/appservices/${RG}/${APP}/${panel}`); await pg.waitForTimeout(1200); };
const NS = async () => await pg.locator("[data-vyomi-not-simulated]").count();

await go("webjobs");
await pg.getByLabel("WebJob name").fill("job1");
await pg.getByLabel("WebJob script").fill("print('ran', 6*7)");
await pg.getByRole("button", { name: "Add", exact: true }).click(); await pg.waitForTimeout(800);
await pg.getByRole("button", { name: "Run job1" }).click(); await pg.waitForTimeout(800);
await pg.getByRole("button", { name: "Logs job1" }).click(); await pg.waitForTimeout(800);
ok("webjob output shown in UI", (await pg.content()).includes("ran 42"));
ok("webjob over wire", (await arm("GET", `${site}/triggeredwebjobs/job1/history`)).body.value[0].properties.output === "ran 42");
ok("webjobs not a not-simulated panel", (await NS()) === 0);

await go("serviceconnector");
await pg.getByLabel("Connection name").fill("tostg");
await pg.getByLabel("Target service").selectOption({ label: `${STG} (storageAccounts)` }); 
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1000);
const st = (await arm("GET", `${site}/config/appsettings`)).body.properties;
ok("service connector wrote app settings", st.AZURE_STORAGEBLOB_RESOURCEENDPOINT === `https://${STG}.blob.core.windows.net`, JSON.stringify(st));

await go("certificates");
await pg.getByLabel("Managed certificate domain").fill("www.example.com");
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1000);
ok("certificate listed", (await pg.content()).includes("www.example.com"));
ok("certificate over wire", (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/certificates`)).body.value.length === 1);

await go("quotas"); ok("quotas shows file system storage", (await pg.content()).includes("File System Storage"));

await go("configuration");
await pg.getByRole("tab", { name: "Default documents" }).click();
await pg.getByLabel("Default document 1").fill("home.html");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("default documents persisted", (await arm("GET", `${site}/config/web`)).body.properties.defaultDocuments[0] === "home.html");
await pg.getByRole("tab", { name: "Path mappings" }).click(); ok("path mappings panel real", (await NS()) === 0);
await pg.getByRole("tab", { name: "Error pages (preview)" }).click(); await pg.getByLabel("404 error page").fill("<h1>nope</h1>");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("error page persisted", (await arm("GET", `${site}/config/web`)).body.properties.errorPages?.["404"] === "<h1>nope</h1>");

await go("healthcheck"); await pg.getByLabel("Enable health check").check(); await pg.getByLabel("Health check path").fill("/healthz");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("health check path persisted", (await arm("GET", `${site}/config/web`)).body.properties.healthCheckPath === "/healthz");

await go("apidefinition"); await pg.getByLabel("API definition location").fill("https://x.test/swagger.json");
await pg.getByRole("button", { name: "Save" }).click(); await pg.waitForTimeout(800);
ok("api definition persisted", (await arm("GET", `${site}/config/web`)).body.properties.apiDefinition?.url === "https://x.test/swagger.json");

await go("authentication"); await pg.getByLabel("App Service authentication").click(); await pg.waitForTimeout(1000);
ok("auth enabled over wire", (await arm("GET", `${site}/config/authsettingsV2`)).body.properties.platform.enabled === true);

await go("scaleout"); await pg.getByLabel("Autoscale maximum").fill("5"); await pg.getByRole("button", { name: "Save autoscale" }).click(); await pg.waitForTimeout(1000);
const as = (await arm("GET", `/providers/Microsoft.Insights/autoscalesettings`, null, "2022-10-01")).body.value || [];
ok("autoscale setting stored", as.some((s) => s.properties.profiles[0].capacity.maximum === "5"), JSON.stringify(as).slice(0, 200));

await go("appserviceplan"); ok("plan page shows plan", (await pg.content()).includes("Pricing plan"));
await go("cloneapp"); await pg.getByRole("button", { name: "Clone", exact: true }).click(); await pg.waitForTimeout(2000);
ok("clone created over wire", (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}-clone`)).status === 200);
const c = (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${APP}-clone/config/appsettings`)).body.properties;
ok("clone copied app settings", !!c.AZURE_STORAGEBLOB_RESOURCEENDPOINT);
// ── Function App: Service Connector, Integration editor, Invocations ──
const FN = `appopsfn${n}`, fsite = `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${FN}`;
await arm("PUT", fsite, { location: "eastus", kind: "functionapp", properties: {} });
await arm("PUT", `${fsite}/functions/f1`, { properties: { files: { "__init__.py": "def main(req):\n    return {'ok': 1}" } } });
await arm("POST", `${fsite}/functions/f1/invoke`, { method: "GET" });
await pg.goto(`${UI}#/functionapp/${RG}/${FN}/functions/f1`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "Invocations" }).click(); await pg.waitForTimeout(800);
ok("invocations tab lists the real run", (await pg.locator("table[aria-label=Invocations] tbody tr").count()) >= 1 && (await pg.content()).includes("Success"));
await pg.getByRole("tab", { name: "Integration" }).click(); await pg.waitForTimeout(500);
await pg.getByRole("button", { name: "Add output binding" }).click();
await pg.getByRole("button", { name: "Save", exact: true }).last().click(); await pg.waitForTimeout(1000);
ok("bindings persisted over wire", ((await arm("GET", `${fsite}/functions/f1`)).body.properties.config.bindings || []).length >= 3);
await pg.goto(`${UI}#/functionapp/${RG}/${FN}/service-connector`); await pg.waitForTimeout(1200);
await pg.getByLabel("Connection name").fill("tostg"); await pg.getByLabel("Target service").selectOption({ label: `${STG} (storageAccounts)` });
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1000);
ok("function service connector wrote app settings", !!(await arm("GET", `${fsite}/config/appsettings`)).body.properties.AZURE_STORAGEBLOB_RESOURCEENDPOINT);
for (const p of ["apimanagement", "webjobs", "certificates", "serviceconnector", "healthcheck", "authentication"]) { await go(p); }
// ── VNet: subnet service endpoints + delegation in the Add-subnet dialog ──
const VN = `appopsvnet${n}`;
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VN}`, { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.5.0.0/16"] } } }, "2023-11-01");
await pg.goto(`${UI}#/vnets/${RG}/${VN}/subnets`); await pg.waitForTimeout(1500);
await pg.getByRole("button", { name: "Subnet", exact: true }).click(); await pg.waitForTimeout(500);
await pg.getByLabel("Name", { exact: true }).fill("sn1"); await pg.getByLabel("Starting address").fill("10.5.1.0");
await pg.getByLabel("Microsoft.Storage").check(); await pg.getByLabel("Delegate subnet to a service").selectOption("Microsoft.Web/serverFarms");
await pg.getByRole("button", { name: "Add", exact: true }).click(); await pg.waitForTimeout(1200);
const sp = (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${VN}/subnets/sn1`, null, "2023-11-01")).body?.properties || {};
ok("subnet carries the service endpoint + delegation", sp.serviceEndpoints?.[0]?.service === "Microsoft.Storage" && sp.delegations?.[0]?.properties?.serviceName === "Microsoft.Web/serverFarms", JSON.stringify(sp));
// ── Key Vault: key activation/expiration/tags + certificate policy in the create dialogs ──
const KVN = `appopskv${n}`;
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${KVN}`, { location: "eastus", properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" }, accessPolicies: [] } }, "2023-07-01");
const kvData = (m, path, body) => pg.evaluate(async ([m, url, body, vault]) => { const r = await fetch(url, { method: m, headers: { "content-type": "application/json", "x-vyomi-vault": vault }, body: body ? JSON.stringify(body) : undefined }); const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null }; }, [m, `${WIRE}${path}${path.includes("?") ? "&" : "?"}api-version=7.4`, body, KVN]);
await pg.goto(`${UI}#/keyvaults/${RG}/${KVN}/keys`); await pg.waitForTimeout(1500);
await pg.getByRole("button", { name: "Generate/Import" }).click(); await pg.waitForTimeout(500);
await pg.getByLabel("Name", { exact: true }).fill("expiredkey"); await pg.getByLabel("Expiration date").fill("2020-01-01T00:00"); await pg.getByLabel("Key tags").fill("env=dev, team=x");
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1200);
const kb = (await kvData("GET", "/keys/expiredkey")).body || {};
ok("key stored with expiration + tags", kb.attributes?.exp === 1577836800 && kb.tags?.team === "x", JSON.stringify(kb).slice(0, 300));
ok("crypto on the expired key is refused (403)", (await kvData("POST", "/keys/expiredkey/encrypt", { alg: "RSA-OAEP", value: "aGk" })).status === 403);
await pg.goto(`${UI}#/keyvaults/${RG}/${KVN}/certificates`); await pg.waitForTimeout(1500);
await pg.getByRole("button", { name: "Generate/Import" }).click(); await pg.waitForTimeout(500);
await pg.getByLabel("Certificate Name").fill("polcert"); await pg.getByRole("radio", { name: "PEM" }).check(); await pg.getByLabel("Key size").selectOption("3072");
await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(1500);
const cp = (await kvData("GET", "/certificates/polcert/policy")).body || {};
ok("certificate policy stored (content type, key size, lifetime action)", cp.secret_properties?.content_type === "application/x-pem-file" && cp.key_properties?.key_size === 3072 && cp.lifetime_actions?.[0]?.action?.action_type === "AutoRenew", JSON.stringify(cp).slice(0, 300));
// ── App Configuration: import a JSON file, export to another store ──
const ACA = `appopscfga${n}`, ACB = `appopscfgb${n}`;
for (const nm of [ACA, ACB]) await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.AppConfiguration/configurationStores/${nm}`, { location: "eastus", sku: { name: "standard" } }, "2024-05-01");
const acData = (store, m, path, body) => pg.evaluate(async ([m, url, body, st]) => { const r = await fetch(url, { method: m, headers: { "content-type": "application/json", "x-vyomi-store": st }, body: body ? JSON.stringify(body) : undefined }); const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null }; }, [m, `${WIRE}${path}${path.includes("?") ? "&" : "?"}api-version=2023-11-01`, body, store]);
await pg.goto(`${UI}#/appconfiguration/${RG}/${ACA}/importexport`); await pg.waitForTimeout(1500);
await pg.getByLabel("File", { exact: true }).setInputFiles({ name: "cfg.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({ app: { name: "demo", db: { host: "h1" } }, flag: "on" })) });
await pg.getByLabel("Prefix").fill("p:"); await pg.getByRole("button", { name: "Apply" }).click(); await pg.waitForTimeout(1500);
const kvs = Object.fromEntries(((await acData(ACA, "GET", "/kv")).body?.items || []).map((i) => [i.key, i.value]));
ok("JSON import flattened with separator + prefix", kvs["p:app.name"] === "demo" && kvs["p:app.db.host"] === "h1" && kvs["p:flag"] === "on", JSON.stringify(kvs));
await pg.getByRole("radio", { name: "Export" }).check(); await pg.getByLabel("Service", { exact: true }).selectOption("store"); await pg.getByLabel("Configuration store").selectOption(ACB);
await pg.getByRole("button", { name: "Export", exact: true }).click(); await pg.waitForTimeout(1500);
const kvb = Object.fromEntries(((await acData(ACB, "GET", "/kv")).body?.items || []).map((i) => [i.key, i.value]));
ok("export copied key-values to the other store", kvb["p:app.name"] === "demo", JSON.stringify(kvb));
// ── ACR: Import image copies manifest + blobs ──
const ACRN = `appopsacr${n}`;
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACRN}`, { location: "eastus", sku: { name: "Basic" } }, "2023-07-01");
const acrCall = (m, path, body, ct) => pg.evaluate(async ([m, url, body, ct, reg]) => { const r = await fetch(url, { method: m, headers: { "x-vyomi-registry": reg, ...(ct ? { "content-type": ct } : {}) }, body: body ?? undefined }); const t = await r.text(); return { status: r.status, text: t }; }, [m, `${WIRE}${path}`, body, ct, ACRN]);
const sha = async (str) => { const b = new TextEncoder().encode(str); const h = await crypto.subtle.digest("SHA-256", b); return "sha256:" + [...new Uint8Array(h)].map((x) => x.toString(16).padStart(2, "0")).join(""); };
const cfgD = "sha256:" + (await import("node:crypto")).createHash("sha256").update("{}").digest("hex");
await acrCall("POST", `/v2/imp-src/blobs/uploads/?digest=${cfgD}`, "{}", "application/octet-stream");
await acrCall("PUT", `/v2/imp-src/manifests/v1`, JSON.stringify({ schemaVersion: 2, config: { digest: cfgD }, layers: [] }), "application/vnd.docker.distribution.manifest.v2+json");
await pg.goto(`${UI}#/acr/${RG}/${ACRN}`); await pg.waitForTimeout(1500);
await pg.getByRole("button", { name: "Import image" }).click(); await pg.waitForTimeout(400);
await pg.getByLabel("Source image").fill("imp-src:v1"); await pg.getByLabel("Target tags").fill("imp-dst/app:prod");
await pg.getByRole("button", { name: "Import", exact: true }).click(); await pg.waitForTimeout(1200);
ok("ACR import created the target tag", (await acrCall("GET", `/v2/imp-dst/app/tags/list`)).text.includes("prod"));
// ── Entra: user sign-ins (non-interactive) via the real ROPC grant ──
const UPN = `appopsuser${n}@vyomilearn.onmicrosoft.com`;
await pg.evaluate(async ([w, upn]) => fetch(`${w}/v1.0/users`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ displayName: "Appops User", userPrincipalName: upn, passwordProfile: { password: "Vy0mi!pass12", forceChangePasswordNextSignIn: false } }) }), [WIRE, UPN]);
await pg.goto(`${UI}#/entra/signinlogs`); await pg.waitForTimeout(1500);
await pg.getByRole("tab", { name: "User sign-ins (non-interactive)" }).click();
await pg.getByLabel("Test sign-in user").fill(UPN); await pg.getByLabel("Test sign-in password").fill("wrong");
await pg.getByRole("button", { name: "Test sign-in" }).click(); await pg.waitForTimeout(800);
await pg.getByLabel("Test sign-in password").fill("Vy0mi!pass12"); await pg.getByRole("button", { name: "Test sign-in" }).click(); await pg.waitForTimeout(1000);
const txt = await pg.locator("table").innerText();
ok("non-interactive sign-ins show one failure and one success", txt.includes("Failure") && txt.includes("Success") && txt.includes("50126"), txt.slice(0, 300));
await b.close(); console.log(`${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
