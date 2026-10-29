/* Offline console conformance: the Tags tab of every ARM resource blade is a real editor. A tag added and saved
 * in the blade is stored on the resource (readable over ARM) and shown again when the tab is re-opened.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/azure-tags-tab.mjs
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
page.on("pageerror", (e) => bad.push("pageerror: " + String(e.message).split("\n")[0]));
const FLOW_SRC = "async function tagsFlow(key) {\n  const svc = (CATALOG.services || []).find((s) => s.key === key);\n  if (!svc) return { key, error: \"service not in catalog\" };\n  const name = \"tagtest\" + key.replace(/[^a-z0-9]/g, \"\").slice(0, 8) + Math.floor(Math.random() * 1e4) + (key === \"dns\" ? \".example.com\" : \"\");\n  const body = { location: LOCATION, properties: {} };\n  (svc.createFields || []).forEach((f) => { if (f.name && f.name !== \"name\" && f.default !== undefined) setPath(body, f.name, f.default === \"__UUID__\" ? \"\" : f.default); });\n  if (body.properties.customSubDomainName) body.properties.customSubDomainName = name;\n  const put = await arm(\"PUT\", resPath(svc, name), body, svc.apiVersion);\n  if (!put.ok) return { key, error: \"create HTTP \" + put.status };\n  const wait = (ms) => new Promise((r) => setTimeout(r, ms));\n  const openTags = async () => {\n    await openDetail(svc, put.json || { id: resPath(svc, name), name, ...body });\n    for (let i = 0; i < 50 && !document.querySelectorAll(\".sub-nav-item\").length; i++) await wait(100);\n    const el = [...document.querySelectorAll(\".sub-nav-item\")].find((e) => (e.querySelector(\".lbl\")?.innerText || e.innerText || \"\").trim() === \"Tags\");\n    if (!el) return null;\n    el.click(); await wait(500);\n    return document.querySelectorAll(\".tags-grid input\");\n  };\n  let inputs = await openTags();\n  if (!inputs) return { key, error: \"no Tags tab\" };\n  if (inputs.length < 2) return { key, error: \"no tag editor inputs\" };\n  const set = (i, v) => { i.value = v; i.dispatchEvent(new Event(\"input\", { bubbles: true })); };\n  set(inputs[0], \"env\"); set(inputs[1], \"ci-\" + key);\n  [...document.querySelectorAll(\".sub-content button, #blade button\")].find((b) => b.innerText.trim() === \"Save\").click();\n  await wait(1500);\n  const got = await arm(\"GET\", resPath(svc, name), undefined, svc.apiVersion);\n  const armTag = got.json && got.json.tags && got.json.tags.env;\n  inputs = await openTags();\n  const shown = inputs && [...inputs].map((i) => i.value);\n  await arm(\"DELETE\", resPath(svc, name), undefined, svc.apiVersion);\n  return { key, armTag, shown: shown || [] };\n}\n";
try {
  await page.goto(`${BASE}/console/azure`, { waitUntil: "domcontentloaded" });
  await sleep(3000);
  // Role definitions / assignments are not taggable resources in Azure, so they have no Tags tab.
  const keys = await page.evaluate(() => (CATALOG.services || []).filter((s) => !s.dataPlane && !s.hidden && s.namespace && !/^Microsoft\.Authorization$/.test(s.namespace)).map((s) => s.key));
  check(keys.length > 5, "console catalog lists ARM services", String(keys.length));
  for (const key of keys) {
    const r = await page.evaluate(`(${FLOW_SRC})("${key}")`);
    if (r.error) { check(false, `${key}: Tags tab`, r.error); continue; }
    check(r.armTag === "ci-" + key, `${key}: saved tag is stored on the resource (ARM GET)`, JSON.stringify(r));
    check(r.shown.includes("env") && r.shown.includes("ci-" + key), `${key}: tag is shown again when the tab is re-opened`, JSON.stringify(r.shown));
  }
  check(!bad.length, "no page errors", bad.slice(0, 3).join("; "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
