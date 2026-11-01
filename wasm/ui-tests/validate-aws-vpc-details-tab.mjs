/* AWS VPC detail: the "VPC details" tab shows the VPC's own attributes and is not
 * identical to Overview (crawler DEAD_TAB).
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
  const name = "vpcd" + Date.now().toString(36);
  const cidr = "10.77.0.0/16";
  await page.evaluate(async ([n, c]) => {
    await fetch("/api/vpc/vpcs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: n, cidr_block: c }) });
  }, [name, cidr]);
  await page.evaluate(([sel]) => [...document.querySelectorAll(sel)].find((e) => /\bvpc\b/i.test(e.innerText.trim()))?.click(), [RAIL_SEL]);
  await sleep(2000);
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().waitFor({ timeout: 60000 });
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().click();
  await sleep(2000);
  const ov = await tabText("Overview");
  const det = await tabText("VPC details");
  check("VPC details tab differs from Overview", det !== ov, det.slice(-200));
  check("VPC details tab shows CIDR, tenancy, DHCP option set, main route table", det.includes(cidr) && /Tenancy/i.test(det) && /dopt-/.test(det) && /rtb-/.test(det), det.slice(-400));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
