/* Playwright (Chrome channel via launch(), not CDP) for the Azure RBAC pickers in the BUILT bundle (wasm/v4/azure), with a mocked wire:
 * the REAL verbatim catalogs from core/iam_catalog/azure are served at /_wire/api/iam/azure/catalog/<name>; Graph users/groups/SPs, ARM
 * resource groups and roleAssignments/roleDefinitions are in-memory.
 *   NODE_PATH=<dir with playwright> SHOTS=<dir> node consoles/tests/smoke-azure-iam-pickers.mjs */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync, mkdirSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const ROOT = new URL("../../wasm", import.meta.url).pathname, CAT = new URL("../../core/iam_catalog/azure", import.meta.url).pathname;
const SHOTS = process.env.SHOTS || "/tmp/azure-iam-pickers"; mkdirSync(SHOTS, { recursive: true });
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer(async (req, res) => {
  let p = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)); if (p.endsWith("/")) p += "index.html";
  const f = join(ROOT, p); if (!f.startsWith(ROOT) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[extname(f)] || "application/octet-stream" }); res.end(await readFile(f));
}).listen(0, "127.0.0.1");
await new Promise((r) => server.once("listening", r));
const BASE = `http://127.0.0.1:${server.address().port}`;
let pass = 0, fail = 0; const check = (n, ok, d = "") => { ok ? pass++ : fail++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 220) : ""}`); };
const SUB = "00000000-0000-0000-0000-cloudlearn01", SAID = `/subscriptions/${SUB}/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/iamsa`;
const roleDefs = [], puts = [], rolePuts = [];
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } }); const page = await ctx.newPage();
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await ctx.addInitScript(() => { window.__vyomiNanoReady = true; });
await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
const J = (r, o, st = 200) => r.fulfill({ status: st, contentType: "application/json", body: JSON.stringify(o) });
await page.route("**/_wire/**", async (r) => {
  const rq = r.request(), u = new URL(rq.url()), p = u.pathname, m = rq.method();
  const cm = /\/api\/iam\/azure\/catalog\/([\w.]+)$/.exec(p);
  if (cm) { const f = join(CAT, cm[1] + ".json"); return existsSync(f) ? r.fulfill({ status: 200, contentType: "application/json", body: await readFile(f) }) : J(r, { error: "no catalog" }, 404); }
  if (p.includes("/api/iam/")) return J(r, {});
  if (p.endsWith("/v1.0/users")) return J(r, { value: [{ id: "u-1", displayName: "Sudhir Ganti", userPrincipalName: "admin@vyomi.cloud" }, { id: "u-2", displayName: "Asha Rao", userPrincipalName: "asha@vyomi.cloud" }] });
  if (p.endsWith("/v1.0/groups")) return J(r, { value: [{ id: "g-1", displayName: "Platform Team", description: "Platform engineers" }] });
  if (p.endsWith("/v1.0/servicePrincipals")) return J(r, { value: [{ id: "sp-1", displayName: "ci-deployer", appId: "app-1" }] });
  if (p.endsWith("/userAssignedIdentities")) return J(r, { value: [{ name: "uami-web", location: "eastus", properties: { principalId: "mi-1" } }] });
  if (p.endsWith("/resourcegroups")) return J(r, { value: [{ id: `/subscriptions/${SUB}/resourceGroups/rg1`, name: "rg1", location: "eastus" }] });
  if (/\/resourceGroups\/rg1\/resources$/.test(p)) return J(r, { value: [{ id: SAID, name: "iamsa", type: "Microsoft.Storage/storageAccounts" }] });
  if (m === "GET" && p.endsWith(`/subscriptions/${SUB}`)) return J(r, { id: `/subscriptions/${SUB}`, subscriptionId: SUB, displayName: "Vyomi subscription", state: "Enabled" });
  if (m === "GET" && /storageAccounts\/iamsa$/.test(p)) return J(r, { id: SAID, name: "iamsa", type: "Microsoft.Storage/storageAccounts", location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" }, properties: { provisioningState: "Succeeded", primaryEndpoints: {} } });
  if (p.includes("roleAssignments/") && m === "PUT") { const b = JSON.parse(rq.postData()); puts.push({ path: p, body: b }); return J(r, { name: "x", properties: b.properties }, 201); }
  if (p.includes("roleAssignments")) return J(r, { value: puts.map((x, i) => ({ name: `ra${i}`, properties: x.body.properties })) });
  if (p.includes("roleDefinitions/") && m === "PUT") { const b = JSON.parse(rq.postData()); rolePuts.push({ path: p, body: b }); roleDefs.push({ name: p.split("/").pop(), properties: { ...b.properties } }); return J(r, { name: "x" }, 201); }
  if (p.includes("roleDefinitions")) return J(r, { value: roleDefs });
  return J(r, {}, 404);
});
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png` });
await page.goto(`${BASE}/v4/azure/#/storage/rg1/iamsa/iam`);
await page.getByRole("tab", { name: "Role assignments" }).waitFor({ timeout: 30000 });
await page.getByRole("tab", { name: "Role assignments" }).click();
await page.getByRole("button", { name: "Add role assignment" }).click();
// ---- Role tab
await page.getByTestId("role-picker").waitFor();
await page.getByLabel("Search by role name, description, or ID").fill("Storage Blob Data Reader");
await page.getByTestId("role-row-Storage Blob Data Reader").waitFor();
check("role list searchable, role row present", true);
await shot("01-role-tab");
await page.getByLabel("View Storage Blob Data Reader").click();
await page.getByText("DataActions (", { exact: false }).first().waitFor();
const permTxt = await page.locator(".vy-pblade").last().innerText();
check("View panel shows Permissions with the verbatim blob read data action", /storageAccounts\/blobServices\/containers\/blobs\/read/.test(permTxt) && /NotDataActions/.test(permTxt));
await shot("02-role-view-permissions");
await page.getByRole("tab", { name: "JSON" }).click();
check("View panel JSON tab", /"roleName": "Storage Blob Data Reader"/.test(await page.getByTestId("role-json").innerText()));
await page.getByRole("button", { name: "Select", exact: true }).click();
// ---- Members
await page.getByRole("tab", { name: "Members" }).click();
await page.getByTestId("select-members").click();
await page.getByTestId("member-picker").waitFor();
await page.getByTestId("member-row-Asha Rao").waitFor();
check("member picker: 'No items selected' + Selected (0)", /Selected \(0\)/.test(await page.getByTestId("member-picker").innerText()) && /No items selected/.test(await page.getByTestId("member-picker").innerText()));
await shot("03-member-picker-empty");
await page.getByLabel("Search", { exact: true }).fill("asha");
check("member picker: search filters ('1 result found')", /1 result found/.test(await page.getByTestId("member-picker").innerText()));
await page.getByLabel("Select Asha Rao").check();
check("member picker: Selected (1)", /Selected \(1\)/.test(await page.getByTestId("member-picker").innerText()));
await shot("04-member-picker-selected");
await page.getByRole("button", { name: "Add", exact: true }).click();
// ---- Conditions
await page.getByRole("tab", { name: "Conditions" }).click();
await page.getByRole("button", { name: "Add condition" }).click();
await page.getByLabel("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read").check();
await page.getByRole("button", { name: "Select", exact: true }).click();
await page.getByLabel("Attribute source").first().selectOption("Resource");
await page.getByLabel("Attribute", { exact: true }).first().selectOption({ label: "Container name" });
await page.getByLabel("Value", { exact: true }).first().fill("logs");
await page.getByRole("tab", { name: "Code" }).click();
const code = await page.getByTestId("abac-code").innerText();
check("ABAC code view", code === "((!(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'})) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'logs'))", code);
await shot("05-abac-code");
// ---- Review + assign
await page.getByRole("button", { name: "Review + assign" }).click();
await page.getByTestId("ra-review").waitFor();
await shot("06-review");
await page.getByRole("button", { name: "Review + assign" }).click();
await page.waitForTimeout(800);
const put = puts[0];
check("PUT roleAssignments payload", !!put && /roleAssignments\/[0-9a-f-]{36}$/.test(put.path) && put.body.properties.principalId === "u-2" && put.body.properties.principalType === "User"
  && put.body.properties.scope === SAID && /roleDefinitions\/2a2b9908-6ea1-4ae2-8e65-a410df84e7d1$/.test(put.body.properties.roleDefinitionId) && put.body.properties.condition === code && put.body.properties.conditionVersion === "2.0", JSON.stringify(put?.body));
// ---- Custom role
await page.getByRole("tab", { name: "Roles" }).click();
await page.getByRole("button", { name: "Add custom role" }).click();
await page.getByLabel("Custom role name").fill("Blob Lister");
await shot("07-custom-basics");
await page.getByRole("tab", { name: "Permissions" }).click();
await page.getByTestId("add-permissions").click();
await page.getByLabel("Search for a resource provider").fill("Microsoft.Stor");
await page.getByTestId("provider-Microsoft.Storage").click();
await page.getByTestId("permission-list").waitFor();
await page.getByLabel("Search for an action").fill("containers/read");
await shot("08-permission-picker");
await page.getByLabel("Microsoft.Storage/storageAccounts/blobServices/containers/read").check();
await page.getByRole("tab", { name: /Data actions/ }).click();
await page.getByLabel("Search for an action").fill("blobs/read");
await page.getByLabel("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read").check();
await page.getByRole("button", { name: "Add", exact: true }).click();
await page.getByRole("tab", { name: "JSON" }).click();
check("custom role JSON has provider-catalog actions", /containers\/read/.test(await page.getByTestId("custom-role-json").innerText()));
await page.getByRole("button", { name: "Review + create" }).click();
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForTimeout(800);
const rp = rolePuts[0]?.body?.properties;
check("PUT roleDefinitions payload", !!rp && rp.roleName === "Blob Lister" && rp.type === "CustomRole" && rp.permissions[0].actions.includes("Microsoft.Storage/storageAccounts/blobServices/containers/read") && rp.permissions[0].dataActions.includes("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"), JSON.stringify(rp));
// ---- Check access + effective access use pickers
await page.getByRole("tab", { name: "Check access" }).click();
await page.getByRole("button", { name: "Select principal" }).click();
await page.getByLabel("Select Sudhir Ganti").check();
await page.getByRole("button", { name: "Select", exact: true }).click();
check("Check access: principal chosen via picker", /Sudhir Ganti/.test(await page.getByTestId("principal-value").innerText()));
await shot("09-check-access");
await page.getByRole("tab", { name: "Effective access" }).click();
check("Effective access: no free-text principal/action inputs", (await page.getByLabel("Principal object ID").count()) === 0 && (await page.getByRole("button", { name: "Select action" }).count()) === 1);
await shot("10-effective-access");
check("no page errors", errs.length === 0, errs.join(" | "));
console.log(`\n${pass} passed, ${fail} failed; screenshots in ${SHOTS}`);
await browser.close(); server.close(); process.exit(fail ? 1 : 0);
