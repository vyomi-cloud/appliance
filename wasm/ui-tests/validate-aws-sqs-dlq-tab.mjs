/* AWS SQS detail > Dead-letter queue tab: a queue without a redrive policy shows
 * "Disabled", not a blank "Maximum receives" cell (real-console behaviour).
 * Offline: VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws. Nano: no URL (NANO_DIR/RELAY_HTTP). */
import { chromium, sleep, RAIL_SEL, startServer, bootConsole } from "./lib.mjs";

let url = process.env.VYOMI_CONSOLE_URL, server = null;
if (!url) { const s = await startServer(); server = s.server; url = null; var nanoBase = s.base; }
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const checks = [];
const check = (name, ok, extra = "") => { checks.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " " + extra}`); };
try {
  if (url) {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else await bootConsole(page, nanoBase, "/aws-console.html");
  const name = "dlq" + Date.now().toString(36);
  await page.evaluate(async (n) => {
    await fetch("/api/sqs/queues", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: n }) });
  }, name);
  await page.evaluate(([sel]) => [...document.querySelectorAll(sel)].find((e) => /\bsqs\b/i.test(e.innerText.trim()))?.click(), [RAIL_SEL]);
  await sleep(2000);
  await page.locator("#main tr", { hasText: name }).locator("a.id").first().click();
  await sleep(2000);
  await page.locator("#main .top-tabs button", { hasText: /dead-letter queue/i }).first().click();
  await sleep(1500);
  const txt = await page.evaluate(() => document.querySelector("#main")?.innerText || "");
  check("DLQ tab shows Disabled for a queue without redrive", /Disabled/.test(txt), txt.slice(-300));
  check("DLQ tab has no blank Maximum receives", !/Maximum receives\s*(—|-|$)/m.test(txt), txt.slice(-300));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close(); server?.close?.();
process.exit(checks.length && checks.every(Boolean) ? 0 : 1);
