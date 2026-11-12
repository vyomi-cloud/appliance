/* Smoke: Diagnose (SQL db / Cosmos / Key Vault / Storage / Service Bus / ACR / DNS), Tasks (VM / Storage / Cosmos / Key Vault /
 * Service Bus / SQL db / Function App), VM Extensions and Key Vault Manage deleted keys/secrets, driven through the UI and
 * verified over the native wire.   BASE=http://127.0.0.1:9081 [NANO=1 UI_PATH=/v4/azure/] node consoles/tests/smoke-azure-depth.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9081";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `dp-rg-${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const arm = (m, path, body, v = "2023-05-01-preview") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const dp = (m, path, body) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}${path}?api-version=7.4`, body]);
const P = (ns, t, name) => `/resourceGroups/${RG}/providers/${ns}/${t}/${name}`;
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "load" });
if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
const mk = async (path, body, v) => ok(`create ${path.split("/").slice(-2).join("/")}`, [200, 201].includes((await arm("PUT", path, body, v)).status));
await mk(P("Microsoft.Sql", "servers", "sq1"), { location: "eastus", properties: { administratorLogin: "a", administratorLoginPassword: "Passw0rd!x1" } });
await mk(P("Microsoft.Sql", "servers", "sq1") + "/databases/db1", { location: "eastus", sku: { name: "GP_Gen5_2" } });
await mk(P("Microsoft.KeyVault", "vaults", "kv1"), { location: "eastus", properties: { tenantId: "t", sku: { family: "A", name: "standard" } } }, "2023-07-01");
await mk(P("Microsoft.Storage", "storageAccounts", "sa1"), { location: "eastus", kind: "StorageV2", sku: { name: "Standard_LRS" } }, "2023-01-01");
await mk(P("Microsoft.DocumentDB", "databaseAccounts", "cos1"), { location: "eastus", kind: "GlobalDocumentDB", properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: "eastus", failoverPriority: 0 }] } }, "2023-11-15");
await mk(P("Microsoft.ServiceBus", "namespaces", "sb1"), { location: "eastus", sku: { name: "Standard" } }, "2022-10-01-preview");
await mk(P("Microsoft.ContainerRegistry", "registries", "acr1"), { location: "eastus", sku: { name: "Basic" } }, "2023-07-01");
await mk(P("Microsoft.Compute", "virtualMachines", "vm1"), { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B1s" }, osProfile: { computerName: "vm1", adminUsername: "u", adminPassword: "Passw0rd!x1" }, networkProfile: { networkInterfaces: [] } } }, "2024-03-01");
await mk(P("Microsoft.Web", "sites", `fn${n}`), { location: "eastus", kind: "functionapp", properties: {} }, "2023-01-01");
const go = async (route) => { await pg.goto(`${UI}#/`); await pg.waitForTimeout(200); await pg.goto(`${UI}#/${route}`); await pg.waitForTimeout(1500); };
const NS = async () => await pg.locator("[data-vyomi-not-simulated]").count();
// Diagnose
for (const [route, label] of [[`sql/${RG}/sq1/db1/diagnose`, "sql database"], [`cosmos/${RG}/cos1/diagnose`, "cosmos"], [`keyvaults/${RG}/kv1/diagnose`, "key vault"],
  [`storage/${RG}/sa1/diagnose`, "storage"], [`servicebus/${RG}/sb1/diagnose`, "service bus"], [`acr/${RG}/acr1/diagnose`, "acr"]]) {
  await go(route);
  ok(`${label}: diagnose is real`, (await NS()) === 0 && (await pg.locator("[data-testid=diagnose-summary]").count()) === 1);
  ok(`${label}: detectors listed`, (await pg.locator("[data-detector]").count()) >= 3);
}
// Tasks
for (const [route, label] of [[`vms/${RG}/vm1/tasks`, "vm"], [`storage/${RG}/sa1/tasks`, "storage"], [`cosmos/${RG}/cos1/tasks`, "cosmos"], [`keyvaults/${RG}/kv1/tasks`, "key vault"],
  [`servicebus/${RG}/sb1/tasks`, "service bus"], [`sql/${RG}/sq1/db1/tasks`, "sql database"], [`functionapp/${RG}/fn${n}/tasks`, "function app"]]) {
  await go(route);
  ok(`${label}: tasks is real (templates offered)`, (await NS()) === 0 && (await pg.getByText(/Tasks are Logic App workflows/).count()) >= 1);
}
// VM extensions
await go(`vms/${RG}/vm1/extensions`);
ok("vm extensions panel is real", (await NS()) === 0 && (await pg.getByRole("button", { name: "Add" }).count()) >= 1);
await pg.getByRole("button", { name: "Add" }).first().click(); await pg.waitForTimeout(400);
await pg.getByRole("button", { name: "Review + create" }).click(); await pg.waitForTimeout(1200);
const ex = (await arm("GET", `${P("Microsoft.Compute", "virtualMachines", "vm1")}/extensions`, null, "2024-03-01")).body?.value || [];
ok("extension install lands over the wire", ex.some((e) => e.name === "CustomScript"));
ok("installed extension is listed", (await pg.getByText("CustomScript").count()) >= 1);
// Key Vault deleted objects
await dp("PUT", "/secrets/sdel", { value: "x" }); await dp("DELETE", "/secrets/sdel");
await dp("POST", "/keys/kdel/create", { kty: "RSA" }); await dp("DELETE", "/keys/kdel");
await go(`keyvaults/${RG}/kv1/secrets`);
ok("deleted secrets panel lists the secret", (await NS()) === 0 && (await pg.locator("table[aria-label='Deleted secrets']").getByText("sdel").count()) === 1);
await pg.locator("table[aria-label='Deleted secrets']").getByRole("button", { name: "Recover" }).click(); await pg.waitForTimeout(800);
ok("recover over the UI restores the secret on the wire", (await dp("GET", "/secrets/sdel")).body?.value === "x");
await go(`keyvaults/${RG}/kv1/keys`);
ok("deleted keys panel lists the key", (await pg.locator("table[aria-label='Deleted keys']").getByText("kdel").count()) === 1);
await pg.locator("table[aria-label='Deleted keys']").getByRole("button", { name: "Purge" }).click(); await pg.waitForTimeout(800);
ok("purge over the UI removes the key for good", (await dp("GET", "/deletedkeys")).body?.value?.length === 0);
// Entra app registration + user blades
const gr = (m, path, body) => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/v1.0${path}`, body]);
const app = (await gr("POST", "/applications", { displayName: `depth-app-${n}` })).body;
const usr = (await gr("POST", "/users", { displayName: `Depth User ${n}`, userPrincipalName: `depth${n}@vyomilearn.onmicrosoft.com`, mailNickname: `depth${n}`, accountEnabled: true, passwordProfile: { password: "Passw0rd!x1", forceChangePasswordNextSignIn: false } })).body;
ok("graph app + user created", !!app?.id && !!usr?.id);
await go(`entra/appregistrations/${app.id}/exposeanapi`);
ok("expose an API is real", (await NS()) === 0);
await pg.getByLabel("Scope name").fill("access_as_user"); await pg.getByRole("button", { name: "Add a scope" }).click(); await pg.waitForTimeout(900);
ok("scope stored on the application over Graph", (await gr("GET", `/applications/${app.id}`)).body?.api?.oauth2PermissionScopes?.[0]?.value === "access_as_user");
await go(`entra/appregistrations/${app.id}/approles`);
await pg.getByLabel("Role display name").fill("Reader"); await pg.getByLabel("Role value").fill("Task.Read"); await pg.getByRole("button", { name: "Create", exact: true }).click(); await pg.waitForTimeout(900);
ok("app role stored over Graph", (await gr("GET", `/applications/${app.id}`)).body?.appRoles?.[0]?.value === "Task.Read");
await go(`entra/appregistrations/${app.id}/tokenconfiguration`);
await pg.getByLabel("email").first().click(); await pg.waitForTimeout(900);
ok("optional claim stored over Graph", (await gr("GET", `/applications/${app.id}`)).body?.optionalClaims?.idToken?.[0]?.name === "email");
await go(`entra/appregistrations/${app.id}/brandingproperties`);
await pg.getByLabel("Home page URL").fill("https://app.example.test"); await pg.getByRole("button", { name: "Save", exact: true }).click(); await pg.waitForTimeout(900);
ok("branding stored over Graph", (await gr("GET", `/applications/${app.id}`)).body?.web?.homePageUrl === "https://app.example.test");
await go(`entra/appregistrations/${app.id}/integrationassistant`);
ok("integration assistant scores the registration", /of 6/.test(await pg.getByTestId("integration-score").innerText()));
await go(`entra/appregistrations/${app.id}/quickstart`);
ok("quickstart shows the app id", (await pg.getByText(app.appId).count()) >= 1);
await go(`entra/users/${usr.id}/authenticationmethods`);
await pg.getByLabel("New password").fill("N3wPassw0rd!zz"); await pg.getByRole("button", { name: "Reset password" }).last().click(); await pg.waitForTimeout(900);
const tok = await pg.evaluate(async ([u, name]) => { const r = await fetch(u, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ grant_type: "password", username: name, password: "N3wPassw0rd!zz", client_id: "x", scope: "openid" }).toString() }); return r.status; },
  [`${WIRE}/${"00000000-0000-0000-0000-cloudlearn01"}/oauth2/v2.0/token`, usr.userPrincipalName]);
ok("password reset takes effect at the token endpoint", tok === 200, String(tok));
await go(`entra/users/${usr.id}/auditlogs`);
ok("user audit logs list the user's own operations", (await pg.getByText("Update user").count()) >= 1);
await go(`entra/users/${usr.id}/licenses`);
ok("licenses stays an honest gap", (await NS()) === 1);
console.log(`\n${pass} passed, ${fail} failed`);
await b.close(); process.exit(fail ? 1 : 0);
