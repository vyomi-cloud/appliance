/* GCP console Metrics tab (offline appliance): the tab charts the requests the
 * simulator actually served for THIS resource (GET /api/metrics/series), not a
 * synthesized curve.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-metrics-tab.mjs
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

const bucket = "metrics-tab-" + Math.random().toString(36).slice(2, 8);
const browser = await chromium.launch();
const page = await browser.newPage();
try {
  const cr = await fetch(`${BASE}/api/gcp/storage/v1/b`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: bucket }) });
  check(cr.ok, "bucket created through the console API", String(cr.status));
  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  await page.locator(RAIL_SEL).filter({ hasText: "Cloud Storage" }).first().click({ timeout: 15000 });
  await sleep(1500);
  const opened = await page.evaluate((b) => {
    const a = [...document.querySelectorAll("#main table.gc tr[data-row-name]")].find((r) => r.getAttribute("data-row-name") === b);
    const l = a && a.querySelector("a.id"); if (l) { l.click(); return true; } return false;
  }, bucket);
  await sleep(1500);
  check(opened, "bucket detail opens");
  const clicked = await page.evaluate(() => {
    const t = [...document.querySelectorAll("#main .sub-nav a.nav-item")].find((e) => /Metrics/.test(e.innerText));
    if (t) { t.click(); return true; } return false;
  });
  check(clicked, "Metrics tab present");
  await sleep(1500);
  const m = await page.evaluate(() => ({
    charts: [...document.querySelectorAll("#main .sub-content svg[role=img]")].map((s) => s.getAttribute("aria-label")),
    text: (document.querySelector("#main .sub-content") || {}).innerText || "",
  }));
  check(["Requests", "Errors (4xx/5xx)", "Latency"].every((l) => m.charts.includes(l)), "charts are the measured Requests / Errors / Latency", JSON.stringify(m.charts));
  check(/Measured from the requests this simulator served for/.test(m.text) && !/No requests/.test(m.text), "tab reports this resource's own recorded requests", m.text.slice(0, 120));
  const api = await (await fetch(`${BASE}/api/metrics/series?provider=gcp&resource=${bucket}&minutes=60&step=60`)).json();
  const shown = Number((m.text.match(/(\d+) requests \(last hour\)/) || [])[1]);
  check(api.total_requests > 0 && shown > 0 && shown <= api.total_requests, "chart total comes from /api/metrics/series", `shown=${shown} api=${api.total_requests}`);
  await fetch(`${BASE}/api/gcp/storage/v1/b/${bucket}`, { method: "DELETE" });
} catch (e) {
  check(false, "GCP Metrics tab flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
