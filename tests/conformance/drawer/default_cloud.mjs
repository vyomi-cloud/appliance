/* Offline: the first-visit "default cloud" dialog and the drawer's "Default cloud" item.
 *   first visit  -> forced dialog on /ui (no close, no Esc, Continue disabled until a cloud is picked)
 *   after a pick -> the browser remembers it and /ui opens straight into that cloud's console
 *   #spaces etc. -> an explicit view is not redirected (classic page still reachable)
 *   drawer       -> "Default cloud" reopens the dialog (dismissible), shows the current default, changes it
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/drawer/default_cloud.mjs
 * Nano twin: wasm/ui-tests/validate-default-cloud.mjs. */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
let fails = 0;
const check = (ok, what, detail = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] default-cloud: ${what}${!ok && detail ? ` :: ${detail}` : ""}`); if (!ok) fails++; };
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 860 } });
const p = await ctx.newPage(); const errs = []; p.on("pageerror", e => errs.push(String(e)));
const dlg = () => p.locator("#vy-pick");
// 1. first visit: forced dialog
await p.goto(`${BASE}/ui`); await dlg().waitFor({ timeout: 20000 });
check(await dlg().isVisible(), "first visit shows the dialog");
await p.waitForSelector("#vy-pick .tile", { timeout: 10000 });
check((await p.locator("#vy-pick .tile").count()) === 3, "three cloud tiles");
check((await p.locator("#vy-pick .cancel").count()) === 0, "no Cancel button when forced");
check(await p.locator("#vy-pick .go").isDisabled(), "Continue is disabled until a cloud is chosen");
await p.keyboard.press("Escape"); await p.mouse.click(8, 8); await p.waitForTimeout(300);
check(await dlg().isVisible(), "Esc and a backdrop click do not close it");
// 2. choose GCP
await p.click('#vy-pick .tile[data-c="gcp"]');
check(!(await p.locator("#vy-pick .go").isDisabled()), "choosing a cloud enables Continue");
await p.click("#vy-pick .go"); await p.waitForURL(/\/console\/gcp/, { timeout: 30000 });
check(/\/console\/gcp/.test(p.url()), "Continue opens that cloud's console", p.url());
check((await p.evaluate(() => localStorage.getItem("vyomi.defaultCloud"))) === "gcp", "the default is remembered");
// 3. later visit: straight in
const p2 = await ctx.newPage(); await p2.goto(`${BASE}/ui`); await p2.waitForURL(/\/console\/gcp/, { timeout: 30000 });
check(/\/console\/gcp/.test(p2.url()) && (await p2.locator("#vy-pick").count()) === 0, "a later visit goes straight to the default cloud, no dialog", p2.url());
// 4. explicit view is not redirected
const p3 = await ctx.newPage(); await p3.goto(`${BASE}/ui#spaces`); await p3.waitForTimeout(2500);
check(/\/clouds/.test(p3.url()) && (await p3.locator("#vy-pick").count()) === 0, "/ui#spaces still opens the classic Spaces page", p3.url());
// 5. drawer: change the default
await p.waitForSelector("#vy-appbar .vy-notch a"); await p.click('#vy-appbar a[data-v="default"]'); await p.waitForSelector("#vy-pick .tile");
check((await p.locator("#vy-pick .cancel").count()) === 1, "from the drawer the dialog can be cancelled");
check((await p.locator('#vy-pick .tile[data-c="gcp"] .badge').count()) === 1, "the current default is badged");
await p.keyboard.press("Escape"); await p.waitForTimeout(200);
check((await dlg().count()) === 0, "Esc closes it when it is not forced");
await p.click('#vy-appbar a[data-v="default"]'); await p.waitForSelector("#vy-pick .tile");
await p.click('#vy-pick .tile[data-c="azure"]'); await p.click("#vy-pick .go"); await p.waitForURL(/\/console\/azure/, { timeout: 30000 });
check(/\/console\/azure/.test(p.url()) && (await p.evaluate(() => localStorage.getItem("vyomi.defaultCloud"))) === "azure", "changing the default opens that cloud and saves it", p.url());
check(errs.length === 0, "no page errors", errs.slice(0, 2).join(" | "));
await b.close(); process.exit(fails ? 1 : 0);
