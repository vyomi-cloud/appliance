/* Smoke for the AZ-02 / AZ-03 sweep (policy, identity, CMK, Event Grid subscriptions, storage
 * data protection, SQL/Cosmos ops). Drives the UI and cross-checks over the native ARM wire.
 *   BASE=http://127.0.0.1:9150 node consoles/tests/smoke-azure-azid.mjs
 *   BASE=http://127.0.0.1:8850 NANO=1 UI_PATH=/nano/v4/azure/ WIRE_PATH=/nano/_wire node consoles/tests/smoke-azure-azid.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9150";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-azid";
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vyazid-rg${n}`;
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
const noNS = async (label, allow = []) => {
  const left = (await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated") || ""))).filter((t) => !allow.some((a) => t.includes(a)));
  check(`${label}: no unexpected Not-simulated panel`, left.length === 0, left.join(" | ").slice(0, 160));
};

try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" });

  // ── Azure Policy (resource group Policies blade) ────────────────────────────────────────
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/vyaz${n}a`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { supportsHttpsTrafficOnly: false } });
  await page.goto(UI + `#/resourcegroups/${RG}/policies`);
  await page.getByRole("tab", { name: "Assignments" }).click();
  await page.getByRole("button", { name: "Assign policy" }).click();
  await page.getByLabel("Policy definition").selectOption({ label: "Secure transfer to storage accounts should be enabled" });
  await page.getByLabel("Assignment name").fill(`sec${n}`);
  await page.getByRole("button", { name: "Assign", exact: true }).click();
  await page.getByRole("tab", { name: "Compliance" }).click();
  await page.getByText("non-compliant", { exact: false }).waitFor({ timeout: 10000 });
  check("RG policy compliance flags http-only storage NonCompliant", (await page.locator("tr", { hasText: `vyaz${n}a` }).innerText()).includes("NonCompliant"));
  const asg = json(await armv("2022-06-01")("GET", `/resourceGroups/${RG}/providers/Microsoft.Authorization/policyAssignments`));
  check("assignment visible over native ARM", (asg.value || []).some((x) => x.name === `sec${n}`));
  await shot("policy-rg");
  await noNS("RG policies");
  // Deny via custom definition authored in the UI
  await page.getByRole("tab", { name: "Definitions" }).click();
  await page.getByRole("button", { name: "New policy definition" }).click();
  await page.getByLabel("Definition name").fill(`denyuntagged${n}`);
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("tab", { name: "Assignments" }).click();
  await page.getByRole("button", { name: "Assign policy" }).click();
  await page.getByLabel("Policy definition").selectOption({ label: `denyuntagged${n}` });
  await page.getByLabel("Assignment name").fill(`deny${n}`);
  await page.getByRole("button", { name: "Assign", exact: true }).click();
  await page.waitForTimeout(800);
  const denied = await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/vyaz${n}b`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } });
  check("custom deny policy authored in the UI blocks create over ARM (403)", denied.status === 403 && /RequestDisallowedByPolicy/.test(denied.text), `HTTP ${denied.status}`);
  // Subscriptions: Manage Policies dialog
  await page.goto(UI + "#/subscriptions");
  await page.getByRole("button", { name: "Manage Policies" }).click();
  await page.getByRole("dialog").getByRole("tab", { name: "Assignments" }).waitFor();
  await noNS("Manage Policies dialog");
  await page.keyboard.press("Escape");
  // AKS policies
  const aks = `vyazaks${n}`;
  await armv("2024-09-02-preview")("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${aks}`, { location: "eastus", properties: { agentPoolProfiles: [] } });
  await page.goto(UI + `#/aks/${RG}/${aks}/policies`);
  await page.getByRole("tab", { name: "Compliance" }).waitFor();
  await noNS("AKS policies");

  // ── Storage: wizard Data protection + Encryption, Properties, key rotation, networking ──
  const SA = `vyazs${n}`;
  await page.goto(UI + "#/storage/create");
  await page.getByLabel("Storage account name", { exact: true }).fill(SA);
  await page.getByRole("link", { name: "Create new" }).or(page.getByRole("button", { name: "Create new" })).first().click();
  await page.getByLabel("New resource group name").fill(RG + "s");
  await page.getByRole("tab", { name: "Data protection", exact: true }).click();
  await page.getByLabel("Enable versioning for blobs").check();
  await page.getByLabel("Enable blob change feed").check();
  await page.getByLabel("Days to retain deleted blobs").fill("9");
  await noNS("wizard Data protection", ["file shares"]);
  await page.getByRole("tab", { name: "Encryption", exact: true }).click();
  await page.getByLabel("Enable infrastructure encryption").check();
  await noNS("wizard Encryption");
  await page.getByRole("button", { name: "Review + create" }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: new RegExp(SA) }).first().waitFor({ timeout: 30000 });
  const bs = json(await arm("GET", `/resourceGroups/${RG}s/providers/Microsoft.Storage/storageAccounts/${SA}/blobServices/default`));
  check("wizard wrote blobServices/default (versioning, change feed, 9d soft delete)", bs.properties?.isVersioningEnabled === true && bs.properties?.changeFeed?.enabled === true && bs.properties?.deleteRetentionPolicy?.days === 9);
  const sacc = json(await arm("GET", `/resourceGroups/${RG}s/providers/Microsoft.Storage/storageAccounts/${SA}`));
  check("infrastructure encryption stored on the account", sacc.properties?.encryption?.requireInfrastructureEncryption === true);
  await page.goto(UI + `#/storage/${RG}s/${SA}/configuration`);
  await page.waitForTimeout(500);
  await page.goto(UI + `#/storage/${RG}s/${SA}`);
  await page.getByRole("tab", { name: "Properties" }).click();
  await page.getByText("Enabled (9 days)").first().waitFor({ timeout: 10000 });
  await noNS("storage Properties", ["NFS v3", "Private endpoints", "Azure Files"]);
  // key rotation
  const before = json(await arm("POST", `/resourceGroups/${RG}s/providers/Microsoft.Storage/storageAccounts/${SA}/listKeys`)).keys[0].value;
  await page.goto(UI + `#/storage/${RG}s/${SA}/accesskeys`);
  await page.getByRole("button", { name: "Rotate key key1" }).click();
  await page.waitForTimeout(800);
  const after = json(await arm("POST", `/resourceGroups/${RG}s/providers/Microsoft.Storage/storageAccounts/${SA}/listKeys`)).keys[0].value;
  check("UI Rotate key really changes the key over ARM", before !== after);
  await noNS("Access keys");
  // networking
  await page.goto(UI + `#/storage/${RG}s/${SA}/networking`);
  await page.getByLabel("Resource instance resource ID").fill("/subscriptions/x/resourceGroups/y/providers/Microsoft.Sql/servers/z");
  await page.getByRole("button", { name: "Add resource instance" }).click();
  await page.waitForTimeout(800);
  await page.getByRole("tab", { name: "Advanced" }).click();
  await page.getByLabel("Publish Internet routing endpoints").click();
  await page.getByLabel("Custom domain name").fill("cdn.example.com");
  await page.getByRole("button", { name: "Save custom domain" }).click();
  await page.waitForTimeout(800);
  const net = json(await arm("GET", `/resourceGroups/${RG}s/providers/Microsoft.Storage/storageAccounts/${SA}`)).properties || {};
  check("resource instance + internet endpoint + custom domain persisted", net.networkAcls?.resourceAccessRules?.length === 1 && !!net.primaryEndpoints?.internetEndpoints && net.customDomain?.name === "cdn.example.com");
  await page.getByRole("tab", { name: "Public access" }).click();
  await noNS("storage Networking (public)", ["Virtual network", "firewall", "trusted services"]);

  // ── Managed identity: user-assigned attach on ACR + Cosmos identity page ──────────────
  const ACR = `vyazacr${n}`, COS = `vyazcos${n}`, MI = `vyazmi${n}`;
  await armv("2023-07-01")("PUT", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}`, { location: "eastus", sku: { name: "Standard" } });
  await page.goto(UI + `#/acr/${RG}/${ACR}/identity`);
  await page.getByRole("tab", { name: "User assigned" }).click();
  await page.getByRole("button", { name: "Add user assigned managed identity" }).click();
  await page.getByLabel("New managed identity name").fill(MI);
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("cell", { name: MI, exact: true }).waitFor({ timeout: 15000 });
  const acr = json(await armv("2023-07-01")("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}`));
  const mi = json(await armv("2023-01-31")("GET", `/resourceGroups/${RG}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${MI}`));
  const ref = Object.values(acr.identity?.userAssignedIdentities || {})[0] || {};
  check("UI-created user-assigned identity attached; principalId resolved over ARM", !!mi.properties?.principalId && ref.principalId === mi.properties.principalId);
  await noNS("ACR user assigned identities");
  await page.getByLabel(`Select ${MI}`).check();
  await page.getByRole("button", { name: "Remove user assigned managed identity" }).click();
  await page.getByText("No user assigned managed identities.").waitFor({ timeout: 10000 });
  check("UI detach clears the attachment over ARM", Object.keys(json(await armv("2023-07-01")("GET", `/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${ACR}`)).identity?.userAssignedIdentities || {}).length === 0);
  await armv("2024-05-15")("PUT", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COS}`, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }] } });
  await page.goto(UI + `#/cosmos/${RG}/${COS}/identity`);
  await page.getByLabel("System assigned status").selectOption("on");
  await page.getByText("Object (principal) ID").waitFor({ timeout: 10000 });
  check("Cosmos Identity page turns on system assigned identity over ARM", !!json(await armv("2024-05-15")("GET", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${COS}`)).identity?.principalId);
  await noNS("Cosmos Identity");

  // ── Event Grid subscriptions on resource events (storage + resource group) ─────────────
  await page.goto(UI + `#/storage/${RG}s/${SA}/events`);
  await page.getByRole("button", { name: "Add event subscription" }).click();
  await page.getByLabel("Event subscription name").fill(`blobs${n}`);
  await page.getByLabel("Microsoft.Storage.BlobCreated", { exact: true }).check();
  await page.getByLabel("Endpoint", { exact: true }).fill("http://localhost:9/hook");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("cell", { name: `blobs${n}`, exact: true }).waitFor({ timeout: 10000 });
  await page.getByLabel("Test event type").selectOption("Microsoft.Storage.BlobCreated");
  await page.getByRole("button", { name: "Send test event" }).click();
  await page.waitForTimeout(800);
  const egs = json(await armv("2022-06-15")("GET", `/resourceGroups/${RG}s/providers/Microsoft.Storage/storageAccounts/${SA}/providers/Microsoft.EventGrid/eventSubscriptions/blobs${n}/deliveryStatus`));
  check("storage Events: UI subscription + test event matched over native ARM", egs.matched === 1);
  await noNS("Storage Events");
  await armv("2022-06-15")("PUT", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/eventSubscriptions/rgsub${n}`, { properties: { destination: { endpointType: "WebHook", properties: { endpointUrl: "http://localhost:9/h" } } } });
  await armv("2023-11-01")("PUT", `/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/vyazvn${n}`, { location: "eastus" });
  await page.goto(UI + `#/resourcegroups/${RG}/events`);
  await page.getByRole("cell", { name: `rgsub${n}`, exact: true }).waitFor({ timeout: 10000 });
  const rgd = json(await armv("2022-06-15")("GET", `/resourceGroups/${RG}/providers/Microsoft.EventGrid/eventSubscriptions/rgsub${n}/deliveryStatus`));
  check("resource group subscription received real ResourceWriteSuccess from an ARM write", rgd.matched >= 1);
  await noNS("RG Events");

  // @@GROUPS@@
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
