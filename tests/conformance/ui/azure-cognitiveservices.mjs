/* Offline console conformance for Azure AI services (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create an account with the form defaults, every grid column filled, every detail
 * tab renders (keys and endpoint, model deployments, quotas…), a deployment created in the blade is
 * readable over ARM, cost-savings metrics move, delete (soft-delete, then purge).
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-cognitiveservices.mjs
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
const SERVICE = /Azure AI services/i;
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
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.cognitiveservices"] || 0 };
};

const sub = "00000000-0000-0000-0000-cloudlearn01";
const NAME = "ai-cloudlearn";
const RGN = "cloudlearn-rg";
const arm = `${BASE}/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.CognitiveServices`;
const deletedUrl = `${BASE}/subscriptions/${sub}/providers/Microsoft.CognitiveServices/locations/eastus/resourceGroups/${RGN}/deletedAccounts`;
const AV = "api-version=2024-10-01";
const cleanup = async (n) => {   // delete + purge the soft-deleted account so the default name is reusable
  await fetch(`${arm}/accounts/${n}?${AV}`, { method: "DELETE" }).catch(() => {});
  await fetch(`${deletedUrl}/${n}?${AV}`, { method: "DELETE" }).catch(() => {});
};

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.CognitiveServices\/accounts\/[^/?]+\?/.test(r.url())) createStatus = r.status();
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
  check((await rail.count()) > 0, "Azure AI services is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/OpenAI|AI Services/i.test(await page.locator("#main").innerText()), "service page explains what the service does");
  const s0 = await savings();

  // create with the form defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(name.length >= 5, "create form has a realistic default name", `name="${name}"`);
  const fields = await page.locator("#blade input").evaluateAll((els) => els.map((e) => e.value));
  check(fields.includes("OpenAI") && fields.includes("S0"), "create form defaults kind OpenAI and tier S0", JSON.stringify(fields));
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new account appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 6 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);

  // cost savings include the new account
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc > 0 && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc > 0 && s1.count >= 1 && s1.usd > s0.usd, "cost-savings metrics include the new account (azure.cognitiveservices priced)",
        `count ${s0.count}→${s1.count}, $${s0.usd}→$${s1.usd}, account $${s1.svc}`);

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
  const keysTab = content["Keys and Endpoint"] || "";
  check(/KEY 1/.test(keysTab) && /KEY 2/.test(keysTab) && /openai\.azure\.com/.test(keysTab), "Keys and Endpoint lists both keys and the endpoint", keysTab.slice(0, 200));

  // model deployments: create one in the blade, read it back over ARM
  const dp = tabIndex(/Model deployments/i);
  await open(dp);
  answers.push("ui-chat", "gpt-4o", "2024-08-06", "10");
  await page.locator(".sub-content button").filter({ hasText: /Create deployment/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const deps = await page.locator(".sub-content").innerText();
  check(/ui-chat/.test(deps) && /gpt-4o/.test(deps) && /Standard/.test(deps), "deployment created in the blade is listed", deps.slice(0, 200));
  const dr = await fetch(`${arm}/accounts/${name}/deployments/ui-chat?${AV}`);
  const dj = await dr.json().catch(() => ({}));
  check(dr.status === 200 && dj.properties?.model?.name === "gpt-4o" && dj.sku?.capacity === 10, "…and readable over ARM", JSON.stringify(dj).slice(0, 160));
  await fetch(`${arm}/accounts/${name}/deployments/api-embed?${AV}`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sku: { name: "Standard", capacity: 5 }, properties: { model: { format: "OpenAI", name: "text-embedding-3-small", version: "1" } } }) });
  await open(tabIndex(/Overview/i));
  await open(dp);
  check(/api-embed/.test(await page.locator(".sub-content").innerText()), "a deployment created through the API shows in the blade");
  const qt = await open(tabIndex(/Quotas/i));
  check(/gpt-4o/.test(qt) && /Tokens Per Minute/.test(qt), "Quotas shows model quota usage", qt.slice(0, 160));

  // delete from the detail pane
  await open(tabIndex(/Overview/i));
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the account from the list", name);
  const r = await fetch(`${arm}/accounts/${name}?${AV}`);
  check(r.status === 404, "deleted account is gone from the ARM API", `HTTP ${r.status}`);
  const gone = await fetch(`${deletedUrl}/${name}?${AV}`);
  check(gone.status === 200, "…and is listed as soft-deleted (restorable)", `HTTP ${gone.status}`);
  await cleanup(name);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
  await cleanup(NAME);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
