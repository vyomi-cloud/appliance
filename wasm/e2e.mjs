/* Headless end-to-end proof that the REAL aws-console runs fully in-browser.
 *
 * Validates the whole Nano loop with no server behind /api/*: the loader
 * establishes service-worker control, Pyodide boots the wasm/ backend, the SW
 * serves the real dumped catalog, the console renders, and CRUD round-trips
 * through the console's own fetch path (SW-intercepted).
 *
 * Setup (Playwright isn't a repo dependency — install it wherever):
 *   npm i -g playwright && playwright install chromium
 * Run (serve the repo root first: `python3 -m http.server 8000`):
 *   PW=$(npm root -g)/playwright node wasm/e2e.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pwPath = process.env.PW || "playwright";
const { chromium } = require(pwPath);

const BASE = process.env.BASE || "http://localhost:8000";
const URL = BASE + "/wasm/console.html";
const log = [];
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
page.on("console", (m) => log.push("[console] " + m.text()));
page.on("pageerror", (e) => log.push("[pageerror] " + e.message));
const fail = (m) => { console.log("FAIL:", m); console.log(log.slice(-30).join("\n")); process.exit(1); };

try {
  await page.goto(URL, { waitUntil: "load" });
  await page.waitForFunction(() => {
    const b = document.getElementById("nano-banner");
    return b && /ready/i.test(b.textContent);
  }, { timeout: 90000 }).catch(() => fail("backend never signalled ready (Pyodide/SW boot)"));
  console.log("1. PASS — Pyodide + SW booted, backend ready");

  const txt = await page.evaluate(() => document.body.innerText);
  if (/Select an AWS space first/i.test(txt)) fail("space gate fired — fixtures not served");
  if (!["S3", "EC2", "IAM", "DynamoDB"].every((s) => txt.includes(s)))
    fail("AWS service nav not rendered from catalog");
  console.log("2. PASS — real catalog rendered (S3/EC2/IAM/DynamoDB nav present)");

  const crud = await page.evaluate(async () => {
    const j = async (m, p, b) => (await (await fetch(p, {
      method: m, headers: b ? { "content-type": "application/json" } : {},
      body: b ? JSON.stringify(b) : undefined,
    })).json());
    await j("POST", "/api/ec2/instances", { name: "e2e-web-1", type: "t3.micro" });
    const listed = await j("GET", "/api/ec2/instances");
    await j("DELETE", "/api/ec2/instances/e2e-web-1");
    const after = await j("GET", "/api/ec2/instances");
    return { listed, after };
  });
  if (!(crud.listed.items || []).some((i) => i.name === "e2e-web-1")) fail("create not reflected in list");
  if ((crud.after.items || []).some((i) => i.name === "e2e-web-1")) fail("delete not reflected");
  console.log("3. PASS — CRUD round-trip in-browser: create→list(found)→delete→list(gone)");

  const cat = await page.evaluate(async () => (await (await fetch("/api/aws/catalog")).json()));
  if (!cat.services || !cat.services.length) fail("catalog empty");
  console.log("4. PASS — /api/aws/catalog served in-browser:", cat.services.length, "services");

  console.log("\nRESULT: PASS — the REAL aws-console runs fully in-browser (no server).");
} catch (e) {
  fail(String(e));
} finally {
  await browser.close();
}
