/* Nano console conformance: the Network Security Group blade's Security rules tab is a real editor. A rule added in the
 * blade is listed, stored on the resource (readable over ARM), survives re-opening the tab, and can be deleted.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-azure-nsg-rules.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";

let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};
const { server, base } = await startServer();
const browser = await chromium.launch();
const ctx = await browser.newContext();
await ctx.addInitScript(() => { try { localStorage.setItem("nano_tunnel_on", "1"); } catch (_) {} });
const page = await ctx.newPage();
const bad = [];
page.on("dialog", (d) => d.accept().catch(() => {}));
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const FLOW_SRC = "async function nsgFlow() {\n  const svc = CATALOG.services.find((s) => s.key === \"nsg\");\n  const wait = (ms) => new Promise((r) => setTimeout(r, ms));\n  const name = \"nsg-ui\" + Math.floor(Math.random() * 1e5);\n  const out = { steps: {} };\n  const put = await arm(\"PUT\", resPath(svc, name), { location: LOCATION, properties: {} }, svc.apiVersion);\n  if (!put.ok) return { error: \"create HTTP \" + put.status };\n  const open = async (label) => {\n    const el = [...document.querySelectorAll(\".sub-nav-item\")].find((e) => (e.querySelector(\".lbl\")?.innerText || e.innerText || \"\").trim() === label);\n    if (!el) return false;\n    el.click(); await wait(1000); return true;\n  };\n  await openDetail(svc, put.json || { id: resPath(svc, name), name, location: LOCATION });\n  for (let i = 0; i < 50 && !document.querySelectorAll(\".sub-nav-item\").length; i++) await wait(100);\n  out.labels = [...document.querySelectorAll(\".sub-nav-item\")].map((e) => (e.querySelector(\".lbl\")?.innerText || \"\").trim());\n  out.hasTab = await open(\"Security rules\");\n  if (!out.hasTab) return out;\n  out.emptyText = document.querySelector(\".sub-content\").innerText;\n  [...document.querySelectorAll(\".sub-content button\")].find((b) => /Add security rule/.test(b.innerText)).click();\n  await wait(300);\n  const inputs = [...document.querySelectorAll(\".sub-content .essentials-grid input\")];\n  const set = (i, v) => { i.value = v; i.dispatchEvent(new Event(\"input\", { bubbles: true })); };\n  set(inputs[0], \"Allow-SSH\"); set(inputs[1], \"310\"); set(inputs[4] || inputs[inputs.length - 1], \"22\");\n  [...document.querySelectorAll(\".sub-content button\")].find((b) => b.innerText.trim() === \"Add\").click();\n  await wait(1500);\n  out.listed = document.querySelector(\".sub-content\").innerText;\n  await open(\"Overview\"); await open(\"Security rules\");\n  out.relisted = document.querySelector(\".sub-content\").innerText;\n  const got = await arm(\"GET\", resPath(svc, name) + \"/securityRules/Allow-SSH\", undefined, svc.apiVersion);\n  out.arm = got.json && got.json.properties;\n  const del = [...document.querySelectorAll(\".sub-content button[title='Delete rule']\")][0];\n  if (del) { del.click(); await wait(1500); }\n  out.afterDelete = document.querySelector(\".sub-content\").innerText;\n  await arm(\"DELETE\", resPath(svc, name), undefined, svc.apiVersion);\n  return out;\n}\n";
try {
  await bootConsole(page, base, "/azure-console.html");
  await sleep(2500);
  const r = await page.evaluate(`(${FLOW_SRC})()`);
  check(!r.error, "NSG created through ARM", r.error || "");
  check(r.hasTab, "NSG blade has a Security rules tab", JSON.stringify(r.labels));
  check(/No custom security rules/i.test(r.emptyText || ""), "new NSG shows no custom rules yet", (r.emptyText || "").slice(0, 80));
  check(/Allow-SSH/.test(r.listed || "") && /310/.test(r.listed || "") && /22/.test(r.listed || ""), "rule added in the blade is listed with priority and port", (r.listed || "").slice(0, 160));
  check(/Allow-SSH/.test(r.relisted || ""), "rule is still listed after re-opening the tab");
  check(r.arm && r.arm.priority === 310 && String(r.arm.destinationPortRange) === "22", "rule is readable over ARM with its values", JSON.stringify(r.arm));
  check(!/Allow-SSH/.test(r.afterDelete || ""), "deleting the rule removes it");
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
