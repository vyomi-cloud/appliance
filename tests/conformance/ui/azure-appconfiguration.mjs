/* Offline console conformance for Azure App Configuration (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create a store with the form defaults, every grid column filled, every detail
 * tab renders (configuration explorer, access settings, geo-replication…), a key-value created in the
 * explorer is readable on the data plane, cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-appconfiguration.mjs
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
const SERVICE = /App Configuration/i;
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
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.appconfiguration"] || 0 };
};

const sub = "00000000-0000-0000-0000-cloudlearn01";
const NAME = "appconfig-cloudlearn";
const arm = `${BASE}/subscriptions/${sub}/resourceGroups/cloudlearn-rg/providers/Microsoft.AppConfiguration`;
const loc = `${BASE}/subscriptions/${sub}/providers/Microsoft.AppConfiguration/locations/eastus/deletedConfigurationStores`;
const AV = "api-version=2024-05-01";
const cleanup = async (n) => {   // delete + purge the soft-deleted store so the default name is reusable
  await fetch(`${arm}/configurationStores/${n}?${AV}`, { method: "DELETE" }).catch(() => {});
  await fetch(`${loc}/${n}/purge?${AV}`, { method: "POST" }).catch(() => {});
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.AppConfiguration\/configurationStores\/[^/?]+\?/.test(r.url())) createStatus = r.status();
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
  check((await rail.count()) > 0, "App Configuration is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/key-values|feature flags/i.test(await page.locator("#main").innerText()), "service page explains what the service does");
  const s0 = await savings();

  // create with the form defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(name.length >= 5, "create form has a realistic default name", `name="${name}"`);
  const fields = await page.locator("#blade input").evaluateAll((els) => els.map((e) => e.value));
  check(fields.includes("Standard"), "create form defaults the pricing tier to Standard", JSON.stringify(fields));
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new store appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  // cost savings include the new store
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > s0.usd, "cost-savings metrics include the new store (azure.appconfiguration priced)",
        `count ${s0.count}→${s1.count}, $${s0.usd}→$${s1.usd}, store $${s1.svc}`);

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
  check(/Standard|Succeeded/.test(content["Overview"] || "") || /appconfig/.test(content["Overview"] || ""), "Overview shows the store", (content["Overview"] || "").slice(0, 120));
  check(/Primary/.test(content["Access settings"] || "") && /Endpoint=/.test(content["Access settings"] || ""), "Access settings lists keys with connection strings", (content["Access settings"] || "").slice(0, 200));

  // configuration explorer: create a key-value in the UI, read it back through the data plane
  const ex = tabIndex(/Configuration explorer/i);
  await open(ex);
  answers.push("ui:greeting", "hello from the console", "prod");
  await page.locator(".sub-content button").filter({ hasText: /Create key-value/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const explorer = await page.locator(".sub-content").innerText();
  check(/ui:greeting/.test(explorer) && /hello from the console/.test(explorer) && /prod/.test(explorer), "key-value created in the explorer is listed", explorer.slice(0, 200));
  const kvRes = await fetch(`${BASE}/azure-data/appconfig/${name}/kv/ui:greeting?label=prod`);
  const kv = await kvRes.json().catch(() => ({}));
  check(kvRes.status === 200 && kv.value === "hello from the console", "…and readable on the data plane (/kv)", JSON.stringify(kv));
  await fetch(`${BASE}/azure-data/appconfig/${name}/kv/api:written?label=dev`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: "from sdk" }) });
  await open(tabIndex(/Overview/i));
  await open(ex);
  check(/api:written/.test(await page.locator(".sub-content").innerText()), "a key-value written through the data plane shows in the explorer");

  // delete from the detail pane
  await open(tabIndex(/Overview/i));
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the store from the list", name);
  const r = await fetch(`${arm}/configurationStores/${name}?${AV}`);
  check(r.status === 404, "deleted store is gone from the ARM API", `HTTP ${r.status}`);
  const dl = await (await fetch(`${loc}?${AV}`)).json();
  check((dl.value || []).some((s) => s.name === name), "…and is listed as soft-deleted (recoverable)");
  await cleanup(name);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
  await cleanup(NAME);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
