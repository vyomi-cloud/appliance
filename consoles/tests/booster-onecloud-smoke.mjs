/* Pro = ONE cloud in the Nano UI. Faked /api/account/booster (+ /primary-cloud) against the Nano preview.
 *   Pro, no cloud yet -> every cloud usable; the first one used is pinned (POST /primary-cloud), the other two then locked
 *   Pro, cloud chosen -> the other clouds are refused (gate + create-space), the chosen one works
 *   Max               -> all three, nothing pinned
 *   unknown (404)     -> not gated
 *   PW=<playwright path> node consoles/tests/booster-onecloud-smoke.mjs     Exit 1 on any FAIL. */
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url); const pw = require(process.env.PW || "playwright");
const here = dirname(fileURLToPath(import.meta.url)); const PORT = Number(process.env.PORT || 8799);
const NANO = `http://127.0.0.1:${PORT}/nano`;
let bad = 0; const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${ok || !d ? "" : " - " + String(d).slice(0, 160)}`); };
const preview = spawn("node", [join(here, "..", "nano_preview.mjs"), "--port", String(PORT)], { stdio: "ignore" });
for (let i = 0; i < 40; i++) { try { if ((await fetch(`${NANO}/`, { redirect: "manual" })).status < 500) break; } catch {} await new Promise((r) => setTimeout(r, 250)); }
const browser = await pw.chromium.launch();
const PRO = (pc) => ({ enabled: true, effective: true, status: "active", source: "subscription", tier: "pro", days_left: 20, trial_used: true, locked: false, clouds: "one", primary_cloud: pc });
const MAX = { enabled: true, effective: true, status: "active", source: "subscription", tier: "max", days_left: 20, trial_used: true, locked: false, clouds: "all", primary_cloud: "" };
async function open(acc) {
  const ctx = await browser.newContext(); const page = await ctx.newPage(); const calls = []; let cur = acc;
  await ctx.addInitScript(() => { try { localStorage.setItem("vyomi.boosters", JSON.stringify([{ id: "bst-demo", name: "lab", paired_at: 1, base: "http://127.0.0.1:1", token: "t" }])); } catch {} });
  await page.route("**/api/account/booster**", async (route) => {
    const u = new URL(route.request().url()), m = route.request().method(); calls.push(m + " " + u.pathname);
    if (cur === null) return route.fulfill({ status: 404, body: "no" });
    if (m === "POST" && u.pathname.endsWith("/primary-cloud")) {
      const want = JSON.parse(route.request().postData() || "{}").cloud;
      if (cur.primary_cloud && cur.primary_cloud !== want) return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: "primary_cloud_fixed", primary_cloud: cur.primary_cloud }) });
      cur = { ...cur, primary_cloud: want };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(cur) });
  });
  await page.goto(`${NANO}/clouds.html`);
  await page.waitForFunction(() => !!window.VyomiBooster && !!navigator.serviceWorker.controller, null, { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
  await page.waitForFunction(() => !!window.VyomiBooster, null, { timeout: 60000 });
  await page.waitForTimeout(800);
  return { ctx, page, calls };
}
const picker = (page) => page.evaluate(() => { window.openCreateSpaceModal(); const f = document.getElementById("csm-home-field"), s = document.getElementById("csm-home"); const r = { shown: f.style.display !== "none", value: s.value, opts: [...s.options].map((o) => o.value) }; window.closeCreateSpaceModal(); return r; });
const allowed = (page) => page.evaluate(() => ["aws", "gcp", "azure"].map((c) => VyomiBooster.cloudAllowed(c)));
try {
  let t = await open(PRO(""));
  check("Pro, no cloud yet: all three usable", JSON.stringify(await allowed(t.page)) === "[true,true,true]");
  check("Pro: first gate use pins that cloud", await t.page.evaluate(async () => await window._cloudGate("gcp", null)) === true && t.calls.includes("POST /api/account/booster/primary-cloud"), t.calls.join(","));
  check("Pro: other clouds now locked, gcp stays", JSON.stringify(await allowed(t.page)) === "[false,true,false]");
  check("Pro: gate refuses aws", await t.page.evaluate(async () => await window._cloudGate("aws", null)) === false);
  await t.ctx.close();

  t = await open(PRO("aws"));
  check("Pro, aws chosen: only aws", JSON.stringify(await allowed(t.page)) === "[true,false,false]");
  const r = await t.page.evaluate(async () => { window.openCreateSpaceModal(); document.getElementById("csm-name").value = "x-space"; const r = document.querySelector('input[name="csm-provider"][value="gcp"]'); if (r) r.checked = true; await window.submitCreateSpace(); return document.getElementById("csm-error").textContent; });
  check("Pro: creating a GCP space is refused with the Max upgrade message", /one cloud/i.test(r) && /Max/.test(r), r);
  check("Pro: no pin call when a cloud is already chosen", !t.calls.includes("POST /api/account/booster/primary-cloud"), t.calls.join(","));
  await t.ctx.close();

  t = await open(MAX);
  check("Max: all three, nothing pinned", JSON.stringify(await allowed(t.page)) === "[true,true,true]" && await t.page.evaluate(async () => await window._cloudGate("azure", null)) === true && !t.calls.includes("POST /api/account/booster/primary-cloud"));
  await t.ctx.close();

  t = await open(null);
  check("account unknown (404): not gated", JSON.stringify(await allowed(t.page)) === "[true,true,true]");
  await t.ctx.close();
} finally { await browser.close(); preview.kill(); }
console.log(bad ? `\n${bad} FAILED` : "\nall passed"); process.exit(bad ? 1 : 0);
