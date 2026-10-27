/* AWS API Gateway detail: the Resources and Stages tabs must request
 * /api/apigateway/apis/<rest_api_id>/... (not the API's display name -> 404).
 * Offline console only (set VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws). */
import { chromium, sleep, RAIL_SEL } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
if (!url) { console.log("[FAIL] VYOMI_CONSOLE_URL not set"); process.exit(1); }
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
const bad = [];
page.on("response", (r) => { if (r.status() === 404 && /\/api\/apigateway\/apis\//.test(r.url())) bad.push(r.url()); });
try {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  const name = "agw" + Date.now().toString(36);
  await page.evaluate(async (n) => {
    await fetch("/api/apigateway/apis", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: n }) });
  }, name);
  await page.evaluate(([sel]) => [...document.querySelectorAll(sel)].find((e) => /api gateway/i.test(e.innerText.trim()))?.click(), [RAIL_SEL]);
  await sleep(2000);
  await page.locator("#main input[type=search], #main input[type=text], #main input:not([type])").first().fill(name).catch(() => {});
  await sleep(500);
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().click();
  await sleep(2000);
  for (const tab of ["Resources", "Stages"]) {
    bad.length = 0;
    await page.locator("#main .top-tabs button", { hasText: new RegExp("^\\s*" + tab + "\\s*$") }).first().click();
    await sleep(1500);
    check(`API Gateway ${tab} tab: no 404`, bad.length === 0, bad.join(","));
    const txt = await page.evaluate(() => document.querySelector("#main")?.innerText || "");
    check(`API Gateway ${tab} tab: does not show a load error`, !/failed|error|404/i.test(txt), txt.slice(0, 120));
  }
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
