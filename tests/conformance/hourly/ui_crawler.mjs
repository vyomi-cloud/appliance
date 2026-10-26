/* Hourly UI crawler — finds broken / unimplemented console functionality.
 *
 * Walks every cloud console of one target, clicks every service on the rail and
 * every tab inside it, and records what a user would hit: uncaught page errors,
 * failing API calls (5xx / 501 / 404), placeholder text ("undefined",
 * "not implemented", "[object Object]"…), empty panels, dead tabs, grid cells
 * showing "-"/blank, and — with CREATE=1 (default) — resources created through
 * the UI's default values that come out with unfilled details or that don't
 * move the space's cost-savings metrics.
 *
 * It does not pass/fail anything itself — it writes a findings inventory that the
 * hourly agent works through (fix the UI, then add a conformance test for it).
 *
 *   TARGET=nano     serves NANO_DIR (default ../../../wasm) with the Nano SW
 *   TARGET=offline  crawls VYOMI_BASE_URL (default http://localhost:9000)/console/*
 *   OUT=path.json   where to write findings (default out/ui-<target>.json)
 *   MAX_SERVICES / MAX_TABS cap the crawl per console (defaults 80 / 10)
 */
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const TARGET = process.env.TARGET || "nano";
if (TARGET === "nano" && !process.env.NANO_DIR) process.env.NANO_DIR = resolve(HERE, "../../../wasm");
const { startServer, bootConsole, chromium, sleep, RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");

const OUT = process.env.OUT || resolve(HERE, `out/ui-${TARGET}.json`);
const MAX_SERVICES = +(process.env.MAX_SERVICES || 80);
const MAX_TABS = +(process.env.MAX_TABS || 10);
const CREATE = (process.env.CREATE ?? "1") !== "0";
// Walking every detail tab of every service takes ~40 min per console, so the
// hourly run walks tabs for 1/TAB_SHARDS of the services (rotating by UTC
// hour) and carries the others' tab results forward from PREV_UI (the previous
// run's ui-findings.json). ONLY limits the crawl to services matching a regex
// (the service gate crawls just the service it checks).
const TAB_SHARDS = Math.max(1, +(process.env.TAB_SHARDS || 1));
const SHARD = new Date().getUTCHours() % TAB_SHARDS;
const ONLY = process.env.ONLY ? new RegExp(process.env.ONLY, "i") : null;
const PREV = (() => {
  try {
    const p = JSON.parse(readFileSync(process.env.PREV_UI, "utf-8"))[TARGET]?.services || [];
    return new Map(p.map((r) => [`${r.cloud}/${r.service}`, (r.surfaces || []).filter((x) => x.kind === "tab")]));
  } catch { return new Map(); }
})();
const shardOf = (key) => [...key].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % TAB_SHARDS;
const OFFLINE_BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");

const CONSOLES = TARGET === "nano"
  ? [{ cloud: "aws", path: "/aws-console.html" }, { cloud: "gcp", path: "/gcp-console.html" }, { cloud: "azure", path: "/azure-console.html" }]
  : [{ cloud: "aws", path: "/console/aws" }, { cloud: "gcp", path: "/console/gcp" }, { cloud: "azure", path: "/console/azure" }];

// Resource-detail tabs: AWS `.top-tabs` buttons, GCP `.sub-nav` items, Azure
// blade `.sub-nav-item`s (as the wasm/ui-tests tab validators use), plus
// generic tab markup.
const TAB_SEL = '.top-tabs button, .sub-nav .nav-item, .sub-nav a, .sub-nav-item, #main [role=tab], #main .tabs button, #main .tabbar button, #main [data-tab]';
const BAD_TEXT = [
  [/\bundefined\b/i, "shows 'undefined'"],
  [/\bNaN\b/, "shows 'NaN'"],
  [/\[object Object\]/, "shows '[object Object]'"],
  [/not implemented|notimplemented/i, "says not implemented"],
  [/coming soon/i, "says coming soon"],
  [/traceback \(most recent call last\)/i, "shows a Python traceback"],
];

// Snapshot of the main panel, used to detect empty panels and dead tabs.
const snap = (page) => page.evaluate(() => {
  const m = document.querySelector("#main");
  const text = (m?.innerText || "").trim();
  return { text: text.slice(0, 4000), len: text.length, html: (m?.innerHTML || "").length };
});

// How implemented each console surface is (service page, create, resource
// detail, each tab):
//   unimplemented  errors / 404 / 501 / "not implemented" / dead or empty
//   partial        backed by the API but shows blank/"-" fields
//   live           loaded data from the API, or shows this resource's own data
//   static         rendered without any API call and nothing specific to the
//                  resource (hard-coded or permanently empty)
const UNIMPL = new Set(["HTTP_501", "HTTP_404", "HTTP_5XX", "PAGE_ERROR", "BAD_TEXT", "EMPTY_PANEL", "DEAD_TAB",
  "CRAWL_ERROR", "CREATE_FAILED", "CREATE_NO_SUBMIT", "CREATE_NO_ROW", "CREATE_REJECTED"]);
function classify(findings, calls, text, tokens) {
  const api404 = (f) => f.type !== "HTTP_404" || !/\.(m?js|css|png|svg|ico|woff2?)(\s|$|\?)/.test(f.detail || "");
  if (findings.some((f) => UNIMPL.has(f.type) && api404(f))) return "unimplemented";
  if (findings.some((f) => f.type === "PLACEHOLDER_CELL")) return "partial";
  if (calls > 0 || (tokens || []).some((t) => text.includes(t))) return "live";
  return "static";
}

function textFindings(text) {
  return BAD_TEXT.filter(([re]) => re.test(text)).map(([, why]) => ({ type: "BAD_TEXT", detail: why }));
}

// Grid cells that render a placeholder instead of real data ("-", "—", "–",
// "n/a", blank). Every resource Vyomi creates — including via a UI default
// action — must have its details filled, so these are findings, keyed by the
// column header so the agent knows which field is missing.
const PLACEHOLDER_CELLS = (page) => page.evaluate(() => {
  const out = [];
  const isPh = (t) => /^(-|—|–|n\/a|null|none)?$/i.test(t.trim());
  for (const table of document.querySelectorAll("#main table")) {
    const heads = [...table.querySelectorAll("thead th, tr:first-child th")].map((h) => (h.innerText || "").trim());
    // Consoles build tables with DOM calls (no <tbody>): data rows are the <tr>s with <td>s.
    [...table.querySelectorAll("tr")].filter((tr) => tr.querySelector("td")).forEach((tr, ri) => {
      [...tr.querySelectorAll("td")].forEach((td, ci) => {
        const col = heads[ci] || `column ${ci + 1}`;
        // Checkbox / action columns legitimately have no text.
        if (td.querySelector("input,button,svg,[role=checkbox]") || !col || /^(actions?|select)$/i.test(col)) return;
        if (isPh(td.innerText || "")) out.push({ row: ri + 1, col });
      });
    });
  }
  // Detail panels are key/value layouts, not tables: flag any leaf element whose
  // whole text is a placeholder, labelled by the nearest preceding label text.
  for (const el of document.querySelectorAll("#main *")) {
    if (el.children.length || el.closest("table,[role=grid],[role=table],button,input,select,textarea")) continue;
    const t = (el.innerText || el.textContent || "").trim();
    if (!/^(-|—|–)$/.test(t)) continue;
    let label = "";
    for (let n = el.previousElementSibling || el.parentElement?.previousElementSibling; n && !label; n = n.previousElementSibling) {
      label = (n.innerText || "").trim().split("\n").pop();
    }
    out.push({ row: 0, col: label || "(unlabelled field)" });
  }
  for (const grid of document.querySelectorAll("#main [role=grid], #main [role=table]")) {
    const heads = [...grid.querySelectorAll("[role=columnheader]")].map((h) => (h.innerText || "").trim());
    grid.querySelectorAll("[role=row]").forEach((r, ri) => {
      [...r.querySelectorAll("[role=cell],[role=gridcell]")].forEach((c, ci) => {
        const col = heads[ci] || `column ${ci + 1}`;
        if (c.querySelector("input,button,svg") || /^(actions?|select)$/i.test(col)) return;
        if (isPh(c.innerText || "")) out.push({ row: ri, col });
      });
    });
  }
  return out;
});

async function placeholderFindings(page, where) {
  const cells = await PLACEHOLDER_CELLS(page).catch(() => []);
  // One finding per column, not per cell, to keep the inventory readable.
  const byCol = new Map();
  for (const c of cells) byCol.set(c.col, (byCol.get(c.col) || 0) + 1);
  return [...byCol].map(([col, n]) => ({ type: "PLACEHOLDER_CELL", detail: `${where}: column "${col}" shows "-"/blank in ${n} row(s)` }));
}

// Active space's cost-savings metrics (core/cost_model → /api/spaces). Fetched
// from inside the page so it works for both targets (Nano's SW serves the API).
const savingsSnapshot = (page) => page.evaluate(async () => {
  try {
    const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
    const sp = d.active_space || (d.spaces || []).find((s) => s.id === d.active_space_id || s.space_id === d.active_space_id) || {};
    const cs = sp.cost_savings || {};
    return { ok: true, count: cs.resource_count ?? null, usd: cs.savings_usd ?? null, byProvider: cs.by_provider || {} };
  } catch (e) { return { ok: false, err: String(e) }; }
});

// Every resource created must show up in the space's savings: resource_count
// goes up, and the creating cloud's saved dollars go up (real cloud would bill it).
function savingsFindings(cloud, before, after, stage) {
  const f = [];
  if (!before.ok || !after.ok) return [{ type: "SAVINGS_UNAVAILABLE", detail: `${stage}: /api/spaces cost_savings unreadable` }];
  if (after.count === null || after.usd === null) return [{ type: "SAVINGS_MISSING", detail: `${stage}: active space has no cost_savings metrics` }];
  if (stage === "create" && !(after.count > before.count)) {
    f.push({ type: "SAVINGS_NOT_UPDATED", detail: `${stage}: resource_count stayed ${before.count} after creating a resource` });
  }
  const b = before.byProvider[cloud] || 0, a = after.byProvider[cloud] || 0;
  if (!(a > b)) f.push({ type: "SAVINGS_NOT_UPDATED", detail: `${stage}: ${cloud} savings stayed $${b} (real ${cloud} would bill this resource)` });
  return f;
}

// Playwright matches a button's textContent, where a Material icon ligature runs
// straight into the label ("addLaunch instances", "add_circleCreate"), so match
// the action word anywhere rather than on word boundaries.
const CREATE_BTN = /create|launch|upload|generate|deploy|new [a-z]/i;
const SUBMIT_BTN = /create|save|submit|launch|confirm|deploy|upload|generate|\bok\b|^\s*add\b/i;
const NOT_SUBMIT = /cancel|close|back|previous/i;

// Create a resource accepting every form default, then check the new row is
// fully populated. Only runs when CREATE=1 (on by default in CI).
// Close nag popups ("Maybe later", "×") that would otherwise sit over the
// console and swallow the crawler's clicks.
async function dismissPopups(page) {
  for (const name of [/^maybe later$/i, /^not now$/i, /^dismiss$/i, /^×$/]) {
    const b = page.getByRole("button", { name }).first();
    if (await b.isVisible().catch(() => false)) await b.click({ timeout: 1000 }).catch(() => {});
  }
}

// Data rows only: consoles often append <tr>s straight to <table> (no <tbody>),
// so match any <tr> holding a <td>, not just "tbody tr".
const ROW_SEL = "#main table tr:has(td), #main [role=row]:has([role=cell],[role=gridcell])";
const rowCount = (page) => page.locator(ROW_SEL).count();

// Create a resource accepting every form default, return to the service list
// (create pages navigate away from it), and check the new row is there, fully
// populated, and reflected in the space's cost savings.
async function createWithDefaults(page, drain, cloud, backToList) {
  const f = [];
  const btn = page.locator("#main button, #main [role=button]").filter({ hasText: CREATE_BTN }).first();
  if (!(await btn.count())) return f;
  const rowsBefore = await rowCount(page);
  const savBefore = await savingsSnapshot(page);
  try {
    await btn.click({ timeout: 3000 });
    await sleep(1200);
    await dismissPopups(page);
    const dialog = page.locator("[role=dialog]:visible, .modal:visible, .drawer:visible").last();
    const scope = (await dialog.count()) ? dialog : page.locator("#main");
    const submit = scope.locator("button, [type=submit]").filter({ hasText: SUBMIT_BTN }).filter({ hasNotText: NOT_SUBMIT }).last();
    if (!(await submit.count())) { f.push({ type: "CREATE_NO_SUBMIT", detail: "create form has no submit button" }); return f; }
    await submit.click({ timeout: 3000 });
    await sleep(3000);
  } catch (e) {
    f.push({ type: "CREATE_FAILED", detail: `create with defaults failed: ${String(e.message || e).split("\n")[0].slice(0, 200)}` });
    return f;
  }
  f.push(...drain().map((x) => ({ ...x, detail: `during create: ${x.detail}` })));
  const s = await snap(page);
  if (/\b(error|failed|invalid)\b/i.test(s.text.slice(0, 800))) {
    f.push({ type: "CREATE_REJECTED", detail: `create with default values was rejected: "${(s.text.match(/[^\n]*(error|failed|invalid)[^\n]*/i) || [""])[0].slice(0, 140)}"` });
  }
  await backToList();
  const rowsAfter = await rowCount(page);
  if (rowsAfter <= rowsBefore) f.push({ type: "CREATE_NO_ROW", detail: "create with defaults added no resource to the list" });
  f.push(...(await placeholderFindings(page, "after create")));
  if (rowsAfter > rowsBefore) {
    await sleep(1500); // savings are recomputed on the space tick after the write
    f.push(...savingsFindings(cloud, savBefore, await savingsSnapshot(page), "create"));
  }
  return f;
}

async function crawlConsole(browser, base, con, needsSW) {
  const ctx = await browser.newContext();
  if (TARGET === "nano") await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
  const page = await ctx.newPage();
  const net = [];          // failing responses since the last drain
  const errs = [];         // uncaught page errors since the last drain
  page.on("response", (r) => {
    const s = r.status(), u = r.url();
    if (s >= 400 && !/favicon|\.map$|hot-update/.test(u)) net.push({ status: s, url: u.replace(base, "").slice(0, 200) });
  });
  page.on("pageerror", (e) => errs.push(String(e.message).split("\n")[0].slice(0, 300)));
  // Successful data calls (the console's /api/* fetches, served by the
  // appliance offline or the service worker in Nano) per surface.
  // Any data fetch counts (Nano serves cloud-native paths like
  // /compute/v1/... from the service worker), not static assets/fixtures.
  // The consoles poll in the background, so a surface only gets credit for
  // paths that weren't already being fetched in the 2.5 s before it opened.
  let log = [], t0 = Date.now();
  page.on("response", (r) => {
    const t = r.request().resourceType();
    if (r.status() < 400 && (t === "fetch" || t === "xhr")
        && !/\.(m?js|css|html|wasm|map|png|svg|ico|woff2?|whl|zip)(\?|$)|\/fixtures\//.test(r.url())) {
      const now = Date.now();
      log.push({ t: now, p: r.url().split("?")[0] });
      if (log.length > 2000) log = log.filter((x) => x.t > now - 60000);
    }
  });
  const calls = () => {
    const now = Date.now();
    const bg = new Set(log.filter((x) => x.t >= t0 - 2500 && x.t < t0).map((x) => x.p));
    const n = new Set(log.filter((x) => x.t >= t0 && x.t <= now && !bg.has(x.p)).map((x) => x.p)).size;
    t0 = now;
    return n;
  };
  const drain = () => {
    const f = [];
    for (const n of net.splice(0)) {
      if (n.status === 501) f.push({ type: "HTTP_501", detail: `${n.url} → 501` });
      else if (n.status >= 500) f.push({ type: "HTTP_5XX", detail: `${n.url} → ${n.status}` });
      else if (n.status === 404) f.push({ type: "HTTP_404", detail: `${n.url} → 404` });
    }
    for (const e of errs.splice(0)) f.push({ type: "PAGE_ERROR", detail: e });
    return f;
  };

  const rows = [];
  try {
    if (needsSW) await bootConsole(page, base, con.path);
    else {
      await page.goto(base + con.path, { waitUntil: "domcontentloaded" });
      await page.waitForFunction((sel) => document.querySelectorAll(sel).length > 0, RAIL_SEL, { timeout: 120000, polling: 500 });
    }
    drain(); // boot noise is reported once below, not per service
    const services = await page.evaluate((sel) => [...document.querySelectorAll(sel)]
      .map((e, i) => ({ i, label: (e.innerText || e.title || e.getAttribute("data-key") || e.getAttribute("data-service") || "").trim().split("\n").pop() }))
      .filter((x) => x.label && !/^home$/i.test(x.label)), RAIL_SEL);
    // Opening a service swaps #rail for that service's own sidebar (EC2 →
    // Events, Instances, …), so the service list's indexes stop matching.
    // Go back to the console home whenever the rail entry isn't this service.
    const railLabel = (i) => page.locator(RAIL_SEL).nth(i).evaluate((e) =>
      (e.innerText || e.title || e.getAttribute("data-key") || e.getAttribute("data-service") || "").trim().split("\n").pop()).catch(() => "");
    const openService = async (svc) => {
      if ((await railLabel(svc.i)) !== svc.label) {
        await page.goto(base + con.path, { waitUntil: "domcontentloaded" });
        await page.waitForFunction((sel) => document.querySelectorAll(sel).length > 0, RAIL_SEL, { timeout: 120000, polling: 500 });
        await sleep(1000);
        await dismissPopups(page);
      }
      try {
        await page.locator(RAIL_SEL).nth(svc.i).click({ timeout: 5000 });
      } catch (e) {
        // A dialog left open by the previous service (e.g. a rejected create)
        // covers the rail: reload the console so one failure doesn't cascade
        // into every service after it.
        await page.goto(base + con.path, { waitUntil: "domcontentloaded" });
        await page.waitForFunction((sel) => document.querySelectorAll(sel).length > 0, RAIL_SEL, { timeout: 120000, polling: 500 });
        await sleep(1000);
        await dismissPopups(page);
        await page.locator(RAIL_SEL).nth(svc.i).click({ timeout: 5000 });
      }
    };
    const seen = new Set();
    for (const svc of services) {
      if (seen.has(svc.label) || seen.size >= MAX_SERVICES || (ONLY && !ONLY.test(svc.label))) continue;
      seen.add(svc.label);
      const row = { target: TARGET, cloud: con.cloud, service: svc.label, tabs: [], findings: [], surfaces: [] };
      const surface = (kind, name, f, n, text, tokens) => row.surfaces.push({ kind, name, state: classify(f, n, text, tokens), calls: n });
      let tokens = [];
      try {
        await dismissPopups(page);
        calls();
        await openService(svc);
        await sleep(1500);
        const s = await snap(page);
        const pf = [...drain(), ...textFindings(s.text)];
        if (s.len < 15) pf.push({ type: "EMPTY_PANEL", detail: "service panel renders no content" });
        pf.push(...(await placeholderFindings(page, "list")));
        row.findings.push(...pf);
        surface("page", svc.label, pf, calls(), s.text);
        if (CREATE) {
          const backToList = async () => {
            await page.keyboard.press("Escape").catch(() => {});
            await dismissPopups(page);
            await openService(svc).catch(() => {});
            await sleep(1500);
          };
          const hasCreate = await page.locator("#main button, #main [role=button]").filter({ hasText: CREATE_BTN }).count();
          const cf = await createWithDefaults(page, drain, con.cloud, backToList);
          row.findings.push(...cf);
          if (hasCreate) surface("create", "create with defaults", cf, 1, "");
          // Values that identify the first resource (names, ids): a tab that
          // shows them is rendering this resource's data, not static text.
          tokens = await page.locator("#main table tr:has(td)").first().locator("td").allInnerTexts().catch(() => []);
          tokens = tokens.map((t) => t.trim()).filter((t) => t.length >= 4 && /[a-z]/i.test(t) && /[\d_.:\/-]/.test(t)).slice(0, 6);
          if (process.env.DEBUG_CRAWL) console.log(`[debug] ${svc.label}: tokens=${JSON.stringify(tokens)}`);
          // Open the first resource so its detail tabs (where most unfilled
          // fields hide) get walked below.
          drain(); calls();
          // Resource links first (as the wasm/ui-tests validators open them);
          // a plain cell only if the row has no link.
          let link = page.locator("#main a.id, #main table tr:has(td) td a, #main [role=row] a").first();
          if (!(await link.count())) link = page.locator("#main table tr:has(td) td:not(.chk)").first();
          if (process.env.DEBUG_CRAWL) console.log(`[debug] ${svc.label}: resource links=${await page.locator("#main a.id, #main table tr:has(td) td a").count()}`);
          if (await link.count()) {
            await link.click({ timeout: 3000 }).catch(() => {});
            await sleep(1500);
            const d = await snap(page);
            const df = [...drain().map((x) => ({ ...x, detail: `resource detail: ${x.detail}` })),
              ...textFindings(d.text), ...(await placeholderFindings(page, "resource detail"))];
            row.findings.push(...df);
            surface("detail", "resource detail", df, calls(), d.text, tokens);
          }
        }

        const carried = PREV.get(`${con.cloud}/${svc.label}`);
        if (TAB_SHARDS > 1 && shardOf(`${con.cloud}/${svc.label}`) !== SHARD && carried?.length) {
          row.surfaces.push(...carried.map((x) => ({ ...x, carried: true })));
          row.tabs.push(...carried.map((x) => x.name));
          row.status = row.findings.length ? "broken" : "ok";
          rows.push(row);
          continue;
        }
        const tabs = await page.locator(TAB_SEL).allInnerTexts().catch(() => []);
        if (process.env.DEBUG_CRAWL) console.log(`[debug] ${svc.label}: tabs=${JSON.stringify(tabs.slice(0, 12))}`);
        for (let t = 0; t < Math.min(tabs.length, MAX_TABS); t++) {
          // Last line: GCP/Azure tabs render an icon name above the label.
          const label = (tabs[t] || "").trim().split("\n").pop().trim() || `tab ${t + 1}`;
          const before = await snap(page);
          calls();
          try {
            await page.locator(TAB_SEL).nth(t).click({ timeout: 3000 });
            await sleep(900);
          } catch (e) {
            row.findings.push({ type: "DEAD_TAB", tab: label, detail: "tab not clickable" });
            surface("tab", label, [{ type: "DEAD_TAB" }], 0, "");
            continue;
          }
          const after = await snap(page);
          const tf = [...drain(), ...textFindings(after.text), ...(await placeholderFindings(page, `tab ${label}`))].map((f) => ({ ...f, tab: label }));
          if (t > 0 && after.text === before.text && after.html === before.html) tf.push({ type: "DEAD_TAB", tab: label, detail: "clicking the tab changes nothing" });
          row.tabs.push(label);
          row.findings.push(...tf);
          // Only the text the tab added counts (the header with the resource
          // name stays on screen for every tab).
          // The first tab is already open when the detail page loads, so its
          // content is the whole panel.
          const prev = new Set(t === 0 ? [] : before.text.split("\n"));
          const added = after.text.split("\n").filter((l) => !prev.has(l)).join("\n");
          surface("tab", label, tf, calls(), added, tokens);
          if (process.env.DEBUG_CRAWL && row.surfaces.at(-1).state === "static") console.log(`[debug] ${svc.label}/${label} static: ${JSON.stringify(added.slice(0, 160))}`);
        }
      } catch (e) {
        row.findings.push({ type: "CRAWL_ERROR", detail: String(e.message || e).split("\n")[0].slice(0, 300) });
        surface("page", svc.label + " (crawl error)", [{ type: "CRAWL_ERROR" }], 0, "");
      }
      row.status = row.findings.length ? "broken" : "ok";
      rows.push(row);
    }
  } catch (e) {
    rows.push({ target: TARGET, cloud: con.cloud, service: "(console boot)", tabs: [], status: "broken",
      findings: [{ type: "BOOT_FAILED", detail: String(e.message || e).split("\n")[0].slice(0, 300) }, ...drain()] });
  }
  await ctx.close();
  return rows;
}

let server = null, base = OFFLINE_BASE;
if (TARGET === "nano") ({ server, base } = await startServer());
const browser = await chromium.launch();
const all = [];
for (const con of CONSOLES) {
  const rows = await crawlConsole(browser, base, con, TARGET === "nano");
  const bad = rows.filter((r) => r.status !== "ok").length;
  console.log(`[${TARGET}/${con.cloud}] ${rows.length} services crawled, ${bad} with findings`);
  all.push(...rows);
  // Written after every console so a suite timeout still leaves results.
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify({ target: TARGET, at: new Date().toISOString(), services: all, partial: true }, null, 1));
}
await browser.close();
server?.close();

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify({ target: TARGET, at: new Date().toISOString(), services: all }, null, 1));
const broken = all.filter((r) => r.status !== "ok");
console.log(`UI crawl ${TARGET}: ${all.length - broken.length}/${all.length} services clean → ${OUT}`);
const st = {};
for (const x of all.flatMap((r) => r.surfaces || [])) st[x.state] = (st[x.state] || 0) + 1;
console.log(`Console surfaces ${TARGET}: ${JSON.stringify(st)}`);
