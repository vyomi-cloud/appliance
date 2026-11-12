#!/usr/bin/env node
/* Per-section probe for baseline gap-queue sections whose "Not simulated" panel is gone but whose
 * state the registry could not determine (gap-status.py "closed-unmatched").
 *
 *   BASE=http://127.0.0.1:9231 PW=<playwright> node consoles/tests/gap-probe.mjs <old-queue.json> <out.json> [offline-scan-dir]
 *   env: UI_PATH=/v4/ (Nano: /nano/v4/ + NANO=1)  ONLY=aws,gcp
 *
 * For every baseline item it opens the item's ORIGINAL routes (tab from `where` clicked), then records:
 *   - ns:      a Not-simulated panel is still present (→ not a closed section after all)
 *   - caps:    data-vyomi-capability ids rendered on that page (registry level is looked up by gap-status.py)
 *   - titleHit: the section title text is visible on the page (the real page replaced the panel)
 *   - text:    short evidence excerpt around the title
 * Routes that carry fixture-created resource ids (e.g. #/s3/buckets/gs68b3d) do not exist in a fresh store;
 * those fall back to the service list route and the result is flagged `needsResource`.
 * Text only, never aborts on a page failure. */
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const pw = require(process.env.PW || "playwright");
const BASE = process.env.BASE || "http://127.0.0.1:9231";
const NANO = !!process.env.NANO;
const UIROOT = process.env.UI_PATH || "/v4/";
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;
const [oldFile, outFile] = process.argv.slice(2);
const old = JSON.parse(readFileSync(oldFile, "utf8"));
const strip = (t) => (t || "").replace(/^[^|]{1,60} \| /, "").replace(/^The page /, "").trim();
const items = [];
for (const b of old.batches) for (const t of b.themes) for (const i of t.items) if (!ONLY || ONLY.has(b.cloud)) items.push({ cloud: b.cloud, ...i });

const browser = await pw.chromium.launch();
const results = [];
for (const cloud of ["aws", "gcp", "azure"]) {
  const mine = items.filter((i) => i.cloud === cloud);
  if (!mine.length) continue;
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage(); page.setDefaultTimeout(4000); page.on("pageerror", () => {});
  const UI = `${BASE}${UIROOT}${cloud}/`;
  try {
    await page.goto(UI, { waitUntil: NANO ? "domcontentloaded" : "load" });
    if (NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
    await page.waitForTimeout(2000);
  } catch (e) { console.error("boot", cloud, e.message.slice(0, 100)); }
  const cache = new Map();   // route|tab → page snapshot
  const snap = async (hash, tab) => {
    const key = hash + "|" + (tab || "");
    if (cache.has(key)) return cache.get(key);
    let r;
    try {
      await page.evaluate((h) => { location.hash = h; }, hash.slice(1));
      await page.waitForTimeout(900);
      if (tab) { const t = page.getByRole("tab", { name: tab, exact: false }).first(); if (await t.count()) { await t.click({ timeout: 2000 }).catch(() => {}); await page.waitForTimeout(500); } }
      r = await page.evaluate(() => {
        const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
        const txt = clean(document.body.innerText);
        return {
          len: txt.length, text: txt.slice(0, 20000),
          ns: [...document.querySelectorAll("[data-vyomi-not-simulated]")].map((e) => e.getAttribute("data-vyomi-not-simulated")),
          caps: [...document.querySelectorAll("[data-vyomi-capability]")].map((e) => [e.getAttribute("data-vyomi-capability-id"), e.getAttribute("data-vyomi-capability")]),
          err: /something went wrong|page not found|404|no route/i.test(txt.slice(0, 600)),
        };
      });
    } catch (e) { r = { len: 0, text: "", ns: [], caps: [], err: true, fail: e.message.slice(0, 80) }; }
    cache.set(key, r); return r;
  };
  for (const it of mine) {
    const title = strip(it.title), tl = title.toLowerCase();
    const tab = (it.where || []).map((w) => /^tab:(.+)/.exec(w)?.[1]).find(Boolean);
    const rts = (it.routes && it.routes.length ? it.routes : ["#/" + it.service]).slice(0, 3);
    let best = null;
    for (const route of rts.concat(["#/" + it.service])) {
      const s = await snap(route, tab);
      const hit = tl.length > 2 && s.text.toLowerCase().includes(tl);
      const cand = { route, tab: tab || null, titleHit: hit, ns: s.ns.length, nsSame: s.ns.some((n) => tl.includes((n || "").toLowerCase()) || (n || "").toLowerCase().includes(tl)), caps: s.caps, len: s.len, err: s.err, fallback: route === "#/" + it.service && !rts.includes(route) };
      if (hit) { const i = s.text.toLowerCase().indexOf(tl); cand.text = s.text.slice(Math.max(0, i - 40), i + 140); }
      if (!best || (cand.titleHit && !best.titleHit) || (cand.nsSame && !best.titleHit)) best = cand;
      if (cand.titleHit || cand.nsSame) break;
    }
    results.push({ cloud, service: it.service, title: it.title, capabilityId: it.capabilityId, ...best });
  }
  await ctx.close();
  writeFileSync(outFile, JSON.stringify(results, null, 1));
  console.log(cloud, "probed", mine.length);
}
await browser.close();
