/* Azure Recovery Services vault console: create vault, enable VM backup, backup now, restore (alternate location), policy create,
 * Site Recovery enable replication + test failover + cleanup. Fresh dev server:  BASE=http://127.0.0.1:9075 node consoles/tests/smoke-azure-recoveryservices.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9075";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `rsv-rg${n}`, DR = `rsv-dr${n}`, VAULT = `vault${n}`, VM = `web${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2024-04-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${DR}`, { location: "westus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${VM}`, { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" } } }, "2023-09-01");
await arm("PUT", `/resourceGroups/${DR}/providers/Microsoft.Network/virtualNetworks/drnet`, { location: "westus", properties: { addressSpace: { addressPrefixes: ["10.1.0.0/16"] }, subnets: [{ name: "s1", properties: { addressPrefix: "10.1.1.0/24" } }] } }, "2023-09-01");

// create a vault through the UI
await page.goto(UI + "#/recoveryservices");
await page.getByRole("button", { name: /Create/ }).first().click();
await page.getByRole("dialog").getByRole("textbox", { name: "Vault name" }).fill(VAULT);
await page.getByRole("dialog").getByRole("combobox", { name: "Resource group" }).selectOption(RG);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("link", { name: VAULT }).waitFor({ timeout: 15000 });
check("vault created from the UI", json(await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.RecoveryServices/vaults/${VAULT}`)).properties?.provisioningState === "Succeeded");

// enable backup + backup now
await page.goto(UI + `#/recoveryservices/${RG}/${VAULT}/items`);
await page.getByRole("button", { name: /Create|Enable backup/ }).first().click();
await page.getByRole("dialog").getByRole("combobox", { name: "Virtual machine" }).selectOption({ label: new RegExp(VM).source ? undefined : undefined, index: 1 }).catch(async () => {});
const opts = await page.getByRole("dialog").getByRole("combobox", { name: "Virtual machine" }).locator("option").allTextContents();
await page.getByRole("dialog").getByRole("combobox", { name: "Virtual machine" }).selectOption({ label: opts.find((o) => o.startsWith(VM)) });
await page.getByRole("dialog").getByRole("button", { name: "Enable backup" }).click();
await page.getByText(VM).first().waitFor({ timeout: 15000 });
const V = `/resourceGroups/${RG}/providers/Microsoft.RecoveryServices/vaults/${VAULT}`;
check("VM is a protected item", json(await arm("GET", `${V}/backupProtectedItems`)).value?.length === 1);
await page.getByRole("row", { name: new RegExp(VM) }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Backup now" }).click();
await page.waitForTimeout(1500);
const ip = json(await arm("GET", `${V}/backupProtectedItems`)).value[0];
const rps = json(await arm("GET", `${ip.id.replace(/^\/subscriptions\/[^/]+/, "")}/recoveryPoints`)).value || [];
check("backup now created a recovery point (a real blob artifact)", rps.length === 1, rps.length);

// restore to a new VM
await page.getByRole("button", { name: "Restore", exact: true }).click();
const d = page.getByRole("dialog");
await d.getByRole("combobox", { name: "Restore type" }).selectOption("AlternateLocation");
await d.getByRole("combobox", { name: "Target resource group" }).selectOption(DR);
await d.getByRole("textbox", { name: "New virtual machine name" }).fill(`${VM}-r`);
await d.getByRole("textbox", { name: "Virtual network ID" }).fill(`/subscriptions/${SUB}/resourceGroups/${DR}/providers/Microsoft.Network/virtualNetworks/drnet`);
await d.getByRole("textbox", { name: "Subnet name" }).fill("s1");
await d.getByRole("button", { name: "Restore", exact: true }).click();
await page.waitForTimeout(1500);
check("restore created a NEW VM", json(await arm("GET", `/resourceGroups/${DR}/providers/Microsoft.Compute/virtualMachines/${VM}-r`, null, "2023-09-01")).name === `${VM}-r`);
await page.goto(UI + `#/recoveryservices/${RG}/${VAULT}/jobs`);
await page.getByText("Restore").first().waitFor({ timeout: 10000 });
check("jobs list shows Backup/Restore operations", true);

// policy
await page.goto(UI + `#/recoveryservices/${RG}/${VAULT}/policies`);
await page.getByRole("button", { name: /Create/ }).first().click();
await page.getByRole("dialog").getByRole("textbox", { name: "Policy name" }).fill("ui-pol");
await page.getByRole("dialog").getByRole("textbox", { name: "Retention days" }).fill("3");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(/7|9999/).first().waitFor({ timeout: 8000 }).catch(() => {});
check("policy with 3 daily days is rejected like Azure (7-9999)", !(json(await arm("GET", `${V}/backupPolicies`)).value || []).some((p) => p.name === "ui-pol"));
await page.getByRole("dialog").getByRole("textbox", { name: "Retention days" }).fill("14");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(1500);
check("policy created", (json(await arm("GET", `${V}/backupPolicies`)).value || []).some((p) => p.name === "ui-pol"));

// Site Recovery
await page.goto(UI + `#/recoveryservices/${RG}/${VAULT}/replicated`);
await page.getByRole("button", { name: /Create|Enable replication/ }).first().click();
const e = page.getByRole("dialog");
const vopts = await e.getByRole("combobox", { name: "Source virtual machine" }).locator("option").allTextContents();
await e.getByRole("combobox", { name: "Source virtual machine" }).selectOption({ label: vopts.find((o) => o.startsWith(VM + " ") || o.startsWith(`${VM} (`)) });
await e.getByRole("combobox", { name: "Target resource group" }).selectOption(DR);
await e.getByRole("button", { name: "Enable replication" }).click();
await page.getByText(`${VM}-repl`).or(page.getByText(VM)).first().waitFor({ timeout: 15000 });
check("replication enabled", (json(await arm("GET", `${V}/replicationProtectedItems`)).value || []).length === 1);
await page.getByRole("row").nth(1).getByRole("checkbox").check();
await page.getByRole("button", { name: "Test failover", exact: true }).click();
const fo = page.getByRole("dialog");
const nopts = await fo.getByRole("combobox", { name: "Azure virtual network" }).locator("option").allTextContents();
await fo.getByRole("combobox", { name: "Azure virtual network" }).selectOption({ label: nopts.find((o) => o.startsWith("drnet")) });
await fo.getByRole("button", { name: "Test failover", exact: true }).click();
await page.waitForTimeout(1500);
check("test failover created the replica VM in the target region", json(await arm("GET", `/resourceGroups/${DR}/providers/Microsoft.Compute/virtualMachines/${VM}-test`, null, "2023-09-01")).name === `${VM}-test`);
await page.getByRole("button", { name: "Cleanup test failover" }).click();
await page.waitForTimeout(1200);
check("cleanup removed it", json(await arm("GET", `/resourceGroups/${DR}/providers/Microsoft.Compute/virtualMachines/${VM}-test`, null, "2023-09-01")).error !== undefined);
await page.goto(UI + `#/vms/${RG}/${VM}/disasterrecovery`);
await page.getByText(VAULT).first().waitFor({ timeout: 15000 });
check("VM Disaster recovery tab lists the replicated item (not a gap panel)", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
await page.goto(UI + `#/vms/${RG}/${VM}/backup`);
await page.getByText("Azure Backup (Recovery Services vault)").waitFor({ timeout: 15000 });
check("VM Backup tab shows vault protection", await page.getByText(/Protection status/).isVisible());
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
