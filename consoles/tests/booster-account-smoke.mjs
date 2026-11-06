/* Account flow: the portal's booster record decides backend vs browser. Faked /api/account/booster (route) against the Nano preview.
 *   not enabled  -> no booster option (no Create Space modal in the portal-Nano flow) (everything stays in the browser)
 *   enabled      -> picker offers the booster and PRESELECTS it (backend)
 *   toggle       -> dialog Turn off / Turn on call POST /disable | /enable and the picker follows
 *   unknown (404, e.g. preview/offline) -> unchanged: a paired booster is offered
 *   PW=<playwright path> node consoles/tests/booster-account-smoke.mjs     Exit 1 on any FAIL. */
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
const EN = { enabled: true, effective: true, status: "trial", source: "trial", tier: "pro", days_left: 14, trial_used: true, locked: false };
const OFF = { enabled: false, effective: false, status: "none", source: "", tier: "", days_left: null, trial_used: false, locked: false };
async function open(acc) {
  const ctx = await browser.newContext(); const page = await ctx.newPage(); const calls = []; let cur = acc;
  await ctx.addInitScript(() => { try { localStorage.setItem("vyomi.boosters", JSON.stringify([{ id: "bst-demo", name: "lab", paired_at: 1, base: "http://127.0.0.1:1", token: "t" }])); } catch {} });
  await page.route("**/api/account/booster**", async (route) => {
    const u = new URL(route.request().url()), m = route.request().method(); calls.push(m + " " + u.pathname);
    if (cur === null) return route.fulfill({ status: 404, body: "no" });
    if (m === "POST" && u.pathname.endsWith("/enable")) cur = { ...EN };
    if (m === "POST" && u.pathname.endsWith("/disable")) cur = { ...cur, enabled: false, effective: false };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(cur) });
  });
  await page.goto(`${NANO}/clouds.html`);
  await page.waitForFunction(() => !!window.VyomiBooster && !!navigator.serviceWorker.controller, null, { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
  await page.waitForFunction(() => !!window.VyomiBooster, null, { timeout: 60000 });
  await page.waitForTimeout(800);
  return { ctx, page, calls };
}
const picker = (page) => page.evaluate(() => { const o = VyomiBooster.homeOptions(); return { shown: o.length > 0, value: VyomiBooster.defaultHome(), opts: ["browser"].concat(o.map((x) => x.id)) }; });   // portal-Nano flow: no Create Space modal; the account decides where spaces/compute live
try {
  let t = await open({ ...OFF });
  check("not enabled: no booster option, browser only", await t.page.evaluate(() => VyomiBooster.homeOptions().length === 0) && !(await picker(t.page)).shown);
  await t.ctx.close();

  t = await open({ ...EN });
  const p = await picker(t.page);
  check("enabled: picker shows the booster and preselects it (backend)", p.shown && p.opts.includes("bst-demo") && p.value === "bst-demo", JSON.stringify(p));
  check("create payload targets the booster", await t.page.evaluate(() => VyomiBooster.homePayload("bst-demo").type === "booster"));
  await t.ctx.close();

  t = await open({ ...EN, enabled: true, effective: false, status: "expired", locked: true });
  check("enabled but trial expired: no booster option, locked flag set", await t.page.evaluate(() => VyomiBooster.homeOptions().length === 0 && VyomiBooster.account().locked === true));
  await t.ctx.close();

  t = await open(null);
  const u = await picker(t.page);
  check("account unknown (404): unchanged, paired booster still offered, browser default", u.shown && u.opts.includes("bst-demo") && u.value === "browser", JSON.stringify(u));
  await t.ctx.close();

  t = await open({ ...OFF });
  await t.page.evaluate(() => { document.documentElement.classList.remove("vy-entering", "vy-pickopen"); VyomiBooster.openPairDialog(); });   // clouds.html hides the page while it auto-enters / shows its cloud picker
  check("dialog shows booster off + Turn on", /Booster:\s*off/i.test(await t.page.innerText("#vyb-acc")) && /Turn on/.test(await t.page.innerText("#vyb-acc-btn")));
  await t.page.click("#vyb-acc-btn"); await t.page.waitForFunction(() => /Turn off/.test((document.getElementById("vyb-acc-btn") || {}).textContent || ""), null, { timeout: 8000 }).catch(() => {});
  check("Turn on -> POST /enable, dialog says on", t.calls.includes("POST /api/account/booster/enable") && /Booster:\s*on/i.test(await t.page.innerText("#vyb-acc")), t.calls.join(","));
  check("picker now offers + preselects the booster", (await picker(t.page)).value === "bst-demo");
  await t.page.click("#vyb-acc-btn"); await t.page.waitForFunction(() => /Turn on/.test((document.getElementById("vyb-acc-btn") || {}).textContent || ""), null, { timeout: 8000 }).catch(() => {});
  check("Turn off -> POST /disable, back to browser only", t.calls.includes("POST /api/account/booster/disable") && !(await picker(t.page)).shown);
  await t.ctx.close();
} catch (e) { bad++; console.log("FAIL harness - " + (e && e.stack || e)); }
finally { await browser.close(); preview.kill(); }
console.log(bad ? `${bad} FAILED` : "ALL PASS"); process.exit(bad ? 1 : 0);
