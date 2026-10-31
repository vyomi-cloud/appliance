/* Offline GCP console: the detail Metrics tab shows MEASURED request series for the
 * resource (GET /api/metrics/series), not a seeded sparkline. Uses API Gateway.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-metrics-tab.mjs
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
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
let id = "";
page.on("response", async (r) => {
  if (r.request().method() === "POST" && /apigateway\/v1\/projects\/[^/]+\/locations\/global\/apis$/.test(r.url()) && r.status() < 300) {
    try { const b = JSON.parse(r.request().postData() || "{}"); id = String(b.apiId || b.name || "").split("/").pop(); } catch (_) {}
  }
});
try {
  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  await page.locator(RAIL_SEL).filter({ hasText: /API Gateway/i }).first().click({ timeout: 5000 });
  await sleep(1500);
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  await page.locator("#main .summary-card button, #main button.primary").filter({ hasText: /create/i }).last().click({ timeout: 5000 });
  for (let i = 0; i < 20 && !id; i++) await sleep(500);
  check(!!id, "API created through the console", `id=${id}`);
  await sleep(1500);
  const row = () => page.locator("#main table tr:has(td)").filter({ hasText: id || "zzz-none" }).first();
  for (let i = 0; i < 10 && !(await row().count()); i++) await sleep(800);
  await row().locator("a.id, a").first().click({ timeout: 5000 });
  await sleep(1500);
  const metrics = page.locator(".sub-nav a.nav-item").filter({ hasText: /Metrics/ }).first();
  await metrics.click({ timeout: 5000 });
  await sleep(1000);
  const txt = () => page.locator(".sub-content").innerText();
  const t1 = await txt();
  check(/Measured from the requests/.test(t1), "Metrics tab says it is measured", t1.slice(0, 120));
  check(/No requests in the last hour/.test(t1) || /requests \(last hour\)/.test(t1), "Metrics tab shows data or the empty state");
  // generate real traffic on this API, then reopen the tab
  const proj = (await (await fetch(`${BASE}/v1/projects`)).json()).projects[0].projectId;
  for (let i = 0; i < 4; i++) await fetch(`${BASE}/api/gcp/apigateway/v1/projects/${proj}/locations/global/apis/${id}`);
  await page.locator(".sub-nav a.nav-item").first().click(); await sleep(500);
  await metrics.click(); await sleep(1200);
  const t2 = await txt();
  const m = t2.match(/(\d+) requests \(last hour\)/);
  check(!!m && Number(m[1]) >= 4, "requests served for this API show up as a measured count", t2.slice(0, 200));
  check(!/units/.test(t2), "no synthesized 'units' values");
} catch (e) { check(false, "Metrics tab flow", String(e.message).split("\n")[0]); }
await browser.close();
process.exit(fails ? 1 : 0);
