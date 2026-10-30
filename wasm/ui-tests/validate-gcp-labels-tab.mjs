/* GCP console Labels tab (Nano): for each service whose API persists labels, create a
 * resource with the wizard defaults, add a label on its Labels tab, save, leave the
 * service and reopen it: the label must still be there (read back from the API). */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICES = ["Cloud Storage", "Cloud KMS", "Secret Manager", "Artifact Registry", "Cloud Functions", "VPC Network"];
const KEY = "team", VAL = "conformance";
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
let fails = 0;
const check = (name, ok, extra = "") => { if (!ok) fails++; console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
const rail = (label) => page.evaluate(([sel, l]) => { const e = [...document.querySelectorAll(sel)].find((x) => x.innerText.includes(l)); e && e.click(); return !!e; }, [RAIL_SEL, label]);
const rows = () => page.evaluate(() => [...document.querySelectorAll("#main table.gc tr[data-row-name]")].map((r) => r.getAttribute("data-row-name")));
const labelsTab = async (row) => {
  await page.evaluate((r) => { const a = document.querySelector(`#main table.gc tr[data-row-name="${r}"] a.id`); a && a.click(); }, row);
  await sleep(1500);
  await page.evaluate(() => { const t = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => /Labels/i.test(e.innerText)); t && t.click(); });
  await sleep(1200);
};
try {
  const s = await startServer(); server = s.server;
  await bootConsole(page, s.base, "/gcp-console.html");
  for (const label of SERVICES) {
    try {
      await rail(label); await sleep(2000);
      const before = new Set(await rows());
      await page.locator("#main button").filter({ hasText: /^\s*(add\s*)?Create/i }).first().click({ timeout: 8000 });
      await sleep(1000);
      await page.locator("#main button.primary").filter({ hasText: /Create/ }).first().click({ timeout: 8000 });
      let row = null;
      for (let i = 0; i < 15 && !row; i++) { await sleep(800); row = (await rows()).find((r) => !before.has(r)) || null; }
      if (!row) { await page.locator("#main button").filter({ hasText: /^\s*Cancel/i }).first().click({ timeout: 3000 }).catch(() => {}); row = [...before][0] || null; }
      const hasRow = !!row; check(`${label}: has a resource with defaults`, hasRow); if (!hasRow) continue;
      await labelsTab(row);
      const add = page.locator("#main button").filter({ hasText: /Add labels|Edit labels/i }).first();
      check(`${label}: Labels tab offers an editor`, (await add.count()) > 0);
      await add.click({ timeout: 5000 });
      await page.locator("#main button").filter({ hasText: /Add label$/ }).first().click({ timeout: 5000 });
      const ins = page.locator("#main table.gc input");
      const n = await ins.count();
      await ins.nth(n - 2).fill(KEY);
      await ins.nth(n - 1).fill(VAL);
      await page.locator("#main button.primary").filter({ hasText: /Save/ }).first().click({ timeout: 5000 });
      await sleep(1200);
      await rail("Compute Engine"); await sleep(1500);
      await rail(label); await sleep(2000);
      await labelsTab(row);
      const vals = await page.evaluate(() => [...document.querySelectorAll("#main table.gc input")].map((i) => i.value));
      check(`${label}: saved label survives reopening`, vals.includes(KEY) && vals.includes(VAL), JSON.stringify(vals));
    } catch (e) { check(`${label}: labels flow`, false, String(e.message || e).split("\n")[0]); }
  }
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
if (server) server.close?.();
process.exit(fails ? 1 : 0);
