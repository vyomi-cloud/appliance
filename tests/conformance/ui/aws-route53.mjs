/* Route 53 console conformance — offline appliance ($VYOMI_BASE_URL/console/aws).
 *
 * Opens Route 53 from the service rail, creates a hosted zone with the form's
 * default values, checks every grid column is filled, opens the detail page and
 * every tab (incl. the Records grid), adds a record and a health check, then
 * deletes the zone from the UI.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-route53.mjs
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
const DEFAULT_NAME = "demo.example.com";   // the create form's default
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const BLANK = /^\s*(-|—|–|undefined|null|nan)?\s*$/i;

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
const text = (sel) => page.locator(sel).first().innerText().catch(() => "");

async function openRail(label) {
  await page.locator(RAIL_SEL).filter({ hasText: label }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1500);
}
async function gridRows() {
  return page.evaluate(() => {
    const tbl = document.querySelector("#main table.aws, #main table");
    if (!tbl) return { headers: [], rows: [] };
    const trs = [...tbl.querySelectorAll("tr")];
    const headers = [...(trs[0]?.querySelectorAll("th") || [])].map((e) => e.innerText.replace(/[▲▼]/g, "").trim());
    const rows = trs.slice(1).map((tr) => [...tr.querySelectorAll("td")].map((e) => e.innerText.trim())).filter((r) => r.length);
    return { headers, rows };
  });
}
function filled(headers, rows, what) {
  const empty = [];
  rows.forEach((r) => r.forEach((c, i) => { if (headers[i] && BLANK.test(c)) empty.push(`${headers[i]}`); }));
  check(rows.length > 0 && empty.length === 0, `${what}: every column filled`, empty.length ? `blank: ${[...new Set(empty)].join(", ")}` : "no rows");
}

try {
  // start from a clean slate (a previous run may have left the default-named zone)
  const old = await (await fetch(`${BASE}/api/aws/route53/hosted-zones`)).json().catch(() => ({ items: [] }));
  for (const z of old.items || []) if (z.name === DEFAULT_NAME + ".") await fetch(`${BASE}/api/aws/route53/hosted-zones/${z.zone_id}`, { method: "DELETE" }).catch(() => {});
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  const rail = await page.locator(RAIL_SEL).filter({ hasText: "Route 53" }).count();
  check(rail > 0, "Route 53 is on the AWS service rail");
  if (!rail) throw new Error("Route 53 missing from the rail");

  await openRail("Route 53");
  check(!(await text("#main")).includes("Failed to load"), "Route 53 list loads");
  check(await page.locator("#main button").filter({ hasText: /Create/ }).count() > 0, "Create button is shown");

  // ── create with the form defaults ──────────────────────────────────────
  await page.locator("#main button").filter({ hasText: /Create/ }).first().click();
  await page.waitForTimeout(1200);
  const defaults = await page.evaluate(() => [...document.querySelectorAll("#main input")].map((i) => i.value));
  check(defaults.includes(DEFAULT_NAME) && defaults.includes("Managed by Vyomi") && defaults.includes("public"),
    "create form has realistic defaults", JSON.stringify(defaults));
  let created = null;
  page.on("response", (r) => { if (r.request().method() === "POST" && /\/api\/aws\/route53\/hosted-zones$/.test(r.url())) created = r.status(); });
  await page.locator("#main .wizard-footer button.primary, #main button.primary").filter({ hasText: /Create/ }).last().click();
  for (let i = 0; i < 20 && created === null; i++) await page.waitForTimeout(400);
  check(created === 200, "create with defaults returns 200", `HTTP ${created}`);
  await page.waitForTimeout(1500);
  if (!(await text("#main")).includes(DEFAULT_NAME)) await openRail("Hosted zones");

  const { headers, rows } = await gridRows();
  check(rows.some((r) => r.includes(DEFAULT_NAME + ".")), "new hosted zone appears in the grid", JSON.stringify(rows));
  check(["Hosted zone name", "Type", "Created by", "Record count", "Description", "Hosted zone ID"].every((h) => headers.includes(h)), "grid has the expected columns", headers.join(", "));
  filled(headers, rows, "hosted zones grid");
  check(rows.some((r) => r.some((c) => c === "Public hosted zone")), "zone is a public hosted zone");

  // ── detail page + every tab ────────────────────────────────────────────
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME + "." }).first().click();
  await page.waitForTimeout(1800);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((e) => e.innerText.trim()).filter(Boolean));
  check(tabs.length >= 5 && tabs.includes("Records"), "detail page has tabs", tabs.join(", "));
  for (const t of tabs) {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp(`^${t}$`) }).first().click();
    await page.waitForTimeout(900);
    const body = await page.evaluate(() => {
      const kids = [...document.querySelectorAll("#main > *")];
      const host = kids[kids.length - 1];
      return host ? host.innerText : "";
    });
    check(body.trim().length > 25 && !/Renderer error|Not yet wired|Failed to load|undefined/i.test(body), `detail tab "${t}" renders`, body.slice(0, 80));
  }
  const summary = await text("#main .summary-grid");
  check(/Public hosted zone/.test(summary) && /Managed by Vyomi/.test(summary), "detail summary shows the zone's real values", summary.slice(0, 160));

  // ── records tab shows SOA + NS, a record added through the console REST appears ──
  const mk = (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    return r.status;
  }, [method, path, body]);
  const zid = await page.evaluate(async (n) => ((await (await fetch("/api/aws/route53/hosted-zones")).json()).items || []).find((z) => z.name === n + ".")?.zone_id, DEFAULT_NAME);
  check(!!zid, "zone has a Route 53 style id", String(zid));
  check((await mk("POST", `/api/aws/route53/hosted-zones/${zid}/records`, { name: "www." + DEFAULT_NAME, type: "A", ttl: 300, values: "192.0.2.10" })) === 200, "create an A record");
  await openRail("Hosted zones");
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME + "." }).first().click();
  await page.waitForTimeout(1500);
  await page.locator("#main .top-tabs button").filter({ hasText: /^Records$/ }).first().click();
  await page.waitForTimeout(900);
  const recs = await gridRows();
  check(recs.rows.length === 3 && recs.rows.some((r) => r[0] === "www." + DEFAULT_NAME + "." && r[1] === "A" && r[4] === "192.0.2.10"), "Records tab lists SOA, NS and the new A record", JSON.stringify(recs.rows.map((r) => r.slice(0, 2))));
  filled(recs.headers, recs.rows, "records grid");
  check((await mk("DELETE", `/api/aws/route53/hosted-zones/${zid}/records?name=www.${DEFAULT_NAME}.&type=A`)) === 200, "delete the A record");

  // ── health checks list (create one through the console REST) ──
  check((await mk("POST", "/api/aws/route53/health-checks", { target: "www." + DEFAULT_NAME, type: "HTTPS", port: 443, path: "/health" })) === 200, "create a health check");
  await openRail("Health checks");
  const hg = await gridRows();
  check(hg.rows.length > 0 && hg.rows.some((r) => r[1] === "HTTPS"), "Health checks list shows the new check", JSON.stringify(hg.rows.slice(0, 2)));
  filled(hg.headers, hg.rows, "Health checks");
  for (const r of hg.rows) await mk("DELETE", `/api/aws/route53/health-checks/${r[0]}`);

  // ── delete from the UI ─────────────────────────────────────────────────
  await openRail("Hosted zones");
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME + "." }).first().click();
  await page.waitForTimeout(1500);
  await page.locator("#main button").filter({ hasText: /Delete/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(2000);
  if (!(await text("#main")).includes("You have no") && (await text("#main")).includes(DEFAULT_NAME)) await openRail("Hosted zones");
  const after = await gridRows();
  check(!after.rows.some((r) => r.includes(DEFAULT_NAME + ".")), "hosted zone is gone after Delete", JSON.stringify(after.rows));
  check(!bad.length, "no API 5xx during the flow", bad.join(", "));
} catch (e) {
  check(false, "Route 53 console flow", String(e.message || e).split("\n")[0]);
} finally {
  await browser.close();
}
console.log(`route53 ui (offline): ${fails ? "FAILED" : "ok"}`);
process.exit(fails ? 1 : 0);
