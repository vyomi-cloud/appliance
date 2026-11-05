/* EventBridge partner event sources (AWS-13): UI <-> native wire.
 *   BASE=http://127.0.0.1:9043 node consoles/tests/smoke-aws-ebpartner.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9043";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SRC = "aws.partner/vyomi.cloud/vyomi-shop/orders";
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const auth = `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/events/aws4_request, SignedHeaders=host, Signature=0`;
const J = (target, body) => page.evaluate(async ([u, a, t, b]) => {
  const r = await fetch(u + "/", { method: "POST", headers: { authorization: a, "x-amz-target": t, "content-type": "application/x-amz-json-1.1" }, body: JSON.stringify(b) });
  const tx = await r.text(); return { status: r.status, json: tx ? JSON.parse(tx) : {} };
}, [WIRE, auth, target, body]);
await page.goto(UI + "#/eventbridge/partner-event-sources");
await page.getByRole("heading", { name: "Vyomi SaaS partners" }).waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Set up source" }).first().click();
await page.getByText(SRC).first().waitFor({ timeout: 10000 });
let l = await J("AWSEvents.ListEventSources", {});
for (let i = 0; i < 20 && !(l.json.EventSources || []).some((s) => s.Name === SRC); i++) { await page.waitForTimeout(500); l = await J("AWSEvents.ListEventSources", {}); }  // Nano: row can render before the wire write lands
check("set up source -> PENDING on the wire", (l.json.EventSources || []).some((s) => s.Name === SRC && s.State === "PENDING"));
await page.locator("tr", { hasText: SRC }).first().getByRole("radio").check();
await page.getByRole("button", { name: "Associate with event bus" }).click();
await page.waitForTimeout(1000);
l = await J("AWSEvents.ListEventSources", {});
check("associate -> ACTIVE", (l.json.EventSources || []).some((s) => s.Name === SRC && s.State === "ACTIVE"));
const b = await J("AWSEvents.DescribeEventBus", { Name: SRC });
check("same-named bus exists", b.status === 200);
await page.getByRole("button", { name: "Send test event" }).first().click();
await page.waitForTimeout(1000);
check("send test event shows success", /sent a "Order Placed" event/.test(await page.locator("body").innerText()));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
