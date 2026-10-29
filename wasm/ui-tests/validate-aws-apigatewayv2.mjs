/* Nano console conformance for API Gateway V2 — same flows as the offline test
 * (tests/conformance/ui/aws-apigatewayv2.mjs), driven against the in-browser Nano
 * bundle: open the service, create with the form defaults, every grid column filled,
 * cost-savings metrics move, every detail tab renders, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-apigatewayv2.mjs
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /API Gateway V2/i;
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
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
let createStatus = null, newId = "";
page.on("response", async (r) => {
  if (r.request().method() === "POST" && /\/api\/apigatewayv2\/apis$/.test(r.url())) {
    createStatus = r.status();
    try { newId = (await r.json()).api_id || ""; } catch (_) {}
  }
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "aws" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "aws") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0 };
});

try {
  await bootConsole(page, base, "/aws-console.html");
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "API Gateway V2 is on the Nano AWS console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  const rows = () => page.locator("#main table tr:has(td)").count();
  const rows0 = await rows();

  await page.locator("#main button").filter({ hasText: /create|launch/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  await page.locator("#main button").filter({ hasText: /^\s*create/i }).filter({ hasNotText: /cancel/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  await sleep(1500);
  let after = await rows();
  for (let i = 0; i < 10 && after <= rows0; i++) { await sleep(800); after = await rows(); }
  check(after > rows0, "new API appears in the list", `rows ${rows0} → ${after}`);

  const heads = await page.locator("#main table th").allInnerTexts();
  const myRow = page.locator("#main table tr:has(td)").filter({ hasText: newId || "zzz-none" }).first();
  const cells = await myRow.locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const apiId = newId || (data.find(([h]) => /API ID/i.test(h)) || [])[1] || "";
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

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
  const routesTab = tabs.findIndex((t) => /routes/i.test(t));
  if (routesTab >= 0) {
    await page.locator(".top-tabs button").nth(routesTab).click();
    await sleep(900);
    check(/\$default/.test(await page.locator("#main").innerText()), "Routes tab lists the quick-create $default route");
  }

  await page.locator("#main button").filter({ hasText: /delete/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  let gone = await rows();
  for (let i = 0; i < 10 && gone > rows0; i++) { await sleep(800); gone = await rows(); }
  check(gone <= rows0, "delete removes the API from the list", `rows ${gone}, started with ${rows0}`);
  const list = await page.evaluate(async () => (await (await fetch("/api/apigatewayv2/apis")).json()));
  check(apiId && !(list.apis || []).some((a) => a.api_id === apiId), "deleted API is gone from the backend", apiId);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
