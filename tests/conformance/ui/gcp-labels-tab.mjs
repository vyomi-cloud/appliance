/* GCP console Labels tab (offline appliance): for each service with a label write API
 * (Compute Engine, Pub/Sub, Eventarc) create a resource with the wizard defaults, add a
 * label on its Labels tab, save, reload the console and check the label is still there.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-labels-tab.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};

const boot = async (page) => {
  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
};
const openService = async (page, label) => {
  await page.locator(RAIL_SEL).filter({ hasText: label }).first().click({ timeout: 15000 });
  await sleep(1500);
};
const openLabels = async (page, row) => {
  await page.evaluate((r) => { const a = document.querySelector(`#main table.gc tr[data-row-name="${r}"] a.id`); a && a.click(); }, row);
  await sleep(1500);
  await page.evaluate(() => { const t = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => /Labels/i.test(e.innerText)); t && t.click(); });
  await sleep(1000);
};

const browser = await chromium.launch();
const page = await browser.newPage();
const KEY = "team", VAL = "conformance";
for (const label of ["Compute Engine", "Pub/Sub", "Eventarc"]) {
  try {
    await boot(page);
    await openService(page, label);
    const rowsOf = () => page.evaluate(() => [...document.querySelectorAll("#main table.gc tr[data-row-name]")].map((r) => r.getAttribute("data-row-name")));
    const before = new Set(await rowsOf());
    await page.locator("#main button").filter({ hasText: /^\s*(add\s*)?Create/i }).first().click({ timeout: 8000 });
    await sleep(1000);
    await page.locator("#main button.primary").filter({ hasText: /Create/ }).first().click({ timeout: 8000 });
    let row = null;
    for (let i = 0; i < 15 && !row; i++) { await sleep(800); row = (await rowsOf()).find((r) => !before.has(r)) || null; }
    // Wizard defaults use a fixed name, so on a re-run the resource already exists: reuse it.
    if (!row) {
      // the duplicate create is rejected and leaves the wizard open: cancel back to the grid
      await page.locator("#main button").filter({ hasText: /^\s*Cancel/i }).first().click({ timeout: 3000 }).catch(() => {});
      await sleep(800);
      row = [...before][0] || null;
    }
    if (!check(!!row, `${label}: has a resource with defaults`)) continue;

    await openLabels(page, row);
    const add = page.locator("#main button").filter({ hasText: /Add labels|Edit labels/i }).first();
    check(await add.count() > 0, `${label}: Labels tab offers an editor`);
    await add.click({ timeout: 5000 });
    await page.locator("#main button").filter({ hasText: /Add label$/ }).first().click({ timeout: 5000 });
    const ins = page.locator("#main table.gc input");
    const n = await ins.count();
    await ins.nth(n - 2).fill(KEY);
    await ins.nth(n - 1).fill(VAL);
    await page.locator("#main button.primary").filter({ hasText: /Save/ }).first().click({ timeout: 5000 });
    await sleep(1200);

    await boot(page);
    await openService(page, label);
    await openLabels(page, row);
    const vals = await page.evaluate(() => [...document.querySelectorAll("#main table.gc input")].map((i) => i.value));
    check(vals.includes(KEY) && vals.includes(VAL), `${label}: saved label survives a reload`, JSON.stringify(vals));
  } catch (e) {
    check(false, `${label}: labels flow`, String(e.message || e).split("\n")[0]);
  }
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
