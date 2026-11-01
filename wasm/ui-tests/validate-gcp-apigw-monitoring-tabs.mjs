/* GCP console (Nano): API Gateway Configs tab is the editable record list (add persists across
 * reopen), API Gateway Logs shows this resource's recorded requests (not a simulated stream), and
 * Cloud Monitoring's Documentation tab shows the alert policy's own data. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let server;
let fails = 0;
const check = (name, ok, extra = "") => { if (!ok) fails++; console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); };
const rail = (label) => page.evaluate(([sel, l]) => { const e = [...document.querySelectorAll(sel)].find((x) => x.innerText.includes(l)); e && e.click(); return !!e; }, [RAIL_SEL, label]);
const rows = () => page.evaluate(() => [...document.querySelectorAll("#main table.gc tr[data-row-name]")].map((r) => r.getAttribute("data-row-name")));
const openTab = async (row, re) => {
  await page.evaluate((r) => { const a = document.querySelector(`#main table.gc tr[data-row-name="${r}"] a.id`); a && a.click(); }, row);
  await sleep(1500);
  await page.evaluate((src) => { const t = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => new RegExp(src, "i").test(e.innerText)); t && t.click(); }, re);
  await sleep(1200);
};
const ensureRow = async () => {
  const before = new Set(await rows());
  await page.locator("#main button").filter({ hasText: /^\s*(add\s*)?Create/i }).first().click({ timeout: 8000 });
  await sleep(1000);
  await page.locator("#main button.primary").filter({ hasText: /Create/ }).first().click({ timeout: 8000 });
  let row = null;
  for (let i = 0; i < 15 && !row; i++) { await sleep(800); row = (await rows()).find((r) => !before.has(r)) || null; }
  return row || [...before][0] || null;
};
const text = () => page.evaluate(() => document.querySelector("#main").innerText);
try {
  const s = await startServer(); server = s.server;
  await bootConsole(page, s.base, "/gcp-console.html");

  await rail("API Gateway"); await sleep(2000);
  const gw = await ensureRow();
  check("API Gateway: has a gateway", !!gw);
  await openTab(gw, "^\\s*(\\w+\\s)?Configs");
  const addBtn = page.locator("#main button").filter({ hasText: /Add|Create|New/i }).first();
  check("API Gateway: Configs tab offers an Add action", (await addBtn.count()) > 0);
  await addBtn.click({ timeout: 5000 });
  const nameIn = page.locator("#main input, .modal input, [role=dialog] input").first();
  await nameIn.fill("cfg-validate-1");
  await page.locator("button.primary").filter({ hasText: /Add|Create|Save/ }).last().click({ timeout: 5000 });
  await sleep(1200);
  await rail("Compute Engine"); await sleep(1500);
  await rail("API Gateway"); await sleep(2000);
  await openTab(gw, "^\\s*(\\w+\\s)?Configs");
  check("API Gateway: added config survives reopening", (await text()).includes("cfg-validate-1"), (await text()).slice(0, 200));
  await openTab(gw, "^\\s*Logs");
  const lt = await text();
  check("API Gateway: Logs is not a simulated stream", !/SIMULATED|health check ok|cache hit/.test(lt), lt.slice(0, 200));
  check("API Gateway: Logs refers to this gateway", lt.includes(gw), lt.slice(0, 200));

  await rail("Cloud Monitoring"); await sleep(2000);
  const pol = await ensureRow();
  check("Cloud Monitoring: has an alert policy", !!pol);
  await openTab(pol, "Documentation");
  const dt = await text();
  check("Cloud Monitoring: Documentation shows the policy's own data", /policy id/i.test(dt) && /subject/i.test(dt) && /text\/markdown/.test(dt), dt.replace(/\n+/g, " | ").slice(-400));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
if (server) server.close?.();
process.exit(fails ? 1 : 0);
