/* Smoke for AZ-02..05 config pages: AKS (KEDA, authorized IPs, extensions), Cosmos (CORS, dedicated gateway, CMK),
 * Service Bus (encryption, networking, events), App Configuration (encryption).
 *   BASE=http://127.0.0.1:9049 node consoles/tests/smoke-azure-cfgext.mjs
 *   BASE=... NANO=1 UI_PATH=/nano/v4/azure/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-azure-cfgext.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9049";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vycx-rg${n}`;
let page; let fails = 0;
const check = (name, ok, d = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + d : ""}`); };
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2024-05-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
const noNS = async (label) => { const left = await page.locator("[data-vyomi-not-simulated]").count(); check(`${label}: no Not-simulated panel`, left === 0); };
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
  const P = (ns, t, name) => `/resourceGroups/${RG}/providers/Microsoft.${ns}/${t}/${name}`;

  // ── AKS
  const K = `cxaks${n}`;
  await arm("PUT", P("ContainerService", "managedClusters", K), { location: "eastus", properties: { kubernetesVersion: "1.29.2", dnsPrefix: K } }, "2024-09-02-preview");
  await page.goto(UI + `#/aks/${RG}/${K}/applicationscaling`);
  await page.getByRole("button", { name: "Enable KEDA" }).click();
  await page.getByText("Enabled", { exact: true }).first().waitFor({ timeout: 10000 });
  check("KEDA enabled in UI and over ARM", json(await arm("GET", P("ContainerService", "managedClusters", K), null, "2024-09-02-preview")).properties?.workloadAutoScalerProfile?.keda?.enabled === true);
  await noNS("AKS application scaling");
  await page.goto(UI + `#/aks/${RG}/${K}/networking`);
  await page.getByRole("textbox", { name: "Authorized IP ranges" }).fill("not-a-cidr");
  await page.getByRole("button", { name: "Save authorized IP ranges" }).click();
  await page.getByText("not a valid CIDR").first().waitFor({ timeout: 10000 }).then(() => check("bad authorized range rejected in UI", true), () => check("bad authorized range rejected in UI", false));
  await page.getByRole("textbox", { name: "Authorized IP ranges" }).fill("203.0.113.0/24");
  await page.getByRole("button", { name: "Save authorized IP ranges" }).click();
  await page.waitForTimeout(800);
  check("authorized ranges stored", JSON.stringify(json(await arm("GET", P("ContainerService", "managedClusters", K), null, "2024-09-02-preview")).properties?.apiServerAccessProfile?.authorizedIPRanges) === '["203.0.113.0/24"]');
  await noNS("AKS networking");
  await page.goto(UI + `#/aks/${RG}/${K}/extensionsapplications`);
  await page.getByLabel("Extension name").fill("dapr");
  await page.getByRole("button", { name: "Install extension" }).click();
  await page.locator("tr", { hasText: "microsoft.dapr" }).waitFor({ timeout: 10000 });
  check("extension installed", true);
  await page.getByLabel("Extension name").fill("dapr2");
  await page.getByRole("button", { name: "Install extension" }).click();
  await page.getByText("already installed").first().waitFor({ timeout: 10000 }).then(() => check("duplicate extension rejected", true), () => check("duplicate extension rejected", false));
  await page.getByRole("button", { name: "Uninstall dapr" }).click();
  await page.getByText("No extensions installed.").waitFor({ timeout: 10000 }).then(() => check("extension uninstalled", true), () => check("extension uninstalled", false));
  await noNS("AKS extensions");

  // ── Key Vault for CMKs
  const KV = `cxkv${n}`;
  await arm("PUT", P("KeyVault", "vaults", KV), { location: "eastus", properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } }, "2023-07-01");
  await wire("/keys/k1/create?api-version=7.4", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ kty: "RSA", key_size: 2048 }) });   // Nano binds the CMK check to the Key Vault keys store: the key must exist

  // ── Cosmos
  const C = `cxcosmos${n}`;
  await arm("PUT", P("DocumentDB", "databaseAccounts", C), { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "East US", failoverPriority: 0 }] } }, "2024-05-15");
  await page.goto(UI + `#/cosmos/${RG}/${C}/cors`);
  await page.getByRole("button", { name: "Add CORS rule" }).click();
  await page.getByLabel("Allowed origins 1").fill("ftp://bad");
  await page.getByRole("button", { name: "Save CORS rules" }).click();
  await page.getByText("not a valid origin").first().waitFor({ timeout: 10000 }).then(() => check("bad CORS origin rejected", true), () => check("bad CORS origin rejected", false));
  await page.getByLabel("Allowed origins 1").fill("https://app.example.com");
  await page.getByRole("button", { name: "Save CORS rules" }).click();
  await page.waitForTimeout(800);
  check("CORS stored", json(await arm("GET", P("DocumentDB", "databaseAccounts", C), null, "2024-05-15")).properties?.cors?.[0]?.allowedOrigins === "https://app.example.com");
  await noNS("Cosmos CORS");
  await page.goto(UI + `#/cosmos/${RG}/${C}/dedicatedgateway`);
  await page.getByRole("button", { name: "Provision dedicated gateway" }).click();
  await page.getByText("Cosmos.D4s").first().waitFor({ timeout: 10000 }).then(() => check("dedicated gateway provisioned", true), () => check("dedicated gateway provisioned", false));
  await noNS("Cosmos dedicated gateway");
  await page.goto(UI + `#/cosmos/${RG}/${C}/dataencryption`);
  await page.getByLabel("Key Vault key URI").fill("https://nonesuch.vault.azure.net/keys/k");
  await page.getByRole("button", { name: "Save encryption key" }).click();
  await page.getByText("does not exist").first().waitFor({ timeout: 10000 }).then(() => check("CMK with missing vault rejected", true), () => check("CMK with missing vault rejected", false));
  await page.getByLabel("Key Vault key URI").fill(`https://${KV}.vault.azure.net/keys/k1`);
  await page.getByRole("button", { name: "Save encryption key" }).click();
  await page.waitForTimeout(1000);
  check("Cosmos CMK stored", (json(await arm("GET", P("DocumentDB", "databaseAccounts", C), null, "2024-05-15")).properties?.keyVaultKeyUri || "").includes(KV));
  await noNS("Cosmos data encryption");

  // ── Cosmos hierarchical partition key via the Data Explorer create dialog
  await page.goto(UI + `#/cosmos/${RG}/${C}/dataexplorer`);
  await page.getByRole("button", { name: /New Container/i }).first().click();
  await page.getByLabel("Database id", { exact: true }).fill(`hdb${n}`);
  await page.getByLabel("Container id").fill("hc");
  await page.getByLabel("Partition key", { exact: true }).fill("/tenant");
  await page.getByRole("button", { name: "Add hierarchical partition key" }).click();
  await page.getByRole("textbox", { name: "Partition key level 2" }).fill("/user");
  await page.getByRole("button", { name: "OK", exact: true }).click();
  await page.waitForTimeout(1500);
  const hc = await wire(`/dbs/hdb${n}/colls/hc`);
  check("hierarchical container created", JSON.parse(hc.text || "{}").partitionKey?.kind === "MultiHash", hc.text.slice(0, 120));

  // ── Service Bus
  const S = `cxsb${n}`;
  await arm("PUT", P("ServiceBus", "namespaces", S), { location: "eastus", sku: { name: "Standard", tier: "Standard" } }, "2022-10-01-preview");
  await page.goto(UI + `#/servicebus/${RG}/${S}/networking`);
  await page.getByText("only available on Premium").first().waitFor({ timeout: 10000 }).then(() => check("Standard namespace shows Premium-only networking", true), () => check("Standard namespace shows Premium-only networking", false));
  await arm("PUT", P("ServiceBus", "namespaces", S), { location: "eastus", sku: { name: "Premium", tier: "Premium", capacity: 1 } }, "2022-10-01-preview");
  await page.reload();
  await page.getByLabel("IP address or CIDR").fill("203.0.113.0/24");
  await page.getByRole("button", { name: "Add IP rule" }).click();
  await page.locator("tr", { hasText: "203.0.113.0/24" }).waitFor({ timeout: 10000 }).then(() => check("SB IP rule added", true), () => check("SB IP rule added", false));
  await noNS("SB networking");
  await page.goto(UI + `#/servicebus/${RG}/${S}/encryption`);
  await page.getByLabel("Key vault URI").fill(`https://${KV}.vault.azure.net`);
  await page.getByLabel("Key name").fill("k1");
  await page.getByRole("button", { name: "Save encryption" }).click();
  await page.waitForTimeout(1000);
  check("SB CMK stored", json(await arm("GET", P("ServiceBus", "namespaces", S), null, "2022-10-01-preview")).properties?.encryption?.keyVaultProperties?.[0]?.keyName === "k1");
  await noNS("SB encryption");
  await page.goto(UI + `#/servicebus/${RG}/${S}/events`);
  await page.getByRole("button", { name: "Add event subscription" }).waitFor({ timeout: 10000 }).then(() => check("SB events page", true), () => check("SB events page", false));
  await noNS("SB events");

  // ── API Management: gateway association in the create flow, soft-delete restore
  const M = `cxapim${n}`;
  await arm("PUT", P("ApiManagement", "service", M), { location: "eastus", sku: { name: "Developer", capacity: 1 }, properties: { publisherEmail: "a@b.co", publisherName: "x" } }, "2022-08-01");
  await arm("PUT", P("ApiManagement", "service", M) + "/gateways/gw1", { properties: { locationData: { name: "dc1" } } }, "2022-08-01");
  await arm("PUT", P("ApiManagement", "service", M) + "/apis/echo", { properties: { displayName: "Echo", path: "echo", protocols: ["https"], serviceUrl: "https://example.com" } }, "2022-08-01");
  await arm("PUT", P("ApiManagement", "service", M) + "/gateways/gw1/apis/echo", { properties: {} }, "2022-08-01");
  await page.goto(UI + `#/apim/${RG}/${M}/selfhostedgateways`);
  await page.locator("tr", { hasText: "gw1" }).getByText("echo").waitFor({ timeout: 10000 }).then(() => check("gateway lists its APIs", true), () => check("gateway lists its APIs", false));
  await page.goto(UI + `#/apim/${RG}/${M}/apis/create/http`);
  await page.getByLabel("Gateway gw1").waitFor({ timeout: 10000 }).then(() => check("create-API wizard offers gateways", true), () => check("create-API wizard offers gateways", false));
  await noNS("APIM create API gateways");
  await arm("DELETE", P("ApiManagement", "service", M), null, "2022-08-01");
  await page.goto(UI + `#/apim`);
  await page.getByRole("button", { name: "Manage deleted services" }).click();
  await page.locator("tr", { hasText: M }).waitFor({ timeout: 10000 }).then(() => check("deleted service listed", true), () => check("deleted service listed", false));
  await page.getByRole("button", { name: `Restore ${M}` }).click();
  await page.waitForTimeout(1500);
  check("APIM restored with its API", json(await arm("GET", P("ApiManagement", "service", M) + "/apis/echo", null, "2022-08-01")).name === "echo");

  // ── SQL Data Discovery & Classification
  const SS = `cxsql${n}`;
  await arm("PUT", P("Sql", "servers", SS), { location: "eastus", properties: { administratorLogin: "sqladmin", administratorLoginPassword: "Pass1234!xyz" } }, "2023-08-01");
  await arm("PUT", P("Sql", "servers", SS) + "/databases/db1", { location: "eastus" }, "2023-08-01");
  await wire(`/azure-sql/servers/${SS}`, { method: "PUT", headers: { "content-type": "application/json" }, body: "{}" });
  await wire(`/azure-sql/servers/${SS}/databases/db1`, { method: "PUT", headers: { "content-type": "application/json" }, body: "{}" });
  await wire(`/azure-sql/servers/${SS}/databases/db1/query`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sql: "CREATE TABLE Customer (CustomerID INTEGER, EmailAddress TEXT, Notes TEXT)" }) });
  await page.goto(UI + `#/sql/${RG}/${SS}/db1/datadiscovery`);
  await page.locator("tr", { hasText: "EmailAddress" }).waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: "Accept all recommendations" }).click();
  await page.locator("tr", { hasText: "EmailAddress" }).getByText("Medium").waitFor({ timeout: 10000 }).then(() => check("recommended classification applied", true), () => check("recommended classification applied", false));
  check("label is an ARM child", json(await arm("GET", P("Sql", "servers", SS) + "/databases/db1/schemas/dbo/tables/Customer/columns/EmailAddress/sensitivityLabels/current", null, "2020-11-01-preview")).properties?.informationType === "Contact Info");
  await noNS("SQL data discovery");

  // ── Storage networking exceptions
  const SA = `cxsa${n}`;
  await arm("PUT", P("Storage", "storageAccounts", SA), { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } }, "2023-01-01");
  await page.goto(UI + `#/storage/${RG}/${SA}/networking`);
  await page.getByRole("button", { name: /Exceptions|Firewalls/ }).first().click().catch(() => {});
  const ex = page.getByLabel("Allow read access to storage logging from any network");
  if (await ex.count() === 0) { await page.getByRole("tab", { name: /Exceptions|Firewalls and virtual networks/ }).first().click().catch(() => {}); }
  await ex.waitFor({ timeout: 10000 }).then(() => ex.check()).catch(() => {});
  await page.waitForTimeout(1200);
  check("storage bypass stored", /Logging/.test(json(await arm("GET", P("Storage", "storageAccounts", SA), null, "2023-01-01")).properties?.networkAcls?.bypass || ""));

  // ── Storage encryption scopes + container scope / version-level immutability
  const ESA = `cxenc${n}`;
  await arm("PUT", P("Storage", "storageAccounts", ESA), { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { immutableStorageWithVersioning: { enabled: true } } }, "2023-05-01");
  await page.goto(UI + `#/storage/${RG}/${ESA}/encryption`);
  await page.getByLabel("Encryption scope name").fill("scopea");
  await page.getByRole("button", { name: "Create encryption scope" }).click();
  await page.locator("tr", { hasText: "scopea" }).waitFor({ timeout: 10000 }).then(() => check("encryption scope listed", true), () => check("encryption scope listed", false));
  check("scope is an ARM child", json(await arm("GET", P("Storage", "storageAccounts", ESA) + "/encryptionScopes/scopea", null, "2023-05-01")).properties?.state === "Enabled");
  await noNS("storage encryption");
  await page.goto(UI + `#/storage/${RG}/${ESA}/containers`);
  await page.getByRole("toolbar", { name: "Command bar" }).getByRole("button", { name: "Create" }).click();
  await page.getByLabel("Container name").fill("wormc");
  await page.getByLabel("Default encryption scope").selectOption("scopea");
  await page.getByLabel("Enable version-level immutability support for this container").check();
  await page.getByRole("dialog", { name: "New container" }).getByRole("button", { name: "Create", exact: true }).click();
  await page.locator("tr", { hasText: "wormc" }).waitFor({ timeout: 15000 });
  const cprops = json(await arm("GET", P("Storage", "storageAccounts", ESA) + "/blobServices/default/containers/wormc", null, "2023-05-01")).properties || {};
  check("container carries scope and WORM over ARM", cprops.defaultEncryptionScope === "scopea" && cprops.immutableStorageWithVersioning?.enabled === true);
  const hp = await wire(`/${ESA}/wormc?restype=container`, { method: "GET", headers: { "x-ms-version": "2021-12-02", authorization: `SharedKey ${ESA}:x` } });
  check("data plane container is created", hp.status === 200);

  // ── VM application security groups
  const VM = `cxvm${n}`;
  await arm("PUT", P("Network", "applicationSecurityGroups", `web${n}`), { location: "eastus" }, "2023-11-01");
  await arm("PUT", P("Network", "networkInterfaces", VM + "-nic"), { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: {} }] } }, "2023-11-01");
  await arm("PUT", P("Compute", "virtualMachines", VM), { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, networkProfile: { networkInterfaces: [{ id: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${VM}-nic` }] } } }, "2023-09-01");
  await page.goto(UI + `#/vms/${RG}/${VM}/asgs`);
  await page.getByLabel(`Member of web${n}`, { exact: true }).click();
  await page.waitForTimeout(1200);
  check("NIC joined the ASG over ARM", JSON.stringify(json(await arm("GET", P("Network", "networkInterfaces", VM + "-nic"), null, "2023-11-01")).properties?.ipConfigurations?.[0]?.properties?.applicationSecurityGroups || []).includes(`applicationSecurityGroups/web${n}`));
  check("in-use ASG delete refused", (await arm("DELETE", P("Network", "applicationSecurityGroups", `web${n}`), null, "2023-11-01")).status === 400);
  await noNS("VM application security groups");

  // ── App Configuration
  const A = `cxappcfg${n}`;
  await arm("PUT", P("AppConfiguration", "configurationStores", A), { location: "eastus", sku: { name: "standard" } }, "2024-05-01");
  await page.goto(UI + `#/appconfiguration/${RG}/${A}/encryption`);
  await page.getByLabel("Key identifier").fill(`https://${KV}.vault.azure.net/keys/k1`);
  await page.getByRole("button", { name: "Save encryption key" }).click();
  await page.waitForTimeout(1000);
  check("AppConfig CMK stored", (json(await arm("GET", P("AppConfiguration", "configurationStores", A), null, "2024-05-01")).properties?.encryption?.keyVaultProperties?.keyIdentifier || "").includes(KV));
  await noNS("AppConfig encryption");
  check("no page errors", errors.length === 0, errors.join(" | ").slice(0, 200));
} catch (e) { fails++; console.log("FAIL harness", e.message); }
await browser.close();
process.exit(fails ? 1 : 0);
