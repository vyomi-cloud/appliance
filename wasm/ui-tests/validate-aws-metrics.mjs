/* AWS Metrics tab draws MEASURED data: N calls against a VPC (one of them failing) show
 * as N requests / 1 error in /api/metrics/series and in the Monitoring chart, a second
 * VPC shows a different series, and an idle resource shows the empty state.
 * Nano by default; offline with VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/aws. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const offlineUrl = process.env.VYOMI_CONSOLE_URL;
let server = null, base = null;
if (!offlineUrl) ({ server, base } = await startServer());
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const results = [];
const check = (name, ok, note = "") => results.push({ name, ok, note });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const series = (id) => page.evaluate(async (id) => (await (await fetch(`/api/metrics/series?provider=aws&service=vpc&resource=${id}&minutes=5&step=60`)).json()), id);
const openRow = async (text) => {   // the grid pages at 10 rows: filter first
  await page.locator("#main input[type=search], #main input[type=text], #main input:not([type])").first().fill(text).catch(() => {});
  await sleep(600);
  await page.locator("#main tr", { hasText: text }).locator("a.id, a").first().click();
};
try {
  if (offlineUrl) {
    await page.goto(offlineUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else await bootConsole(page, base, "/aws-console.html");
  const tag = "mt" + Date.now().toString(36);
  const ids = await page.evaluate(async (tag) => {
    const out = [];
    for (const n of ["a", "b", "c"]) {
      const r = await fetch("/api/vpc/vpcs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: `${tag}-${n}`, cidr_block: "10.7.0.0/16", cidr: "10.7.0.0/16" }) });
      const j = await r.json(); out.push(j.vpc_id || j.id);
    }
    return out;
  }, tag);
  const [A, B, C] = ids;
  check("three VPCs created", ids.every((i) => /^vpc-/.test(i || "")), JSON.stringify(ids));
  await sleep(1000);
  await page.evaluate(async ([A, B]) => {
    for (let i = 0; i < 3; i++) await fetch(`/api/vpc/vpcs/${A}`);
    await fetch(`/api/vpc/vpcs/${A}/no-such-subresource`);
    await fetch(`/api/vpc/vpcs/${B}`);
  }, [A, B]);
  await sleep(500);
  const sa = await series(A), sb = await series(B), sc = await series(C);
  check("series counts the 4 calls made against VPC A", sa.total_requests === 4, `got ${sa.total_requests}`);
  check("series counts the 1 failing call as an error", sa.total_errors === 1, `got ${sa.total_errors}`);
  check("a second VPC has a different series", sb.total_requests === 1 && sb.total_requests !== sa.total_requests, `B=${sb.total_requests}`);
  check("an untouched VPC reports no requests", sc.total_requests === 0, `C=${sc.total_requests}`);
  check("series is zero-filled per minute", sa.points.length === 5 && sa.points.every((p) => "requests" in p && "errors" in p && "latency_p95" in p), `${sa.points.length} points`);

  await page.locator("#rail >> text=/^\\s*(\\w+\\s*)?VPC\\s*$/").first().click();
  await sleep(2500);
  await openRow(`${tag}-a`);
  await sleep(2000);
  await page.locator("#main .top-tabs button", { hasText: /^\s*Metrics\s*$/ }).first().click();
  await sleep(2000);
  const txt = await page.locator("#main").innerText();
  const req = /(\d+)\s+requests \(last hour\)/i.exec(txt), err = /(\d+)\s+errors \(last hour\)/i.exec(txt);
  check("Metrics tab shows the measured request count", !!req && +req[1] >= 4, txt.slice(-250).replace(/\n/g, "|"));
  check("Metrics tab shows the failing call as an error", !!err && +err[1] >= 1, txt.slice(-250).replace(/\n/g, "|"));
  check("Metrics tab has no synthesized 'units' values", !/\bunits\b/i.test(txt));
  check("no page error", errors.length === 0, errors.join(";"));
} catch (e) { check("flow", false, String(e).split("\n")[0] + " :: " + (await page.locator("#main").innerText().catch(() => "")).slice(0, 250).replace(/\n/g, "|")); }
await browser.close(); if (server) server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
