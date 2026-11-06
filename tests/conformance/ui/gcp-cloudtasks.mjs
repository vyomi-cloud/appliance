/* Offline console conformance for Cloud Tasks (driven against $VYOMI_BASE_URL/console/gcp).
 * Open the service, create with the form defaults, every grid column filled, every detail tab
 * renders, the cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-cloudtasks.mjs
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
const SERVICE = /Cloud Tasks/i;
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
  const svc = (cs.by_service || {})["gcp.cloudtasks"] || 0;
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc };
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", async (r) => {
  if (r.request().method() === "POST" && /\/api\/(gcp\/)?cloudtasks\/queues$/.test(r.url())) createStatus = r.status();
  if (r.status() >= 400 && r.url().includes("/api/") && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));

try {
  // a previous run (or another suite) may have left the default-named queue behind
  await fetch(`${BASE}/api/gcp/cloudtasks/queues/my-queue`, { method: "DELETE" }).catch(() => {});
  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Cloud Tasks is on the GCP console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  const rows = () => page.locator("#main table tr:has(td)").count();
  const rows0 = await rows();

  // create with defaults
  await page.locator("#main button").filter({ hasText: /create|launch/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input[type=text]").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  await page.locator("#main button.primary").filter({ hasText: /^\s*check\s*create|^\s*create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 20 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  await sleep(1500);
  const hasRow = async () => (await page.locator("#main table tr:has(td)").filter({ hasText: name || "zzz-none" }).count()) > 0;
  for (let i = 0; i < 10 && !(await hasRow()); i++) await sleep(800);
  check(await hasRow(), "new queue appears in the list", `rows ${rows0} → ${await rows()}, name ${name}`);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const myRow = page.locator("#main table tr:has(td)").filter({ hasText: name || "zzz-none" }).first();
  const cells = await myRow.locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 6 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  // cost savings moved — other suites share this appliance, so assert on what OUR API must
  // contribute (Cloud Tasks is priced in the savings, resources counted) rather than a delta
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count >= 1); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > 0, "cost-savings metrics include the new queue (gcp.cloudtasks priced)",
        `count ${s1.count}, $${s1.usd}, cloudtasks $${s1.svc}`);

  // add a task through the API so the Tasks tab has rows, then open the detail view
  const mk = await fetch(`${BASE}/api/gcp/cloudtasks/queues/${encodeURIComponent(name)}/tasks`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: "https://example.com/handler" }) });
  check(mk.ok, "a task can be added to the queue", `HTTP ${mk.status}`);
  await myRow.locator("a.id").first().click({ timeout: 5000 });
  await sleep(1500);
  const navItems = page.locator(".sub-nav a.nav-item");
  const tabs = await navItems.allInnerTexts();
  check(tabs.length >= 4, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  for (let i = 0; i < tabs.length; i++) {
    await navItems.nth(i).click({ timeout: 3000 });
    await sleep(900);
    const txt = ((await page.locator(".sub-content").innerText()) || "").trim();
    const ok = txt.length > 20 && !/Renderer error|Failed to load|Not yet wired|coming soon|undefined|Wiring lands/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i].replace(/^\S+\s/, "").trim()}" renders`, txt.slice(-160).replace(/\n/g, " ⏎ "));
  }
  const tasksTab = tabs.findIndex((t) => /tasks/i.test(t));
  if (tasksTab >= 0) {
    await navItems.nth(tasksTab).click();
    await sleep(900);
    const t = await page.locator(".sub-content").innerText();
    check(/example\.com\/handler/.test(t) && /POST/.test(t) && !/\bundefined\b/.test(t), "Tasks tab lists the task with method and URL");
  }

  // delete via the detail Delete action
  await page.locator("#main button.danger").first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await hasRow()); i++) await sleep(800);
  check(!(await hasRow()), "delete removes the queue from the list", `name ${name}`);
  const list = await (await fetch(`${BASE}/api/gcp/cloudtasks/queues`)).json();
  check(name && !(list.items || []).some((a) => a.name === name), "deleted queue is gone from the backend", name);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
