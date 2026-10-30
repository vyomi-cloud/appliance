/* Offline console conformance — AWS DynamoDB settings tabs (driven against $VYOMI_BASE_URL/console/aws).
 *
 * Creates a table, opens it, and checks that Indexes / Streams / Capacity / Encryption / TTL /
 * Backups / PITR / Insights show this table's real data (DescribeTable & friends) and that an
 * edit saved on a tab survives re-opening the tab.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-dynamodb-settings.mjs
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
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const T = "ui-ddb-settings-" + Math.floor(Math.random() * 1e5);
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
try {
  const cr = await fetch(`${BASE}/api/dynamodb/tables`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ table_name: T, partition_key_name: "pk", sort_key_name: "sk" }) });
  check(cr.ok, "table created", `HTTP ${cr.status}`);
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.locator(RAIL_SEL).filter({ hasText: /DynamoDB\s*$/ }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  await page.locator("#main table a.id, #main table td a").filter({ hasText: T }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const openTab = async (name) => {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp("^\\s*" + name + "\\s*$") }).first().click({ timeout: 5000 });
    await page.waitForTimeout(900);
    return page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText : ""; });
  };
  const noPlaceholder = (t) => !/This pane mirrors|Not yet wired/.test(t);

  let t = await openTab("Indexes");
  check(noPlaceholder(t) && /global secondary indexes/i.test(t), "Indexes tab lists secondary indexes", t.slice(0, 80));
  t = await openTab("Streams and triggers");
  check(noPlaceholder(t) && /Disabled/.test(t), "Streams tab shows the stream status", t.slice(0, 80));
  t = await openTab("Read/write capacity");
  check(/On-demand/.test(t), "Capacity tab shows the on-demand billing mode", t.slice(0, 80));
  await page.locator('[data-testid=ddb-billing]').selectOption("PROVISIONED");
  await page.fill('[data-testid=ddb-rcu]', "7");
  await page.fill('[data-testid=ddb-wcu]', "9");
  await page.click('[data-testid=ddb-capacity-save]');
  await page.waitForTimeout(1200);
  await openTab("Encryption at rest");
  t = await openTab("Read/write capacity");
  check(/Provisioned/.test(t) && /\b7\b/.test(t) && /\b9\b/.test(t), "saved capacity (7/9 provisioned) survives re-opening the tab", t.slice(0, 160));
  t = await openTab("Encryption at rest");
  check(noPlaceholder(t) && /Owned by Amazon DynamoDB/.test(t), "Encryption tab shows the encryption type", t.slice(0, 80));

  t = await openTab("Time to live");
  check(/DISABLED/.test(t), "TTL tab shows DISABLED for a new table", t.slice(0, 80));
  await page.fill('[data-testid=ddb-ttl-attr]', "expires_at");
  await page.click('[data-testid=ddb-ttl-save]');
  await page.waitForTimeout(1200);
  await openTab("Encryption at rest");
  t = await openTab("Time to live");
  check(/ENABLED/.test(t) && /expires_at/.test(t), "TTL on + attribute survives re-opening the tab", t.slice(0, 120));

  t = await openTab("Backups");
  check(noPlaceholder(t) && /No backups/.test(t), "Backups tab starts empty", t.slice(0, 80));
  await page.fill('[data-testid=ddb-backup-name]', "nightly-1");
  await page.click('[data-testid=ddb-backup-create]');
  await page.waitForTimeout(1200);
  await openTab("Encryption at rest");
  t = await openTab("Backups");
  check(/nightly-1/.test(t) && /AVAILABLE/.test(t) && /arn:aws:dynamodb/.test(t), "created backup is listed with status and ARN", t.slice(0, 200));

  t = await openTab("Point-in-time recovery");
  check(noPlaceholder(t) && /Off/.test(t), "PITR tab shows Off", t.slice(0, 80));
  await page.click('[data-testid=ddb-pitr-toggle]');
  await page.waitForTimeout(1200);
  await openTab("Encryption at rest");
  t = await openTab("Point-in-time recovery");
  check(/\bOn\b/.test(t) && /UTC/.test(t), "PITR on survives re-opening, with restore window", t.slice(0, 160));

  t = await openTab("Insights");
  check(noPlaceholder(t) && /Disabled/.test(t), "Insights tab shows Contributor Insights status", t.slice(0, 80));
  await page.click('[data-testid=ddb-insights-toggle]');
  await page.waitForTimeout(1200);
  await openTab("Encryption at rest");
  t = await openTab("Insights");
  check(/Enabled/.test(t), "Contributor Insights enabled survives re-opening", t.slice(0, 120));
} catch (e) {
  check(false, "flow completed", String(e).slice(0, 300));
} finally {
  await fetch(`${BASE}/api/dynamodb/tables/${T}`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
