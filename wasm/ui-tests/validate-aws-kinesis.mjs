/* Nano console conformance for Amazon Kinesis Data Streams: the same flows as the
 * offline console test (tests/conformance/ui/aws-kinesis.mjs), run against the Nano
 * bundle (in-browser Pyodide cores). Open the service, create with defaults, every grid
 * column filled, detail tabs render, the stream is visible over the relay's native wire
 * (the aws CLI / SDK side), delete.
 *
 *   NANO_DIR=$PWD/wasm RELAY_HTTP=http://127.0.0.1:8090 node wasm/ui-tests/validate-aws-kinesis.mjs
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { startServer, bootConsole, chromium, sleep, RAIL_SEL } from "./lib.mjs";

const NAME = "my-stream";
const COLUMNS = ["Name", "Status", "Capacity mode", "Open shards", "Data retention", "Encryption", "Consumers", "Created"];
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};

const { server, base } = await startServer();
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url()}`); });
try {
  await bootConsole(page, base, "/aws-console.html");
  await sleep(1500);
  const rail = page.locator(RAIL_SEL).filter({ hasText: /kinesis/i }).first();
  check(await rail.count() > 0, "Kinesis is on the service rail");
  await rail.click({ timeout: 10000 });
  await sleep(1500);

  const rows = () => page.locator("#main table tr:has(td)").count();
  const before = await rows();
  await page.locator("#main button").filter({ hasText: /create/i }).first().click({ timeout: 5000 });
  await sleep(1200);
  for (let i = 0; i < 6; i++) {
    const next = page.locator("#main button").filter({ hasText: /^\s*(arrow_forward\s*)?Next\s*$/i }).last();
    if (!(await next.count()) || !(await next.isVisible())) break;
    await next.click(); await sleep(400);
  }
  const created = page.waitForResponse((r) => r.request().method() === "POST" && /\/api\/kinesis\/streams$/.test(r.url()), { timeout: 20000 }).catch(() => null);
  await page.locator("#main button").filter({ hasText: /create/i }).filter({ hasNotText: /cancel/i }).last().click({ timeout: 5000 });
  const resp = await created;
  check(resp !== null && resp.status() < 300, "create with the form's defaults returns 2xx", `HTTP ${resp && resp.status()}`);
  await rail.click().catch(() => {});
  let after = before;
  for (let i = 0; i < 12 && after <= before; i++) { await sleep(800); after = await rows(); }
  check(after > before, "the new stream appears in the list", `rows ${before} → ${after}`);

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

  await page.locator("#main a", { hasText: NAME }).first().click({ timeout: 5000 });
  await sleep(1500);
  for (const label of ["Overview", "Configuration", "Shards and consumers", "Tags"]) {
    const tab = page.locator("#main").getByText(label, { exact: true }).first();
    if (!(await tab.count())) { check(false, `tab "${label}" exists`); continue; }
    await tab.click(); await sleep(600);
    const len = await page.evaluate(() => (document.querySelector("#main").innerText || "").trim().length);
    check(len > 60, `tab "${label}" renders content`, `${len} chars`);
  }

  // The console and the relay share ONE store: the stream made in the UI is visible to the SDK/CLI wire.
  const viaWire = await page.evaluate(async () => {
    const r = await fetch("/api/kinesis/streams");
    return (await r.json()).items.map((s) => s.name);
  });
  check(viaWire.includes(NAME), "the stream is in the Nano store the relay serves", JSON.stringify(viaWire));

  const del = await page.evaluate(async (n) => (await fetch(`/api/kinesis/streams/${n}`, { method: "DELETE" })).status, NAME);
  check(del < 300, "delete the stream", `HTTP ${del}`);
  const left = await page.evaluate(async () => (await (await fetch("/api/kinesis/streams")).json()).items.length);
  check(left === 0, "the stream is gone from the list", left);
  check(!bad.length, "no API 5xx while driving the console", bad.join(", "));
} catch (e) {
  check(false, "console flow", String(e.message || e).split("\n")[0]);
}
await browser.close(); server.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
