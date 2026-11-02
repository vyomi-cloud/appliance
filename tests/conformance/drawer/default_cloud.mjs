/* Offline: the first-visit "default space" dialog, and the star on Spaces cards.
 *   first visit  -> forced, OPAQUE dialog on /ui (nothing of the page behind it; no close/Esc; Continue disabled until chosen)
 *   after a pick -> the browser remembers the space and /ui opens straight into its cloud's console
 *   drawer       -> no separate "Default cloud" item: Spaces is the only way to switch; a star there picks the default
 *   #spaces etc. -> an explicit view is not redirected (classic page still reachable)
 *   stale default-> a default space that no longer exists brings the dialog back
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
const KEY = () => p.evaluate(() => localStorage.getItem("vyomi.defaultSpace"));
// 1. first visit: forced, opaque dialog
await p.goto(`${BASE}/ui`); await dlg().waitFor({ timeout: 20000 });
check(await dlg().isVisible(), "first visit shows the dialog");
await p.waitForSelector("#vy-pick .news .opt", { timeout: 10000 });
check((await p.locator("#vy-pick .news .opt").count()) === 3, "three 'new space' options (AWS / Google Cloud / Azure)");
check((await p.locator("#vy-pick .cancel, #vy-pick .ft button:not(.go)").count()) === 0, "no Cancel button");
check(await p.locator("#vy-pick .go").isDisabled(), "Continue is disabled until a space is chosen");
const covered = await p.evaluate(() => {
  const top = document.elementFromPoint(8, 8), grid = document.getElementById("spaces-grid");
  const bg = getComputedStyle(document.getElementById("vy-pick")).backgroundColor;
  return { topIsDialog: !!top && !!top.closest("#vy-pick"), gridHidden: !grid || getComputedStyle(grid).visibility === "hidden", opaque: !/rgba\(.*,\s*0?\.\d+\)/.test(bg), bg };
});
check(covered.topIsDialog && covered.gridHidden && covered.opaque, "the old Spaces page is not visible behind the dialog", JSON.stringify(covered));
await p.keyboard.press("Escape"); await p.mouse.click(8, 8); await p.waitForTimeout(300);
check(await dlg().isVisible(), "Esc and a backdrop click do not close it");
// 2. pick an existing GCP space as the default
check((await p.locator('#vy-pick .opt[data-s][data-c="gcp"]').count()) >= 1, "existing spaces are listed to pick from");
await p.click('#vy-pick .opt[data-s][data-c="gcp"]');
check(!(await p.locator("#vy-pick .go").isDisabled()), "choosing enables Continue");
await p.click("#vy-pick .go"); await p.waitForURL(/\/console\/gcp/, { timeout: 30000 });
check(/\/console\/gcp/.test(p.url()), "Continue opens that space's console", p.url());
const gcpId = await KEY();
const spaces = async () => (await (await p.request.get(`${BASE}/api/spaces`)).json());
let d = await spaces();
check(!!gcpId && (d.spaces || []).some(s => s.space_id === gcpId && /gcp/i.test(s.provider || s.provider_id || "")), "the default is the chosen GCP space's id", gcpId);
// 3. later visit: straight in
const p2 = await ctx.newPage(); await p2.goto(`${BASE}/ui`); await p2.waitForURL(/\/console\/gcp/, { timeout: 30000 });
check(/\/console\/gcp/.test(p2.url()) && (await p2.locator("#vy-pick").count()) === 0, "a later visit goes straight to the default space, no dialog", p2.url());
await p2.close();
// 4. explicit view is not redirected
const p3 = await ctx.newPage(); await p3.goto(`${BASE}/ui#spaces`); await p3.waitForTimeout(2500);
check(/\/clouds/.test(p3.url()) && (await p3.locator("#vy-pick").count()) === 0, "/ui#spaces still opens the classic Spaces page", p3.url());
await p3.close();
// 5. drawer: Spaces is the only switcher; the star makes another space the default
await p.waitForSelector("#vy-appbar .vy-notch a");
check((await p.locator('#vy-appbar a[data-v="default"]').count()) === 0, "no separate 'Default cloud' item in the drawer");
const azId = ((await spaces()).spaces || []).filter(s => /azure/i.test(s.provider || s.provider_id || ""))[0].space_id;
await p.click('#vy-appbar a[data-v="spaces"]');
const fr = p.frameLocator("#vy-modal iframe");
await fr.locator(`[data-star="${azId}"]`).waitFor({ timeout: 20000 });
check((await fr.locator(".space-star.on").count()) === 1 && (await fr.locator(`[data-star="${gcpId}"].on`).count()) === 1, "exactly one starred (default) space - the GCP one");
await fr.locator(`[data-star="${azId}"]`).click(); await p.waitForTimeout(800);
check((await KEY()) === azId && /\/console\/gcp/.test(p.url()), "starring another space makes it the default without navigating", p.url());
check((await fr.locator(".space-star.on").count()) === 1 && (await fr.locator(`[data-star="${azId}"].on`).count()) === 1, "the star moved - still exactly one default");
const p4 = await ctx.newPage(); await p4.goto(`${BASE}/ui`); await p4.waitForURL(/\/console\/azure/, { timeout: 30000 });
check(/\/console\/azure/.test(p4.url()), "the next visit opens the newly starred space", p4.url());
await p4.close();
// 6. a default that no longer exists -> dialog again
await p.evaluate(() => localStorage.setItem("vyomi.defaultSpace", "space-does-not-exist"));
const p5 = await ctx.newPage(); await p5.goto(`${BASE}/ui`); await p5.locator("#vy-pick").waitFor({ timeout: 20000 });
check(/\/clouds|\/ui/.test(p5.url()) && (await p5.locator("#vy-pick .go").isDisabled()), "a stale default brings the dialog back", p5.url());
check(errs.length === 0, "no page errors", errs.slice(0, 2).join(" | "));
await b.close(); process.exit(fails ? 1 : 0);
