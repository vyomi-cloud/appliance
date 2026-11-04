/* Backup and DR (GCP lens): UI <-> native backupdr v1 wire; backups are real Compute snapshots.
 *   python3 consoles/dev_server.py --port 9091 -q &   PROJECT=nano-project BASE=http://127.0.0.1:9091 node consoles/tests/smoke-gcp-backupdr.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9071";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await page.goto(UI, { waitUntil: "networkidle" });
if (process.env.PROJECT) { await page.evaluate((p) => localStorage.setItem("vyomi.v4.gcp.project", p), process.env.PROJECT); await page.reload({ waitUntil: "networkidle" }); }   // dev_server (no Space) only knows nano-project
const project = await page.evaluate(() => { try { return localStorage.getItem("vyomi.v4.gcp.project") || (document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano" ? "nano-project" : "vyomi-project"); } catch { return "nano-project"; } });
const W = (method, path, body) => page.evaluate(async ([u, m, b]) => { const r = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return { status: r.status, text: await r.text() }; }, [WIRE + path, method, body]);
const L = `/v1/projects/${project}/locations/us-central1`;
const inst = await W("POST", `/compute/v1/projects/${project}/zones/us-central1-a/instances`, { name: "bdr-vm", machineType: "e2-medium", disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }] });
check("instance created", inst.status === 200 || inst.status === 409, inst.text);
await page.goto(`${UI}#/backupdr`);
await page.getByRole("button", { name: "Create backup vault" }).click();
await page.getByLabel("Backup vault name").fill("smoke-vault");
await page.getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("cell", { name: "smoke-vault" }).waitFor({ timeout: 15000 });
check("vault created in the UI", true);
const plan = await W("POST", `${L}/backupPlans?backupPlanId=smoke-plan`, { resourceType: "compute.googleapis.com/Instance", backupVault: `projects/${project}/locations/us-central1/backupVaults/smoke-vault`, backupRules: [{ ruleId: "daily", backupRetentionDays: 7, standardSchedule: { recurrenceType: "DAILY", backupWindow: { startHourOfDay: 2, endHourOfDay: 6 } } }] });
check("plan created", plan.status === 200, plan.text);
const asc = await W("POST", `${L}/backupPlanAssociations?backupPlanAssociationId=smoke-assoc`, { resourceType: "compute.googleapis.com/Instance", resource: `projects/${project}/zones/us-central1-a/instances/bdr-vm`, backupPlan: `projects/${project}/locations/us-central1/backupPlans/smoke-plan` });
check("instance protected", asc.status === 200, asc.text);
await page.goto(`${UI}#/backupdr?tab=protected`); await page.reload({ waitUntil: "networkidle" });
await page.getByRole("button", { name: "Back up now" }).click();
await page.goto(`${UI}#/backupdr?tab=backups`); await page.reload({ waitUntil: "networkidle" });
await page.getByRole("cell", { name: "ON_DEMAND" }).waitFor({ timeout: 15000 });
check("on-demand backup listed", true);
const snaps = await W("GET", `/compute/v1/projects/${project}/global/snapshots`);
check("a real Compute snapshot backs it", /vyomi-backupdr/.test(snaps.text), snaps.text.slice(0, 80));
await page.getByRole("button", { name: "Restore" }).first().click();
await page.getByLabel("New resource name").fill("bdr-vm-restored");
await page.getByRole("button", { name: "Restore", exact: true }).last().click();
await page.waitForTimeout(1500);
const got = await W("GET", `/compute/v1/projects/${project}/zones/us-central1-a/instances/bdr-vm-restored`);
check("restore created a new instance", got.status === 200, got.text.slice(0, 80));
await W("DELETE", `${L}/backupPlanAssociations/smoke-assoc`);
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
