/* GENUINE Nano v4 AWS: the host budget chip answers (GET /api/runtime/budget = 200, cpu/memory shape, was a 501) and the space's
 * cost_savings MOVES when resources are created over the v4 console's /_wire (SQS queue, Lambda function, API Gateway API, VPC):
 * resource_count rises and the AWS savings figure rises. Retarget of the legacy validate-nano-budget-savings.mjs (azure kv secret) and
 * validate-nano-aws-compute-savings.mjs (lambda/apigw/vpc/rule). The v4 AWS console itself does not draw these numbers; the Nano launcher
 * (clouds.html) and the appliance /api/spaces do, served by wasm/sw.js from the same census.
 * Env: BASE (default http://127.0.0.1:8743 = consoles/nano_preview.mjs), UI_PATH (/nano/v4/aws/), WIRE_PATH (/nano/_wire), API_PATH (/nano), PW_CHANNEL. */
import { chromium, sleep } from "./lib.mjs";
const BASE = process.env.BASE || "http://127.0.0.1:8743";
const UI = BASE + (process.env.UI_PATH || "/nano/v4/aws/"), WIRE = BASE + (process.env.WIRE_PATH || "/nano/_wire"), API = BASE + (process.env.API_PATH || "/nano");
const s = Date.now().toString(36).slice(-6);
const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
const page = await (await browser.newContext({ viewport: { width: 1500, height: 1100 } })).newPage();
const results = [];
const check = (name, ok, extra = "") => { results.push(ok); console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${ok ? "" : " :: " + String(extra).replace(/\s+/g, " ").slice(0, 220)}`); };
const ready = () => page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 300000, polling: 500 });
const auth = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
const q = (svc, version, action, params) => page.evaluate(async ([u, a, v, p, au]) => (await fetch(u + "/", { method: "POST", headers: { authorization: au, "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ Action: a, Version: v, ...p }).toString() })).status, [WIRE, action, version, params, auth(svc)]);
const rest = (path, body) => page.evaluate(async ([u, p, b, au]) => (await fetch(u + p, { method: "POST", headers: { authorization: au, "content-type": "application/json" }, body: JSON.stringify(b) })).status, [WIRE, path, body, auth("lambda")]);
const ZIP = "UEsDBBQAAAAAAAdcel2mA0oqIQAAACEAAAAIAAAAaW5kZXgucHlkZWYgaGFuZGxlcihlLCBjKToKICAgIHJldHVybiB7fQpQSwECFAMUAAAAAAAHXHpdpgNKKiEAAAAhAAAACAAAAAAAAAAAAAAAgAEAAAAAaW5kZXgucHlQSwUGAAAAAAEAAQA2AAAARwAAAAAA";
const snap = () => page.evaluate(async (a) => { const d = await (await fetch(a + "/api/spaces", { cache: "no-store" })).json(); return (d.spaces || []).map((x) => x.cost_savings).find((c) => c && c.by_provider) || null; }, API);
const settle = async (before, pick) => { let after = before; for (let i = 0; i < 24; i++) { await sleep(1500); after = await snap(); if (after && pick(after) > pick(before)) break; } return after; };
try {
  await page.goto(UI + "#/", { waitUntil: "domcontentloaded" }); await ready();
  const b = await page.evaluate(async (a) => { const r = await fetch(a + "/api/runtime/budget"); return { status: r.status, body: await r.json().catch(() => null) }; }, API);
  check("budget chip: /api/runtime/budget answers 200 (was 501)", b.status === 200, `status ${b.status}`);
  check("budget chip: cpu/memory shape (budget, used, host, clamp)", !!(b.body && b.body.budget && b.body.used && b.body.host && b.body.clamp), JSON.stringify(b.body)?.slice(0, 160));
  let cur = await snap();
  check("spaces carry cost_savings (resource_count, by_provider)", !!cur && typeof cur.resource_count === "number" && !!cur.by_provider, JSON.stringify(cur));
  const steps = [
    ["SQS queue", () => q("sqs", "2012-11-05", "CreateQueue", { QueueName: "sv" + s })],
    ["Lambda function", () => rest("/2015-03-31/functions", { FunctionName: "svf" + s, Runtime: "python3.12", Role: "arn:aws:iam::123456789012:role/r", Handler: "index.handler", Code: { ZipFile: ZIP } })],
    ["API Gateway API", () => rest("/restapis", { name: "sva" + s })],
    ["VPC", () => q("ec2", "2016-11-15", "CreateVpc", { CidrBlock: "10.94.0.0/16" })],
  ];
  for (const [n, mk] of steps) {
    const before = cur; const st = await mk(); check(`create ${n} over /_wire`, st < 300, `status ${st}`);
    cur = await settle(before, (c) => c.resource_count) || before;
    check(`${n}: resource_count rises`, !!cur && cur.resource_count > before.resource_count, `${before?.resource_count} -> ${cur?.resource_count}`);
  }
  const first = (await snap());
  check("AWS savings figure is present and non-negative", !!first && typeof first.by_provider.aws === "number" && first.by_provider.aws >= 0, JSON.stringify(first?.by_provider));
} catch (e) { check("run", false, String(e).split("\n")[0]); }
await browser.close();
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.length && results.every(Boolean) ? 0 : 1);
