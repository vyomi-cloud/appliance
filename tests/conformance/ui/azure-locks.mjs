/* Offline console conformance: a resource's Locks tab is backed by Microsoft.Authorization/locks. A lock added in the
 * blade is listed, stored (readable over ARM), survives re-opening the tab, and can be deleted.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-locks.mjs
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
const FLOW_SRC = "async function lockFlow() {\n  const svc = CATALOG.services.find((s) => s.key === \"nsg\");\n  const wait = (ms) => new Promise((r) => setTimeout(r, ms));\n  const name = \"nsg-lk\" + Math.floor(Math.random() * 1e5);\n  const out = {};\n  const put = await arm(\"PUT\", resPath(svc, name), { location: LOCATION, properties: {} }, svc.apiVersion);\n  if (!put.ok) return { error: \"create HTTP \" + put.status };\n  const open = async (label) => {\n    const el = [...document.querySelectorAll(\".sub-nav-item\")].find((e) => (e.querySelector(\".lbl\")?.innerText || e.innerText || \"\").trim() === label);\n    if (!el) return false;\n    el.click(); await wait(1000); return true;\n  };\n  const until = async (re) => { for (let i = 0; i < 40 && !re.test(document.querySelector(\".sub-content\").innerText); i++) await wait(250); };\n  await openDetail(svc, put.json || { id: resPath(svc, name), name, location: LOCATION });\n  for (let i = 0; i < 50 && !document.querySelectorAll(\".sub-nav-item\").length; i++) await wait(100);\n  out.hasTab = await open(\"Locks\");\n  if (!out.hasTab) return out;\n  await until(/No locks/);\n  out.emptyText = document.querySelector(\".sub-content\").innerText;\n  [...document.querySelectorAll(\".sub-content button\")].find((b) => /Add/.test(b.innerText)).click();\n  await wait(300);\n  const inputs = [...document.querySelectorAll(\".sub-content .essentials-grid input\")];\n  const set = (i, v) => { i.value = v; i.dispatchEvent(new Event(\"input\", { bubbles: true })); };\n  set(inputs[0], \"keep-me\"); set(inputs[1], \"do not delete\");\n  document.querySelector(\".sub-content .essentials-grid select\").value = \"CanNotDelete\";\n  [...document.querySelectorAll(\".sub-content button\")].find((b) => b.innerText.trim() === \"OK\").click();\n  await until(/keep-me/);\n  out.listed = document.querySelector(\".sub-content\").innerText;\n  await open(\"Overview\"); await open(\"Locks\"); await until(/keep-me/);\n  out.relisted = document.querySelector(\".sub-content\").innerText;\n  const got = await arm(\"GET\", resPath(svc, name) + \"/providers/Microsoft.Authorization/locks/keep-me\", undefined, \"2020-05-01\");\n  out.arm = got.json && got.json.properties;\n  const del = document.querySelector(\".sub-content button[title='Delete lock']\");\n  if (del) { del.click(); await until(/No locks/); }\n  out.afterDelete = document.querySelector(\".sub-content\").innerText;\n  await arm(\"DELETE\", resPath(svc, name), undefined, svc.apiVersion);\n  return out;\n}\n";
try {
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await sleep(3000);
  const r = await page.evaluate(`(${FLOW_SRC})()`);
  check(!r.error, "NSG created through ARM", r.error || "");
  check(r.hasTab, "NSG blade has a Locks tab");
  check(/No locks on this resource/i.test(r.emptyText || ""), "new NSG shows no locks yet", (r.emptyText || "").slice(0, 120));
  check(/keep-me/.test(r.listed || "") && /Delete/.test(r.listed || "") && /do not delete/.test(r.listed || ""), "lock added in the blade is listed with type and notes", (r.listed || "").slice(0, 160));
  check(/keep-me/.test(r.relisted || ""), "lock is still listed after re-opening the tab");
  check(r.arm && r.arm.level === "CanNotDelete" && r.arm.notes === "do not delete", "lock is readable over ARM with its values", JSON.stringify(r.arm));
  check(!/keep-me/.test(r.afterDelete || ""), "deleting the lock removes it");
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
