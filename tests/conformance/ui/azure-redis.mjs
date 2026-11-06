/* Offline console conformance for Azure Cache for Redis (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create a cache with the form defaults, every grid column filled, every detail tab renders
 * (connect, access keys, advanced settings, firewall, schedule updates, geo-replication, reboot/import/export…),
 * keys rotate and firewall rules added in the blade are readable over ARM, the Valkey data plane answers,
 * cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-redis.mjs
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
const SERVICE = /Azure Cache for Redis/i;
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
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.redis"] || 0 };
};

const sub = "00000000-0000-0000-0000-cloudlearn01";
const NAME = "cloudlearn-cache";
const RGN = "cloudlearn-rg";
const arm = `${BASE}/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.Cache`;
const AV = "api-version=2024-03-01";
const cleanup = async (n) => { await fetch(`${arm}/Redis/${n}?${AV}`, { method: "DELETE" }).catch(() => {}); };

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.Cache\/Redis\/[^/?]+\?/.test(r.url())) createStatus = r.status();
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
  check((await rail.count()) > 0, "Azure Cache for Redis is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/managed redis caches/i.test(await page.locator("#main").innerText()), "service page explains what the service does");
  const s0 = await savings();

  // create with the wizard defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(/^[a-z0-9-]{3,}$/.test(name), "create form has a realistic default cache name", `name="${name}"`);
  // portal-style wizard: Basics -> Advanced -> Tags -> Review + create
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
  check(await rowFor().count() > 0, "new cache appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 8 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);
  check(data.some(([h, v]) => /Pricing tier/i.test(h) && v === "Basic") && data.some(([h, v]) => /Host name/i.test(h) && v === `${name}.redis.cache.windows.net`) &&
        data.some(([h, v]) => /SSL port/i.test(h) && v === "6380") && data.some(([h, v]) => /Status/i.test(h) && v === "Succeeded"),
        "grid shows tier, host name, SSL port and status", JSON.stringify(data));

  // cost savings include the new cache
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > s0.usd, "cost-savings metrics include the new cache (azure.redis priced)",
        `count ${s0.count}→${s1.count}, $${s0.usd}→$${s1.usd}, cache $${s1.svc}`);

  // detail tabs
  await rowFor().locator("a").first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = (await page.locator(".sub-nav-item .lbl").allInnerTexts()).map((t) => t.trim());
  check(tabs.length >= 10, "detail view shows its tabs", tabs.join(" | "));
  const tabIndex = (re) => tabs.findIndex((t) => re.test(t));
  const open = async (i) => { await page.locator(".sub-nav-item").nth(i).click({ timeout: 3000 }); await sleep(900); return ((await page.locator(".sub-content").innerText()) || "").trim(); };
  const seen = new Set();
  const content = {};
  for (let i = 0; i < tabs.length; i++) {
    const txt = await open(i);
    content[tabs[i]] = txt;
    const ok = txt.length > 25 && !/Renderer error|Failed to load|coming soon|undefined|null|\[object Object\]/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  const conn = content["Connect"] || "";
  check(new RegExp(`${name}\\.redis\\.cache\\.windows\\.net`).test(conn) && /6380/.test(conn) && /Valkey data plane/.test(conn) && /redis-cli -h/.test(conn),
        "Connect shows the host name, TLS port and the Valkey data plane", conn.slice(0, 240));
  const cfgTab = content["Advanced settings"] || "";
  check(/maxclients/.test(cfgTab) && /256/.test(cfgTab) && /maxmemory-policy/.test(cfgTab) && /volatile-lru/.test(cfgTab), "Advanced settings lists the computed Redis configuration", cfgTab.slice(0, 200));

  // the Valkey data plane answers a real Redis PING
  await open(tabIndex(/^Connect$/i));
  const ping = await (await fetch(`${BASE}/azure-data/redis/ping`)).json().catch(() => ({}));
  check(ping.dataPlane === true && /PONG/.test(ping.reply || ""), "the Valkey data plane answers a Redis PING", JSON.stringify(ping));

  // rotate a key in the blade, read it over ARM
  const keysBefore = await (await fetch(`${arm}/Redis/${name}/listKeys?${AV}`, { method: "POST" })).json();
  await open(tabIndex(/Access keys/i));
  const keyText = await page.locator(".sub-content").innerText();
  check(keyText.includes(keysBefore.primaryKey) && keyText.includes(keysBefore.secondaryKey), "Access keys tab shows both keys", keyText.slice(0, 200));
  await page.locator(".sub-content button").filter({ hasText: /Regenerate/ }).first().click({ timeout: 5000 });
  await sleep(1500);
  const keysAfter = await (await fetch(`${arm}/Redis/${name}/listKeys?${AV}`, { method: "POST" })).json();
  check(keysAfter.primaryKey !== keysBefore.primaryKey && keysAfter.secondaryKey === keysBefore.secondaryKey, "Regenerate in the blade rotates the primary key (visible over ARM)");

  // firewall rule: add in the blade, read over ARM; one created through the API shows in the blade
  await open(tabIndex(/Firewall/i));
  answers.push("ui_office", "10.1.0.1", "10.1.0.50");
  await page.locator(".sub-content button").filter({ hasText: /Add rule/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const fwText = await page.locator(".sub-content").innerText();
  check(/ui_office/.test(fwText) && /10\.1\.0\.1/.test(fwText) && /10\.1\.0\.50/.test(fwText), "firewall rule added in the blade is listed", fwText.slice(0, 240));
  const fr = await fetch(`${arm}/Redis/${name}/firewallRules/ui_office?${AV}`);
  const frj = await fr.json().catch(() => ({}));
  check(fr.status === 200 && frj.properties?.endIP === "10.1.0.50", "…and readable over ARM", JSON.stringify(frj).slice(0, 160));
  await fetch(`${arm}/Redis/${name}/firewallRules/api_rule?${AV}`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ properties: { startIP: "10.2.0.1", endIP: "10.2.0.9" } }) });
  await open(tabIndex(/Overview/i));
  await open(tabIndex(/Firewall/i));
  check(/api_rule/.test(await page.locator(".sub-content").innerText()), "a firewall rule created through the API shows in the blade");

  // advanced settings: change the eviction policy
  await open(tabIndex(/Advanced settings/i));
  await page.locator(".sub-content select").first().selectOption("allkeys-lru");
  await page.locator(".sub-content button").filter({ hasText: /save\s*$/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const got = await (await fetch(`${arm}/Redis/${name}?${AV}`)).json();
  check(got.properties?.redisConfiguration?.["maxmemory-policy"] === "allkeys-lru", "saving Advanced settings updates the eviction policy over ARM", JSON.stringify(got.properties?.redisConfiguration));
  await fetch(`${arm}/Redis/${name}/firewallRules/ui_office?${AV}`, { method: "DELETE" }).catch(() => {});
  await fetch(`${arm}/Redis/${name}/firewallRules/api_rule?${AV}`, { method: "DELETE" }).catch(() => {});

  // delete from the detail pane
  await open(tabIndex(/Overview/i));
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the cache from the list", name);
  const r = await fetch(`${arm}/Redis/${name}?${AV}`);
  check(r.status === 404, "deleted cache is gone from the ARM API", `HTTP ${r.status}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
  await cleanup(NAME);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
