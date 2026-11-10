/* Offline console conformance for Amazon Kinesis Data Streams (driven against
 * $VYOMI_BASE_URL/console/aws): open the service, create a stream with the form's
 * defaults, every grid column filled, every detail tab renders, delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-kinesis.mjs
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
const NAME = "my-stream";
const COLUMNS = ["Name", "Status", "Capacity mode", "Open shards", "Data retention", "Encryption", "Consumers", "Created"];
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Start clean: a leftover stream from an earlier run would hide a create regression.
await fetch(`${BASE}/api/kinesis/streams/${NAME}`, { method: "DELETE" }).catch(() => {});

const browser = await chromium.launch();
const page = await browser.newPage();
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
try {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: /kinesis/i }).first();
  check(await rail.count() > 0, "Kinesis is on the service rail");
  await rail.click({ timeout: 10000 });
  await sleep(1500);

  // ── create with the form defaults ──
  const rows = () => page.locator("#main table tr:has(td)").count();
  const before = await rows();
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  // Stepped wizard: walk to the last step (Next …), then Create.
  for (let i = 0; i < 6; i++) {
    const next = page.locator("#main button").filter({ hasText: /^\s*(arrow_forward\s*)?Next\s*$/i }).last();
    if (!(await next.count()) || !(await next.isVisible())) break;
    await next.click(); await sleep(400);
  }
  const submit = page.locator("#main button").filter({ hasText: /create/i }).filter({ hasNotText: /cancel/i }).last();
  let status = null;
  page.once("response", () => {});
  const created = page.waitForResponse((r) => r.request().method() === "POST" && /\/api\/kinesis\/streams$/.test(r.url()), { timeout: 15000 }).catch(() => null);
  await submit.click({ timeout: 5000 });
  const resp = await created;
  status = resp ? resp.status() : null;
  check(status !== null && status < 300, "create with the form's defaults returns 2xx", `HTTP ${status}`);
  await rail.click().catch(() => {});
  let after = before;
  for (let i = 0; i < 10 && after <= before; i++) { await sleep(800); after = await rows(); }
  check(after > before, "the new stream appears in the list", `rows ${before} → ${after}`);

  // ── every grid column filled ──
  const grid = await page.evaluate(() => {
    const t = document.querySelector("#main table");
    const heads = [...t.querySelectorAll("th")].map((h) => h.innerText.replace(/[▲▼]/g, "").trim());
    const row = [...t.querySelectorAll("tr")].find((r) => r.querySelector("td"));
    return { heads, cells: [...row.querySelectorAll("td")].map((c) => c.innerText.trim()) };
  });
  for (const col of COLUMNS) {
    const i = grid.heads.indexOf(col);
    const v = i >= 0 ? grid.cells[i] : undefined;
    check(i >= 0 && v && !/^(-|—|undefined|null)$/i.test(v), `column "${col}" is filled`, `value=${JSON.stringify(v)}`);
  }

  // ── detail tabs render ──
  await page.locator("#main a", { hasText: NAME }).first().click({ timeout: 5000 });
  await sleep(1500);
  const tabs = await page.evaluate(() => [...document.querySelectorAll("#main .top-tabs button, #main .subnav button, #main .sub-nav a, #main [data-subblade]")].map((e) => (e.innerText || "").trim()).filter(Boolean));
  check(tabs.length >= 3, "detail blade has tabs", JSON.stringify(tabs));
  for (const label of ["Overview", "Configuration", "Shards and consumers", "Tags"]) {
    const tab = page.locator("#main").getByText(label, { exact: true }).first();
    if (!(await tab.count())) { check(false, `tab "${label}" exists`); continue; }
    await tab.click(); await sleep(600);
    const len = await page.evaluate(() => (document.querySelector("#main").innerText || "").trim().length);
    check(len > 60, `tab "${label}" renders content`, `${len} chars`);
  }

  // ── delete ──
  const del = await (await fetch(`${BASE}/api/kinesis/streams/${NAME}`, { method: "DELETE" })).status;
  check(del < 300, "delete the stream", `HTTP ${del}`);
  const list = await (await fetch(`${BASE}/api/kinesis/streams`)).json();
  check(!(list.items || []).some((s) => s.name === NAME), "the stream is gone from the list");
  check(!bad.length, "no API 5xx while driving the console", bad.join(", "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
