/* GCP Metrics tab draws MEASURED data (issue #178): N calls against a resource (one
 * failing) show as N requests / 1 error in /api/metrics/series and in the console's own
 * Metrics-tab renderer; a second resource shows a different series; an idle one shows the
 * empty state; no console holds a seeded sparkline.
 * Nano by default; offline with VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/gcp. */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
import { readFileSync } from "node:fs";
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
const series = (n) => page.evaluate(async (n) => (await (await fetch(`/api/metrics/series?provider=gcp&resource=${n}&minutes=5&step=60`)).json()), n);
try {
  for (const f of ["static/gcp-console.html", "wasm/gcp-console.html"]) {
    const src = readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
    check(`${f} has no seeded sparkline`, !/buildSparkline/.test(src) && !/1103515245/.test(src));
  }
  if (offlineUrl) {
    await page.goto(offlineUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else await bootConsole(page, base, "/gcp-console.html");
  const tag = "mt" + Date.now().toString(36).slice(-6);
  const [A, B] = ["a", "b"].map((x) => `${tag}${x}`);
  const made = await page.evaluate(async (names) => {
    const out = [];
    for (const n of names) out.push((await fetch("/api/gcp/rds/databases", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: n }) })).status);
    return out;
  }, [A, B]);
  check("two resources created", made.every((s) => s < 300), JSON.stringify(made));
  await sleep(1000);
  const a0 = await series(A), b0 = await series(B);
  await page.evaluate(async ([A, B]) => {
    const g = (n, s = "") => fetch(`/api/gcp/rds/databases/${n}${s}`);
    for (let i = 0; i < 3; i++) await g(A);
    await g(A, "/no-such-child");
    await g(B);
  }, [A, B]);
  await sleep(500);
  const sa = await series(A), sb = await series(B);
  const dA = sa.total_requests - a0.total_requests, dB = sb.total_requests - b0.total_requests, dE = sa.total_errors - a0.total_errors;
  check("series counts the 4 calls made against A", dA === 4, `got ${dA}`);
  check("series counts the failing call as an error", dE === 1, `got ${dE}`);
  check("a second resource has a different series", dB === 1, `B=${dB}`);
  check("series is zero-filled per minute", sa.points.length === 5 && sa.points.every((p) => "requests" in p && "errors" in p && "latency_p95" in p));

  const render = (n) => page.evaluate((n) => {
    const host = document.createElement("div"); document.body.append(host);
    renderMetricsTab(host, { key: "pubsub", name_field: "name" }, undefined);
    return new Promise((res) => setTimeout(() => res(host.innerText), 1500));
  }, n);
  const showFor = async (n) => { await page.evaluate((n) => { STATE.item = { name: n }; }, n); return render(n); };
  const txtA = await showFor(A);
  const req = /(\d+)\s+requests \(last hour\)/i.exec(txtA), err = /(\d+)\s+errors \(last hour\)/i.exec(txtA);
  check("Metrics tab shows the measured request count", !!req && +req[1] >= sa.total_requests, txtA.slice(-200).replace(/\n/g, "|"));
  check("Metrics tab shows the failing call as an error", !!err && +err[1] === sa.total_errors, txtA.slice(-200).replace(/\n/g, "|"));
  const txtZ = await showFor(tag + "never-touched");
  check("an idle resource shows the empty state", /No requests for/i.test(txtZ), txtZ.slice(0, 150).replace(/\n/g, "|"));
  check("no page error", errors.length === 0, errors.join(";"));
} catch (e) { check("flow", false, String(e).split("\n")[0]); }
await browser.close(); if (server) server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
