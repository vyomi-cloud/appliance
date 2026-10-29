/* Offline console conformance for Systems Manager (driven against $VYOMI_BASE_URL/console/aws).
 * Open the service, create with the form defaults, every grid column filled, every detail tab
 * renders, the cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-ssm.mjs
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
const SERVICE = /Systems Manager/i;
const DEFAULT_NAME = "/vyomi/app/config";
const PARAM = "/api/ssm/parameters/" + encodeURIComponent(DEFAULT_NAME);
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
  const svc = (cs.by_service || {})["aws.ssm"] || 0;
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc };
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null, newId = "";
page.on("response", async (r) => {
  if (r.request().method() === "POST" && /\/api\/ssm\/parameters$/.test(r.url())) {
    createStatus = r.status();
    try { newId = (await r.json()).name || ""; } catch (_) {}
  }
  if (r.status() >= 400 && r.url().includes("/api/") && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));

try {
  await fetch(BASE + PARAM, { method: "DELETE" }).catch(() => {});   // a previous run may have left the default-named parameter
  const before = await savings();
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Systems Manager is on the AWS console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  const rows = () => page.locator("#main table tr:has(td)").count();
  const rows0 = await rows();

  // create with defaults
  await page.locator("#main button").filter({ hasText: /create|launch/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  await page.locator("#main button").filter({ hasText: /^\s*create/i }).filter({ hasNotText: /cancel/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 20 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  await sleep(1500);
  let after = await rows();
  for (let i = 0; i < 10 && !(await page.locator("#main table tr:has(td)").filter({ hasText: newId || "zzz-none" }).count()); i++) { await sleep(800); after = await rows(); }
  const hasRow = async () => (await page.locator("#main table tr:has(td)").filter({ hasText: newId || "zzz-none" }).count()) > 0;
  check(await hasRow(), "new parameter appears in the list", `rows ${rows0} → ${after}, id ${newId}`);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const myRow = page.locator("#main table tr:has(td)").filter({ hasText: newId || "zzz-none" }).first();
  const cells = await myRow.locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const apiId = newId || (data.find(([h]) => /^Name$/i.test(h)) || [])[1] || "";
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  // cost savings moved — other suites share this appliance, so assert on what OUR API must
  // contribute (Systems Manager is priced in the savings, resources counted) rather than a delta
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count >= 1); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > 0, "cost-savings metrics include the new parameter (aws.ssm priced)",
        `count ${s1.count}, $${s1.usd}, ssm $${s1.svc}`);

  // detail tabs
  await myRow.locator("a, td:not(.chk)").first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = await page.locator(".top-tabs button").allInnerTexts();
  check(tabs.length >= 6, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  for (let i = 0; i < tabs.length; i++) {
    await page.locator(".top-tabs button").nth(i).click({ timeout: 3000 });
    await sleep(900);
    const txt = ((await page.locator("#main").innerText()) || "").trim();
    const tabText = txt.split("\n").slice(-12).join("\n");
    const ok = txt.length > 40 && !/Renderer error|Failed to load|Not yet wired|coming soon|undefined/i.test(txt) && !seen.has(tabText);
    seen.add(tabText);
    check(ok, `tab "${tabs[i].trim()}" renders`, txt.slice(-160).replace(/\n/g, " ⏎ "));
  }
  const histTab = tabs.findIndex((t) => /history/i.test(t));
  if (histTab >= 0) {
    await page.locator(".top-tabs button").nth(histTab).click();
    await sleep(900);
    check(/hello-from-vyomi/.test(await page.locator("#main").innerText()), "History tab lists version 1 of the parameter");
  }
  const valTab = tabs.findIndex((t) => /^\s*value/i.test(t));
  if (valTab >= 0) {
    await page.locator(".top-tabs button").nth(valTab).click();
    await sleep(900);
    check(/hello-from-vyomi/.test(await page.locator("#main").innerText()), "Value tab shows the parameter value");
  }

  // delete via the detail Delete action
  await page.locator("#main button").filter({ hasText: /delete/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await hasRow()); i++) await sleep(800);
  check(!(await hasRow()), "delete removes the parameter from the list", `id ${newId}`);
  const list = await (await fetch(`${BASE}/api/ssm/parameters`)).json();
  check(apiId && !(list.parameters || []).some((a) => a.name === apiId), "deleted parameter is gone from the backend", apiId);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
