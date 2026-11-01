/* Release startup check: does every service come up, and does the UI say so?
 *
 * Against a running appliance (BASE, default http://localhost:9000):
 *   1. wait for the simulator to answer /healthz
 *   2. start every on-demand backend the way the UI does on first use
 *      (POST /api/runtime/backends/{name}/provision) and wait until
 *      /api/runtime/readiness reports every service ready
 *   3. in a real browser: /clouds shows "Appliance is Ready — all N services
 *      running", and the AWS, GCP and Azure consoles load their service rail
 *      with no page errors and no failing API calls
 *
 * Prints one PASS/FAIL line per check, writes OUT/summary.md + screenshots,
 * exits 1 on any failure.
 *   BASE=http://localhost:9000 OUT=startup-check TIMEOUT_S=900 node tests/installer/startup_check.mjs
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = (process.env.BASE || "http://localhost:9000").replace(/\/$/, "");
const OUT = process.env.OUT || "startup-check";
const TIMEOUT_S = +(process.env.TIMEOUT_S || 900);
const VERSION = process.env.VERSION || "";
mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok: !!ok, detail: String(detail) });
  console.log(`${ok ? "PASS" : "FAIL"}: ${name}${detail ? " — " + detail : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Every request gets a real (ref'd) timeout: while a container is starting,
// Docker's port proxy accepts the TCP connection and then drops it, and a bare
// fetch can then stay pending with nothing keeping Node alive (exit code 13).
const fetchT = (url, opts = {}, ms = 10_000) => {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), ms);
  return fetch(url, { ...opts, signal: ac.signal }).finally(() => clearTimeout(timer));
};
const getJson = async (path, opts) => { const r = await fetchT(BASE + path, opts); return { status: r.status, body: await r.json().catch(() => null) }; };

// ── 1. Simulator up ───────────────────────────────────────────────────────
const t0 = Date.now();
let healthy = false;
while (Date.now() - t0 < 300_000) {
  try { if ((await fetchT(BASE + "/healthz", {}, 5000)).ok) { healthy = true; break; } } catch {}
  await sleep(2000);
}
check("simulator answers /healthz", healthy, `${Math.round((Date.now() - t0) / 1000)}s`);

// ── 2. Every backend ready ────────────────────────────────────────────────
let rd = null;
const firstReady = {};
const kicked = new Set();
if (healthy) {
  const t1 = Date.now();
  while (Date.now() - t1 < TIMEOUT_S * 1000) {
    try { rd = (await getJson("/api/runtime/readiness")).body; } catch { rd = null; }
    for (const s of rd?.services || []) {
      if (s.status === "ready" && !firstReady[s.name]) firstReady[s.name] = Math.round((Date.now() - t0) / 1000);
      // On-demand backends start on first use; do what the UI would.
      if (s.status !== "ready" && s.name !== "simulator" && !kicked.has(s.name)) {
        kicked.add(s.name);
        await fetchT(`${BASE}/api/runtime/backends/${s.name}/provision`, { method: "POST" }).catch(() => {});
      }
    }
    if (rd?.ready) break;
    await sleep(5000);
  }
  check("readiness reports every service ready", rd?.ready, `${rd?.ready_count ?? "?"}/${rd?.total_count ?? "?"} ready, ${rd?.overall_pct ?? "?"}%`);
  for (const s of rd?.services || []) {
    check(`service ${s.label || s.name} ready`, s.status === "ready",
      s.status === "ready" ? `ready after ${firstReady[s.name] ?? "?"}s` : `status ${s.status}${s.detail ? ": " + s.detail : ""}`);
  }
}

// ── 3. The UI says so ─────────────────────────────────────────────────────
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [], bad = [];
page.on("pageerror", (e) => errors.push(String(e.message).split("\n")[0]));
page.on("response", (r) => { if (r.status() >= 500) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });

try {
  await page.goto(BASE + "/clouds", { waitUntil: "domcontentloaded" });
  const title = page.locator("#vyr-title");
  await title.waitFor({ state: "attached", timeout: 60_000 });   // lives in the banner's collapsed panel
  await page.waitForFunction(() => /Appliance is Ready/.test(document.querySelector("#vyr-title")?.textContent || ""), null, { timeout: 120_000 }).catch(() => {});
  const t = (await title.textContent())?.trim();
  const sum = (await page.locator("#vyr-summary").textContent())?.trim();
  check("/clouds status banner says 'Appliance is Ready'", t === "Appliance is Ready", t);
  check("/clouds banner counts every service", rd?.total_count && sum?.includes(`all ${rd.total_count} services running`), sum);
  if (VERSION) {
    const v = (await getJson("/api/runtime/version").catch(() => ({}))).body?.version;
    check(`running version is ${VERSION}`, v === VERSION, `reports ${v}`);
  }
  await page.screenshot({ path: `${OUT}/clouds.png` });
} catch (e) { check("/clouds loads", false, String(e.message).split("\n")[0]); }

for (const cloud of ["aws", "gcp", "azure"]) {
  const e0 = errors.length, b0 = bad.length;
  try {
    await page.goto(`${BASE}/console/${cloud}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => document.querySelectorAll("#rail a, #rail button, #rail li, #rail [data-service], #rail .navitem, #rail [data-key]").length > 0, null, { timeout: 60_000 });
    await sleep(2500);
    const n = await page.locator("#rail a, #rail button, #rail li, #rail [data-service], #rail .navitem, #rail [data-key]").count();
    check(`${cloud.toUpperCase()} console loads its service rail`, n > 0, `${n} rail items`);
    check(`${cloud.toUpperCase()} console has no page errors`, errors.length === e0, errors.slice(e0, e0 + 3).join(" | "));
    check(`${cloud.toUpperCase()} console has no 5xx API calls`, bad.length === b0, bad.slice(b0, b0 + 3).join(" | "));
    await page.screenshot({ path: `${OUT}/console-${cloud}.png` });
  } catch (e) { check(`${cloud.toUpperCase()} console loads`, false, String(e.message).split("\n")[0]); }
}
await browser.close();

// ── Report ────────────────────────────────────────────────────────────────
const failed = results.filter((r) => !r.ok);
const md = [`### Vyomi ${VERSION || ""} startup — ${results.length - failed.length}/${results.length} checks passed`, "",
  "| | Check | Detail |", "|---|---|---|",
  ...results.map((r) => `| ${r.ok ? "✅" : "❌"} | ${r.name} | ${r.detail.replace(/\|/g, "\\|")} |`)].join("\n");
writeFileSync(`${OUT}/summary.md`, md + "\n");
writeFileSync(`${OUT}/results.json`, JSON.stringify({ readiness: rd, results }, null, 1));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
