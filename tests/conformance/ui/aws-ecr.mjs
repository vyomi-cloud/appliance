/* ECR console conformance, offline (Playwright against $VYOMI_BASE_URL/console/aws).
 *
 * Open ECR from the service rail → create a repository with the form's defaults →
 * every grid column filled (never "-"/blank) → open it, every detail tab renders
 * (and differs from the last) → delete it → it leaves the list.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-ecr.mjs
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
const ROWS = "#main table tr:has(td)";

const browser = await chromium.launch();
const page = await browser.newPage();
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
page.on("dialog", (d) => d.accept().catch(() => {}));
try {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: /ECR\s*$/ }).first();
  check(await rail.count() > 0, "ECR is on the AWS console service rail");
  await rail.click({ timeout: 5000 });
  await page.waitForTimeout(1500);

  const before = await page.locator(ROWS).count();
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1200);
  const name = `ui-ecr-${Date.now().toString(36)}`;
  const nameInput = page.locator("#main input").first();
  await nameInput.fill(name);
  await page.locator("#main button").filter({ hasText: /create/i }).filter({ hasNotText: /cancel/i }).last().click({ timeout: 5000 });
  await page.waitForTimeout(2500);
  let after = await page.locator(ROWS).count();
  for (let i = 0; i < 8 && after <= before; i++) { await page.waitForTimeout(700); after = await page.locator(ROWS).count(); }
  check(after > before, "creating a repository with the form defaults adds a row", `rows ${before} → ${after}`);

  const row = page.locator(ROWS).filter({ hasText: name }).first();
  check(await row.count() === 1, "the new repository is listed by name", name);
  const heads = await page.locator("#main table tr:first-child th").allInnerTexts();
  const cells = await row.locator("td").allInnerTexts();
  const blanks = heads.map((h, i) => [h.trim(), (cells[i] || "").trim()])
    .filter(([h, v]) => h && !/^(actions?|select)$/i.test(h) && /^(-|—|–|n\/a|null|none)?$/i.test(v));
  check(heads.length >= 6 && blanks.length === 0, "every grid column of the new repository is filled",
    `blank: ${blanks.map((b) => b[0]).join(", ")} (columns: ${heads.join("|")})`);
  check(cells.join(" ").includes("/" + name), "URI column shows the repository URI");

  await row.locator("a").first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const tabs = await page.locator(".top-tabs button").allInnerTexts();
  check(tabs.length >= 4, "repository detail has tabs", tabs.join(", "));
  let prev = await page.locator("#main").innerText();
  for (let t = 1; t < tabs.length; t++) {
    await page.locator(".top-tabs button").nth(t).click({ timeout: 5000 });
    await page.waitForTimeout(900);
    const txt = await page.locator("#main").innerText();
    check(txt.trim().length > 20 && txt !== prev && !/coming soon|not implemented|undefined|\[object Object\]/i.test(txt),
      `detail tab "${tabs[t].trim()}" renders its own content`);
    prev = txt;
  }

  await page.locator("#main button").filter({ hasText: /delete/i }).first().click({ timeout: 5000 });
  await page.waitForTimeout(2500);
  let gone = false;
  for (let i = 0; i < 8 && !gone; i++) { gone = (await page.locator(ROWS).filter({ hasText: name }).count()) === 0; if (!gone) await page.waitForTimeout(700); }
  check(gone, "deleting the repository removes it from the list");
  check(!bad.length, "no API 5xx while using the ECR console", bad.join(", "));
} catch (e) {
  check(false, "ECR console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
