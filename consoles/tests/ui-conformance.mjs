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

/** Everything a user can read on the page right now, plus honest-gap text. */
async function snapshot(page) {
  return page.evaluate(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const text = document.body.innerText;
    const attrs = [...document.querySelectorAll("[placeholder],[aria-label]")].filter(vis)
      .map((e) => (e.getAttribute("placeholder") || "") + " " + (e.getAttribute("aria-label") || ""));
    const honest = [...document.querySelectorAll("[data-vyomi-not-simulated]")].map((e) => {
      const box = e.closest("[class*=container]") || e.parentElement;
      return (box?.innerText || "") + " " + e.getAttribute("data-vyomi-not-simulated");
    });
    return { text, attrs: attrs.join("\n"), honest: honest.join("\n") };
  });
}

async function checkService(browser, svc) {
  const specPath = join(ROOT, "ui-spec", cloud, `${svc}.json`);
  const mapPath = join(ROOT, "consoles", "src", cloud, "services", svc, "spec-map.json");
  if (!existsSync(specPath)) return { svc, error: `no spec ${specPath}` };
  const spec = JSON.parse(await readFile(specPath, "utf8"));
  const map = existsSync(mapPath) ? JSON.parse(await readFile(mapPath, "utf8")) : {};
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const pages = [];
  for (const sp of spec.pages) {
    const m = map[sp.id];
    // Spec placeholders like {resource-name} resolve to this page's fixture resource.
    const els = elements(sp).map((e) => ({ ...e, text: e.text.replace(/\{([\w-]+)\}/g, (x, k) => m?.vars?.[k] ?? x) }));
    const rec = { id: sp.id, kind: sp.kind, route: m?.route || null, total: els.length, present: [], honest: [], missing: [] };
    if (!m?.route) { rec.missing = els.map((e) => `${e.kind}: ${e.text}`); rec.unmapped = true; pages.push(rec); continue; }
    for (const f of m.fixtures || []) await FIXTURES[f]?.();
    await page.goto(`${UI}${cloud}/${m.route}`, { waitUntil: "networkidle" }).catch(() => {});
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
    const honest = norm(snaps.map((s) => s.honest).join("\n"));
    for (const e of els) {
      const t = norm(e.text);
      const label = `${e.kind}: ${e.text}`;
      if (honest.includes(t)) rec.honest.push(label);
      else if (all.includes(t)) rec.present.push(label);
      else if (m.honest_page) rec.honest.push(label);
      else rec.missing.push(label);
    }
    pages.push(rec);
  }
  await ctx.close();
  const sum = (k) => pages.reduce((a, p) => a + (Array.isArray(p[k]) ? p[k].length : p[k]), 0);
  const total = sum("total"), present = sum("present"), honest = sum("honest");
  return { svc, total, present, honest, missing: total - present - honest, fidelity: total ? (present + honest) / total : 1, coverage: total ? present / total : 1, pages };
}

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const results = [];
for (const svc of services) results.push(await checkService(browser, svc));
await browser.close();

const pct = (x) => `${(x * 100).toFixed(1)}%`;
let md = `# UI conformance — ${cloud}\n\n| Service | Elements | Present | Not simulated | Missing | Fidelity | Real coverage |\n|---|---|---|---|---|---|---|\n`;
for (const r of results) md += r.error ? `| ${r.svc} | — | — | — | — | error: ${r.error} | — |\n`
  : `| ${r.svc} | ${r.total} | ${r.present} | ${r.honest} | ${r.missing} | ${pct(r.fidelity)} | ${pct(r.coverage)} |\n`;
for (const r of results.filter((x) => !x.error)) {
  md += `\n## ${r.svc}\n`;
  for (const p of r.pages.filter((p) => p.missing.length)) md += `\n- **${p.id}** (${p.kind}${p.unmapped ? ", no v4 route" : ""}): ${p.missing.length} missing — ${p.missing.slice(0, 12).join("; ")}${p.missing.length > 12 ? " …" : ""}\n`;
}
await writeFile(join(OUT, `${cloud}.json`), JSON.stringify(results, null, 2));
await writeFile(join(OUT, `${cloud}.md`), md);
console.log(md.split("\n## ")[0]);
const bad = results.filter((r) => r.error || r.fidelity < MIN);
if (bad.length) console.log(`Below ${pct(MIN)} fidelity: ${bad.map((r) => r.svc).join(", ")}`);
process.exit(bad.length ? 1 : 0);
