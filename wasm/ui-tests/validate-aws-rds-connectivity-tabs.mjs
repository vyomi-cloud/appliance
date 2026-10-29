/* AWS RDS detail: Endpoints and Networking tabs show the instance's endpoint/port
 * (not "—") and the Networking tab has RDS fields, not EC2 IPv4 addresses.
 * Offline: VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws. Nano: no URL (NANO_DIR/RELAY_HTTP). */
import { chromium, sleep, RAIL_SEL, startServer, bootConsole } from "./lib.mjs";

let url = process.env.VYOMI_CONSOLE_URL, server = null, nanoBase = null;
if (!url) { const s = await startServer(); server = s.server; nanoBase = s.base; }
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
const tabText = async (tab) => {
  await page.locator("#main .top-tabs button", { hasText: new RegExp("^\\s*" + tab + "\\s*$") }).first().click();
  await sleep(1500);
  return page.evaluate(() => document.querySelector("#main")?.innerText || "");
};
try {
  if (url) {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else await bootConsole(page, nanoBase, "/aws-console.html");
  const name = "rdsc" + Date.now().toString(36);
  await page.evaluate(async (n) => {
    await fetch("/api/rds/databases", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: n }) });
  }, name);
  await page.evaluate(([sel]) => [...document.querySelectorAll(sel)].find((e) => /\brds\b/i.test(e.innerText.trim()))?.click(), [RAIL_SEL]);
  await sleep(2000);
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().click();
  await sleep(2000);
  const ep = await tabText("Endpoints");
  check("Endpoints tab shows a real endpoint", /ENDPOINT\s*\n\s*[\w.-]{3,}/i.test(ep) && !/ENDPOINT\s*\n\s*—/i.test(ep), ep.slice(-250));
  const net = await tabText("Networking");
  check("Networking tab has RDS endpoint + subnet group", /Endpoint/i.test(net) && /Subnet group/i.test(net), net.slice(-300));
  check("Networking tab has no EC2 IPv4 rows", !/Private IPv4|Public IPv4/i.test(net), net.slice(-300));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
