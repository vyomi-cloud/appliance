/* Offline console conformance for Azure Managed Identities (driven against $VYOMI_BASE_URL/console/azure).
 * Open the service, create an identity with the form defaults, every grid column filled, every detail tab
 * renders (federated credentials, associated resources…), a federated credential added in the blade is
 * readable over ARM, resource count in the cost-savings metrics moves, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-msi.mjs
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
const SERVICE = /Managed Identities/i;
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
  return { count: cs.resource_count || 0, usd: cs.savings_usd || 0, svc: (cs.by_service || {})["azure.msi"] };
};

const sub = "00000000-0000-0000-0000-cloudlearn01";
const NAME = "cloudlearn-identity";
const RGN = "cloudlearn-rg";
const arm = `${BASE}/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.ManagedIdentity`;
const AV = "api-version=2023-01-31";
const cleanup = async (n) => { await fetch(`${arm}/userAssignedIdentities/${n}?${AV}`, { method: "DELETE" }).catch(() => {}); };

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const bad = [];
let createStatus = null;
page.on("response", (r) => {
  if (r.request().method() === "PUT" && /Microsoft\.ManagedIdentity\/userAssignedIdentities\/[^/?]+\?/.test(r.url())) createStatus = r.status();
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
  check((await rail.count()) > 0, "Managed Identities is on the Azure console rail");
  await rail.click({ timeout: 5000 });
  await sleep(1500);
  check(/managed identit/i.test(await page.locator("#main").innerText()), "service page explains what the service does");
  const s0 = await savings();

  // create with the form defaults
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1000);
  const name = (await page.locator("#blade input").first().inputValue()) || "";
  check(/^[a-z0-9][a-z0-9_-]{2,}$/i.test(name), "create form has a realistic default identity name", `name="${name}"`);
  await page.locator("#blade .blade-actions button").filter({ hasText: /^create$/i }).first().click({ timeout: 5000 });
  for (let i = 0; i < 30 && createStatus === null; i++) await sleep(500);
  check(createStatus !== null && createStatus < 300, "create with defaults returns 2xx", `HTTP ${createStatus}`);
  const rowFor = () => page.locator("#main table tr:has(td)").filter({ hasText: name }).first();
  for (let i = 0; i < 15 && !(await rowFor().count()); i++) await sleep(800);
  check(await rowFor().count() > 0, "new identity appears in the list", name);

  // every grid column filled
  const heads = await page.locator("#main table th").allInnerTexts();
  const cells = await rowFor().locator("td").allInnerTexts();
  const data = cells.map((c, i) => [(heads[i] || "").replace(/[▲▼]/g, "").trim(), c.trim()]).filter(([h]) => h);
  const blanks = data.filter(([, v]) => BLANK.test(v)).map(([h]) => h);
  check(data.length >= 5 && !blanks.length, "every grid column is filled", `blank: ${blanks.join(", ") || "-"} · ${JSON.stringify(data)}`);
  check(data.some(([h, v]) => /Client ID/i.test(h) && /^[0-9a-f-]{36}$/.test(v)) && data.some(([h, v]) => /Principal/i.test(h) && /^[0-9a-f-]{36}$/.test(v)),
        "grid shows the client ID and principal ID as GUIDs", JSON.stringify(data));

  // the new identity is counted in the cost-savings metrics (user-assigned identities list at $0, so the
  // resource count and the azure.msi line move, the dollar amount does not)
  let s1 = await savings();
  for (let i = 0; i < 12 && !(s1.svc !== undefined && s1.count > s0.count); i++) { await sleep(1000); s1 = await savings(); }
  check(s1.svc !== undefined && s1.count > s0.count, "cost-savings metrics count the new identity (azure.msi listed)",
        `count ${s0.count}→${s1.count}, azure.msi ${s1.svc}`);

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
  const fcTab = content["Federated credentials"] || "";
  check(/Add credential/i.test(fcTab) && /No federated credentials yet/i.test(fcTab), "Federated credentials starts empty with an Add button", fcTab.slice(0, 200));
  const asTab = content["Associated resources"] || "";
  check(/No resources are using this identity yet/i.test(asTab), "Associated resources explains that nothing uses the identity yet", asTab.slice(0, 200));

  // add a federated credential in the blade, read it back over ARM
  const fc = tabIndex(/Federated credentials/i);
  await open(fc);
  answers.push("github-main", "https://token.actions.githubusercontent.com", "repo:cloudlearn/demo:ref:refs/heads/main");
  await page.locator(".sub-content button").filter({ hasText: /Add credential/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  const creds = await page.locator(".sub-content").innerText();
  check(/github-main/.test(creds) && /token\.actions\.githubusercontent\.com/.test(creds) && /AzureADTokenExchange/.test(creds), "credential added in the blade is listed", creds.slice(0, 240));
  const rr = await fetch(`${arm}/userAssignedIdentities/${name}/federatedIdentityCredentials/github-main?${AV}`);
  const rj = await rr.json().catch(() => ({}));
  check(rr.status === 200 && rj.properties?.subject === "repo:cloudlearn/demo:ref:refs/heads/main", "…and readable over ARM", JSON.stringify(rj).slice(0, 160));
  await fetch(`${arm}/userAssignedIdentities/${name}/federatedIdentityCredentials/from-api?${AV}`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ properties: { issuer: "https://oidc.example.com/cluster", subject: "system:serviceaccount:default:app", audiences: ["api://AzureADTokenExchange"] } }) });
  await open(tabIndex(/Overview/i));
  await open(fc);
  check(/from-api/.test(await page.locator(".sub-content").innerText()), "a credential created through the API shows in the blade");
  // a resource that uses the identity appears under Associated resources
  const rid = `/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${name}`;
  const acct = `uiacct${Date.now() % 100000}`;
  const csUrl = `${BASE}/subscriptions/${sub}/resourceGroups/${RGN}/providers/Microsoft.CognitiveServices/accounts/${acct}?api-version=2024-10-01`;
  await fetch(csUrl, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location: "eastus", kind: "OpenAI", sku: { name: "S0" }, identity: { type: "UserAssigned", userAssignedIdentities: { [rid]: {} } }, properties: {} }) });
  await open(tabIndex(/Associated resources/i));
  await sleep(500);
  const at = await page.locator(".sub-content").innerText();
  check(new RegExp(acct).test(at) && /CognitiveServices\/accounts/i.test(at), "Associated resources lists a resource that uses the identity", at.slice(0, 200));
  await fetch(csUrl, { method: "DELETE" }).catch(() => {});

  // delete from the detail pane
  await open(tabIndex(/Overview/i));
  await page.locator("#blade .blade-actions button.del, #blade button").filter({ hasText: /^delete$/i }).first().click({ timeout: 5000 });
  await sleep(2000);
  for (let i = 0; i < 10 && (await rowFor().count()); i++) await sleep(800);
  check(!(await rowFor().count()), "delete removes the identity from the list", name);
  const r = await fetch(`${arm}/userAssignedIdentities/${name}?${AV}`);
  check(r.status === 404, "deleted identity is gone from the ARM API", `HTTP ${r.status}`);
  check(!bad.length, "no API errors / page errors during the flow", bad.slice(0, 5).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
  await cleanup(NAME);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
