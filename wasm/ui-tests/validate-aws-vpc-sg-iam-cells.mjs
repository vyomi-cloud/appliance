/* AWS VPC "Security groups" tab shows the group id and name (crawler PLACEHOLDER_CELL), and
 * IAM users carry an ARN.
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
  const name = "vpcsg" + Date.now().toString(36);
  const uname = "u" + Date.now().toString(36);
  const made = await page.evaluate(async ([n, u]) => {
    await fetch("/api/vpc/vpcs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: n, cidr_block: "10.78.0.0/16" }) });
    await fetch("/api/iam/users", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ user_name: u }) });
    const sgs = (await (await fetch("/api/vpc/security-groups")).json()).security_groups || [];
    const users = (await (await fetch("/api/iam/users")).json()).users || [];
    return { sgs, user: users.find((x) => x.user_name === u) };
  }, [name, uname]);
  check("IAM user listing carries an ARN", /^arn:aws:iam::\d{12}:user\/.+/.test(made.user?.arn || ""), JSON.stringify(made.user));
  await page.evaluate(([sel]) => [...document.querySelectorAll(sel)].find((e) => /\bvpc\b/i.test(e.innerText.trim()))?.click(), [RAIL_SEL]);
  await sleep(2000);
  await page.locator("#main input.search").first().fill(name); // list is paged (10/page): filter so the new VPC is on screen
  await sleep(500);
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().click();
  await sleep(2000);
  const txt = await tabText("Security groups");
  const rows = await page.evaluate(() => [...document.querySelectorAll("#main table tr")].map((r) => [...r.querySelectorAll("td")].map((c) => c.innerText.trim())).filter((c) => c.length));
  check("Security groups tab lists a row", rows.length > 0, txt.slice(-200));
  check("Security group rows show id and name", rows.length > 0 && rows.every((c) => /^sg-/.test(c[0]) && c[1] && c[1] !== "—" && c[1] !== "-"), JSON.stringify(rows));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
