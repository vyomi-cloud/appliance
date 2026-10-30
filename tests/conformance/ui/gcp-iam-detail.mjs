/* GCP IAM & Admin service-account detail (offline appliance): Members, Permissions and
 * Properties show the account's real data from the API (project policy bindings,
 * the account itself), and a binding added through the API shows up on reopen.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-iam-detail.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const j = async (m, p, b) => {
  const r = await fetch(BASE + p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
  return r.json().catch(() => ({}));
};

const browser = await chromium.launch();
const page = await browser.newPage();
try {
  const project = (await j("GET", "/api/gcp/catalog")).project;
  const acct = "iam-val-" + Date.now().toString(36);
  const email = `${acct}@${project}.iam.gserviceaccount.com`;
  await j("POST", `/api/gcp/iam/v1/projects/${project}/serviceAccounts`, { accountId: acct, serviceAccount: { displayName: acct } });
  const pol = await j("GET", `/api/gcp/iam/v1/projects/${project}:getIamPolicy`);
  const bindings = [...(pol.bindings || []), { role: "roles/viewer", members: [`serviceAccount:${email}`] }];
  await j("POST", `/api/gcp/iam/v1/projects/${project}:setIamPolicy`, { policy: { ...pol, bindings } });

  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  await page.locator(RAIL_SEL).filter({ hasText: "IAM & Admin" }).first().click({ timeout: 15000 });
  await sleep(1500);
  const opened = await page.evaluate((e) => { const a = [...document.querySelectorAll("#main a.id")].find((x) => x.innerText.trim() === e); if (a) { a.click(); return true; } return false; }, email);
  await sleep(1500);
  check(opened, "IAM: service account detail opens");
  const tab = async (label) => {
    await page.evaluate((l) => { const b = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => e.innerText.includes(l)); b && b.click(); }, label);
    await sleep(1000);
    return page.evaluate(() => ((document.querySelector("#main .sub-content") || {}).innerText || ""));
  };
  let t = await tab("Members");
  check(t.includes(email) && t.includes("roles/viewer"), "IAM: Members lists the role granted to this account", t.slice(0, 120));
  t = await tab("Permissions");
  check(t.includes("roles/viewer") && t.includes(email), "IAM: Permissions lists the project policy bindings", t.slice(0, 120));
  t = await tab("Properties");
  check(t.includes(email) && t.toLowerCase().includes("unique id"), "IAM: Properties shows the account read from the API", t.slice(0, 120));

  // remove the binding, reopen Members: the change persisted through the API
  await j("POST", `/api/gcp/iam/v1/projects/${project}:setIamPolicy`, { policy: { ...pol, bindings: pol.bindings || [] } });
  await page.evaluate(() => { const b = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => e.innerText.includes("Overview")); b && b.click(); });
  t = await tab("Members");
  check(!t.includes("roles/viewer") && t.includes("no roles"), "IAM: Members reflects a removed binding after reopening", t.slice(0, 120));
  await j("DELETE", `/api/gcp/iam/v1/projects/${project}/serviceAccounts/${email}`);
} catch (e) {
  check(false, "IAM detail flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
