/* Playwright (Chrome channel via launch(), not CDP) for the Azure RBAC pickers in the BUILT bundle (wasm/v4/azure), with a mocked wire:
 * the REAL verbatim catalogs from core/iam_catalog/azure are served at /_wire/api/iam/azure/catalog/<name>; Graph users/groups/SPs, ARM
 * resource groups and roleAssignments/roleDefinitions are in-memory.
 *   NODE_PATH=<dir with playwright> SHOTS=<dir> node consoles/tests/smoke-azure-resource-iam-tabs.mjs */
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
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RES = { kv: `/subscriptions/${SUB}/resourceGroups/rg1/providers/Microsoft.KeyVault/vaults/kv1`, sb: `/subscriptions/${SUB}/resourceGroups/rg1/providers/Microsoft.ServiceBus/namespaces/sb1`, q: `/subscriptions/${SUB}/resourceGroups/rg1/providers/Microsoft.ServiceBus/namespaces/sb1/queues/q1` };
const READER = { name: "acdd72a7-3385-48ef-bd42-f606fba81ae7", id: `/subscriptions/${SUB}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7`, properties: { roleName: "Reader", type: "BuiltInRole", description: "View all resources, but does not allow you to make any changes.", permissions: [{ actions: ["*/read"], notActions: [], dataActions: [], notDataActions: [] }], assignableScopes: ["/"] } };
const puts = [], seeded = [{ name: "seed1", properties: { scope: RES.kv, principalId: "u-1", principalType: "User", roleDefinitionId: READER.id } }];
const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } }); const page = await ctx.newPage();
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await ctx.addInitScript(() => { window.__vyomiNanoReady = true; });
await page.route(/nano-boot\.js|mesh-link\.js|nano-kernel\.js|nano-.*\.js|vyomi-appbar|mesh-widget|vyomi-dl-card/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
const J = (r, o, st = 200) => r.fulfill({ status: st, contentType: "application/json", body: JSON.stringify(o) });
await page.route("**/_wire/**", async (r) => {
  const rq = r.request(), u = new URL(rq.url()), p = u.pathname.replace(/^.*\/_wire/, ""), m = rq.method();
  const cm = /\/api\/iam\/azure\/catalog\/([\w.]+)$/.exec(p);
  if (cm) { const f = join(CAT, cm[1] + ".json"); return existsSync(f) ? r.fulfill({ status: 200, contentType: "application/json", body: await readFile(f) }) : J(r, { error: "no catalog" }, 404); }
  if (p.includes("/api/iam/")) return J(r, {});
  if (p.endsWith("/v1.0/users")) return J(r, { value: [{ id: "u-1", displayName: "Sudhir Ganti", userPrincipalName: "admin@vyomi.cloud" }, { id: "u-2", displayName: "Asha Rao", userPrincipalName: "asha@vyomi.cloud" }] });
  if (p.endsWith("/v1.0/groups") || p.endsWith("/v1.0/servicePrincipals") || p.endsWith("/userAssignedIdentities")) return J(r, { value: [] });
  if (p.endsWith("/resourcegroups")) return J(r, { value: [{ id: `/subscriptions/${SUB}/resourceGroups/rg1`, name: "rg1", location: "eastus" }] });
  if (m === "GET" && p.endsWith(`/subscriptions/${SUB}`)) return J(r, { id: `/subscriptions/${SUB}`, subscriptionId: SUB, displayName: "Vyomi subscription", state: "Enabled" });
  if (m === "GET" && p === RES.kv) return J(r, { id: RES.kv, name: "kv1", type: "Microsoft.KeyVault/vaults", location: "eastus", properties: { enableRbacAuthorization: true, accessPolicies: [], vaultUri: "https://kv1.vault.azure.net/", sku: { name: "standard", family: "A" }, tenantId: "t" } });
  if (m === "GET" && p === RES.sb) return J(r, { id: RES.sb, name: "sb1", type: "Microsoft.ServiceBus/namespaces", location: "eastus", sku: { name: "Standard", tier: "Standard" }, properties: { serviceBusEndpoint: "https://sb1.servicebus.windows.net:443/", status: "Active" } });
  if (m === "GET" && p === RES.q) return J(r, { id: RES.q, name: "q1", type: "Microsoft.ServiceBus/Namespaces/Queues", properties: { status: "Active", messageCount: 0, countDetails: {} } });
  if (p.includes("roleAssignments/") && m === "PUT") { const b = JSON.parse(rq.postData()); puts.push({ path: p, body: b }); seeded.push({ name: p.split("/").pop(), properties: b.properties }); return J(r, { name: "x", properties: b.properties }, 201); }
  if (p.includes("roleAssignments") && m === "DELETE") { const n = p.split("/").pop(); const i = seeded.findIndex((x) => x.name === n); if (i >= 0) seeded.splice(i, 1); dels.push(n); return J(r, {}); }
  if (p.includes("roleAssignments")) return J(r, { value: seeded });
  if (p.includes("roleDefinitions")) return J(r, { value: [READER] });
  return J(r, {}, 404);
});
const dels = [];
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
async function addReader(label, resId, hash) {
  await page.goto(`${BASE}/v4/azure/#${hash}`);
  await page.getByRole("tab", { name: "Role assignments" }).waitFor({ timeout: 30000 });
  check(`${label}: blade is the shared Access control (IAM) kit (Check access / Role assignments / Roles / Deny assignments tabs)`, (await page.getByRole("tab", { name: "Check access" }).count()) === 1 && (await page.getByRole("tab", { name: "Roles" }).count()) >= 1 && (await page.getByRole("tab", { name: "Deny assignments" }).count()) === 1);
  await page.getByRole("tab", { name: "Role assignments" }).click();
  await page.getByRole("button", { name: "Add role assignment" }).click();
  await page.getByTestId("role-picker").waitFor();
  await page.getByLabel("Search by role name, description, or ID").fill("Reader");
  await page.getByTestId("role-row-Reader").waitFor();
  await page.getByLabel("View Reader", { exact: true }).click();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("tab", { name: "Members" }).click();
  await page.getByTestId("select-members").click();
  await page.getByTestId("member-row-Asha Rao").waitFor();
  await page.getByLabel("Select Asha Rao").check();
  await page.getByRole("button", { name: "Select", exact: true }).click().catch(() => {});
  await page.getByRole("button", { name: "Add", exact: true }).click().catch(() => {});
  await page.getByRole("button", { name: "Review + assign" }).click();
  await page.getByTestId("ra-review").waitFor();
  await page.getByRole("button", { name: "Review + assign" }).click();
  await page.waitForTimeout(800);
  const put = puts.at(-1);
  check(`${label}: PUT roleAssignments scope is the resource id`, !!put && put.body.properties.scope === resId && put.body.properties.principalId === "u-2" && /roleDefinitions\/acdd72a7-3385-48ef-bd42-f606fba81ae7$/.test(put.body.properties.roleDefinitionId) && /roleAssignments\/[0-9a-f-]{36}$/.test(put.path), put && JSON.stringify(put.body.properties).slice(0,200));
}
await addReader("Key Vault", RES.kv, "/keyvaults/rg1/kv1/iam");
await page.getByRole("tab", { name: "Role assignments" }).click();
await page.getByText("This resource").first().waitFor({ timeout: 10000 }).catch(() => {});
check("Key Vault: stored assignments shown scoped to the resource (seed + new)", (await page.getByText("This resource").count()) >= 1);
await shot("kv-role-assignments");
await addReader("Service Bus namespace", RES.sb, "/servicebus/rg1/sb1/iam");
await addReader("Service Bus queue (newly added IAM blade)", RES.q, "/servicebus/rg1/sb1/queues/q1/iam");
await shot("queue-iam");
check("no page errors", errs.length === 0, errs.join(" | "));
console.log(`\n${pass} passed, ${fail} failed; screenshots in ${SHOTS}`);
await browser.close(); server.close(); process.exit(fail ? 1 : 0);
