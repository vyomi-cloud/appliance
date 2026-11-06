/* Azure SQL database Backups + Replicas blades: copy, PITR restore, retention, geo-replica create/failover/terminate.
 *   BASE=http://127.0.0.1:9075 node consoles/tests/smoke-azure-sqlbackup.mjs   (fresh dev server) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9075";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `sqb-rg${n}`, S1 = `sqa${n}`, S2 = `sqb${n}`, DB = "orders";
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (method, path, body, av = "2023-08-01") => wire(`/subscriptions/${SUB}${path}${path.includes("?") ? "&" : "?"}api-version=${av}`, { method, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
const json = (r) => { try { return JSON.parse(r.text); } catch { return {}; } };
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
const srv = (s, loc) => arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${s}`, { location: loc, properties: { administratorLogin: "a", administratorLoginPassword: "P@ssw0rd123!" } });
await srv(S1, "eastus"); await srv(S2, "westus");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${S1}/databases/${DB}`, { location: "eastus", properties: {} });
const dbp = (s, d) => `/resourceGroups/${RG}/providers/Microsoft.Sql/servers/${s}/databases/${d}`;

await page.goto(UI + `#/sql/${RG}/${S1}/${DB}/backups`);
await page.getByText("Earliest PITR restore point").waitFor({ timeout: 20000 });
check("Backups blade is real (no Not-simulated panel)", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
// copy
await page.getByRole("button", { name: "Copy", exact: true }).click();
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.waitForTimeout(1500);
check("Copy created a new database", json(await arm("GET", dbp(S1, `${DB}_copy`))).properties?.createMode === "Copy");
// PITR
await page.getByRole("button", { name: "Restore (point in time)" }).click();
await page.getByRole("dialog").getByRole("button", { name: "Review + create" }).click();
await page.waitForTimeout(1500);
check("PITR restore created a database", json(await arm("GET", dbp(S1, `${DB}_restored`))).properties?.createMode === "PointInTimeRestore");
// retention
await page.getByRole("button", { name: "Configure retention" }).click();
await page.getByRole("textbox", { name: "PITR retention days" }).fill("40");
await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();
await page.getByText(/retention/i).first().waitFor();
await page.waitForTimeout(800);
check("40-day PITR retention is rejected (1-35)", json(await arm("GET", dbp(S1, DB) + "/backupShortTermRetentionPolicies/default")).properties?.retentionDays !== 40);
await page.getByRole("textbox", { name: "PITR retention days" }).fill("14");
await page.getByRole("dialog").getByRole("button", { name: "Apply" }).click();
await page.waitForTimeout(1000);
check("14-day PITR retention applied", json(await arm("GET", dbp(S1, DB) + "/backupShortTermRetentionPolicies/default")).properties?.retentionDays === 14);
// geo replica
await page.goto(UI + `#/sql/${RG}/${S1}/${DB}/replicas`);
await page.getByRole("button", { name: /Create/ }).first().click();
await page.getByRole("dialog").getByRole("combobox", { name: "Target server" }).selectOption(S2);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("Primary").first().waitFor({ timeout: 15000 });
check("geo-replica exists on the other server", json(await arm("GET", dbp(S2, DB))).properties?.createMode === "Secondary");
await page.getByRole("row", { name: /Primary/ }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Forced failover (planned)" }).click();
await page.waitForTimeout(1500);
const lk = json(await arm("GET", dbp(S1, DB) + "/replicaLinks")).value || [];
check("planned failover swapped the roles", lk[0]?.properties?.role === "Secondary", JSON.stringify(lk[0]?.properties));
await page.getByRole("button", { name: /Refresh/ }).first().click().catch(() => {});
await page.getByRole("row", { name: /Secondary/ }).getByRole("checkbox").check();
const lk2 = json(await arm("GET", dbp(S1, DB) + "/replicaLinks")).value;
await page.getByRole("button", { name: "Delete" }).first().click();
await page.getByRole("dialog").getByRole("textbox", { name: "Confirm deletion" }).fill(lk2[0].name);
await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
await page.waitForTimeout(1500);
check("terminate removed the link", ((json(await arm("GET", dbp(S1, DB) + "/replicaLinks")).value) || []).length === 0);
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
