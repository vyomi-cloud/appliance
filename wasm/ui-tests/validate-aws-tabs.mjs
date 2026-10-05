/* Goal: every AWS detail sub-screen renders content — no blank tabs.
 * Creates an S3 bucket (has the most stub tabs: Versions, Lifecycle rules,
 * Default encryption, Block Public Access, CORS), opens its detail view,
 * clicks EACH top-tab and asserts the tab-content area is non-empty (>25). */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = process.env.SVC || "s3";
const RES = process.env.RES || "tabtest-bucket";
// Per-service create recipe: {url, method, body} and the rail regex + name the
// opened row is matched by. Each resource exercises the generic stub fallback.
const RECIPES = {
  s3:       { url: "/api/s3/buckets/tabtest-bucket", method: "POST", body: { name: "tabtest-bucket" }, open: "tabtest-bucket", rail: "s3" },
  kms:      { url: "/api/aws/kms/keys", method: "POST", body: { description: "tab test key" }, open: "", rail: "kms" },
  dynamodb: { url: "/api/dynamodb/tables", method: "POST", body: { name: "tabtest", key_schema: [{ AttributeName: "id", KeyType: "HASH" }], attribute_definitions: [{ AttributeName: "id", AttributeType: "S" }], billing_mode: "PAY_PER_REQUEST" }, open: "tabtest", rail: "dynamo" },
  sqs:      { url: "/api/sqs/queues", method: "POST", body: { name: "tabtest-q" }, open: "tabtest-q", rail: "sqs" },
};
const R = RECIPES[SERVICE] || RECIPES.s3;

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const results = [];
try {
  await bootConsole(page, base, "/aws-console.html");

  // Create the resource directly via the console's create API (PUT /api/s3/buckets/{name}).
  const createRes = await page.evaluate(async (r) => {
    try {
      const resp = await fetch(r.url, { method: r.method, headers: { "content-type": "application/json" }, body: JSON.stringify(r.body) });
      const txt = await resp.text();
      let name = "";
      try { const j = JSON.parse(txt); name = j.key_id || j.name || j.function_name || j.queue_name || j.table_name || ""; } catch {}
      return { status: resp.status, body: txt.slice(0, 160), name };
    } catch (e) { return { status: 0, body: String(e), name: "" }; }
  }, R);
  // If the recipe didn't pin a row name, use the one returned by create.
  if (!R.open && createRes.name) R.open = createRes.name;
  results.push({ tab: "(create)", len: 999, blank: false, note: `${createRes.status} ${createRes.body}` });
  await sleep(600);

  // Open the service from the rail.
  await page.evaluate(([sel, svc]) => {
    const e = [...document.querySelectorAll(sel)].find((x) => new RegExp(svc, "i").test((x.innerText || "") + (x.getAttribute("data-service") || "") + (x.getAttribute("data-key") || "")));
    e && e.click();
  }, [RAIL_SEL, R.rail]);
  await sleep(1400);

  // Refresh the list then open the resource's detail view.
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main button")].find((x) => /refresh/i.test(x.innerText)); b && b.click(); });
  await sleep(1200);
  const opened = await page.evaluate((name) => {
    const anchors = [...document.querySelectorAll("#main a.id, #main td a, #main a")];
    const e = name ? anchors.find((x) => (x.innerText || "").trim().includes(name)) : anchors.find((x) => x.className.includes("id") || /^[\w-]/.test((x.innerText || "").trim()));
    if (e) { e.click(); return true; }
    return false;
  }, R.open);
  await sleep(1500);

  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button")].map((e) => (e.innerText || "").trim()).filter(Boolean));

  // The tab content is the div rendered right after .top-tabs in #main.
  const contentOf = () => page.evaluate(() => {
    const strip = document.querySelector("#main .top-tabs");
    let node = strip && strip.nextElementSibling;
    return (node ? node.innerText : "").trim();
  });

  for (let i = 0; i < tabs.length; i++) {
    await page.evaluate((i) => { const items = [...document.querySelectorAll("#main .top-tabs button")]; items[i] && items[i].click(); }, i);
    await sleep(450);
    const content = await contentOf();
    results.push({ tab: tabs[i], len: content.length, blank: content.length < 25 });
  }
  if (!opened) results.push({ tab: "(open resource)", len: 0, blank: true, note: "could not open detail" });
  if (!tabs.length) results.push({ tab: "(no tabs)", len: 0, blank: true, note: "no .top-tabs buttons found" });
} catch (e) { results.push({ tab: "(err)", blank: true, note: String(e).split("\n")[0] }); }
await browser.close(); server.close();

console.log(`===== AWS ${SERVICE} detail tabs — content check =====`);
for (const r of results) console.log(`  [${r.blank ? "BLANK" : "OK   "}] ${String(r.tab).padEnd(34)} contentLen:${r.len ?? "-"} ${r.note || ""}`);
const blanks = results.filter((r) => r.blank);
console.log(`\n${results.length - blanks.length}/${results.length} tabs render content` + (blanks.length ? ` — BLANK: ${blanks.map((b) => b.tab).join(", ")}` : " — NO blank tabs"));
process.exit(blanks.length ? 1 : 0);
