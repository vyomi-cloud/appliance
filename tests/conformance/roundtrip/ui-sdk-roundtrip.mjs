/* UI <-> SDK bi-directional parity (offline appliance, AWS).
 *
 * For each service, in both directions, with the DATA compared, not just presence:
 *   A. created with the official SDK  -> listed in the console grid, ARN shown == the SDK's ARN
 *   B. created in the console (form defaults) -> the SDK sees it, same ARN, same type (standard/FIFO)
 *   C. deleted with the SDK           -> gone from the console after a reload
 *   D. deleted in the console         -> the SDK no longer sees it
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/roundtrip/ui-sdk-roundtrip.mjs
 * One [PASS]/[FAIL] line per check; exit 1 on any failure. Python with boto3 is $PYTHON (default python3).
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
const PY = process.env.PYTHON || "python3";
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const sdk = (svc, op, name) => {
  try { return JSON.parse(execFileSync(PY, [resolve(HERE, "sdk_side.py"), svc, op, name], { env: { ...process.env, VYOMI_BASE_URL: BASE }, encoding: "utf-8", timeout: 60000 })); }
  catch (e) { return { error: String(e.stderr || e.message).split("\n").filter(Boolean).pop() }; }
};

// rail = how the service is found on the AWS rail; defaultName = the create form's default name
const SERVICES = [
  { id: "sns", label: /Amazon SNS/, defaultName: "MyTopic", noun: "topic" },
  { id: "sqs", label: /Simple Queue|SQS/, defaultName: "MyQueue", noun: "queue" },
];

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));

async function openService(svc) {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.locator(RAIL_SEL).filter({ hasText: svc.label }).first().click({ timeout: 15000 });
  await page.waitForTimeout(1800);
}
const rows = () => page.evaluate(() => [...document.querySelectorAll("#main table tr")]
  .map((tr) => [...tr.querySelectorAll("td")].map((e) => e.innerText.trim())).filter((r) => r.length));
const rowFor = async (name) => (await rows()).find((r) => r.some((c) => c === name || c.endsWith("/" + name) || c.endsWith(":" + name))) || null;

try {
  for (const svc of SERVICES) {
    const T = `${svc.id.toUpperCase()}`;
    const sdkName = `rt-${svc.id}-${Date.now().toString(36)}`;
    // clean slate for the form-default name
    sdk(svc.id, "delete", svc.defaultName);

    // A. SDK -> UI
    const made = sdk(svc.id, "create", sdkName);
    check(!!made.arn, `${T}: SDK creates a ${svc.noun}`, JSON.stringify(made));
    await openService(svc);
    let row = await rowFor(sdkName);
    check(!!row, `${T}: SDK-created ${svc.noun} is listed in the console`, `rows=${JSON.stringify((await rows()).slice(0, 3))}`);
    check(!!row && row.some((c) => c === made.arn), `${T}: console shows the SDK's ARN for it`, row ? JSON.stringify(row) : "no row");

    // C. SDK delete -> UI
    sdk(svc.id, "delete", sdkName);
    await openService(svc);
    check(!(await rowFor(sdkName)), `${T}: SDK-deleted ${svc.noun} is gone from the console`);

    // B. UI -> SDK (form defaults)
    await page.locator("#main button").filter({ hasText: /Create/ }).first().click({ timeout: 8000 });
    await page.waitForTimeout(1200);
    await page.locator("#main .wizard-footer button.primary, #main button.primary").filter({ hasText: /Create/ }).last().click({ timeout: 8000 });
    await page.waitForTimeout(2500);
    await openService(svc);
    row = await rowFor(svc.defaultName);
    check(!!row, `${T}: console-created ${svc.noun} (form defaults) is listed`, `rows=${JSON.stringify((await rows()).slice(0, 3))}`);
    const seen = sdk(svc.id, "describe", svc.defaultName);
    check(seen.exists === true, `${T}: SDK sees the console-created ${svc.noun}`, JSON.stringify(seen));
    check(!!row && !!seen.arn && row.some((c) => c === seen.arn), `${T}: console's ARN matches the SDK's ARN`, `sdk=${seen.arn} row=${row ? JSON.stringify(row) : "-"}`);
    const uiFifo = !!row && row.some((c) => /fifo/i.test(c));
    check(seen.exists === true && seen.fifo === uiFifo, `${T}: console type (Standard/FIFO) matches the SDK`, `sdk fifo=${seen.fifo} ui fifo=${uiFifo}`);

    // D. UI delete -> SDK
    await page.locator("#main a.id, #main td a").filter({ hasText: svc.defaultName }).first().click({ timeout: 8000 });
    await page.waitForTimeout(1500);
    await page.locator("#main button").filter({ hasText: /Delete/ }).first().click({ timeout: 8000 });
    await page.waitForTimeout(1200);
    await page.locator("button").filter({ hasText: /^\s*(Delete|Confirm|Yes)/i }).last().click({ timeout: 2500 }).catch(() => {});
    await page.waitForTimeout(2000);
    check((await sdk(svc.id, "describe", svc.defaultName)).exists === false, `${T}: SDK no longer sees the console-deleted ${svc.noun}`);
  }
} catch (e) {
  check(false, "round-trip run", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
