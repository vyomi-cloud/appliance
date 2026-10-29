/* AWS EC2 instance detail: Status-and-alarms and Monitoring are distinct tabs,
 * and the Networking / Security tabs show the instance's own subnet, security
 * group and launch time instead of "-". Offline: set VYOMI_CONSOLE_URL; else Nano. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + String(extra).slice(0, 200)}`); };
let server;
try {
  if (url) {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else {
    const s = await startServer(); server = s.server;
    await bootConsole(page, s.base, "/aws-console.html");
  }
  const name = "ec2tab" + Date.now().toString(36);
  await page.evaluate(async (n) => {
    await fetch("/api/ec2/instances", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: n, instance_type: "t3.micro", ami: "ami-amzn2023-x86_64", image_id: "ami-amzn2023-x86_64" }) });
  }, name);
  await sleep(800);
  await page.evaluate((sel) => [...document.querySelectorAll(sel)].find((e) => /\bec2\b/i.test(e.innerText.trim()))?.click(), RAIL_SEL);
  await sleep(2000);
  await page.locator("#main tr", { hasText: name }).first().locator("a.id").first().click({ timeout: 15000 });
  await sleep(2000);
  const tab = async (label) => {
    await page.locator(".top-tabs button", { hasText: label }).first().click();
    await sleep(900);
    return page.evaluate(() => document.querySelector("#main")?.innerText || "");
  };
  const status = await tab("Status and alarms");
  const mon = await tab("Monitoring");
  check("Status and alarms shows the status checks", /System reachability/.test(status), status);
  check("Monitoring differs from Status and alarms", mon !== status && /CPU/.test(mon), mon);
  const net = await tab("Networking");
  check("Networking: Subnet ID filled", /Subnet ID\s*\n\s*subnet-/i.test(net), net);
  check("Networking: Security groups filled", !/Security groups\s*\n\s*[—-]\s*(\n|$)/.test(net), net);
  const sec = await tab("Security");
  check("Security: Launch time filled", !/Launch time\s*\n\s*[—-]\s*(\n|$)/.test(sec), sec);
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
