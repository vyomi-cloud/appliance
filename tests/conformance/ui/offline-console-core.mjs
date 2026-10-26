/* Offline console core-path conformance (driven against $VYOMI_BASE_URL/console/*).
 *
 *  1. Storing a binary S3 object must not break /api/spaces — every console
 *     polls it, and a 500 there left the AWS/GCP/Azure consoles half-booted.
 *  2. Launching a VM with the form's default values must succeed (2xx from the
 *     create API) and add a row to the list, on AWS EC2 and GCP Compute Engine,
 *     even when the host deploy dir isn't writable by the simulator.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/offline-console-core.mjs
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
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};

// ── 1. binary S3 object vs /api/spaces ─────────────────────────────────────
const bucket = `bin-${Date.now().toString(36)}`;
await fetch(`${BASE}/${bucket}`, { method: "PUT" });
const bin = new Uint8Array(256).map((_, i) => (i * 37 + 0xe4) & 0xff); // not valid UTF-8
const put = await fetch(`${BASE}/${bucket}/blob.bin`, { method: "PUT", body: bin, headers: { "Content-Type": "application/octet-stream" } });
check(put.ok, "S3 PutObject with a binary body", `HTTP ${put.status}`);
for (const path of ["/api/spaces", "/api/spaces/active"]) {
  const r = await fetch(BASE + path);
  const body = r.ok ? await r.json().catch(() => null) : null;
  check(r.ok && body && typeof body === "object", `GET ${path} after a binary object is stored`, `HTTP ${r.status}`);
}

// ── 2. VM create with defaults through the real console ────────────────────
const CREATE_BTN = /create|launch/i;
const SUBMIT_BTN = /create|launch|submit|confirm/i;
const NOT_SUBMIT = /cancel|close|back|previous/i;

async function launchWithDefaults(browser, cloud, service, apiRe) {
  const page = await browser.newPage();
  const bad = [];
  let created = null;
  page.on("response", (r) => {
    if (r.request().method() === "POST" && apiRe.test(r.url())) created = r.status();
    if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`);
  });
  try {
    await page.goto(`${BASE}/console/${cloud}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
    await page.waitForTimeout(1500);
    check(!bad.length, `${cloud} console boots without API 5xx`, bad.join(", "));
    const rail = page.locator(RAIL_SEL).filter({ hasText: service }).first();
    await rail.click({ timeout: 5000 });
    await page.waitForTimeout(1500);
    const rows = () => page.locator("#main table tr:has(td), #main [role=row]:has([role=cell],[role=gridcell])").count();
    const before = await rows();
    await page.locator("#main button, #main [role=button]").filter({ hasText: CREATE_BTN }).first().click({ timeout: 5000 });
    await page.waitForTimeout(1200);
    const dialog = page.locator("[role=dialog]:visible, .modal:visible, .drawer:visible").last();
    const scope = (await dialog.count()) ? dialog : page.locator("#main");
    await scope.locator("button, [type=submit]").filter({ hasText: SUBMIT_BTN }).filter({ hasNotText: NOT_SUBMIT }).last().click({ timeout: 5000 });
    for (let i = 0; i < 20 && created === null; i++) await page.waitForTimeout(500);
    check(created !== null && created < 300, `${cloud} ${service}: create with defaults returns 2xx`, `HTTP ${created}`);
    await page.keyboard.press("Escape").catch(() => {});
    await rail.click({ timeout: 5000 }).catch(() => {});
    let after = before;
    for (let i = 0; i < 10 && after <= before; i++) { await page.waitForTimeout(800); after = await rows(); }
    check(after > before, `${cloud} ${service}: new instance appears in the list`, `rows ${before} → ${after}`);
  } catch (e) {
    check(false, `${cloud} ${service}: create with defaults`, String(e.message || e).split("\n")[0]);
  }
  await page.close();
}

const browser = await chromium.launch();
await launchWithDefaults(browser, "aws", "EC2", /\/api\/ec2\/instances$/);
await launchWithDefaults(browser, "gcp", "Compute Engine", /\/compute\/v1\/projects\/[^/]+\/zones\/[^/]+\/instances$/);
await browser.close();

console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
