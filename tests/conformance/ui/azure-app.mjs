/* Offline console conformance for Azure Container Apps (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create an app with the form defaults, every grid column filled, every detail
 * tab renders (revisions, containers, ingress, scale, secrets…), cost-savings metrics move, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-app.mjs
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
const SERVICE = /Container Apps/i;
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
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.app"] || 0 };
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
const NAME = "ca-cloudlearn";
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.App\/containerApps\//.test(r.url())) createStatus = r.status();
  if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
});
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
page.on("dialog", (d) => d.accept().catch(() => {}));

try {
  const sub = "00000000-0000-0000-0000-cloudlearn01";
  await fetch(`${BASE}/subscriptions/${sub}/resourceGroups/cloudlearn-rg/providers/Microsoft.App/containerApps/${NAME}?api-version=2024-03-01`, { method: "DELETE" }).catch(() => {});   // leftover from an aborted run
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: SERVICE }).first();
  check((await rail.count()) > 0, "Container Apps is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/control plane|Docker/i.test(await page.locator("#main").innerText()), "service page says what runs below the Pro tier (control plane / Docker)");
  const s0 = await savings();

  // create with the form defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(name.length > 0, "create form has a realistic default name", `name="${name}"`);
  const image = await page.locator("#blade input").nth(1).inputValue();
  check(/\//.test(image), "create form defaults a container image", image);
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new container app appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  // cost savings include the new app
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > s0.usd, "cost-savings metrics include the new app (azure.app priced)",
        `count ${s0.count}→${s1.count}, $${s0.usd}→$${s1.usd}, app $${s1.svc}`);

  // detail tabs
  await rowFor().locator("a").first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = (await page.locator(".sub-nav-item .lbl").allInnerTexts()).map((t) => t.trim());
  check(tabs.length >= 9, "detail view shows its tabs", tabs.join(" | "));
  const seen = new Set();
  const content = {};
  for (let i = 0; i < tabs.length; i++) {
    await page.locator(".sub-nav-item").nth(i).click({ timeout: 3000 });
    await sleep(700);
    const txt = ((await page.locator(".sub-content").innerText()) || "").trim();
    content[tabs[i]] = txt;
    const ok = txt.length > 25 && !/Renderer error|Failed to load|coming soon|undefined|null|\[object Object\]/i.test(txt) && !seen.has(txt);
    seen.add(txt);
    check(ok, `tab "${tabs[i]}" renders`, txt.slice(0, 160).replace(/\n/g, " ⏎ "));
  }
  check(/--[0-9a-f]{7}/.test(content["Revisions and replicas"] || "") && /Yes/.test(content["Revisions and replicas"] || ""), "Revisions tab lists the active revision", (content["Revisions and replicas"] || "").slice(0, 200));
  check(/quickstart/.test(content["Containers"] || ""), "Containers tab shows the image", (content["Containers"] || "").slice(0, 200));
  check(/https:\/\/ca-cloudlearn\.\S+azurecontainerapps\.io/.test(content["Ingress"] || ""), "Ingress tab shows the application URL", (content["Ingress"] || "").slice(0, 200));

  // delete from the detail pane
  await page.locator(".sub-nav-item").filter({ hasText: /^\s*\S*\s*Overview/ }).first().click({ timeout: 3000 }).catch(() => {});
  await sleep(500);
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the app from the list", name);
  const r = await fetch(`${BASE}/subscriptions/${sub}/resourceGroups/cloudlearn-rg/providers/Microsoft.App/containerApps/${name}?api-version=2024-03-01`);
  check(r.status === 404, "deleted app is gone from the ARM API", `HTTP ${r.status}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
