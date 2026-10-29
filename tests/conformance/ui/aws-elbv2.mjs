/* Elastic Load Balancing console conformance — offline appliance ($VYOMI_BASE_URL/console/aws).
 *
 * Opens Load Balancing from the service rail, creates a load balancer with the form's
 * default values, checks every grid column is filled, opens the detail page and
 * every tab, visits the Target groups / Listeners lists, then
 * deletes the load balancer from the UI.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-elbv2.mjs
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
const DEFAULT_NAME = "my-alb";   // the create form's default
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
  // start from a clean slate (a previous run may have left the default-named load balancer)
  await fetch(`${BASE}/api/aws/elbv2/load-balancers/${DEFAULT_NAME}`, { method: "DELETE" }).catch(() => {});

  await fetch(`${BASE}/api/aws/elbv2/target-groups/my-tg`, { method: "DELETE" }).catch(() => {});
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  const rail = await page.locator(RAIL_SEL).filter({ hasText: "Load Balancing" }).count();
  check(rail > 0, "Load Balancing is on the AWS service rail");
  if (!rail) throw new Error("Load Balancing missing from the rail");

  await openRail("Load Balancing");
  check(!(await text("#main")).includes("Failed to load"), "Load Balancing list loads");
  check(await page.locator("#main button").filter({ hasText: /Create/ }).count() > 0, "Create button is shown");

  // ── create with the form defaults ──────────────────────────────────────
  await page.locator("#main button").filter({ hasText: /Create/ }).first().click();
  await page.waitForTimeout(1200);
  const defaults = await page.evaluate(() => [...document.querySelectorAll("#main input")].map((i) => i.value));
  check(defaults.includes(DEFAULT_NAME) && defaults.includes("application") && defaults.includes("internet-facing"),
    "create form has realistic defaults", JSON.stringify(defaults));
  let created = null;
  page.on("response", (r) => { if (r.request().method() === "POST" && /\/api\/aws\/elbv2\/load-balancers$/.test(r.url())) created = r.status(); });
  await page.locator("#main .wizard-footer button.primary, #main button.primary").filter({ hasText: /Create/ }).last().click();
  for (let i = 0; i < 20 && created === null; i++) await page.waitForTimeout(400);
  check(created === 200, "create with defaults returns 200", `HTTP ${created}`);
  await page.waitForTimeout(1500);
  if (!(await text("#main")).includes(DEFAULT_NAME)) await openRail("Load balancers");

  const { headers, rows } = await gridRows();
  check(rows.some((r) => r.includes(DEFAULT_NAME)), "new load balancer appears in the grid", JSON.stringify(rows));
  check(["Name", "DNS name", "State", "Type", "Scheme", "VPC ID", "Availability Zones", "Date created"].every((h) => headers.includes(h)), "grid has the expected columns", headers.join(", "));
  filled(headers, rows, "load balancers grid");
  check(rows.some((r) => r.some((c) => c.toLowerCase() === "active")), "state is active");

  // ── detail page + every tab ────────────────────────────────────────────
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME }).first().click();
  await page.waitForTimeout(1800);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((e) => e.innerText.trim()).filter(Boolean));
  check(tabs.length >= 4, "detail page has tabs", tabs.join(", "));
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
  check(/application/i.test(summary) && /internet-facing/.test(summary), "detail summary shows the load balancer's real values", summary.slice(0, 120));

  // ── child lists (create a target group + listener through the console REST) ──
  const mk = (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const r = await fetch(p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    return r.status;
  }, [method, path, body]);
  check((await mk("POST", "/api/aws/elbv2/target-groups", { name: "my-tg" })) === 200, "create a target group");
  check((await mk("POST", "/api/aws/elbv2/listeners", { load_balancer: DEFAULT_NAME, port: 80 })) === 200, "create a listener");
  for (const [label, want] of [["Target groups", "my-tg"], ["Listeners", ""]]) {
    await openRail(label);
    const g = await gridRows();
    check(g.rows.length > 0 && (!want || g.rows.some((r) => r[0] === want)), `${label} list shows the new resource`, JSON.stringify(g.rows.slice(0, 2)));
    filled(g.headers, g.rows, label);
  }

  // ── delete from the UI ─────────────────────────────────────────────────
  await openRail("Load balancers");
  await page.locator("#main a.id, #main td a").filter({ hasText: DEFAULT_NAME }).first().click();
  await page.waitForTimeout(1500);
  await page.locator("#main button").filter({ hasText: /Delete/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(2000);
  if (!(await text("#main")).includes("You have no") && (await text("#main")).includes(DEFAULT_NAME)) await openRail("Load balancers");
  const after = await gridRows();
  check(!after.rows.some((r) => r.includes(DEFAULT_NAME)), "load balancer is gone after Delete", JSON.stringify(after.rows));
  await mk("DELETE", "/api/aws/elbv2/target-groups/my-tg");
  check(!bad.length, "no API 5xx during the flow", bad.join(", "));
} catch (e) {
  check(false, "Load Balancing console flow", String(e.message || e).split("\n")[0]);
} finally {
  await browser.close();
}
console.log(`elbv2 ui (offline): ${fails ? "FAILED" : "ok"}`);
process.exit(fails ? 1 : 0);
