/* Smoke: Create Web App wizard > Database tab. Drives the REAL wizard (Azure SQL new server + database, then
 * Cosmos DB for NoSQL new account + database), then verifies over the native ARM wire that the database exists in its
 * own lens and the web app got the connection string.
 *   BASE=http://127.0.0.1:9142 PW=<playwright path> [SHOT=<dir>] node consoles/tests/smoke-azure-appsdb.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9142";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000, RG = `appsdb-rg-${n}`;
const SQLAPP = `sqlapp${n}`, SRV = `appsrv${n}`, DB = `appdb${n}`, COSAPP = `cosapp${n}`, ACCT = `appcos${n}`, CDB = `cosdb${n}`;
let pass = 0, fail = 0;
const ok = (name, c, d = "") => { c ? pass++ : fail++; console.log(`[${c ? "PASS" : "FAIL"}] ${name}${c ? "" : " " + d}`); };
let pg;
const arm = (m, path, body, v = "2023-12-01") => pg.evaluate(async ([m, url, body]) => {
  const r = await fetch(url, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); return { status: r.status, body: t ? JSON.parse(t) : null };
}, [m, `${WIRE}/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${v}`, body]);
const b = await pw.chromium.launch(); pg = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
await pg.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await pg.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await arm("PUT", `/resourcegroups/${RG}`, { location: "eastus" }, "2021-04-01");
const shot = async (name) => { if (process.env.SHOT) await pg.screenshot({ path: `${process.env.SHOT}/${name}.png`, fullPage: true }); };

async function wizard(app, dbSetup, shotTag) {
  await pg.goto(`${UI}#/appservices/create`); await pg.waitForTimeout(1500);
  await pg.getByLabel("Resource Group", { exact: true }).selectOption(RG);
  await pg.getByLabel("Name", { exact: true }).fill(app);
  await pg.getByRole("tab", { name: "Database" }).click(); await pg.waitForTimeout(400);
  ok("Database tab no longer says not-simulated for the create flow", !(await pg.locator("[data-vyomi-not-simulated]").filter({ hasText: "not modelled" }).count()));
  await pg.getByLabel("Create a Database").check();
  await dbSetup(); await shot(`${shotTag}-database-tab`);
  await pg.getByRole("button", { name: /Review \+ create/ }).first().click(); await pg.waitForTimeout(500);
  await shot(`${shotTag}-review`);
  await pg.getByRole("button", { name: "Create", exact: true }).click();
  await pg.waitForURL(new RegExp(`#/appservices/${RG}/${app}`), { timeout: 30000 }); await pg.waitForTimeout(1500);
}

// ── Azure SQL: new server + database ───────────────────────────────────────────────
await wizard(SQLAPP, async () => {
  await pg.getByLabel("New server name").fill(SRV);
  await pg.getByLabel("Database name").fill(DB);
  await pg.getByLabel("Server admin login").fill("sqladmin");
  await pg.getByLabel("Password", { exact: true }).fill("Sup3rS3cret!");
  await pg.getByLabel("Confirm password").fill("Sup3rS3cret!");
}, "sql");
const sdb = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${SRV}/databases/${DB}`, null, "2023-08-01");
ok("SQL database exists over ARM (own lens)", sdb.status === 200 && sdb.body.sku.name === "Basic", JSON.stringify(sdb.body).slice(0, 200));
const scs = (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${SQLAPP}/config/connectionstrings`)).body.properties || {};
ok("web app has AZURE_SQL_CONNECTIONSTRING (SQLAzure)", scs.AZURE_SQL_CONNECTIONSTRING?.type === "SQLAzure"
  && scs.AZURE_SQL_CONNECTIONSTRING.value.includes(`Server=tcp:${SRV}.database.windows.net`) && scs.AZURE_SQL_CONNECTIONSTRING.value.includes(`Initial Catalog=${DB}`), JSON.stringify(scs));
await pg.goto(`${UI}#/sql/${RG}/${SRV}/${DB}`); await pg.waitForTimeout(1500);
ok("database visible in the SQL lens UI", (await pg.content()).includes(DB));
await shot("sql-lens");

// ── Cosmos DB for NoSQL: new account + database ────────────────────────────────────
await wizard(COSAPP, async () => {
  await pg.getByLabel("Engine").selectOption("cosmos");
  await pg.getByLabel("New Cosmos DB account name").fill(ACCT);
  await pg.getByLabel("Database name").fill(CDB);
}, "cosmos");
const acct = await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.DocumentDB/databaseAccounts/${ACCT}`, null, "2024-05-15");
ok("Cosmos account exists over ARM", acct.status === 200 && acct.body.name === ACCT);
const dbs = await pg.evaluate(async ([u, a]) => (await (await fetch(u, { headers: { "x-vyomi-account": a } })).json()).Databases || [], [`${WIRE}/dbs`, ACCT]);
ok("Cosmos database exists on the data plane", dbs.some((d) => d.id === CDB), JSON.stringify(dbs).slice(0, 200));
const ccs = (await arm("GET", `/resourceGroups/${RG}/providers/Microsoft.Web/sites/${COSAPP}/config/connectionstrings`)).body.properties || {};
ok("web app has AZURE_COSMOS_CONNECTIONSTRING (DocDb) with the account key", ccs.AZURE_COSMOS_CONNECTIONSTRING?.type === "DocDb"
  && ccs.AZURE_COSMOS_CONNECTIONSTRING.value.startsWith(`AccountEndpoint=https://${ACCT}.documents.azure.com:443/;AccountKey=`), JSON.stringify(ccs));
await pg.goto(`${UI}#/cosmos/${RG}/${ACCT}`); await pg.waitForTimeout(1500);
ok("account visible in the Cosmos lens UI", (await pg.content()).includes(ACCT));
await shot("cosmos-lens");

await pg.goto(`${UI}#/appservices/${RG}/${SQLAPP}/envvars`); await pg.waitForTimeout(1500);
await b.close();
console.log(`\n${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
