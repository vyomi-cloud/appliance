/* Azure Metrics tab draws MEASURED data (issue #179): N ARM calls against a Key Vault (one
 * failing) show as N requests / 1 error in /api/metrics/series and in the Metrics tab, a
 * second vault shows a different series, an idle vault shows the empty state, and the
 * console source holds no seeded sparkline.
 * Nano by default; offline with VYOMI_CONSOLE_URL=$VYOMI_BASE_URL/console/azure. */
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
const series = (n) => page.evaluate(async (n) => (await (await fetch(`/api/metrics/series?provider=azure&resource=${n}&minutes=5&step=60`)).json()), n);
const SUB = "00000000-0000-0000-0000-cloudlearn01", RG = "cloudlearn-rg";
const vault = (n) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${n}?api-version=2023-07-01`;
try {
  for (const f of ["static/azure-console.html", "wasm/azure-console.html"]) {
    const src = readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
    check(`${f} has no seeded sparkline`, !/buildSparkline/.test(src) && !/1103515245/.test(src));
  }
  if (offlineUrl) {
    await page.goto(offlineUrl, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  } else await bootConsole(page, base, "/azure-console.html");
  const tag = "mt" + Date.now().toString(36).slice(-6);
  const [A, B, C] = ["a", "b", "c"].map((x) => `${tag}${x}`);
  const made = await page.evaluate(async ([paths]) => {
    const out = [];
    for (const p of paths) out.push((await fetch(p, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ location: "eastus", properties: { sku: { family: "A", name: "standard" }, tenantId: "t" } }) })).status);
    return out;
  }, [[A, B, C].map(vault)]);
  check("three key vaults created", made.every((s) => s < 300), JSON.stringify(made));
  await sleep(1000);
  const a0 = await series(A), b0 = await series(B);   // creation traffic is measured too: take deltas
  await page.evaluate(async ([a, b, A, B]) => {
    for (let i = 0; i < 3; i++) await fetch(a);
    await fetch(a.replace("?api-version", "/secrets/no-such-secret?api-version"));
    await fetch(b);
  }, [vault(A), vault(B), A, B]);
  await sleep(500);
  const sa = await series(A), sb = await series(B);
  const dA = sa.total_requests - a0.total_requests, dB = sb.total_requests - b0.total_requests, dE = sa.total_errors - a0.total_errors;
  check("series counts the 4 calls made against vault A", dA === 4, `got ${dA}`);
  check("series counts the failing call as an error", dE === 1, `got ${dE}`);
  check("a second vault has a different series", dB === 1 && sb.total_requests !== sa.total_requests, `B=${dB}`);
  check("series is zero-filled per minute", sa.points.length === 5 && sa.points.every((p) => "requests" in p && "errors" in p && "latency_p95" in p));

  const openMetrics = async (n) => {
    await page.locator("#rail >> text=/Key vaults/i").first().click();
    await sleep(2500);
    await page.locator("#main input[type=search], #main input[type=text], #main input:not([type])").first().fill(n).catch(() => {});
    await sleep(600);
    await page.locator("#main tr", { hasText: n }).locator("td").first().click();
    await sleep(2000);
    await page.locator("#bladeBody .sub-nav *", { hasText: /^\s*Metrics\s*$/ }).last().click();
    await sleep(2000);
    return page.locator("#bladeBody .sub-content").innerText();
  };
  const txtA = await openMetrics(A);
  const req = /(\d+)\s+requests \(last hour\)/i.exec(txtA), err = /(\d+)\s+errors \(last hour\)/i.exec(txtA);
  check("Metrics tab shows the measured request count", !!req && +req[1] >= sa.total_requests, txtA.slice(-200).replace(/\n/g, "|"));
  check("Metrics tab shows the failing call as an error", !!err && +err[1] === sa.total_errors, txtA.slice(-200).replace(/\n/g, "|"));
  check("Metrics tab has no synthesized 'units' values", !/\bunits\b/i.test(txtA));
  const sz = await series(tag + "never-touched");
  check("a never-touched resource reports no requests", sz.total_requests === 0, `got ${sz.total_requests}`);
  check("no page error", errors.length === 0, errors.join(";"));
} catch (e) { check("flow", false, String(e).split("\n")[0] + " :: " + (await page.locator("#main").innerText().catch(() => "")).slice(0, 250).replace(/\n/g, "|")); }
await browser.close(); if (server) server.close();
for (const r of results) console.log(`[${r.ok ? "PASS" : "FAIL"}] ${r.name} ${r.ok ? "" : r.note}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
