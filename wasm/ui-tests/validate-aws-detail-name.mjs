/* AWS DynamoDB table and SQS queue detail: opening a resource from the grid
 * must fetch /api/<svc>/<collection>/<its name> (not an empty name -> 404) and
 * the detail tabs must show that resource's own data. Offline console only
 * (set VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws); Nano already keys by name. */
import { chromium, sleep, RAIL_SEL } from "./lib.mjs";

const url = process.env.VYOMI_CONSOLE_URL;
if (!url) { console.log("[FAIL] VYOMI_CONSOLE_URL not set"); process.exit(1); }
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
const bad = [];
page.on("response", (r) => { if (r.status() === 404 && /\/api\/(dynamodb\/tables|sqs\/queues)\//.test(r.url())) bad.push(r.url()); });
try {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  const stamp = Date.now().toString(36);
  const t = "dtl" + stamp, q = "dtlq" + stamp;
  await page.evaluate(async ([t, q]) => {
    const j = { method: "POST", headers: { "content-type": "application/json" } };
    await fetch("/api/dynamodb/tables", { ...j, body: JSON.stringify({ table_name: t, partition_key_name: "id", partition_key_type: "S" }) });
    await fetch("/api/sqs/queues", { ...j, body: JSON.stringify({ queue_name: q }) });
  }, [t, q]);
  for (const [svc, rx, name] of [["DynamoDB", /dynamodb/i, t], ["SQS", /\bsqs\b/i, q]]) {
    bad.length = 0;
    await page.evaluate(([sel, src]) => [...document.querySelectorAll(sel)].find((e) => new RegExp(src, "i").test(e.innerText.trim()))?.click(), [RAIL_SEL, rx.source]);
    await sleep(2000);
    // The grid pages at 10 rows; filter so this run's resource is on page 1.
    await page.locator("#main input[type=search], #main input[type=text], #main input:not([type])").first().fill(name).catch(() => {});
    await sleep(500);
    await page.locator("#main a.id, #main td a", { hasText: name }).first().click();
    await sleep(2000);
    const head = await page.evaluate(() => document.querySelector("#main h1")?.innerText || "");
    check(`${svc}: detail heading is the resource name`, head.trim() === name, head);
    check(`${svc}: no 404 fetching the resource`, bad.length === 0, bad.join(","));
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  }
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
