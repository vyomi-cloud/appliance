/* Offline console conformance for Azure DNS (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create a zone with the form defaults, every grid column filled, every detail tab
 * renders (recordsets, name servers, test query…), a record set added in the blade is readable over
 * ARM and answers a DNS query, cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-dns.mjs
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
const SERVICE = /DNS zones/i;
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
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.dns"] || 0 };
};

const sub = "00000000-0000-0000-0000-cloudlearn01";
const NAME = "cloudlearn.example.com";
const RGN = "cloudlearn-rg";
const arm = `${BASE}/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.Network`;
const AV = "api-version=2018-05-01";
const cleanup = async (n) => { await fetch(`${arm}/dnsZones/${n}?${AV}`, { method: "DELETE" }).catch(() => {}); };

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.Network\/dnsZones\/[^/?]+\?/.test(r.url())) createStatus = r.status();
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
  check((await rail.count()) > 0, "DNS zones is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/Azure DNS/i.test(await page.locator("#main").innerText()), "service page explains what the service does");
  const s0 = await savings();

  // create with the form defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(name), "create form has a realistic default zone name", `name="${name}"`);
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new zone appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);
  check(data.some(([, v]) => /azure-dns\.com/.test(v)) && data.some(([h, v]) => /Record sets/i.test(h) && v === "2"),
        "grid shows the name servers and the SOA+NS record-set count", JSON.stringify(data));

  // cost savings include the new zone
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > s0.usd, "cost-savings metrics include the new zone (azure.dns priced)",
        `count ${s0.count}→${s1.count}, $${s0.usd}→$${s1.usd}, zone $${s1.svc}`);

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
  const nsTab = content["Name servers"] || "";
  check(/ns1-\d+\.azure-dns\.com/.test(nsTab) && /ns4-\d+\.azure-dns\.info/.test(nsTab), "Name servers lists the four delegation servers", nsTab.slice(0, 200));
  const rsTab = content["Recordsets"] || "";
  check(/SOA/.test(rsTab) && /NS/.test(rsTab) && /ns1-\d+\.azure-dns\.com/.test(rsTab), "Recordsets lists the SOA and NS record sets", rsTab.slice(0, 200));

  // add a record set in the blade, read it back over ARM, resolve it
  const rs = tabIndex(/Recordsets/i);
  await open(rs);
  answers.push("web", "A", "300", "10.20.30.40");
  await page.locator(".sub-content button").filter({ hasText: /Add record set/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const sets = await page.locator(".sub-content").innerText();
  check(/web/.test(sets) && /10\.20\.30\.40/.test(sets) && /300/.test(sets), "record set added in the blade is listed", sets.slice(0, 240));
  const rr = await fetch(`${arm}/dnsZones/${name}/A/web?${AV}`);
  const rj = await rr.json().catch(() => ({}));
  check(rr.status === 200 && rj.properties?.ARecords?.[0]?.ipv4Address === "10.20.30.40" && rj.properties?.TTL === 300, "…and readable over ARM", JSON.stringify(rj).slice(0, 160));
  await fetch(`${arm}/dnsZones/${name}/TXT/@?${AV}`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ properties: { TTL: 120, TXTRecords: [{ value: ["hello-from-api"] }] } }) });
  await open(tabIndex(/Overview/i));
  await open(rs);
  check(/hello-from-api/.test(await page.locator(".sub-content").innerText()), "a record set created through the API shows in the blade");
  const q = await (await fetch(`${BASE}/azure-data/dns/query?name=web.${name}&type=A`)).json();
  check(q.Status === 0 && q.Answer?.[0]?.data === "10.20.30.40", "the record resolves over /azure-data/dns/query", JSON.stringify(q).slice(0, 160));
  await open(tabIndex(/Test query/i));
  await page.locator(".sub-content input").first().fill(`web.${name}`);
  await page.locator(".sub-content button").filter({ hasText: /query$/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const qt = await page.locator(".sub-content").innerText();
  check(/NOERROR/.test(qt) && /10\.20\.30\.40/.test(qt), "Test query answers from the zone", qt.slice(0, 200));

  // delete from the detail pane
  await open(tabIndex(/Overview/i));
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the zone from the list", name);
  const r = await fetch(`${arm}/dnsZones/${name}?${AV}`);
  check(r.status === 404, "deleted zone is gone from the ARM API", `HTTP ${r.status}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
  await cleanup(NAME);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
