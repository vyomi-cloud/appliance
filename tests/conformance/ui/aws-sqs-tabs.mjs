/* Offline console conformance — AWS SQS Purge + Encryption tabs (against $VYOMI_BASE_URL/console/aws).
 * Purge shows this queue's message counts and empties it; Encryption shows the queue's SSE
 * attributes (SSE-SQS by default, like AWS) and a saved change is visible to GetQueueAttributes
 * and when the tab is reopened.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-sqs-tabs.mjs
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
const Q = "ui-sqs-tabs-" + Math.floor(Math.random() * 1e5);
const J = { "content-type": "application/json" };
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
try {
  check((await fetch(`${BASE}/api/sqs/queues`, { method: "POST", headers: J, body: JSON.stringify({ queue_name: Q }) })).ok, "queue created");
  for (const m of ["a", "b", "c"]) await fetch(`${BASE}/api/sqs/queues/${Q}/messages`, { method: "POST", headers: J, body: JSON.stringify({ message_body: m }) });
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.locator(RAIL_SEL).filter({ hasText: /SQS/ }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  await page.locator("#main table a.id, #main table td a").filter({ hasText: Q }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const openTab = async (name) => {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp("^\\s*" + name + "\\s*$") }).first().click({ timeout: 5000 });
    await page.waitForTimeout(900);
    return page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText : ""; });
  };
  let t = await openTab("Purge messages");
  check(!/This pane mirrors/.test(t) && (await page.locator("[data-testid=sqs-purge-visible]").innerText()).trim() === "3", "Purge tab shows this queue's 3 messages", t.slice(0, 120));
  await page.click("[data-testid=sqs-purge]");
  await page.waitForTimeout(1200);
  await openTab("Encryption");
  t = await openTab("Purge messages");
  check((await page.locator("[data-testid=sqs-purge-visible]").innerText()).trim() === "0", "after Purge the tab shows 0 messages", t.slice(0, 120));

  t = await openTab("Encryption");
  check(/SSE-SQS/.test(t) && /Enabled/.test(t), "Encryption tab shows SSE-SQS enabled by default", t.slice(0, 160));
  await page.selectOption("[data-testid=sqs-sse-type]", "kms");
  await page.fill("[data-testid=sqs-kms-key]", "alias/ui-test-key");
  await page.click("[data-testid=sqs-sse-save]");
  await page.waitForTimeout(1200);
  await openTab("Purge messages");
  t = await openTab("Encryption");
  check(/SSE-KMS/.test(t) && /alias\/ui-test-key/.test(t), "saved KMS key survives re-opening the tab", t.slice(0, 200));
  const attrs = (await (await fetch(`${BASE}/api/sqs/queues/${Q}`)).json()).attributes || {};
  check(attrs.KmsMasterKeyId === "alias/ui-test-key" && !("SqsManagedSseEnabled" in attrs), "queue attributes carry KmsMasterKeyId", JSON.stringify(attrs));
} catch (e) {
  check(false, "flow completed", String(e).slice(0, 300));
} finally {
  await fetch(`${BASE}/api/sqs/queues/${Q}`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
