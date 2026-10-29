/* Offline console conformance — RDS instance tabs ($VYOMI_BASE_URL/console/aws).
 *
 * For one DB instance: Endpoints, Networking, Modify, Automated backups, Maintenance, Logs & events
 * and Performance Insights show the instance's real values (no placeholder text); edits made in
 * Modify / Automated backups / Maintenance survive a reload and are visible through the RDS API.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-rds-tabs.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const DB = "rdstabs-" + Date.now().toString(36);
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
async function openDb() {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.locator(RAIL_SEL).filter({ hasText: /RDS\s*$/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1500);
  await page.locator("#main a.id", { hasText: DB }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1500);
}
async function tab(label) {
  await page.locator("#main .top-tabs button").filter({ hasText: label }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1200);
}
const main = () => page.locator("#main").innerText();
const api = async (m, p, b) => (await fetch(`${BASE}${p}`, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined })).json();
try {
  await api("POST", "/api/rds/databases", { name: DB, engine: "postgres", instance_class: "db.t3.micro" });
  await openDb();
  for (const t of ["Endpoints", "Networking", "Modify", "Automated backups", "Maintenance", "Logs & events", "Performance Insights"]) {
    await tab(t);
    const txt = await main();
    check(!/This pane mirrors|Not yet wired|placeholder/i.test(txt), `${t}: no placeholder text`);
    check(txt.includes(DB), `${t}: shows this instance`);
  }
  await tab("Networking");
  const net = await main();
  check(/vpc-[0-9a-f]+/.test(net) && /sg-[0-9a-f]+/.test(net), "Networking shows the instance's real VPC and security group ids");

  await tab("Modify");
  await page.locator("[data-testid=rds-allocated_storage]").fill("55");
  await page.locator("[data-testid=rds-db_instance_class]").selectOption("db.t3.small");
  await page.locator("#main button", { hasText: "Apply changes" }).click();
  await page.waitForTimeout(1000);
  await tab("Automated backups");
  await page.locator("[data-testid=rds-retention-input]").fill("12");
  await page.locator("#main button", { hasText: "Save retention" }).click();
  await page.waitForTimeout(1000);
  await tab("Maintenance");
  await page.locator("[data-testid=rds-window-input]").fill("mon:04:00-mon:04:30");
  await page.locator("#main button", { hasText: "Save window" }).click();
  await page.waitForTimeout(1000);

  await openDb();
  await tab("Modify");
  check((await page.locator("[data-testid=rds-allocated_storage]").inputValue()) === "55", "storage edit survives reload");
  check((await page.locator("[data-testid=rds-db_instance_class]").inputValue()) === "db.t3.small", "instance class edit survives reload");
  await tab("Automated backups");
  check((await page.locator("[data-testid=rds-retention]").innerText()).trim() === "12 days", "backup retention survives reload");
  await tab("Maintenance");
  check((await page.locator("[data-testid=rds-window]").innerText()).trim() === "mon:04:00-mon:04:30", "maintenance window survives reload");
  await tab("Logs & events");
  const evText = await main();
  check((await page.locator("[data-testid=rds-event]").count()) >= 4 && /CreateDBInstance/.test(evText) && /ModifyDBInstance/.test(evText), "Logs & events lists this instance's create + modify events");
  const db = await api("GET", `/api/rds/databases/${DB}`);
  check(db.allocated_storage === 55 && db.backup_retention_period === 12 && db.db_instance_class === "db.t3.small", "RDS API returns the console edits");
  check(!bad.length, "no API 5xx while using the tabs", bad.join(", "));
} catch (e) {
  check(false, "RDS tabs flow ran to completion", String(e).split("\n")[0]);
} finally {
  await fetch(`${BASE}/api/rds/databases/${DB}`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
