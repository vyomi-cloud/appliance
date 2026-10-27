/* Nano console conformance for Azure Cache for Redis — same flows as the offline test
 * (tests/conformance/ui/azure-redis.mjs), driven against the in-browser Nano bundle: open the service, create a
 * cache with the wizard defaults, every grid column filled, every detail tab renders, keys rotate and firewall
 * rules added in the blade are stored, cost-savings metrics move, delete. Nano runs the control plane only
 * (no Valkey container in the browser) and says so in the Connect tab.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-redis.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Azure Cache for Redis/i;
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
const AV = "api-version=2024-03-01";
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.Cache\/Redis\/[^/?]+\?/.test(r.url())) createStatus = r.status();
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const answers = [];
page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()).catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "azure" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "azure") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.redis"] || 0 };
});

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Azure Cache for Redis is on the Nano Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/managed redis caches/i.test(await page.locator("#main").innerText()), "service page explains what the service does");

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
  for (let i = 0; i < 40 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new cache appears in the list", name);

  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 8 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);
  check(data.some(([h, v]) => /Pricing tier/i.test(h) && v === "Basic") && data.some(([h, v]) => /Host name/i.test(h) && v === `${name}.redis.cache.windows.net`) &&
        data.some(([h, v]) => /SSL port/i.test(h) && v === "6380") && data.some(([h, v]) => /Status/i.test(h) && v === "Succeeded"),
        "grid shows tier, host name, SSL port and status", JSON.stringify(data));

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

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
    const ok = txt.length > 25 && !/Renderer error|Failed to load|coming soon|undefined|\[object Object\]/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  const conn = content["Connect"] || "";
  check(new RegExp(`${name}\\.redis\\.cache\\.windows\\.net`).test(conn) && /6380/.test(conn) && /Control plane only/.test(conn),
        "Connect shows the host name, TLS port and says Nano is control plane only", conn.slice(0, 240));
  const cfgTab = content["Advanced settings"] || "";
  check(/maxclients/.test(cfgTab) && /256/.test(cfgTab) && /maxmemory-policy/.test(cfgTab) && /volatile-lru/.test(cfgTab), "Advanced settings lists the computed Redis configuration", cfgTab.slice(0, 200));

  const rg = await page.evaluate(() => RG);
  const SUBID = await page.evaluate(() => SUB);
  const armCall = (path, method, body) => page.evaluate(async ([sub, rg, p, m, b, av]) => {
    const r = await fetch(`/subscriptions/${sub}/resourceGroups/${rg}/providers/Microsoft.Cache/${p}${p.includes("?") ? "&" : "?"}${av}`,
      { method: m, headers: b ? { "Content-Type": "application/json" } : {}, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  }, [SUBID, rg, path, method || "GET", body || null, AV]);

  const keysBefore = (await armCall(`Redis/${name}/listKeys`, "POST", {})).body;
  await open(tabIndex(/Access keys/i));
  const keyText = await page.locator(".sub-content").innerText();
  check(keyText.includes(keysBefore.primaryKey) && keyText.includes(keysBefore.secondaryKey), "Access keys tab shows both keys", keyText.slice(0, 200));
  await page.locator(".sub-content button").filter({ hasText: /Regenerate/ }).first().click({ timeout: 5000 });
  await sleep(1500);
  const keysAfter = (await armCall(`Redis/${name}/listKeys`, "POST", {})).body;
  check(keysAfter.primaryKey !== keysBefore.primaryKey && keysAfter.secondaryKey === keysBefore.secondaryKey, "Regenerate in the blade rotates the primary key (visible over ARM)");

  await open(tabIndex(/Firewall/i));
  answers.push("ui_office", "10.1.0.1", "10.1.0.50");
  await page.locator(".sub-content button").filter({ hasText: /Add rule/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const fwText = await page.locator(".sub-content").innerText();
  check(/ui_office/.test(fwText) && /10\.1\.0\.1/.test(fwText) && /10\.1\.0\.50/.test(fwText), "firewall rule added in the blade is listed", fwText.slice(0, 240));
  const frj = await armCall(`Redis/${name}/firewallRules/ui_office`);
  check(frj.status === 200 && frj.body.properties?.endIP === "10.1.0.50", "…and readable over ARM", JSON.stringify(frj).slice(0, 160));
  await armCall(`Redis/${name}/firewallRules/ui_office`, "DELETE");

  await open(tabIndex(/Advanced settings/i));
  await page.locator(".sub-content select").first().selectOption("allkeys-lru");
  await page.locator(".sub-content button").filter({ hasText: /save\s*$/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const got = await armCall(`Redis/${name}`);
  check(got.body.properties?.redisConfiguration?.["maxmemory-policy"] === "allkeys-lru", "saving Advanced settings updates the eviction policy over ARM", JSON.stringify(got.body.properties?.redisConfiguration));

  await open(tabIndex(/Overview/i));
  await page.locator("#blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the cache from the list", name);
  const st = await armCall(`Redis/${name}`);
  check(st.status === 404, "deleted cache is gone from the ARM API", `HTTP ${st.status}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
