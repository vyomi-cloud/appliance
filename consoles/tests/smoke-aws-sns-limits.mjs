/* SNS maximum message size + TTL fields are real: set a topic cap in the create form, a publish over it is rejected by the core,
 * a publish with a TTL is accepted and an out-of-range TTL is refused.   BASE=http://127.0.0.1:9084 node consoles/tests/smoke-aws-sns-limits.mjs */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9084";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
const OUT = process.env.OUT || "smoke-out";
const T = `limits-${Date.now() % 100000}`;
const results = [];
const check = (name, ok, d = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1600 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const body = () => page.locator("body").innerText();
await page.goto(UI + "#/sns/create-topic");
await page.getByLabel("Maximum message size").waitFor();
check("max size is a real field (no Not-simulated panel)", !/Not simulated in Vyomi/i.test(await body()));
await page.getByLabel("Name", { exact: true }).fill(T);
await page.getByLabel("Maximum message size").fill("200");
await page.getByRole("button", { name: "Create topic" }).last().click();
await page.waitForURL(new RegExp(`#/sns/topics/${T}`), { timeout: 15000 });
const attrs = await page.evaluate(async ([t]) => { const r = await fetch(`/_wire/`, { method: "POST", headers: { authorization: "AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/sns/aws4_request, SignedHeaders=host, Signature=0", "content-type": "application/x-www-form-urlencoded" }, body: `Action=GetTopicAttributes&TopicArn=arn:aws:sns:us-east-1:123456789012:${t}` }); return r.text(); }, [T]);
check("VyomiMaximumMessageSize stored on the topic", /VyomiMaximumMessageSize[\s\S]*?200/.test(attrs));
// over the cap
await page.goto(UI + `#/sns/topics/${T}/publish`);
await page.getByLabel("Message body").fill("x".repeat(260));
await page.getByRole("button", { name: "Publish message" }).last().click();
await page.getByText(/Message too long/).first().waitFor({ timeout: 10000 });
check("publish over the cap is rejected", true);
await page.getByLabel("Message body").fill("x".repeat(20));
await page.getByLabel("Time to Live").fill("9999999");
await page.getByRole("button", { name: "Publish message" }).last().click();
await page.getByText(/TTL must be a whole number|Enter a whole number of seconds/).first().waitFor({ timeout: 10000 }).catch(async () => { console.log((await body()).slice(0, 1500)); throw new Error("no ttl error"); });
check("out-of-range TTL is rejected by the core", true);
await page.getByLabel("Time to Live").fill("3600");
await page.screenshot({ path: `${OUT}/sns-limits.png`, fullPage: true });
await page.getByRole("button", { name: "Publish message" }).last().click();
await page.waitForURL(new RegExp(`#/sns/topics/${T}$`), { timeout: 15000 });
check("publish within cap + valid TTL succeeds", true);
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
const bad = results.filter((r) => !r.ok);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
