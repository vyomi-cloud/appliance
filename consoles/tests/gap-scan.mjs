#!/usr/bin/env node
/* Gap scanner: find every section of the v4 consoles that still shows "Not simulated in Vyomi"
 * (DOM: [data-vyomi-not-simulated]), plus the "Limited in Vyomi"/"Config only" counts (reported
 * separately - they are NOT the implementation queue).
 *
 *   BASE=http://127.0.0.1:9121 node consoles/tests/gap-scan.mjs aws gcp azure                        (offline)
 *   BASE=http://127.0.0.1:9123 UI_PATH=/nano/v4/ WIRE_PATH=/nano/_wire NANO=1 node consoles/tests/gap-scan.mjs aws
 *   env: OUT=<dir> (default consoles/gap-scan-out)  PW=<playwright path>  ONLY=s3,ec2 (service filter)
 *        MAX_PAGES=900  PAGE_MS=25000  SKIP_BFS=1  SKIP_MODALS=1
 *
 * Route sources (union): (1) route tables in consoles/src/<cloud>/services/** (parameter-free patterns),
 * (2) spec-map.json routes - their `fixtures` / `live` fixtures (services/<svc>/fixtures.mjs) are run
 * through the page's own fetch first, so detail routes get a real resource and `{live}` is substituted,
 * (3) a BFS over every <a href="#/..."> found on each page / tab (sidebar, row links, tabs) which also
 * reaches detail pages of resources the fixtures created.
 * On every page: click every [role=tab] (nested too), expand the spec-map `expand` selectors, step
 * through wizards (Next), and open the main action buttons (modals/drawers) and cancel.
 * Findings are de-duplicated by (cloud, service, capability id | feature) and written incrementally to
 * <OUT>/<substrate>-<cloud>.json. Text only, no screenshots. Never aborts the run on a page failure. */
import { createRequire } from "node:module";
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); }
catch { pw = require("/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance/16ae368c-31b1-4512-8411-8e4b65fe67d1/scratchpad/pw/node_modules/playwright"); }

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = join(ROOT, "consoles", "src");
const BASE = process.env.BASE || "http://127.0.0.1:9121";
const NANO = !!process.env.NANO;
const UIROOT = process.env.UI_PATH || "/v4/";          // + <cloud>/
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || join(ROOT, "consoles", "gap-scan-out");
const SUB = NANO ? "nano" : "offline";
const MAX_PAGES = Number(process.env.MAX_PAGES || 900);
const PAGE_MS = Number(process.env.PAGE_MS || 25000);
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;
const clouds = process.argv.slice(2).length ? process.argv.slice(2) : ["aws", "gcp", "azure"];
mkdirSync(OUT, { recursive: true });

const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : /\.(jsx|js)$/.test(p) ? [p] : []; });
const svcOf = (hashPath) => (hashPath.replace(/^#?\/?/, "").split(/[/?]/)[0]) || "(home)";
const matchPat = (pat, path) => { const a = pat.split("/").filter(Boolean), b = path.split("/").filter(Boolean); return a.length === b.length && a.every((s, i) => s.startsWith(":") || s === b[i]); };
const DANGER = /delete|terminate|remove|empty|reboot|stop|destroy|purge|revoke|detach|disassociate|release|deregister|close|disable|reset|cancel|discard|sign out|log ?out/i;
const ACTION = /^(create|add|launch|upload|import|new|register|attach|associate|allocate|connect|enable|manage|set up|start|request|generate|copy|edit|configure|assign|invite|share|view|deploy|run|test|simulate|apply|restore|schedule)\b/i;

/** capability registry: not_simulated + level counts, and note→id lookup */
function loadRegistry(cloud) {
  const dir = join(ROOT, "core", "capabilities", cloud), reg = {};
  if (!existsSync(dir)) return reg;
  for (const f of readdirSync(dir).filter((x) => x.endsWith(".json"))) {
    const svc = f.replace(".json", ""), j = JSON.parse(readFileSync(join(dir, f), "utf8"));
    for (const [id, e] of Object.entries(j)) if (!id.startsWith("$")) reg[id] = { svc, title: e.title, level: e.level || {}, limitations: e.limitations || [] };
  }
  return reg;
}

for (const cloud of clouds) {
  const reg = loadRegistry(cloud);
  const noteToId = new Map(Object.entries(reg).map(([id, e]) => [e.limitations.join(" ").trim(), id]).filter(([n]) => n));
  const findings = new Map();      // key → finding
  const limited = new Map();       // capability id → {level, svc, routes:Set}
  const visited = new Set(), visitedRoutes = [], errors = [], queue = [];
  const queued = new Set(), perShape = new Map();
  const outFile = join(OUT, `${SUB}-${cloud}.json`);
  const flush = () => writeFileSync(outFile, JSON.stringify({
    cloud, substrate: SUB, base: BASE, at: new Date().toISOString(), pagesVisited: visitedRoutes.length,
    findings: [...findings.values()].map((f) => ({ ...f, routes: [...f.routes], contexts: [...f.contexts] })),
    limited: [...limited].map(([id, v]) => ({ id, level: v.level, svc: v.svc, routes: [...v.routes].slice(0, 5) })),
    visited: visitedRoutes, errors: errors.slice(0, 200),
  }, null, 1));

  // ---- route sources
  const patterns = new Set(), routes = new Set();
  for (const f of walk(join(SRC, cloud, "services")).concat(walk(join(SRC, cloud, "pages")))) {
    const t = readFileSync(f, "utf8");
    for (const m of t.matchAll(/pattern:\s*"(\/[^"]*)"/g)) { patterns.add(m[1]); if (!m[1].includes(":")) routes.add("#" + m[1]); }
    for (const m of t.matchAll(/href:\s*"#(\/[^"?$]+)"/g)) if (!m[1].includes(":")) routes.add("#" + m[1]);
  }
  const specRoutes = [];   // {svc, route, fixtures, live, expand}
  const fxBySvc = {};
  const svcDir = join(SRC, cloud, "services");
  for (const svc of readdirSync(svcDir).filter((d) => statSync(join(svcDir, d)).isDirectory())) {
    if (ONLY && !ONLY.has(svc)) continue;
    const fx = join(svcDir, svc, "fixtures.mjs");
    if (existsSync(fx)) { try { fxBySvc[svc] = (await import(pathToFileURL(fx).href)).default || {}; } catch (e) { errors.push(`fixtures ${svc}: ${e.message}`); } }
    const sm = join(svcDir, svc, "spec-map.json");
    if (existsSync(sm)) for (const [id, m] of Object.entries(JSON.parse(readFileSync(sm, "utf8")))) if (m && m.route) specRoutes.push({ svc, id, ...m });
  }
  // GCP has a subpages.json hint file
  const sub = join(svcDir, "subpages.json");
  if (existsSync(sub)) { try { const j = JSON.parse(readFileSync(sub, "utf8")); (function w(o) { for (const v of Object.values(o || {})) { if (typeof v === "string" && v.startsWith("#/")) routes.add(v); else if (v && typeof v === "object") w(v); } })(j); } catch { /* ignore */ } }

  const browser = await pw.chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  page.setDefaultTimeout(4000);
  page.on("pageerror", () => {});
  const UI = `${BASE}${UIROOT}${cloud}/`;

  try {
    await page.goto(UI, { waitUntil: NANO ? "domcontentloaded" : "load" });
    if (NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
    await page.waitForTimeout(2500);
  } catch (e) { errors.push("boot: " + e.message.slice(0, 120)); }

  // wire() for fixtures runs INSIDE the page so it works on Nano (service worker) and offline alike.
  const sign = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;
  const wire = async (method, path, { headers = {}, body, svc = "s3", target } = {}) => {
    const h = { ...(svc ? { authorization: sign(svc) } : {}), ...headers };
    if (target) Object.assign(h, { "x-amz-target": target, "content-type": "application/x-amz-json-1.0" });
    const isBin = body instanceof Uint8Array;
    const b = body === undefined ? undefined : (typeof body === "string" || isBin ? (isBin ? Array.from(body) : body) : JSON.stringify(body));
    const r = await page.evaluate(async ([u, m, hd, bd, bin]) => {
      const x = await fetch(u, { method: m, headers: hd, body: bd === undefined ? undefined : bin ? new Uint8Array(bd) : bd });
      return { ok: x.ok, status: x.status, text: await x.text() };
    }, [WIRE + path, method, h, b, isBin]);
    if (!r.ok) throw new Error(`${method} ${path} -> ${r.status} ${r.text.slice(0, 120)}`);
    try { return JSON.parse(r.text); } catch { return r.text; }
  };
  const fixtureLog = [];
  const runFx = async (svc, name, uniq) => {
    const fn = fxBySvc[svc]?.[name];
    if (!fn) return null;
    try { return await fn(wire, uniq); } catch (e) { fixtureLog.push(`${svc}/${name}: ${e.message.slice(0, 140)}`); return null; }
  };

  // ---- page probe (runs in the page)
  const probe = () => page.evaluate(() => {
    const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
    const out = { ns: [], textNs: 0, cap: [] };
    const els = [...document.querySelectorAll("[data-vyomi-not-simulated]")];
    for (const el of els) {
      const box = el.closest("[data-vyomi-gap-box]") || el;
      const feature = el.getAttribute("data-vyomi-not-simulated") || "";
      const heading = box.querySelector("h1,h2,h3,[class*=header] h2")?.textContent;
      const full = clean(box.innerText || el.innerText);
      const note = clean(full.replace(/Not simulated in Vyomi/gi, "").replace(feature + " isn't backed by a Vyomi backend yet.", "").replace(heading || "\u0000", ""));
      out.ns.push({ feature, title: clean(heading) || feature, note: note.slice(0, 400), badge: /Not simulated in Vyomi/i.test(full) ? "Not simulated in Vyomi" : clean(el.textContent).slice(0, 40) });
    }
    // badge text that lacks the attribute (should be zero; flag it)
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) if (/Not simulated in Vyomi/i.test(n.nodeValue) && !n.parentElement.closest("[data-vyomi-not-simulated]")) out.textNs++;
    for (const el of document.querySelectorAll("[data-vyomi-capability]")) out.cap.push([el.getAttribute("data-vyomi-capability-id"), el.getAttribute("data-vyomi-capability")]);
    out.links = [...new Set([...document.querySelectorAll('a[href^="#/"]')].map((a) => a.getAttribute("href")))];
    out.tabs = document.querySelectorAll("[role=tab]").length;
    return out;
  }).catch(() => ({ ns: [], textNs: 0, cap: [], links: [], tabs: 0 }));

  const record = (hash, ctxName, p) => {
    const service = svcOf(hash);
    for (const n of p.ns) {
      const capId = noteToId.get(n.note) || null;
      const norm = (n.feature || n.title || "").replace(/^[^|]{1,60} \| /, "");   // ARM blades: "<resource> | Insights" -> "Insights"
      const key = `${cloud}|${service}|${capId || norm}`;
      let f = findings.get(key);
      if (!f) { f = { cloud, service, capabilityId: capId, feature: n.feature, title: n.title, badge: n.badge, note: n.note, routes: new Set(), contexts: new Set(), count: 0 }; findings.set(key, f); }
      f.count++; f.routes.add(hash.replace(/\?.*/, "")); f.contexts.add(ctxName);
    }
    if (p.textNs) { const key = `${cloud}|${service}|__textonly__${hash}`; if (!findings.has(key)) findings.set(key, { cloud, service, capabilityId: null, feature: "(badge text without data-vyomi-not-simulated)", title: hash, badge: "Not simulated in Vyomi", note: "", routes: new Set([hash]), contexts: new Set([ctxName]), count: p.textNs }); }
    for (const [id, level] of p.cap) { if (!id) continue; const v = limited.get(id) || { level, svc: service, routes: new Set() }; v.routes.add(hash); limited.set(id, v); }
  };
  const enqueue = (h, front) => {
    if (process.env.NO_SEED) return;
    if (!h || !h.startsWith("#/")) return;
    const key = h.replace(/\?.*/, "");
    if (queued.has(h) || queued.has(key) && !h.includes("?")) return;
    // cap near-duplicate shapes (e.g. hundreds of object rows) per (svc, first two segs, depth)
    const segs = key.slice(2).split("/"), shape = `${segs[0]}/${segs[1] || ""}/${segs.length}`;
    const n = perShape.get(shape) || 0;
    if (n >= Number(process.env.SHAPE_CAP || 8)) return;
    perShape.set(shape, n + 1);
    if (ONLY && !ONLY.has(segs[0])) return;
    queued.add(h); queued.add(key);
    front ? queue.unshift({ hash: h }) : queue.push({ hash: h });
  };

  const goto = async (hash) => {
    // Use the hash route inside the SPA (no reload) when already on this app, for speed.
    const cur = page.url();
    if (cur.startsWith(UI)) { await page.evaluate((h) => { location.hash = h; }, hash.slice(1)); }
    else await page.goto(UI + hash, { waitUntil: "load" });
    await page.waitForTimeout(700);
    await page.waitForLoadState("networkidle", { timeout: 3000 }).catch(() => {});
  };

  async function scanTabs(hash, ctxName, depth = 0) {
    const tabs = page.locator("[role=tab]");
    const n = Math.min(await tabs.count().catch(() => 0), 24);
    const seen = new Set();
    for (let i = 0; i < n; i++) {
      const t = tabs.nth(i);
      const label = ((await t.innerText({ timeout: 800 }).catch(() => "")) || `#${i}`).trim().split("\n")[0].slice(0, 40);
      const sig = label + "|" + depth; if (seen.has(sig)) continue; seen.add(sig);
      if (!(await t.isVisible().catch(() => false))) continue;
      if ((await t.getAttribute("aria-disabled").catch(() => null)) === "true") continue;
      await t.click({ timeout: 1500 }).catch(() => {});
      await page.waitForTimeout(450);
      const p = await probe();
      record(hash, `tab:${label}`, p);
      p.links.forEach((l) => enqueue(l));
      // nested tab lists inside the opened panel
      if (depth < 1) {
        const total = await tabs.count().catch(() => 0);
        if (total > n) await scanNested(hash, label, n, total);
      }
    }
  }
  async function scanNested(hash, parent, from, total) {
    const tabs = page.locator("[role=tab]");
    for (let i = from; i < Math.min(total, from + 16); i++) {
      const t = tabs.nth(i);
      const label = ((await t.innerText({ timeout: 800 }).catch(() => "")) || `#${i}`).trim().split("\n")[0].slice(0, 40);
      if (!(await t.isVisible().catch(() => false))) continue;
      await t.click({ timeout: 1500 }).catch(() => {});
      await page.waitForTimeout(350);
      record(hash, `tab:${parent}>${label}`, await probe());
    }
  }

  async function scanActions(hash) {
    if (process.env.SKIP_MODALS) return;
    const names = await page.evaluate(() => [...document.querySelectorAll("button, [role=button]")]
      .filter((b) => b.offsetParent && !b.disabled && b.getAttribute("aria-disabled") !== "true")
      .map((b) => (b.innerText || b.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim()).filter((t) => t && t.length < 40)).catch(() => []);
    const picks = [...new Set(names)].filter((t) => ACTION.test(t) && !DANGER.test(t)).slice(0, 5);
    for (const name of picks) {
      try {
        const before = page.url();
        await page.getByRole("button", { name, exact: true }).first().click({ timeout: 1500 });
        await page.waitForTimeout(600);
        const p = await probe();
        const modal = await page.locator('[role=dialog], [class*=modal], .MuiDrawer-root, [class*=drawer]').count().catch(() => 0);
        record(hash, `${modal ? "modal" : "action"}:${name}`, p);
        p.links.forEach((l) => enqueue(l));
        if (modal) {
          // modal tabs
          const mt = page.locator('[role=dialog] [role=tab]'); const mn = Math.min(await mt.count().catch(() => 0), 8);
          for (let i = 0; i < mn; i++) { await mt.nth(i).click({ timeout: 1000 }).catch(() => {}); await page.waitForTimeout(300); record(hash, `modal:${name}>tab${i}`, await probe()); }
          await page.keyboard.press("Escape").catch(() => {});
          await page.getByRole("button", { name: /^(cancel|close)$/i }).first().click({ timeout: 600 }).catch(() => {});
          await page.waitForTimeout(250);
        }
        if (page.url() !== before) { const nh = "#" + page.url().split("#")[1]; enqueue(nh, true); await goto(hash); }
      } catch { /* keep going */ }
    }
  }

  async function wizardSteps(hash) {
    if (!/create|launch|new|wizard|add|import|register|deploy/i.test(hash)) return;
    for (let step = 1; step <= 7; step++) {
      const next = page.getByRole("button", { name: /^(next|continue|review)/i }).first();
      if (!(await next.isVisible().catch(() => false)) || !(await next.isEnabled().catch(() => false))) break;
      await next.click({ timeout: 1500 }).catch(() => {});
      await page.waitForTimeout(500);
      record(hash, `wizard-step${step + 1}`, await probe());
    }
  }

  async function visit(item) {
    const { hash, ctxName, expand } = item;
    if (visited.has(hash) || visitedRoutes.length >= MAX_PAGES) return;
    visited.add(hash);
    const t0 = Date.now();
    try {
      await Promise.race([(async () => {
        await goto(hash);
        const p = await probe();
        record(hash, ctxName || "page", p);
        p.links.forEach((l) => enqueue(l));
        for (const sel of expand || []) { await page.locator(sel).first().click({ timeout: 1200 }).catch(() => {}); await page.waitForTimeout(350); record(hash, `expand:${sel}`, await probe()); }
        if (p.tabs) await scanTabs(hash, ctxName);
        await wizardSteps(hash);
        await goto(hash).catch(() => {});
        await scanActions(hash);
      })(), new Promise((_, rej) => setTimeout(() => rej(new Error("page timeout")), PAGE_MS))]);
      visitedRoutes.push(hash);
    } catch (e) { errors.push(`${hash}: ${String(e.message).slice(0, 100)}`); visitedRoutes.push(hash + " (error)"); }
    if (visitedRoutes.length % 10 === 0) flush();
    if (process.env.VERBOSE) console.log(`  ${cloud} ${visitedRoutes.length} ${hash} ${Date.now() - t0}ms findings=${findings.size}`);
  }

  // ---- run
  // EXTRA_ROUTES=#/a/b,#/c/d [NO_SEED=1]: visit just these (e.g. param routes the BFS could not reach); NO_SEED skips fixtures/spec-map/BFS.
  if (process.env.EXTRA_ROUTES) for (const r of process.env.EXTRA_ROUTES.split(",")) { queued.add(r); queue.push({ hash: r, ctxName: "page" }); }
  if (!process.env.NO_SEED) {
  // 1) fixtures: run every fixture a service exposes (creates fixed resources), uniq-named live ones too
  for (const [svc, fx] of Object.entries(fxBySvc)) for (const name of Object.keys(fx)) { if (ONLY && !ONLY.has(svc)) continue; await runFx(svc, name, "gs" + Math.random().toString(36).slice(2, 7)); }
  // 2) spec-map routes with live substitution
  for (const sr of specRoutes) {
    let route = sr.route;
    if (route.includes("{live}") && sr.live) { const v = await runFx(sr.svc, sr.live, "gs" + Math.random().toString(36).slice(2, 7)); if (v) route = route.replaceAll("{live}", encodeURIComponent(v)); else continue; }
    for (const f of sr.fixtures || []) await runFx(sr.svc, f, "gs");
    if (!queued.has(route)) { queued.add(route); queue.push({ hash: route, ctxName: "page", expand: sr.expand }); }
  }
  for (const r of [...routes].sort()) if (!ONLY || ONLY.has(svcOf(r))) enqueue(r);
  enqueue("#/");
  }
  if (process.env.NO_SEED) perShape.set("*", 1e9);
  while (queue.length && visitedRoutes.length < MAX_PAGES) {
    const item = queue.shift();
    await visit(item);
  }
  flush();

  // unreached parameterised route patterns
  const reachedPaths = visitedRoutes.map((h) => h.replace(/ \(error\)$/, "").replace(/^#/, "").replace(/\?.*/, "")).map((p) => p.split("/").map(decodeURIComponent).join("/"));
  const unreached = [...patterns].filter((pt) => !reachedPaths.some((p) => matchPat(pt, p)) && (!ONLY || ONLY.has(pt.split("/")[1])));
  const final = JSON.parse(readFileSync(outFile, "utf8"));
  final.unreachedPatterns = unreached; final.fixtureErrors = fixtureLog;
  final.registry = { notSimulated: Object.entries(reg).filter(([, e]) => (e.level[SUB] || e.level.offline) === "not_simulated").map(([id, e]) => ({ id, svc: e.svc, title: e.title })) };
  writeFileSync(outFile, JSON.stringify(final, null, 1));
  console.log(`${SUB}/${cloud}: pages=${visitedRoutes.length} notSimulated(unique)=${findings.size} limited/config ids=${limited.size} unreachedPatterns=${unreached.length} fixtureErrors=${fixtureLog.length} registryNotSim=${final.registry.notSimulated.length}`);
  await browser.close();
}
