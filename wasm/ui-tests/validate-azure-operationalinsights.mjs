/* Nano console conformance for Azure Log Analytics — same flows as the offline test
 * (tests/conformance/ui/azure-operationalinsights.mjs), driven against the in-browser Nano bundle:
 * open the service, create with the form defaults, every grid column filled, every detail tab
 * renders, items added in the blade are stored, cost-savings metrics move, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-operationalinsights.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Log Analytics/i;
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
const AV = "api-version=2022-10-01";
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
  if (r.request().method() === "PUT" && /Microsoft\.OperationalInsights\/workspaces\/[^/?]+\?/.test(r.url())) createStatus = r.status();
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const answers = [];
page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()).catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "azure" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "azure") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.operationalinsights"] || 0 };
});

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Log Analytics is on the Nano Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/Log Analytics workspaces/i.test(await page.locator("#main").innerText()), "service page explains what the service does");

  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(/^[a-z0-9-]{4,}$/.test(name), "create form has a realistic default workspace name", `name="${name}"`);
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 40 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new workspace appears in the list", name);

  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);
  check(data.some(([, v]) => /PerGB2018/.test(v)) && data.some(([h, v]) => /Retention/i.test(h) && v === "30") && data.some(([, v]) => /Succeeded/.test(v)),
        "grid shows the pricing tier, retention and provisioning state", JSON.stringify(data));

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

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
    const ok = txt.length > 25 && !/Renderer error|Failed to load|coming soon|undefined|\[object Object\]/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  const tblTab = content["Tables"] || "";
  check(/Heartbeat/.test(tblTab) && /Syslog/.test(tblTab) && /Analytics/.test(tblTab), "Tables lists the built-in tables with their plan", tblTab.slice(0, 200));
  const keyTab = content["Agents (keys)"] || "";
  check(/Workspace ID/.test(keyTab) && /Primary key/.test(keyTab) && /[A-Za-z0-9+/=]{40,}/.test(keyTab), "Agents tab shows the workspace ID and shared keys", keyTab.slice(0, 200));
  const usageTab = content["Usage and quota"] || "";
  check(/Data Analyzed/.test(usageTab), "Usage tab lists the data-analysed quota", usageTab.slice(0, 200));

  const rg = await page.evaluate(() => RG);
  const SUBID = await page.evaluate(() => SUB);
  const armGet = (path) => page.evaluate(async ([sub, rg, n, av, p]) => {
    const r = await fetch(`/subscriptions/${sub}/resourceGroups/${rg}/providers/Microsoft.OperationalInsights/workspaces/${n}${p}?${av}`);
    return { status: r.status, body: await r.json().catch(() => ({})) };
  }, [SUBID, rg, name, AV, path]);
  await open(tabIndex(/Saved searches/i));
  answers.push("ui-search", "Heartbeat | take 5");
  await page.locator(".sub-content button").filter({ hasText: /Add saved search/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/ui-search/.test(await page.locator(".sub-content").innerText()), "saved search added in the blade is listed");
  const sj = await armGet("/savedSearches/ui-search");
  check(sj.status === 200 && sj.body.properties?.query === "Heartbeat | take 5", "…and readable over ARM", JSON.stringify(sj).slice(0, 160));

  await open(tabIndex(/^Tables/i));
  answers.push("Sales_CL");
  await page.locator(".sub-content button").filter({ hasText: /Add table/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/Sales_CL/.test(await page.locator(".sub-content").innerText()), "custom table added in the blade is listed");
  const tj = await armGet("/tables/Sales_CL");
  check(tj.status === 200, "…and readable over ARM", JSON.stringify(tj).slice(0, 160));

  await open(tabIndex(/Data sources/i));
  answers.push("UiWinApp");
  await page.locator(".sub-content button").filter({ hasText: /Add data source/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  check(/UiWinApp/.test(await page.locator(".sub-content").innerText()), "data source added in the blade is listed");

  await open(tabIndex(/Overview/i));
  await page.locator("#blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the workspace from the list", name);
  const st = (await armGet("")).status;
  check(st === 404, "deleted workspace is gone from the ARM API", `HTTP ${st}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
