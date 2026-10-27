/* Nano console conformance for Azure Event Hubs — same flows as the offline test
 * (tests/conformance/ui/azure-eventhub.mjs), driven against the in-browser Nano bundle:
 * open the service, create with the form defaults, every grid column filled, every detail
 * tab renders, an event hub + consumer group created in the blade are stored, an event sent in the Data
 * Explorer is read back, cost-savings metrics move, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-eventhub.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Event Hubs/i;
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
const AV = "api-version=2024-01-01";
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
  if (r.request().method() === "PUT" && /Microsoft\.EventHub\/namespaces\/[^/?]+\?/.test(r.url())) createStatus = r.status();
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const answers = [];
page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()).catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "azure" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "azure") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.eventhub"] || 0 };
});

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Event Hubs is on the Nano Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/event hubs|partition|consumer group/i.test(await page.locator("#main").innerText()), "service page explains what the service does");

  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(name.length >= 6, "create form has a realistic default name", `name="${name}"`);
  const fields = await page.locator("#blade input, #blade select").evaluateAll((els) => els.map((e) => e.value));
  check(fields.includes("Standard") && fields.includes("1"), "create form defaults tier Standard and 1 throughput unit", JSON.stringify(fields));
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 40 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new namespace appears in the list", name);

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
  const sas = content["Shared access policies"] || "";
  check(/RootManageSharedAccessKey/.test(sas) && /Listen, Send, Manage|Listen, Manage, Send/.test(sas) && /Endpoint=sb:\/\//.test(sas), "Shared access policies shows the root policy with a connection string", sas.slice(0, 200));

  const eh = tabIndex(/^Event Hubs$/i);
  await open(eh);
  answers.push("ui-orders", "4", "1");
  await page.locator(".sub-content button").filter({ hasText: /Event Hub/ }).first().click({ timeout: 5000 });
  await sleep(1500);
  const hubs = await page.locator(".sub-content").innerText();
  check(/ui-orders/.test(hubs) && /Active/.test(hubs), "event hub created in the blade is listed", hubs.slice(0, 200));
  const rg = await page.evaluate(() => RG);
  const SUBID = await page.evaluate(() => SUB);
  const arm = (p) => page.evaluate(async ([u]) => {
    const r = await fetch(u);
    return { status: r.status, body: await r.json().catch(() => ({})) };
  }, [`/subscriptions/${SUBID}/resourceGroups/${rg}/providers/Microsoft.EventHub/namespaces/${name}${p ? "/" + p : ""}?${AV}`]);
  const hj = await arm("eventhubs/ui-orders");
  check(hj.status === 200 && hj.body.properties?.partitionCount === 4 && hj.body.properties?.messageRetentionInDays === 1, "…and readable over ARM", JSON.stringify(hj).slice(0, 160));
  await page.locator(".sub-content a").filter({ hasText: "ui-orders" }).first().click({ timeout: 5000 });
  await sleep(1200);
  const drill = await page.locator(".sub-content").innerText();
  check(/\$Default/.test(drill) && /Partitions/.test(drill) && /Consumer groups/i.test(drill), "event hub drill-down shows $Default consumer group and partitions", drill.slice(0, 200));
  answers.push("ui-analytics");
  await page.locator(".sub-content button").filter({ hasText: /Consumer group/ }).first().click({ timeout: 5000 });
  await sleep(1200);
  check(/ui-analytics/.test(await page.locator(".sub-content").innerText()), "consumer group created in the blade is listed");
  const cr = await arm("eventhubs/ui-orders/consumergroups/ui-analytics");
  check(cr.status === 200, "…and readable over ARM", `HTTP ${cr.status}`);

  await open(tabIndex(/Data Explorer/i));
  await page.locator("#eh-hub").selectOption("ui-orders");
  await page.locator("#eh-body").fill('{"orderId": 4242}');
  await page.locator(".sub-content button").filter({ hasText: /Send event/ }).first().click({ timeout: 5000 });
  await sleep(1500);
  const ex = await page.locator(".sub-content").innerText();
  check(/4242/.test(ex) && /Sequence/.test(ex), "event sent in the Data Explorer is listed with partition + sequence", ex.slice(0, 200));

  await open(tabIndex(/Overview/i));
  await page.locator("#blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the namespace from the list", name);
  const st = await arm("").then((r) => r.status);
  check(st === 404, "deleted namespace is gone from the ARM API", `HTTP ${st}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
