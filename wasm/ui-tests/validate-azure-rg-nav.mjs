/* Opening "Resource groups" from Home must replace the Home dashboard at once.
 * selectRG used to await the ARM list before clearing #main, so for a slow list
 * the Home service cards (count placeholders "—") stayed on screen under the
 * Resource groups title. Works against Nano (default) or offline (VYOMI_CONSOLE_URL).
 */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
const srv = url ? null : await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); if (!ok) failed++; };

try {
  if (url) { await page.goto(url, { waitUntil: "domcontentloaded" }); await page.waitForSelector("#navItems .navitem", { timeout: 60000 }); }
  else await bootConsole(page, srv.base, "/azure-console.html");
  await sleep(1500);
  // Make the Resource groups list slow so the transient state is observable.
  await page.evaluate(() => {
    const orig = window.arm;
    window.arm = async (m, p, ...r) => { if (/\/resourcegroups$/i.test(p)) await new Promise((x) => setTimeout(x, 2500)); return orig(m, p, ...r); };
  });
  await page.locator("#navItems .navitem", { hasText: /Resource groups\s*$/ }).first().click();
  await sleep(500);
  const mid = await page.locator("#main").innerText();
  check(!/Services — click to manage/.test(mid), "Home dashboard is gone while the list loads", mid.slice(0, 120));
  check(/Resource groups/.test(mid), "Resource groups page header shown while loading");
  await page.waitForFunction(() => document.querySelectorAll("#main table tr td").length > 0, null, { timeout: 15000 });
  const end = await page.locator("#main").innerText();
  check(/Name\s+Location\s+Status/.test(end) && !/Loading…/.test(end), "list renders with Name/Location/Status", end.slice(0, 160));
} catch (e) {
  check(false, "validator ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
srv?.server.close();
process.exit(failed ? 1 : 0);
