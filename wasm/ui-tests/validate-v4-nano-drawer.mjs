/* GENUINE Nano: the bottom drawer (wasm/vyomi-appbar.js) on the three v4 consoles (/nano/v4/<cloud>/). Retarget of the legacy validate-drawer.mjs
 * (which drove <cloud>-console.html). v4 drawer = Spaces, Health, Knowledge Center, Vyomi Labs (usage / api / account items were retired from it).
 * Each item opens its appliance page in a modal (clouds.html?embed=1) WITHOUT navigating the console, with no appliance chrome inside;
 * Esc closes; a session opened on clouds.html#spaces shows Spaces; no page errors.
 * Env: BASE (default http://127.0.0.1:8743 = `node consoles/nano_preview.mjs --port 8743`), PW_CHANNEL. */
import { chromium, sleep } from "./lib.mjs";
const BASE = process.env.BASE || "http://127.0.0.1:8743";
const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
let ok = 0, bad = 0;
const check = (n, c, note = "") => { console.log(`[${c ? "PASS" : "FAIL"}] ${n}${c ? "" : " :: " + String(note).slice(0, 200)}`); c ? ok++ : bad++; };
for (const cloud of ["aws", "gcp", "azure"]) {
  const p = await (await browser.newContext({ viewport: { width: 1440, height: 860 } })).newPage();
  const errs = []; p.on("pageerror", (e) => errs.push(String(e)));
  try {
    await p.goto(`${BASE}/nano/v4/${cloud}/`, { waitUntil: "domcontentloaded" });
    await p.waitForSelector("#vy-appbar .vy-notch a[data-v]", { timeout: 90000 });
    const items = await p.evaluate(() => [...document.querySelectorAll("#vy-appbar .vy-notch a[data-v]")].map((a) => a.getAttribute("data-v")));
    check(`${cloud}: drawer has Spaces, Health, Knowledge Center, Vyomi Labs`, JSON.stringify(items) === JSON.stringify(["spaces", "workspace", "kc", "labs"]), items.join(","));
    check(`${cloud}: usage / api items are gone from the drawer`, (await p.locator('#vy-appbar a[data-v="usage"], #vy-appbar a[data-v="api"]').count()) === 0);
    const url0 = p.url();
    for (const v of items) {
      await p.click(`#vy-appbar a[data-v="${v}"]`);
      const fr = p.frameLocator("#vy-modal iframe");
      // Spaces / Health / Knowledge Center = clouds.html views (#view-<v>); Vyomi Labs = its own page (labs/index.html) in the same modal
      let vis = false;
      if (v === "labs") { try { await p.waitForSelector("#vy-modal.open.labs iframe[src*='labs/index.html']", { timeout: 30000 }); await fr.locator("body *").first().waitFor({ state: "attached", timeout: 45000 }); vis = true; } catch (_) {} }
      else { try { await fr.locator(`#view-${v}`).waitFor({ state: "visible", timeout: 45000 }); vis = true; } catch (_) {} }
      check(`${cloud}/${v}: modal open + view visible in iframe, console not navigated`, vis && p.url() === url0, p.url());
      check(`${cloud}/${v}: no appliance chrome in modal`, !(await fr.locator("#app-sidebar").isVisible().catch(() => false)) && !(await fr.locator(".top-bar").isVisible().catch(() => false)));
      await p.keyboard.press("Escape"); await sleep(300);
      check(`${cloud}/${v}: Esc closes`, (await p.locator("#vy-modal.open").count()) === 0);
    }
    check(`${cloud}: no page errors`, errs.filter((e) => !/ResizeObserver/.test(e)).length === 0, JSON.stringify(errs.slice(0, 2)));
  } catch (e) { check(`${cloud}: run`, false, String(e).split("\n")[0]); }
  await p.context().close();
}
const p2 = await (await browser.newContext()).newPage(); await p2.goto(`${BASE}/nano/clouds.html#spaces`); await sleep(5000);
check("opening clouds.html#spaces shows the Spaces view", await p2.locator("#view-spaces").isVisible().catch(() => false));
console.log(`\n${ok}/${ok + bad} passed`); await browser.close(); process.exit(bad ? 1 : 0);
