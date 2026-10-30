/* Offline console conformance: a resource's Identity tab is backed by the resource's ARM `identity` block. Turning on
 * the system-assigned identity shows a principal ID, survives re-opening the tab and is readable over ARM; adding a
 * user-assigned identity is listed; turning it all off clears the block.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-identity.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

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
};
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const bad = [];
page.on("dialog", (d) => d.accept().catch(() => {}));
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const FLOW_SRC = `async function identityFlow() {
  const svc = CATALOG.services.find((s) => s.key === "servicebus");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const name = "sb-id" + Math.floor(Math.random() * 1e5);
  const out = {};
  const put = await arm("PUT", resPath(svc, name), { location: LOCATION, sku: { name: "Standard" }, properties: {} }, svc.apiVersion);
  if (!put.ok) return { error: "create HTTP " + put.status };
  const text = () => document.querySelector(".sub-content").innerText;
  const open = async (label) => {
    const el = [...document.querySelectorAll(".sub-nav-item")].find((e) => (e.querySelector(".lbl")?.innerText || e.innerText || "").trim() === label);
    if (!el) return false;
    el.click(); await wait(800); return true;
  };
  const btn = (re) => [...document.querySelectorAll(".sub-content button")].find((b) => re.test(b.innerText));
  const until = async (re) => { for (let i = 0; i < 40 && !re.test(text()); i++) await wait(250); };
  await openDetail(svc, put.json);
  for (let i = 0; i < 50 && !document.querySelectorAll(".sub-nav-item").length; i++) await wait(100);
  out.hasTab = await open("Identity");
  if (!out.hasTab) return out;
  await until(/Off/);
  out.before = text();
  btn(/Turn on/).click();
  await until(/principal\\) ID/);
  out.on = text();
  await open("Overview"); await open("Identity"); await until(/Status/);
  out.reopened = text();
  const got = await arm("GET", resPath(svc, name), undefined, svc.apiVersion);
  out.arm = got.json && got.json.identity;
  const ua = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami-1";
  const inp = document.querySelector(".sub-content input");
  inp.value = ua; inp.dispatchEvent(new Event("input", { bubbles: true }));
  btn(/^Add$/).click();
  await until(/uami-1/);
  out.user = text();
  btn(/Turn off/).click();
  await until(/Status\\s*Off/);
  const after = await arm("GET", resPath(svc, name), undefined, svc.apiVersion);
  out.afterArm = after.json && after.json.identity;
  await arm("DELETE", resPath(svc, name), undefined, svc.apiVersion);
  return out;
}`;
try {
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await sleep(3000);
  const r = await page.evaluate(`(${FLOW_SRC})()`);
  check(!r.error, "Service Bus namespace created through ARM", r.error || "");
  check(r.hasTab, "blade has an Identity tab");
  check(/Off/.test(r.before || ""), "new resource has no system-assigned identity", (r.before || "").slice(0, 120));
  check(/On/.test(r.on || "") && /[0-9a-f]{8}-[0-9a-f]{4}-/.test(r.on || ""), "turning it on shows a principal ID", (r.on || "").slice(0, 160));
  check(/On/.test(r.reopened || ""), "identity is still on after re-opening the tab");
  check(r.arm && r.arm.type === "SystemAssigned" && r.arm.principalId && r.arm.tenantId, "identity is readable over ARM", JSON.stringify(r.arm));
  check(/uami-1/.test(r.user || ""), "user-assigned identity is listed", (r.user || "").slice(0, 160));
  check(!r.afterArm || !Object.keys(r.afterArm).length || r.afterArm.type === "UserAssigned", "turning system-assigned off keeps only the user identity", JSON.stringify(r.afterArm));
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
