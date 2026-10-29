/* The Nano boot/status banner is fixed to the bottom of the viewport and used to
 * swallow clicks on whatever sat under it — the last service in the Azure rail
 * ("Storage queues") could not be opened while it showed. The banner is
 * informational: it must never intercept pointer events. The permanent relay-tunnel
 * footer covered it too: the rail must leave room so the last service can be reached.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let failed = 0;
const check = (ok, name, extra = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + extra}`); if (!ok) failed++; };
try {
  await bootConsole(page, base, "/azure-console.html");
  const pe = await page.evaluate(() => { const b = document.getElementById("nano-banner"); return b ? getComputedStyle(b).pointerEvents : "no-banner"; });
  check(pe === "none" || pe === "no-banner", "Nano banner does not intercept pointer events", `pointer-events=${pe}`);
  const items = page.locator(RAIL_SEL);
  const last = items.nth((await items.count()) - 1);
  const label = (await last.innerText()).trim().split("\n").pop();
  let ok = true, err = "";
  try { await last.click({ timeout: 5000 }); } catch (e) { ok = false; err = String(e.message).split("\n")[0]; }
  check(ok, `last rail service (${label}) opens while the banner is showing`, err);
  await sleep(1000);
  check((await page.locator("#main").innerText()).includes(label), `${label} page renders`);
} catch (e) {
  check(false, "validator ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
process.exit(failed ? 1 : 0);
