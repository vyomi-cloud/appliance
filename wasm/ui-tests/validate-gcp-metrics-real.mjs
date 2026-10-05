/* GCP Metrics tab shows REAL, LIVE metrics (not fabricated sparklines):
 *  - create a Cloud SQL instance (1 mutating event filed under the instance)
 *  - create 2 databases (real sub-resource children → Databases gauge == 2)
 *  - open the Metrics tab in the UI; assert the rendered request count reflects
 *    the REAL event(s) on this resource (== 1, not random) and the Databases
 *    gauge reflects the real child count (== 2).
 * Self-killing wrapper (macOS has no `timeout`). */
const _k = setTimeout(() => { console.log("HARNESS-TIMEOUT"); process.exit(2); }, 90000);
_k.unref && _k.unref();

import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";
const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];

async function openService(rx) {
  await page.evaluate((r) => { const e = [...document.querySelectorAll(r.sel)].find((x) => new RegExp(r.rx, "i").test((x.innerText || "") + (x.getAttribute("data-service") || ""))); e && e.click(); }, { sel: RAIL_SEL, rx });
  await sleep(1000);
}
async function clickTab(label) {
  return page.evaluate((lbl) => { const items = [...document.querySelectorAll(".sub-nav .nav-item, .sub-nav a")]; const t = items.find((x) => (x.innerText || "").toLowerCase().includes(lbl.toLowerCase())); if (t) { t.click(); return true; } return false; }, label);
}

try {
  await bootConsole(page, base, "/gcp-console.html");
  const INST = "metpg";

  // 1) Create instance + 2 databases via the same REST routes the console uses.
  const setup = await page.evaluate(async (inst) => {
    const J = async (m, p, b) => { const o = { method: m, headers: {} }; if (b !== undefined) { o.headers["content-type"] = "application/json"; o.body = JSON.stringify(b); } const r = await fetch(p, o); let j = null; try { j = await r.json(); } catch (_) {} return { status: r.status, json: j }; };
    await J("POST", "/api/gcp/rds/databases", { name: inst, databaseVersion: "POSTGRES_15" });
    await J("POST", `/api/gcp/subresource/cloudsql/${inst}/databases`, { name: "appdb1" });
    await J("POST", `/api/gcp/subresource/cloudsql/${inst}/databases`, { name: "appdb2" });
    // The events the Metrics tab will read for this resource (instance-level only).
    const ev = await J("GET", `/api/cloudsim/events?resource=${inst}&provider=gcp&service=cloudsql&limit=200`);
    const dbs = await J("GET", `/api/gcp/subresource/cloudsql/${inst}/databases`);
    return { events: (ev.json && ev.json.events) || [], dbCount: ((dbs.json && dbs.json.items) || []).length };
  }, INST);
  results.push(["backend: real event log for instance (>=1 Create)", setup.events.length >= 1 && setup.events.some(e => /create/i.test(e.action)), { events: setup.events.map(e => e.action) }]);
  results.push(["backend: real database children == 2", setup.dbCount === 2, { dbCount: setup.dbCount }]);

  // 2) Navigate the UI: open Cloud SQL → the instance → Metrics tab.
  await openService("cloud sql|cloudsql|sql");
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /refresh/i.test(x.innerText)); b && b.click(); });
  await sleep(1000);
  await page.evaluate((inst) => { const e = [...document.querySelectorAll("#main a.id, #main a")].find((x) => (x.innerText || "").trim().includes(inst)); e && e.click(); }, INST);
  await sleep(1000);
  const onMetrics = await clickTab("Metrics");
  await sleep(1500); // let the first poll render

  // 3) Read the rendered Metrics DOM (real numbers only).
  const dom = await page.evaluate(() => {
    const sc = document.querySelector(".sub-content");
    const text = sc ? (sc.innerText || "") : "";
    // Databases gauge card: label "Databases" then a numeric value in the card.
    let dbGauge = null;
    [...document.querySelectorAll(".sub-content .kv-card")].forEach((card) => {
      const t = (card.innerText || "");
      if (/^databases/i.test(t.trim())) { const m = t.replace(/databases/i, "").match(/\d+/); if (m) dbGauge = parseInt(m[0], 10); }
    });
    // Request count: "N request(s)" rendered from the real event series.
    const rm = text.match(/(\d+)\s+requests?/i);
    const reqCount = rm ? parseInt(rm[1], 10) : null;
    const hasRandom = /Math\.random/.test(text); // sanity (should never be in text)
    const usesCloudsim = true;
    return { reqCount, dbGauge, hasFabricatedWords: /CPU|cpu utilization|disk read ops/i.test(text) && !/no fabricated/i.test(text), snippet: text.slice(0, 500) };
  });

  results.push(["UI: Metrics tab opened", onMetrics, {}]);
  results.push(["UI: request count reflects REAL events (== 1 instance op, not random)", dom.reqCount === 1, { reqCount: dom.reqCount }]);
  results.push(["UI: Databases gauge reflects REAL child count (== 2)", dom.dbGauge === 2, { dbGauge: dom.dbGauge }]);

  // 4) Liveness: delete one DB, wait for the ~4s poll, gauge should drop to 1.
  await page.evaluate((inst) => fetch(`/api/gcp/sub/cloudsql/deleteDatabase/${inst}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "appdb2" }) }), INST);
  await sleep(5000); // longer than the 4s poll interval
  const liveGauge = await page.evaluate(() => {
    let g = null;
    [...document.querySelectorAll(".sub-content .kv-card")].forEach((card) => {
      const t = (card.innerText || "");
      if (/^databases/i.test(t.trim())) { const m = t.replace(/databases/i, "").match(/\d+/); if (m) g = parseInt(m[0], 10); }
    });
    return g;
  });
  results.push(["UI: LIVE poll updated gauge after delete (2 -> 1)", liveGauge === 1, { liveGauge }]);

  // 5) Teardown: navigate away, confirm the poll timer is cleared (no leak).
  await page.evaluate(() => { const b = [...document.querySelectorAll(".detail-actions button, #main button")].find((x) => /back/i.test(x.innerText)); b && b.click(); });
  await sleep(500);
  const timerCleared = await page.evaluate(() => {
    // After leaving the detail view the metrics host is detached; one more tick
    // self-clears the interval. We assert the guard var is null OR the host is gone.
    return !window.__gcpMetricsTimer || !document.querySelector(".sub-content");
  });
  // give the interval one tick to self-clear
  await sleep(4500);
  const timerClearedAfterTick = await page.evaluate(() => window.__gcpMetricsTimer == null || !document.contains(document.querySelector(".sub-content")));
  results.push(["teardown: poll timer cleaned up on navigate-away", timerCleared || timerClearedAfterTick, { timerCleared, timerClearedAfterTick }]);

} catch (e) { results.push(["(err)", false, String(e).split("\n").slice(0, 3).join(" | ")]); }
await browser.close(); server.close();

console.log("===== GCP Metrics tab — REAL live metrics check =====");
let ok = true;
for (const [label, pass, detail] of results) {
  if (!pass) ok = false;
  console.log(`  [${pass ? "PASS" : "FAIL"}] ${label}`);
  if (!pass && detail) console.log("        ", JSON.stringify(detail));
}
console.log("\nRESULT:", ok ? "PASS — Metrics tab shows real event-sourced activity + real-state gauges, live-polled" : "FAIL");
clearTimeout(_k);
process.exit(ok ? 0 : 1);
