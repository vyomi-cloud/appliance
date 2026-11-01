/* UI conformance: does each Vyomi v4 page carry what the native console page carries?
 *
 * Inputs: ui-spec/<cloud>/<service>.json (from the real console) + the service's
 * consoles/src/<cloud>/services/<svc>/spec-map.json (spec page id → v4 route, fixtures).
 * For every mapped page it loads the route, clicks through the page's tabs, and checks each
 * spec element (title, tabs, columns, header actions, filter placeholder, sections, form
 * fields, wizard steps) against the rendered page.
 *
 *   present   — element is on the page
 *   honest    — element sits inside a "Not simulated in Vyomi" panel (a declared gap)
 *   missing   — neither: a fidelity failure
 *
 * fidelity = (present + honest) / total     coverage = present / total
 *
 *   BASE=http://127.0.0.1:8740 node consoles/tests/ui-conformance.mjs aws s3 dynamodb
 *   Exit 1 if any service is under MIN_FIDELITY (default 0.90).
 */
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const BASE = process.env.BASE || "http://127.0.0.1:8740";
const UI = `${BASE}${process.env.UI_PATH || "/v4/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || join(ROOT, "consoles", "ui-conformance-out");
const MIN = Number(process.env.MIN_FIDELITY || 0.9);
const [cloud = "aws", ...services] = process.argv.slice(2);

const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, " ").replace(/[‐-―]/g, "-").trim();
const sig = (svc) => `AWS4-HMAC-SHA256 Credential=X/20261030/us-east-1/${svc}/aws4_request, SignedHeaders=host, Signature=0`;

// Fixtures a page needs before it can render (e.g. a detail page needs a resource).
const FIXTURES = {
  "s3-bucket": async () => { await fetch(`${WIRE}/uic-bucket`, { method: "PUT", headers: { authorization: sig("s3") } }); await fetch(`${WIRE}/uic-bucket/uic-object.txt`, { method: "PUT", body: "x", headers: { authorization: sig("s3") } }); },
  "ddb-table": async () => {
    await fetch(`${WIRE}/`, { method: "POST", headers: { "x-amz-target": "DynamoDB_20120810.CreateTable", "content-type": "application/x-amz-json-1.0", authorization: sig("dynamodb") },
      body: JSON.stringify({ TableName: "uic-table", AttributeDefinitions: [{ AttributeName: "pk", AttributeType: "S" }], KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }], BillingMode: "PAY_PER_REQUEST" }) });
  },
};

/** Native-wire helper handed to per-service fixtures. */
async function wire(method, path, { headers = {}, body, svc = "s3", target } = {}) {
  // svc: null → no AWS signature (GCP REST / Azure ARM and data-plane requests).
  const h = { ...(svc ? { authorization: sig(svc) } : {}), ...headers };
  if (target) Object.assign(h, { "x-amz-target": target, "content-type": "application/x-amz-json-1.0" });
  const r = await fetch(`${WIRE}${path}`, { method, headers: h, body: body && typeof body !== "string" && !(body instanceof Uint8Array) ? JSON.stringify(body) : body });
  const text = await r.text();
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status} ${text.slice(0, 160)}`);
  try { return JSON.parse(text); } catch { return text; }
}

/** Flatten a spec page into checkable elements: [{kind, text}]. */
function elements(page) {
  const els = [];
  const add = (kind, text) => text && els.push({ kind, text: String(text) });
  add("title", page.title);
  (page.tabs || []).forEach((t) => add("tab", t));
  const t = page.table;
  if (t) {
    (t.columns || []).forEach((c) => add("column", typeof c === "string" ? c : c.label || c.header));
    (t.header_actions || []).forEach((a) => !/^refresh$/i.test(a) && add("action", typeof a === "string" ? a : a.label));
    if (t.filter_placeholder) add("placeholder", t.filter_placeholder);
  }
  const walkFields = (fields) => (fields || []).forEach((f) => {
    if (f.label && f.type !== "readonly") add("field", f.label);
    walkFields(f.children);
  });
  const walkSections = (secs) => (secs || []).forEach((s) => { add("section", s.title); walkFields(s.fields); });
  walkSections(page.sections);
  (page.steps || []).forEach((st) => { add("step", st.title); walkSections(st.sections); });
  Object.values(page.tab_panels || {}).forEach((p) => walkSections(p.sections || (Array.isArray(p) ? p : [])));
  // de-dup by kind+text
  const seen = new Set();
  return els.filter((e) => { const k = e.kind + "|" + norm(e.text); if (seen.has(k)) return false; seen.add(k); return true; });
}

/** Everything a user can read on the page right now — split into text OUTSIDE any
 *  "Not simulated" panel (real UI) and text inside those panels (declared gaps). */
async function snapshot(page) {
  return page.evaluate(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    // A gap's boundary is the element marked data-vyomi-gap-box (the Not-simulated section),
    // else the Not-simulated element itself — never a broad ancestor like a tab set.
    const gapBoxes = [...document.querySelectorAll("[data-vyomi-not-simulated]")].map((e) => e.closest("[data-vyomi-gap-box]") || e);
    const inGap = (el) => gapBoxes.some((g) => g.contains(el));
    // Real text: walk visible text nodes that are not inside a gap panel.
    const parts = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) {
      const el = n.parentElement;
      if (!el || inGap(el) || !n.nodeValue.trim()) continue;
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      parts.push(n.nodeValue);
    }
    const attrs = [...document.querySelectorAll("[placeholder],[aria-label]")].filter((e) => vis(e) && !inGap(e))
      .map((e) => (e.getAttribute("placeholder") || "") + " " + (e.getAttribute("aria-label") || ""));
    const honest = gapBoxes.map((g) => (g.innerText || "") + " " + (g.querySelector("[data-vyomi-not-simulated]")?.getAttribute("data-vyomi-not-simulated") || ""));
    return { text: parts.join("\n"), attrs: attrs.join("\n"), honest: honest.join("\n") };
  });
}

async function checkService(browser, svc) {
  const specPath = join(process.env.SPEC_DIR || join(ROOT, "ui-spec"), cloud, `${svc}.json`);
  const mapPath = join(ROOT, "consoles", "src", cloud, "services", svc, "spec-map.json");
  if (!existsSync(specPath)) return { svc, error: `no spec ${specPath}` };
  const spec = JSON.parse(await readFile(specPath, "utf8"));
  const map = existsSync(mapPath) ? JSON.parse(await readFile(mapPath, "utf8")) : {};
  // Per-service fixtures (consoles/src/<cloud>/services/<svc>/fixtures.mjs): async (wire, uniq) → text.
  const fxPath = join(ROOT, "consoles", "src", cloud, "services", svc, "fixtures.mjs");
  const svcFx = existsSync(fxPath) ? (await import(fxPath)).default || {} : {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const pages = [];
  for (const sp of spec.pages) {
    const m = map[sp.id];
    if (!m?.route) {
      const els = elements(sp).map((e) => ({ ...e, text: e.text.replace(/\{([\w-]+)\}/g, (x, k) => m?.vars?.[k] ?? x) }));
      pages.push({ id: sp.id, kind: sp.kind, route: null, total: els.length, present: [], honest: [], missing: els.map((e) => `${e.kind}: ${e.text}`), unmapped: true });
      continue;
    }
    const rec = { id: sp.id, kind: sp.kind, route: m.route, present: [], honest: [], missing: [] };
    for (const f of m.fixtures || []) await (svcFx[f] ? svcFx[f](wire, "uic") : FIXTURES[f]?.());
    // Liveness ("no statics"): create a uniquely named resource over the native wire right
    // before loading the page; the page must show that exact name.
    let liveText = null;
    if (m.live) {
      const uniq = `live${Math.random().toString(36).slice(2, 8)}`;
      try { liveText = await svcFx[m.live](wire, uniq); } catch (e) { liveText = null; rec.liveError = e.message; }
    }
    // Detail routes may embed the live resource: "#/s3/object/uic-bucket?key={live}".
    const route = liveText ? m.route.replaceAll("{live}", encodeURIComponent(liveText)) : m.route;
    // Spec placeholders like {resource-name} resolve to this page's fixture resource — the
    // freshly created live resource wins over a static var ONLY when the page has no static
    // resource-name of its own (e.g. a brand-new top-level resource's own detail page, created
    // BY the live check). When a page already names its fixed parent resource (a list/detail
    // page whose title is "{resource-name} | <tab>" but whose live check creates a CHILD item
    // shown as a grid row, not in the title — apim-users, s3 bucket-detail, …), keep the
    // static name so the title element still matches what's actually rendered.
    const vars = { ...m.vars, ...(liveText && m.vars?.["resource-name"] === undefined ? { "resource-name": liveText } : {}) };
    const els = elements(sp).map((e) => ({ ...e, text: e.text.replace(/\{([\w-]+)\}/g, (x, k) => vars[k] ?? x) }));
    rec.total = els.length;
    await page.goto(`${UI}${cloud}/${route}`, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(900);
    const snaps = [await snapshot(page)];
    // Click every tab (top-level and nested) so their panels are inspected too.
    const tabs = page.locator("[role=tab]");
    for (let i = 0, n = Math.min(await tabs.count(), 15); i < n; i++) {
      await tabs.nth(i).click().catch(() => {});
      await page.waitForTimeout(500);
      snaps.push(await snapshot(page));
    }
    for (const sel of m.expand || []) { await page.locator(sel).first().click().catch(() => {}); await page.waitForTimeout(400); snaps.push(await snapshot(page)); }
    const all = norm(snaps.map((s) => s.text + "\n" + s.attrs).join("\n"));
    if (m.live) {
      let ok = !!liveText && all.includes(norm(liveText));
      if (liveText && !ok) {
        // Paginated lists: search for it like a user would (text filter on the page).
        await page.goto(`${UI}${cloud}/${route}`, { waitUntil: "networkidle" }).catch(() => {});
        const box = page.locator('input[type="search"], input[placeholder^="Find"], input[placeholder^="Filter"], input[placeholder*="filter" i]').first();
        if (await box.isVisible().catch(() => false)) {
          await box.fill(liveText); await page.waitForTimeout(700);
          ok = norm((await snapshot(page)).text).includes(norm(liveText));
        }
      }
      rec.live = { ok, expected: liveText, error: rec.liveError };
    }
    const honest = norm(snaps.map((s) => s.honest).join("\n"));
    for (const e of els) {
      const t = norm(e.text);
      const label = `${e.kind}: ${e.text}`;
      // Real UI wins: an element shown outside every gap panel is present even if a gap
      // panel elsewhere happens to mention the same words.
      if (all.includes(t)) rec.present.push(label);
      else if (honest.includes(t)) rec.honest.push(label);
      else if (m.honest_page) rec.honest.push(label);
      else rec.missing.push(label);
    }
    pages.push(rec);
  }
  await ctx.close();
  const sum = (k) => pages.reduce((a, p) => a + (Array.isArray(p[k]) ? p[k].length : p[k]), 0);
  const total = sum("total"), present = sum("present"), honest = sum("honest");
  const live = pages.filter((p) => p.live);
  return { svc, total, present, honest, missing: total - present - honest, fidelity: total ? (present + honest) / total : 1, coverage: total ? present / total : 1,
    liveness: { checked: live.length, failed: live.filter((p) => !p.live.ok).map((p) => p.id) }, pages };
}

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const results = [];
for (const svc of services) results.push(await checkService(browser, svc));
await browser.close();

const pct = (x) => `${(x * 100).toFixed(1)}%`;
let md = `# UI conformance — ${cloud}\n\n| Service | Elements | Present | Not simulated | Missing | Fidelity | Real coverage | Live pages |\n|---|---|---|---|---|---|---|---|\n`;
for (const r of results) md += r.error ? `| ${r.svc} | — | — | — | — | error: ${r.error} | — |\n`
  : `| ${r.svc} | ${r.total} | ${r.present} | ${r.honest} | ${r.missing} | ${pct(r.fidelity)} | ${pct(r.coverage)} | ${r.liveness.checked - r.liveness.failed.length}/${r.liveness.checked} |\n`;
for (const r of results.filter((x) => !x.error)) {
  md += `\n## ${r.svc}\n`;
  for (const p of r.pages.filter((p) => p.missing.length)) md += `\n- **${p.id}** (${p.kind}${p.unmapped ? ", no v4 route" : ""}): ${p.missing.length} missing — ${p.missing.slice(0, 12).join("; ")}${p.missing.length > 12 ? " …" : ""}\n`;
}
await writeFile(join(OUT, `${cloud}.json`), JSON.stringify(results, null, 2));
await writeFile(join(OUT, `${cloud}.md`), md);
console.log(md.split("\n## ")[0]);
const bad = results.filter((r) => r.error || r.fidelity < MIN || r.liveness?.failed.length);
if (bad.length) console.log(`Below ${pct(MIN)} fidelity: ${bad.map((r) => r.svc).join(", ")}`);
process.exit(bad.length ? 1 : 0);
