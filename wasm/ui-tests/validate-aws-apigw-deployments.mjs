/* AWS API Gateway detail: Deployments and Logs/Tracing tabs show this API's own
 * deployments and execution logs (not the "This pane mirrors…" placeholder).
 * Offline console only (set VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws). */
import { chromium, sleep, RAIL_SEL } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
if (!url) { console.log("[FAIL] VYOMI_CONSOLE_URL not set"); process.exit(1); }
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  const name = "agwd" + Date.now().toString(36);
  const ids = await page.evaluate(async (n) => {
    const j = (r) => r.json();
    const h = { "content-type": "application/json" };
    const a = await j(await fetch("/api/apigateway/apis", { method: "POST", headers: h, body: JSON.stringify({ name: n }) }));
    const d = await j(await fetch(`/api/apigateway/apis/${a.rest_api_id}/deployments`, { method: "POST", headers: h, body: JSON.stringify({ stage_name: "dev", description: "first release" }) }));
    return { api: a.rest_api_id, dep: d.deployment.deployment_id };
  }, name);
  await page.evaluate(([sel]) => [...document.querySelectorAll(sel)].find((e) => /api gateway/i.test(e.innerText.trim()))?.click(), [RAIL_SEL]);
  await sleep(2000);
  await page.locator("#main input[type=search], #main input[type=text], #main input:not([type])").first().fill(name).catch(() => {});
  await sleep(500);
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().click();
  await sleep(2000);
  const tab = async (t) => {
    await page.locator("#main .top-tabs button", { hasText: new RegExp("^\\s*" + t + "\\s*$") }).first().click();
    await sleep(1500);
    return page.evaluate(() => document.querySelector("#main")?.innerText || "");
  };
  let txt = await tab("Deployments");
  check("Deployments tab lists this API's deployment id", txt.includes(ids.dep), txt.slice(0, 160));
  check("Deployments tab is not the placeholder", !/This pane mirrors|Not yet wired/i.test(txt));
  txt = await tab("Logs/Tracing");
  check("Logs/Tracing tab is not the placeholder", !/This pane mirrors|Not yet wired/i.test(txt), txt.slice(0, 160));
  check("Logs/Tracing tab shows the empty state for an uninvoked API", /No execution logs/i.test(txt), txt.slice(0, 160));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
