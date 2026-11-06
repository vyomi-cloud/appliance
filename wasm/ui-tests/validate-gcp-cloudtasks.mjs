/* Nano console conformance for Cloud Tasks — same flows as the offline test
 * (tests/conformance/ui/gcp-cloudtasks.mjs), driven against the in-browser Nano bundle: open the
 * service, create with the form defaults, every grid column filled, cost-savings metrics move,
 * every detail tab renders, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-gcp-cloudtasks.mjs
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Cloud Tasks/i;
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
let createStatus = null;
page.on("response", async (r) => {
  if (r.request().method() === "POST" && /\/api\/(gcp\/)?cloudtasks\/queues$/.test(r.url())) createStatus = r.status();
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
  check((await rail.count()) > 0, "Cloud Tasks is on the Nano GCP console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  const rows = () => page.locator("#main table tr:has(td)").count();
  const rows0 = await rows();

  await page.locator("#main button").filter({ hasText: /create|launch/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  const name = (await page.locator("#main input[type=text]").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  await page.locator("#main button.primary").filter({ hasText: /^\s*check\s*create|^\s*create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  await sleep(1500);
  const hasRow = async () => (await page.locator("#main table tr:has(td)").filter({ hasText: name || "zzz-none" }).count()) > 0;
  for (let i = 0; i < 10 && !(await hasRow()); i++) await sleep(800);
  check(await hasRow(), "new queue appears in the list", `rows ${rows0} → ${await rows()}, name ${name}`);

  const heads = await page.locator("#main table th").allInnerTexts();
  const myRow = page.locator("#main table tr:has(td)").filter({ hasText: name || "zzz-none" }).first();
  const cells = await myRow.locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);   // skip the checkbox column
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 6 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  let s1 = await savings();
  for (let i = 0; i < 20 && !(s1.count > before.count && s1.usd > before.usd); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.count > before.count && s1.usd > before.usd, "cost-savings metrics updated by the create",
        `count ${before.count}→${s1.count}, $${before.usd}→$${s1.usd}`);

  const mk = await page.evaluate(async (n) => { const r = await fetch(`/api/gcp/cloudtasks/queues/${encodeURIComponent(n)}/tasks`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: "https://example.com/handler" }) });
    return { ok: r.ok, status: r.status }; }, name);
  check(mk.ok, "a task can be added to the queue", `HTTP ${mk.status}`);
  await myRow.locator("a.id").first().click({ timeout: 5000 });
  await sleep(1500);
  const navItems = page.locator(".sub-nav a.nav-item");
  const tabs = await navItems.allInnerTexts();
  check(tabs.length >= 4, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  for (let i = 0; i < tabs.length; i++) {
    await navItems.nth(i).click({ timeout: 3000 });
    await sleep(900);
    const txt = ((await page.locator(".sub-content").innerText()) || "").trim();
    const ok = txt.length > 20 && !/Renderer error|Failed to load|Not yet wired|coming soon|undefined|Wiring lands/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i].replace(/^\S+\s/, "").trim()}" renders`, txt.slice(-160).replace(/\n/g, " ⏎ "));
  }
  const tasksTab = tabs.findIndex((t) => /tasks/i.test(t));
  if (tasksTab >= 0) {
    await navItems.nth(tasksTab).click();
    await sleep(900);
    const t = await page.locator(".sub-content").innerText();
    check(/example\.com\/handler/.test(t) && /POST/.test(t) && !/\bundefined\b/.test(t), "Tasks tab lists the task with method and URL");
  }

  await page.locator("#main button.danger").first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await hasRow()); i++) await sleep(800);
  check(!(await hasRow()), "delete removes the queue from the list", `name ${name}`);
  const list = await page.evaluate(async () => (await (await fetch("/api/gcp/cloudtasks/queues")).json()));
  check(name && !(list.items || []).some((a) => a.name === name), "deleted queue is gone from the backend", name);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
