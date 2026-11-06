/* Offline console conformance for BigQuery (driven against $VYOMI_BASE_URL/console/gcp).
 * Open the service, create a dataset with the form defaults, every grid column filled, every
 * detail tab renders, sample table + query actions fill the child tabs, the cost-savings
 * metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-bigquery.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const SERVICE = /BigQuery/i;
const DEFAULT_NAME = "my_dataset";
const API = "/api/gcp/bigquery/datasets";
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const savings = async () => {
  const d = await (await fetch(`${BASE}/api/spaces`)).json();
  const cs = (d.active_space || {}).cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["gcp.bigquery"] || 0 };
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null, newId = "";
page.on("response", async (r) => {
  if (r.request().method() === "POST" && r.url().endsWith(API)) {
    createStatus = r.status();
    try { newId = (await r.json()).name || ""; } catch (_) {}
  }
  if (r.status() >= 400 && r.url().includes("/api/") && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));

try {
  await fetch(`${BASE}${API}/${DEFAULT_NAME}`, { method: "DELETE" }).catch(() => {});   // a previous run may have left the default-named dataset
  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "BigQuery is on the GCP console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);

  // create with defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input").first().inputValue()) || "";
  check(name === DEFAULT_NAME, "create form has a realistic default dataset ID", `name="${name}"`);
  await page.locator("#main button").filter({ hasText: /create/i }).filter({ hasNotText: /cancel/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 20 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  await sleep(1500);
  const rowLoc = () => page.locator("#main table tr:has(td)").filter({ hasText: newId || DEFAULT_NAME });
  for (let i = 0; i < 10 && !(await rowLoc().count()); i++) await sleep(800);
  check((await rowLoc().count()) > 0, "new dataset appears in the list", `id ${newId}`);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowLoc().first().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 6 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  // cost savings moved — other suites share this appliance, so assert on what OUR service must contribute
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count >= 1); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > 0, "cost-savings metrics include the new dataset (gcp.bigquery priced)",
        `count ${s1.count}, $${s1.usd}, bigquery $${s1.svc}`);

  // detail tabs
  await rowLoc().first().locator("td").nth(1).click({ timeout: 5000 });
  await sleep(1800);
  const nav = page.locator(".sub-nav a.nav-item");
  const tabs = (await nav.allInnerTexts()).map((t) => t.replace(/^[a-z_]+\n/, "").trim());
  check(tabs.length >= 5, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  for (let i = 0; i < tabs.length; i++) {
    await nav.nth(i).click({ timeout: 3000 });
    await sleep(900);
    const txt = ((await page.locator("#main").innerText()) || "").trim();
    const tabText = txt.split("\n").slice(-8).join("\n");
    const ok = txt.length > 40 && !/Renderer error|Failed to load|Not yet wired|coming soon|undefined/i.test(txt) && !seen.has(tabText);
    seen.add(tabText);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(-160).replace(/\n/g, " ⏎ "));
  }

  // child tabs: sample table + sample query fill their grids, no blank cell
  const tab = async (label) => {
    const i = tabs.findIndex((t) => t === label);
    await nav.nth(i).click({ timeout: 3000 });
    await sleep(900);
  };
  const filled = async () => {
    const hs = (await page.locator("#main table th").allInnerTexts()).map((h) => h.trim());
    const cs = (await page.locator("#main table tr:has(td)").first().locator("td").allInnerTexts()).map((c) => c.trim());
    return { hs, cs, blank: hs.filter((_, i) => BLANK.test(cs[i] || "")) };
  };
  await tab("Tables");
  await page.locator("#main button").filter({ hasText: /create sample table/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  let f = await filled();
  check(f.cs.includes("sample_table") && !f.blank.length, "Tables tab lists the sample table with every column filled", JSON.stringify(f));
  await tab("Jobs");
  await page.locator("#main button").filter({ hasText: /run sample query/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  f = await filled();
  check(f.cs.some((c) => /^DONE/.test(c)) && !f.blank.length, "Jobs tab lists the query job (DONE) with every column filled", JSON.stringify(f));
  const live = await (await fetch(`${BASE}/bigquery/v2/projects/${(await (await fetch(`${BASE}${API}/${newId}`)).json()).project}/datasets/${newId}/tables/sample_table/data`)).json();
  check(live.totalRows === "3", "the sample table is queryable over the native wire", JSON.stringify(live).slice(0, 120));

  // delete via the detail Delete action
  await page.locator("#main button").filter({ hasText: /delete/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowLoc().count()); i++) await sleep(800);
  check(!(await rowLoc().count()), "delete removes the dataset from the list", `id ${newId}`);
  const list = await (await fetch(`${BASE}${API}`)).json();
  check(newId && !(list.items || []).some((a) => a.name === newId), "deleted dataset is gone from the backend", newId);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
