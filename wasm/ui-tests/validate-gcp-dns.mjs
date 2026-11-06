/* Nano console conformance for Cloud DNS — same flows as the offline test
 * (tests/conformance/ui/gcp-dns.mjs), driven against the in-browser Nano bundle.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-gcp-dns.mjs
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Cloud DNS/i;
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
  if (r.request().method() === "POST" && /\/api\/gcp\/dns\/zones$/.test(r.url())) {
    createStatus = r.status();
    try { newId = (await r.json()).id || ""; } catch (_) {}
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
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Cloud DNS is on the Nano GCP console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  const rows = () => page.locator("#main table tr:has(td)").count();
  const rows0 = await rows();

  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input[type=text]").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  await page.locator("#main .summary-card button, #main button.primary").filter({ hasText: /create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  await sleep(1500);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: newId || "zzz-none" }).first();
  for (let i = 0; i < 10 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new zone appears in the list", `rows ${rows0} → ${await rows()}, id ${newId}`);

  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 8 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

  // detail tabs
  await rowFor().locator("a.id, a").first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = (await page.locator(".sub-nav a.nav-item").allInnerTexts()).map((t) => t.trim().split("\n").pop().trim());   // drop the icon ligature line
  check(tabs.length >= 7, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  for (let i = 0; i < tabs.length; i++) {
    await page.locator(".sub-nav a.nav-item").nth(i).click({ timeout: 3000 });
    await sleep(700);
    const txt = ((await page.locator(".sub-content").innerText()) || "").trim();
    const ok = txt.length > 30 && !/Renderer error|Failed to load|Wiring lands|coming soon|undefined|null/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i].trim()}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  const tabText = async (label) => {
    const i = tabs.findIndex((t) => t.toLowerCase() === label.toLowerCase());
    await page.locator(".sub-nav a.nav-item").nth(i).click({ timeout: 3000 });
    await sleep(600);
    return (await page.locator(".sub-content").innerText()) || "";
  };
  const records = await tabText("Record sets");
  check(/\bNS\b/.test(records) && /\bSOA\b/.test(records) && /ns-cloud-/.test(records) && /cloud-dns-hostmaster/.test(records),
        "Record sets tab lists the default NS + SOA records", records.slice(0, 160).replace(/\n/g, " ⏎ "));
  check(/example\.com\./.test(await tabText("Zone details")), "Zone details tab shows the DNS name");
  check(/ns-cloud-[a-d]\d\.googledomains\.com\./.test(await tabText("Name servers")), "Name servers tab lists the zone's name servers");
  check(/Off/.test(await tabText("DNSSEC")), "DNSSEC tab shows the state");

  // delete via the detail Delete action
  await page.locator("#main .detail-actions button").filter({ hasText: /delete/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the zone from the list", `id ${newId}`);
  const list = await page.evaluate(async () => (await (await fetch("/api/gcp/dns/zones")).json()));
  check(newId && !(list.items || []).some((a) => a.id === newId), "deleted zone is gone from the backend", newId);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
