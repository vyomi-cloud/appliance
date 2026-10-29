/* Offline console conformance for Azure Monitor (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create a metric alert rule with the form defaults, every grid column filled, every
 * detail tab renders (condition, action groups, activity log alerts, autoscale…), items added in the blade
 * are readable over ARM, cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-monitor.mjs
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
const SERVICE = /Monitor alerts/i;
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
  const sp = d.active_space || (d.spaces || []).find((s) => s.provider === "azure" && s.cost_savings) || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.monitor"] || 0 };
};

const sub = "00000000-0000-0000-0000-cloudlearn01";
const NAME = "cloudlearn-cpu-high";
const RGN = "cloudlearn-rg";
const arm = `${BASE}/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.Insights`;
const AV = "api-version=2018-03-01";
const cleanup = async (n) => { await fetch(`${arm}/metricAlerts/${n}?${AV}`, { method: "DELETE" }).catch(() => {}); };

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.Insights\/metricAlerts\/[^/?]+\?/.test(r.url())) createStatus = r.status();
  if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const answers = [];
page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()).catch(() => {}));

try {
  await cleanup(NAME);   // leftover from an aborted run
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Monitor alerts is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/metric alert rules/i.test(await page.locator("#main").innerText()), "service page explains what the service does");
  const s0 = await savings();

  // create with the form defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(/^[a-z0-9-]{3,}$/.test(name), "create form has a realistic default alert rule name", `name="${name}"`);
  // portal-style wizard: Basics -> Condition -> Tags -> Review + create
  for (let i = 0; i < 6; i++) {
    const fin = page.locator("#blade button").filter({ hasText: /^\s*create\s*$/i });
    if (await fin.count()) break;
    await page.locator("#blade button").filter({ hasText: /^\s*(next|review \+ create)\s*$/i }).last().click({ timeout: 5000 });
    await sleep(300);
  }
  await page.locator("#blade button").filter({ hasText: /^\s*create\s*$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new alert rule appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 7 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);
  check(data.some(([h, v]) => /Severity/i.test(h) && v === "3") && data.some(([h, v]) => /Evaluation/i.test(h) && v === "PT1M") &&
        data.some(([h, v]) => /Scopes/i.test(h) && /virtualMachines/.test(v)), "grid shows severity, evaluation frequency and the scope", JSON.stringify(data));

  // cost savings include the new rule
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > s0.usd, "cost-savings metrics include the new rule (azure.monitor priced)",
        `count ${s0.count}→${s1.count}, $${s0.usd}→$${s1.usd}, rule $${s1.svc}`);

  // detail tabs
  await rowFor().locator("a").first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = (await page.locator(".sub-nav-item .lbl").allInnerTexts()).map((t) => t.trim());
  check(tabs.length >= 9, "detail view shows its tabs", tabs.join(" | "));
  const tabIndex = (re) => tabs.findIndex((t) => re.test(t));
  const open = async (i) => { await page.locator(".sub-nav-item").nth(i).click({ timeout: 3000 }); await sleep(700); return ((await page.locator(".sub-content").innerText()) || "").trim(); };
  const seen = new Set();
  const content = {};
  for (let i = 0; i < tabs.length; i++) {
    const txt = await open(i);
    content[tabs[i]] = txt;
    const ok = txt.length > 25 && !/Renderer error|Failed to load|coming soon|undefined|null|\[object Object\]/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  const cond = content["Condition"] || "";
  check(/Percentage CPU/.test(cond) && /GreaterThan/.test(cond) && /80/.test(cond) && /PT5M/.test(cond), "Condition shows the metric, operator, threshold and window", cond.slice(0, 200));

  // add an action group in the blade, read it back over ARM
  const agt = tabIndex(/Action groups/i);
  await open(agt);
  answers.push("ui-ops", "uiops", "oncall@example.com");
  await page.locator(".sub-content button").filter({ hasText: /Add action group/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const sets = await page.locator(".sub-content").innerText();
  check(/ui-ops/.test(sets) && /uiops/.test(sets) && /oncall@example\.com/.test(sets), "action group added in the blade is listed", sets.slice(0, 240));
  const rr = await fetch(`${arm}/actionGroups/ui-ops?api-version=2023-01-01`);
  const rj = await rr.json().catch(() => ({}));
  check(rr.status === 200 && rj.properties?.emailReceivers?.[0]?.status === "Enabled" && rj.properties?.groupShortName === "uiops", "…and readable over ARM", JSON.stringify(rj).slice(0, 160));
  await fetch(`${arm}/actionGroups/api-ops?api-version=2023-01-01`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location: "Global", properties: { groupShortName: "apiops", enabled: true } }) });
  await open(tabIndex(/Overview/i));
  await open(agt);
  check(/api-ops/.test(await page.locator(".sub-content").innerText()), "an action group created through the API shows in the blade");
  // activity log alert + autoscale tabs add flows
  await open(tabIndex(/Activity log alerts/i));
  answers.push("ui-deploy-failed", "Administrative");
  await page.locator(".sub-content button").filter({ hasText: /Add activity log alert/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/ui-deploy-failed/.test(await page.locator(".sub-content").innerText()), "activity log alert added in the blade is listed");
  await open(tabIndex(/Autoscale/i));
  answers.push("ui-autoscale");
  await page.locator(".sub-content button").filter({ hasText: /Add autoscale setting/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/ui-autoscale/.test(await page.locator(".sub-content").innerText()), "autoscale setting added in the blade is listed");
  for (const [t, n, v] of [["actionGroups", "ui-ops", "2023-01-01"], ["actionGroups", "api-ops", "2023-01-01"], ["activityLogAlerts", "ui-deploy-failed", "2020-10-01"], ["autoscaleSettings", "ui-autoscale", "2022-10-01"]])
    await fetch(`${arm}/${t}/${n}?api-version=${v}`, { method: "DELETE" }).catch(() => {});

  // delete from the detail pane
  await open(tabIndex(/Overview/i));
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the alert rule from the list", name);
  const r = await fetch(`${arm}/metricAlerts/${name}?${AV}`);
  check(r.status === 404, "deleted alert rule is gone from the ARM API", `HTTP ${r.status}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
  await cleanup(NAME);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
