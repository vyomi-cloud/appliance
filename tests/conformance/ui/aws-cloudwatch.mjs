/* Offline console conformance — AWS CloudWatch (driven against $VYOMI_BASE_URL/console/aws).
 *
 * Opens the service from the rail, creates an alarm with the form's DEFAULT values,
 * checks every grid column of the new row is filled, opens the alarm, renders every
 * detail tab (non-empty), then deletes it.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-cloudwatch.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
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
const STACK = "my-alarm";   // the create form's default name (an alarm, here)

const browser = await chromium.launch();
const page = await browser.newPage();
const bad = [];
let createStatus = null;
page.on("dialog", (d) => d.accept().catch(() => {}));
page.on("response", (r) => {
  if (r.request().method() === "POST" && /\/api\/aws\/cloudwatch\/alarms/.test(r.url())) createStatus = r.status();
  if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
});
try {
  // start clean: a previous run may have left the default-named alarm behind
  await fetch(`${BASE}/api/aws/cloudwatch/alarms/${STACK}`, { method: "DELETE" }).catch(() => {});
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: /CloudWatch\s*$/ }).first();
  check(await rail.count() > 0, "CloudWatch is on the AWS console rail");
  await rail.click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  check(!bad.length, "opening CloudWatch causes no API 5xx", bad.join(", "));

  await page.locator("#main button, #main [role=button]").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1200);
  check((await page.locator("#main input").count()) >= 2, "create form shows the alarm name + metric fields");
  await page.locator("#main button.primary, #main button").filter({ hasText: /^\s*create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 20 && createStatus === null; i++) await page.waitForTimeout(500);
  check(createStatus !== null && createStatus < 300, "create with the default values returns 2xx", `HTTP ${createStatus}`);

  await page.waitForTimeout(1500);
  const headers = await page.locator("#main table th").allInnerTexts();
  const cells = await page.locator("#main table tr:has(td)").filter({ hasText: STACK }).first().locator("td").allInnerTexts();
  check(cells.length > 0, "the new alarm appears in the list", `rows with ${STACK}: ${cells.length}`);
  const dataCells = cells.slice(Math.max(0, cells.length - headers.length));   // skip a leading checkbox cell
  const blank = dataCells.map((c, i) => [headers[i], c.trim()]).filter(([h, c]) => (c === "" || c === "-" || c === "—") && h.trim() !== "");
  check(cells.length > 0 && !blank.length, "every grid column of the new row is filled", `blank: ${JSON.stringify(blank)}`);
  check(cells.some((c) => /INSUFFICIENT_DATA/.test(c)), "alarm state is INSUFFICIENT_DATA until data arrives", cells.join(" | "));

  await page.locator("#main table a.id, #main table td a").filter({ hasText: STACK }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const tabs = await page.locator("#main .top-tabs button").allInnerTexts();
  for (const want of ["Details", "History", "Actions"])
    check(tabs.some((t) => t.trim() === want), `detail tab "${want}" is present`, tabs.join(", "));
  for (let i = 0; i < tabs.length; i++) {
    await page.locator("#main .top-tabs button").nth(i).click();
    await page.waitForTimeout(500);
    const txt = await page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText.trim() : ""; });
    check(txt.length >= 10, `detail tab "${tabs[i].trim()}" renders content`, `len=${txt.length}`);
  }
  const detTab = tabs.findIndex((t) => t.trim() === "Details");
  await page.locator("#main .top-tabs button").nth(detTab).click();
  await page.waitForTimeout(500);
  const detText = await page.locator("#main").innerText();
  check(/CPUUtilization/.test(detText) && /AWS\/EC2/.test(detText), "Details tab shows the metric the alarm watches");
  const actTab = tabs.findIndex((t) => t.trim() === "Actions");
  await page.locator("#main .top-tabs button").nth(actTab).click();
  await page.waitForTimeout(500);
  check(/arn:aws:sns:us-east-1:123456789012:alerts/.test(await page.locator("#main").innerText()), "Actions tab lists the SNS alarm action");

  await page.locator("#main button").filter({ hasText: /delete/i }).last().click({ timeout: 5000 });
  let gone = false;
  for (let i = 0; i < 12 && !gone; i++) {
    await page.waitForTimeout(800);
    gone = (await page.locator("#main table tr:has(td)").filter({ hasText: STACK }).count()) === 0;
  }
  check(gone, "deleting the alarm removes it from the list");
  const list = await (await fetch(`${BASE}/api/aws/cloudwatch/alarms`)).json();
  check(!list.items.some((s) => s.name === STACK), "alarm is gone from the API too");
  check(!bad.length, "no API 5xx during the whole flow", bad.join(", "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
