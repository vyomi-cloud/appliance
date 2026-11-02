/* Offline: the bottom drawer (static/vyomi-appbar.js) on a cloud console. Each icon opens its appliance page in
 * a modal (clouds?embed=1) without leaving the console; Esc/✕ close it; no appliance chrome inside the modal;
 * the console's own back-to-spaces/api/usage links are gone; opening a space from the modal navigates the
 * window to that cloud's console; a fresh browser session lands on Spaces.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/drawer/drawer_modal.mjs aws|gcp|azure
 * Needs at least one space (any default install has one). Nano twin: wasm/ui-tests/validate-drawer.mjs. */
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
const CLOUD = process.argv[2];
if (!["aws", "gcp", "azure"].includes(CLOUD)) { console.error("usage: drawer_modal.mjs aws|gcp|azure"); process.exit(2); }
let fails = 0;
const check = (ok, what, detail = "") => { console.log(`[${ok ? "PASS" : "FAIL"}] ${CLOUD} drawer: ${what}${!ok && detail ? ` :: ${detail}` : ""}`); if (!ok) fails++; };
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 1440, height: 860 } })).newPage();
const errs = []; p.on("pageerror", e => errs.push(String(e)));
await p.goto(`${BASE}/console/${CLOUD}`); await p.waitForSelector("#vy-appbar .vy-notch a", { timeout: 30000 });
check((await p.locator("#vy-appbar .vy-notch a").count()) === 5, "five appliance links in the drawer");
check((await p.locator("header .back-spaces, header .az-back-spaces, header a[href$='#api'], header a[href$='#usage']").count()) === 0, "old back-to-spaces/api/usage header links are gone");
const url0 = p.url();
for (const v of ["spaces", "workspace", "kc", "usage", "api"]) {
  await p.click(`#vy-appbar a[data-v="${v}"]`);
  const fr = p.frameLocator("#vy-modal iframe");
  let vis = false; try { await fr.locator(`#view-${v}`).waitFor({ state: "visible", timeout: 20000 }); vis = true; } catch (_) {}
  check(vis && p.url() === url0, `${v}: opens in a modal, console not navigated`);
  check(!(await fr.locator("#app-sidebar").isVisible()) && !(await fr.locator(".top-bar").isVisible()), `${v}: no appliance chrome inside the modal`);
  await p.keyboard.press("Escape"); await p.waitForTimeout(200);
  check((await p.locator("#vy-modal.open").count()) === 0, `${v}: Esc closes the modal`);
}
await p.click('#vy-appbar a[data-v="spaces"]');
const fr = p.frameLocator("#vy-modal iframe");
await fr.locator("#spaces-grid .space-card").first().waitFor({ timeout: 20000 });
await fr.locator("#spaces-grid .space-card").first().click(); await p.waitForTimeout(3000);
check(/\/console\/(aws|gcp|azure)/.test(p.url()), "opening a space from the modal navigates to a cloud console", p.url());
const p2 = await (await b.newContext()).newPage(); await p2.goto(`${BASE}/ui`); await p2.waitForTimeout(1500);
check((await p2.evaluate(() => location.hash)) === "#spaces", "a fresh browser session lands on Spaces");
check(errs.length === 0, "no page errors", errs.slice(0, 2).join(" | "));
await b.close(); process.exit(fails ? 1 : 0);
