/* Nano console conformance for Azure Application Insights — same flows as the offline test
 * (tests/conformance/ui/azure-applicationinsights.mjs), driven against the in-browser Nano bundle:
 * open the service, create with the form defaults, every grid column filled, every detail
 * tab renders, cost-savings metrics move, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-applicationinsights.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Application Insights/i;
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
const SUB = "nano-sub";
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
  if (r.request().method() === "PUT" && /Microsoft\.Insights\/components\//.test(r.url())) createStatus = r.status();
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "azure" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "azure") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.applicationinsights"] || 0 };
});

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Application Insights is on the Nano Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/control plane/i.test(await page.locator("#main").innerText()), "service page says it is a control plane (telemetry ingestion is not simulated)");

  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 40 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new component appears in the list", name);

  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 6 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

  await rowFor().locator("a").first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = (await page.locator(".sub-nav-item .lbl").allInnerTexts()).map((t) => t.trim());
  check(tabs.length >= 12, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  const content = {};
  for (let i = 0; i < tabs.length; i++) {
    await page.locator(".sub-nav-item").nth(i).click({ timeout: 3000 });
    await sleep(700);
    const txt = ((await page.locator(".sub-content").innerText()) || "").trim();
    content[tabs[i]] = txt;
    const ok = txt.length > 25 && !/Renderer error|Failed to load|coming soon|undefined|\[object Object\]/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  check(/InstrumentationKey=[0-9a-f-]{36};IngestionEndpoint=https:\/\//.test(content["Connection and keys"] || ""), "Connection tab shows the connection string", (content["Connection and keys"] || "").slice(0, 200));
  check(/Basic/.test(content["Usage and estimated costs"] || "") && /90/.test(content["Usage and estimated costs"] || ""), "Usage tab shows pricing plan and retention", (content["Usage and estimated costs"] || "").slice(0, 200));
  check(/Enabled/.test(content["Network Isolation"] || ""), "Network Isolation tab shows public access", (content["Network Isolation"] || "").slice(0, 200));

  await page.locator(".sub-nav-item").first().click({ timeout: 3000 });
  await sleep(500);
  await page.locator("#blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the component from the list", name);
  const st = await page.evaluate(async ([sub, n]) =>
    (await fetch(`/subscriptions/${sub}/resourceGroups/cloudlearn-rg/providers/Microsoft.Insights/components/${n}?api-version=2020-02-02`)).status, [SUB, name]);
  check(st === 404, "deleted component is gone from the ARM API", `HTTP ${st}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
