/* Smoke for AZ-06 (support requests filed with Vyomi). Drives the UI on several blades and
 * cross-checks the tickets over the native ARM wire.
 *   BASE=http://127.0.0.1:9046 node consoles/tests/smoke-azure-az06.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9046";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `vyaz06-rg${n}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2023-01-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`,
  { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Azure services" }).waitFor({ timeout: 120000 });
  await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" });
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/vyazkv${n}`, { location: "eastus", properties: { tenantId: "x", sku: { family: "A", name: "standard" } } }, "2023-07-01");

  // File a request from a Key Vault blade
  await page.goto(UI + `#/keyvaults/${RG}/vyazkv${n}/support`);
  await page.getByRole("button", { name: "New support request" }).click();
  await page.getByLabel("Summary", { exact: true }).first().fill("Cannot read secrets");
  await page.getByLabel("Details", { exact: true }).first().fill("403 on get secret");
  await page.getByLabel("First name", { exact: true }).first().fill("Ada");
  await page.getByLabel("Last name", { exact: true }).first().fill("L");
  await page.getByLabel("Email", { exact: true }).first().fill("not-an-email");
  await page.getByRole("button", { name: "Create support request" }).click();
  const bad = await page.getByText("not a valid email", { exact: false }).waitFor({ timeout: 8000 }).then(() => true, () => false);
  check("invalid email is rejected with the real error", bad);
  await page.getByLabel("Email", { exact: true }).first().fill("ada@example.com");
  await page.getByRole("button", { name: "Create support request" }).click();
  await page.getByText("Conversation").waitFor({ timeout: 10000 });
  check("ticket opens with Vyomi acknowledgement", await page.getByText("We received your request", { exact: false }).count() > 0);
  const list = json(await arm("GET", "/providers/Microsoft.Support/supportTickets", null, "2020-04-01")).value || [];
  const t = list.find((x) => x.properties.title === "Cannot read secrets");
  check("ticket visible over native ARM", !!t && t.properties.technicalTicketDetails.resourceId.toLowerCase().includes(`vyazkv${n}`));
  check("service defaults to Key Vault", t?.properties.serviceDisplayName === "Key Vault");
  await page.getByLabel("Reply", { exact: true }).first().fill("Adding the vault id");
  await page.getByRole("button", { name: "Send reply" }).click();
  await page.getByText("Adding the vault id").waitFor({ timeout: 8000 });
  check("reply shows in the conversation", true);
  await page.getByRole("button", { name: "Close request" }).click();
  await page.getByText("Status").first().waitFor();
  const closed = json(await arm("GET", `/providers/Microsoft.Support/supportTickets/${t.name}`, null, "2020-04-01"));
  check("close request persisted", closed.properties?.status === "Closed");

  // The same list is reachable from other blades + standalone pages
  for (const [label, hash] of [["monitor", "#/monitor/support"], ["cost", "#/cost/support"], ["resource group", `#/resourcegroups/${RG}/support`]]) {
    await page.goto(UI + hash);
    check(`${label}: support page lists the filed request`, await page.getByText(t.properties.supportTicketId).first().waitFor({ timeout: 8000 }).then(() => true, () => false));
    check(`${label}: no Not-simulated panel`, (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  }
  // Defender for Cloud page on a storage account: live recommendations for that resource
  await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/vyaz06${n}`, { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { supportsHttpsTrafficOnly: false, allowBlobPublicAccess: true } });
  await page.goto(UI + `#/storage/${RG}/vyaz06${n}/defender`);
  check("storage Defender page lists a real recommendation", await page.getByText("secure transfer", { exact: false }).first().waitFor({ timeout: 10000 }).then(() => true, () => false));
  check("storage Defender page: no Not-simulated panel", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  check("no page errors", errors.length === 0, errors.join(" | ").slice(0, 200));
} catch (e) { check("smoke ran", false, String(e).slice(0, 300)); }
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
