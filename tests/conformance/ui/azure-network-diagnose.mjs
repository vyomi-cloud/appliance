/* Offline console conformance: a Key Vault's Networking tab shows its real publicNetworkAccess/defaultAction and a saved
 * edit persists over ARM and after re-opening; its "Diagnose and solve problems" tab shows the resource's own health.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-network-diagnose.mjs
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
const FLOW_SRC = `async function flow() {
  const svc = CATALOG.services.find((s) => s.key === "keyvault");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const name = "kv-nd" + Math.floor(Math.random() * 1e5);
  const out = {};
  const put = await arm("PUT", resPath(svc, name), { location: LOCATION, properties: { tenantId: "00000000-0000-0000-0000-000000000000", sku: { family: "A", name: "standard" } } }, svc.apiVersion);
  if (!put.ok) return { error: "create HTTP " + put.status };
  const text = () => document.querySelector(".sub-content").innerText;
  const open = async (label) => {
    const el = [...document.querySelectorAll(".sub-nav-item")].find((e) => (e.querySelector(".lbl")?.innerText || e.innerText || "").trim() === label);
    if (!el) return false;
    el.click(); await wait(900); return true;
  };
  await openDetail(svc, put.json);
  for (let i = 0; i < 50 && !document.querySelectorAll(".sub-nav-item").length; i++) await wait(100);
  out.hasDiag = await open("Diagnose and solve problems");
  out.diag = text();
  out.hasNet = await open("Networking");
  await wait(500);
  out.net = text();
  const sels = document.querySelectorAll(".sub-content select");
  sels[0].value = "Disabled"; sels[1].value = "Deny";
  [...document.querySelectorAll(".sub-content button")].find((b) => /^Save$/.test(b.innerText)).click();
  await wait(1200);
  await open("Overview"); await open("Networking"); await wait(500);
  const again = document.querySelectorAll(".sub-content select");
  out.reopened = [again[0].value, again[1].value];
  const got = await arm("GET", resPath(svc, name), undefined, svc.apiVersion);
  out.arm = got.json && got.json.properties;
  await arm("DELETE", resPath(svc, name), undefined, svc.apiVersion);
  return out;
}`;
try {
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await sleep(3000);
  const r = await page.evaluate(`(${FLOW_SRC})()`);
  check(!r.error, "Key Vault created through ARM", r.error || "");
  check(r.hasDiag && /Resource health/.test(r.diag || "") && /Succeeded/.test(r.diag || ""), "Diagnose tab shows this resource's health and provisioning state", (r.diag || "").slice(0, 160));
  check(!/This pane mirrors|Not yet wired/.test(r.diag || ""), "Diagnose tab is not a placeholder");
  check(r.hasNet && /Public network access/.test(r.net || ""), "Networking tab shows public network access", (r.net || "").slice(0, 160));
  check(r.reopened && r.reopened[0] === "Disabled" && r.reopened[1] === "Deny", "saved network edit survives re-opening the tab", JSON.stringify(r.reopened));
  check(r.arm && r.arm.publicNetworkAccess === "Disabled" && r.arm.networkAcls && r.arm.networkAcls.defaultAction === "Deny", "network edit is readable over ARM", JSON.stringify(r.arm));
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
