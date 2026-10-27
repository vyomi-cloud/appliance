/* Nano console conformance for Azure Container Registry — same flows as the offline test
 * (tests/conformance/ui/azure-containerregistry.mjs), driven against the in-browser Nano bundle:
 * open the service, create with the form defaults, every grid column filled, every detail
 * tab renders, a webhook created through ARM is listed, cost-savings metrics move, delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-containerregistry.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const SERVICE = /Container Registry/i;
const BLANK = /^\s*(|-|—|–|n\/a|undefined|null)\s*$/i;
const AV = "api-version=2023-07-01";
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
  if (r.request().method() === "PUT" && /Microsoft\.ContainerRegistry\/registries\/[^/?]+\?/.test(r.url())) createStatus = r.status();
  if ((r.status() >= 500 || r.status() === 404) && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(base, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const answers = [];
page.on("dialog", (d) => (d.type() === "prompt" ? d.accept(answers.shift() ?? "") : d.accept()).catch(() => {}));
const savings = () => page.evaluate(async () => {
  const d = await (await fetch("/api/spaces", { cache: "no-store" })).json();
  const sp = (d.spaces || []).find((s) => s.provider === "azure" && s.cost_savings) || (d.spaces || []).find((s) => s.provider === "azure") || {};
  const cs = sp.cost_savings || {};
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.containerregistry"] || 0 };
});

try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  bad.length = 0;   // boot-time requests that raced the service worker aren't part of the flow under test
  const before = await savings();
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Container Registry is on the Nano Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/docker|registry/i.test(await page.locator("#main").innerText()), "service page explains what the service does");

  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(name.length >= 5, "create form has a realistic default name", `name="${name}"`);
  const fields = await page.locator("#blade input").evaluateAll((els) => els.map((e) => e.value));
  check(fields.includes("Basic"), "create form defaults the pricing plan to Basic", JSON.stringify(fields));
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 40 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new registry appears in the list", name);

  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

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
  check(/Login server/.test(content["Access keys"] || "") && /azurecr\.io/.test(content["Access keys"] || ""), "Access keys shows the login server", (content["Access keys"] || "").slice(0, 200));

  const repoTxt = await open(tabIndex(/^Repositories$/i));
  check(/No repositories|Repository/i.test(repoTxt) && /control plane/i.test(repoTxt), "Repositories tab says Nano keeps the control plane only", repoTxt.slice(0, 200));
  const rg = await page.evaluate(() => RG);
  const SUBID = await page.evaluate(() => SUB);
  const wh = await page.evaluate(async ([sub, rg, n, av]) => {
    const r = await fetch(`/subscriptions/${sub}/resourceGroups/${rg}/providers/Microsoft.ContainerRegistry/registries/${n}/webhooks/uihook?${av}`,
      { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ location: "eastus", properties: { serviceUri: "https://example.com/h", actions: ["push"] } }) });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  }, [SUBID, rg, name, AV]);
  check(wh.status < 300 && wh.body.properties && wh.body.properties.serviceUri === "https://example.com/h", "a webhook can be created on the registry", JSON.stringify(wh).slice(0, 200));
  await open(tabIndex(/Overview/i));
  check(/uihook/.test(await open(tabIndex(/^Webhooks$/i))), "…and is listed in the Webhooks tab");

  await open(tabIndex(/Overview/i));
  await page.locator("#blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the registry from the list", name);
  const st = await page.evaluate(async ([sub, rg, n, av]) =>
    (await fetch(`/subscriptions/${sub}/resourceGroups/${rg}/providers/Microsoft.ContainerRegistry/registries/${n}?${av}`)).status, [SUBID, rg, name, AV]);
  check(st === 404, "deleted registry is gone from the ARM API", `HTTP ${st}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
