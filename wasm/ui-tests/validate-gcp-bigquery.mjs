/* Nano console conformance for BigQuery — same flows as the offline test
 * (tests/conformance/ui/gcp-bigquery.mjs), driven against the in-browser Nano bundle:
 * open the service, create a dataset with the form defaults, every grid column filled,
 * cost-savings metrics move, every detail tab renders, sample table + query actions fill the
 * child tabs, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-gcp-bigquery.mjs
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /BigQuery/i;
const DEFAULT_NAME = "my_dataset";
const API = "/api/gcp/bigquery/datasets";
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
const posts = [];
page.on("response", async (r) => {
  if (r.request().method() !== "GET" && r.url().includes("/api/")) posts.push(`${r.request().method()} ${r.status()} ${r.url().replace(base, "")}`);
  if (r.request().method() === "POST" && r.url().endsWith(API)) {
    createStatus = r.status();
    try { newId = (await r.json()).name || ""; } catch (_) {}
  }
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "gcp" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "gcp") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0 };
});

try {
  await bootConsole(page, base, "/gcp-console.html");
  // The service worker holds /api/* until Pyodide has loaded the cores: wait for the first real answer.
  const ready = await page.evaluate(async (a) => {
    for (let i = 0; i < 120; i++) {
      try { const r = await fetch(a, { cache: "no-store" }); const j = await r.json(); if (j && j.ok) return true; } catch (_) {}
      await new Promise((r) => setTimeout(r, 2000));
    }
    return false;
  }, API);
  check(ready, "Nano backend answers the BigQuery console API");
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  await page.evaluate((p) => fetch(p, { method: "DELETE" }).catch(() => {}), `${API}/${DEFAULT_NAME}`);
  bad.length = 0;
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "BigQuery is on the Nano GCP console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);

  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input").first().inputValue()) || "";
  check(name === DEFAULT_NAME, "create form has a realistic default dataset ID", `name="${name}"`);
  await page.locator("#main button").filter({ hasText: /create/i }).filter({ hasNotText: /cancel/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 60 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus} · ${posts.join("; ")} · ${(await page.locator("#main").innerText()).replace(/\n/g, " | ").slice(0, 200)}`);
  await sleep(1500);
  const rowLoc = () => page.locator("#main table tr:has(td)").filter({ hasText: newId || DEFAULT_NAME });
  for (let i = 0; i < 10 && !(await rowLoc().count()); i++) await sleep(800);
  check((await rowLoc().count()) > 0, "new dataset appears in the list", `id ${newId}`);

  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowLoc().first().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 6 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

  await rowLoc().first().locator("td").nth(1).click({ timeout: 5000 });
  await sleep(1800);
  const nav = page.locator(".sub-nav a.nav-item");
  const tabs = (await nav.allInnerTexts()).map((t) => t.replace(/^[a-z_]+\n/, "").trim());
  check(tabs.length >= 5, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  for (let i = 0; i < tabs.length; i++) {
    await nav.nth(i).click({ timeout: 3000 });
    await sleep(900);
    const txt = ((await page.locator("#main").innerText()) || "").trim();
    const tabText = txt.split("\n").slice(-8).join("\n");
    const ok = txt.length > 40 && !/Renderer error|Failed to load|Not yet wired|coming soon|undefined/i.test(txt) && !seen.has(tabText);
    seen.add(tabText);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(-160).replace(/\n/g, " ⏎ "));
  }

  const tab = async (label) => {
    const i = tabs.findIndex((t) => t === label);
    await nav.nth(i).click({ timeout: 3000 });
    await sleep(900);
  };
  const filled = async () => {
    const hs = (await page.locator("#main table th").allInnerTexts()).map((h) => h.trim());
    const cs = (await page.locator("#main table tr:has(td)").first().locator("td").allInnerTexts()).map((c) => c.trim());
    return { hs, cs, blank: hs.filter((_, i) => BLANK.test(cs[i] || "")) };
  };
  await tab("Tables");
  await page.locator("#main button").filter({ hasText: /create sample table/i }).first().click({ timeout: 5000 });
  await sleep(1800);
  let f = await filled();
  check(f.cs.includes("sample_table") && !f.blank.length, "Tables tab lists the sample table with every column filled", JSON.stringify(f));
  await tab("Jobs");
  await page.locator("#main button").filter({ hasText: /run sample query/i }).first().click({ timeout: 5000 });
  await sleep(1800);
  f = await filled();
  check(f.cs.some((c) => /^DONE/.test(c)) && !f.blank.length, "Jobs tab lists the query job (DONE) with every column filled", JSON.stringify(f));

  await page.locator("#main button").filter({ hasText: /delete/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowLoc().count()); i++) await sleep(800);
  check(!(await rowLoc().count()), "delete removes the dataset from the list", `id ${newId}`);
  const list = await page.evaluate(async (a) => (await (await fetch(a)).json()), API);
  check(newId && !(list.items || []).some((a) => a.name === newId), "deleted dataset is gone from the backend", newId);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
