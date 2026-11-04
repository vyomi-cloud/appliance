/* AKS Backup blade, Cosmos point-in-time restore, App Service backups/restore, deleted storage account restore.
 *   BASE=http://127.0.0.1:9082 node consoles/tests/smoke-azure-azbackup.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9082";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `abk-rg${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: "networkidle" });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2024-05-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");

// ── AKS ──
const CL = `/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters`;
for (const c of ["src", "dst"]) await arm("PUT", `${CL}/${c}`, { location: "eastus", properties: { dnsPrefix: c, agentPoolProfiles: [{ name: "np", count: 1, vmSize: "Standard_DS2_v2", mode: "System" }] } });
const kubectl = async (c, command) => json(await arm("POST", `${CL}/${c}/runCommand`, { command }));
await kubectl("src", "kubectl create namespace shop");
await kubectl("src", `kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: shop}
spec: {replicas: 1, selector: {matchLabels: {app: web}}, template: {metadata: {labels: {app: web}}, spec: {containers: [{name: web, image: nginx}]}}}
EOF`);
await page.goto(UI + `#/aks/${RG}/src/backup`);
await page.getByText("Backup extension").first().waitFor({ timeout: 20000 });
check("Backup blade is real (no Not-simulated panel)", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
await page.getByRole("button", { name: "Install extension" }).click();
await page.getByRole("button", { name: "Configure backup" }).waitFor({ timeout: 10000 });
await page.getByRole("button", { name: "Configure backup" }).click();
await page.getByRole("dialog").getByRole("textbox", { name: "New vault name" }).fill(`bv${n}`);
await page.getByRole("dialog").getByRole("button", { name: "Configure", exact: true }).click();
await page.getByRole("button", { name: "Backup now" }).waitFor({ timeout: 10000 });
check("backup instance exists in the new vault", ((json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.DataProtection/backupVaults/bv${n}/backupInstances`, null, "2023-05-01")).value) || []).length === 1);
await page.getByRole("button", { name: "Backup now" }).click();
await page.getByRole("button", { name: "Restore", exact: true }).first().waitFor({ timeout: 10000 });
// dst needs the extension too
await arm("PUT", `${CL}/dst/providers/Microsoft.KubernetesConfiguration/extensions/azure-aks-backup`, { properties: { extensionType: "microsoft.dataprotection.kubernetes", scope: { cluster: { releaseNamespace: "dataprotection-microsoft" } } } }, "2023-05-01");
await page.reload();
await page.getByRole("button", { name: "Restore", exact: true }).first().click();
const d = page.getByRole("dialog");
await d.getByRole("combobox", { name: "Target cluster" }).selectOption("dst");
await d.getByRole("combobox", { name: "Conflict policy" }).selectOption("Patch");
await d.getByRole("button", { name: "Restore", exact: true }).click();
await page.waitForTimeout(2000);
const out = await kubectl("dst", "kubectl get deployments -n shop");
check("restore re-created the deployment on the target cluster", /web/.test(JSON.stringify(out)), JSON.stringify(out).slice(0, 120));

// ── Cosmos ──
const COS = `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts`;
const cv = "2024-05-15";
await arm("PUT", `${COS}/cdb${n}`, { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }], backupPolicy: { type: "Continuous", continuousModeProperties: { tier: "Continuous7Days" } } } }, cv);
await arm("PUT", `${COS}/cdb${n}/sqlDatabases/orders`, { properties: { resource: { id: "orders" }, options: {} } }, cv);
await new Promise((r) => setTimeout(r, 1500));
await page.goto(UI + `#/cosmos/${RG}/cdb${n}/backup`);
await page.getByText("Restorable accounts in").waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "Restore to a new account" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Restore", exact: true }).click();
await page.waitForTimeout(1500);
const restored = json(await arm("GET", `${COS}/cdb${n}-restored/sqlDatabases/orders`, null, cv));
check("PITR restore created a NEW account with the database", restored.name === "orders", JSON.stringify(restored).slice(0, 120));

// ── App Service backups ──
const SA = `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/abkstore${n}`;
await arm("PUT", SA, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } }, "2023-01-01");
const WEB = `/resourceGroups/${RG}/providers/Microsoft.Web`;
await arm("PUT", `${WEB}/serverfarms/std`, { location: "eastus", sku: { name: "S1", tier: "Standard" } }, "2023-12-01");
await arm("PUT", `${WEB}/sites/app${n}`, { location: "eastus", kind: "app", properties: { serverFarmId: `/subscriptions/${SUB}${WEB}/serverfarms/std` } }, "2023-12-01");
await arm("PUT", `${WEB}/sites/app${n}/config/appsettings`, { properties: { MODE: "prod" } }, "2023-12-01");
const sas = `https://abkstore${n}.blob.core.windows.net/backups?sv=2022-11-02&sig=abc`;
// create the container through the Azure Blob wire (the customer container the SAS URL points at)
const mk = (await arm("PUT", `${SA}/blobServices/default/containers/backups`, { properties: {} }, "2023-01-01")).status;
await page.goto(UI + `#/appservices/${RG}/app${n}/backups`);
await page.getByRole("textbox", { name: /container/i }).first().waitFor({ timeout: 20000 }).catch(() => {});
await page.locator("input[placeholder*='blob.core.windows.net']").fill(sas);
await page.getByRole("button", { name: "Backup Now" }).click();
await page.waitForTimeout(1500);
const bl = json(await arm("GET", `${WEB}/sites/app${n}/backups`, null, "2023-12-01")).value || [];
check("Backup Now wrote a real zip backup", bl.length === 1 && bl[0].properties.sizeInBytes > 100, mk + " " + JSON.stringify(bl).slice(0, 160));
await arm("PUT", `${WEB}/sites/app${n}/config/appsettings`, { properties: { MODE: "broken" } }, "2023-12-01");
await page.reload();
await page.locator("input[placeholder*='blob.core.windows.net']").fill(sas);
await page.getByRole("button", { name: "Restore", exact: true }).first().click();
await page.getByRole("dialog").getByRole("button", { name: "Restore", exact: true }).click();
await page.waitForTimeout(1500);
const apps = json(await arm("POST", `${WEB}/sites/app${n}/config/appsettings/list`, null, "2023-12-01"));
check("Restore re-applied the backed-up app settings", apps.properties?.MODE === "prod", JSON.stringify(apps).slice(0, 120));

// ── deleted storage account ──
const SB = `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/gone${n}`;
await arm("PUT", SB, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } }, "2023-01-01");
await arm("DELETE", SB, null, "2023-01-01");
await page.goto(UI + `#/storage`);
await page.getByRole("button", { name: "Restore", exact: true }).click();
await page.getByRole("radio", { name: `Select gone${n}` }).check();
await page.getByRole("dialog").getByRole("button", { name: "Restore", exact: true }).click();
await page.waitForTimeout(1500);
check("deleted storage account is back", json(await arm("GET", SB, null, "2023-01-01")).name === `gone${n}`);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
