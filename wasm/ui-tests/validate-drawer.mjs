/* Nano: the bottom drawer (vyomi-appbar.js) on all three consoles — each icon opens its appliance page in a
 * modal (clouds.html?embed=1) without leaving the console; Esc/✕ close it; no appliance chrome inside; the
 * console's own back-to-spaces / api / usage links are gone; a fresh session lands on Spaces.
 * Run: NANO_DIR=<worktree>/wasm node validate-drawer.mjs */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const b = await chromium.launch(); let ok = 0, bad = 0;
const check = (n, c, note = "") => { console.log(`[${c ? "PASS" : "FAIL"}] ${n}${c ? "" : " " + note}`); c ? ok++ : bad++; };
for (const cloud of ["aws", "gcp", "azure"]) {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 860 } }); const p = await ctx.newPage();
  const errs = []; p.on("pageerror", e => errs.push(String(e)));
  await bootConsole(p, base, `/${cloud}-console.html`);
  await p.waitForSelector("#vy-appbar .vy-notch a", { timeout: 60000 });
  check(`${cloud}: drawer has 5 appliance links`, (await p.locator("#vy-appbar .vy-notch a").count()) === 5);
  check(`${cloud}: old back-to-spaces/api/usage header links removed`,
    (await p.locator("header .back-spaces, header .az-back-spaces, header a[href$='#api'], header a[href$='#usage']").count()) === 0);
  const url0 = p.url();
  for (const v of ["spaces", "workspace", "kc", "usage", "api"]) {
    await p.click(`#vy-appbar a[data-v="${v}"]`);
    const fr = p.frameLocator("#vy-modal iframe");
    let vis = false; try { await fr.locator(`#view-${v}`).waitFor({ state: "visible", timeout: 45000 }); vis = true; } catch (_) {}
    check(`${cloud}/${v}: modal open + view visible in iframe, console not navigated`, vis && p.url() === url0);
    check(`${cloud}/${v}: no appliance chrome in modal`, !(await fr.locator("#app-sidebar").isVisible()) && !(await fr.locator(".top-bar").isVisible()));
    if (cloud === "gcp" && v === "spaces") await p.screenshot({ path: "/tmp/nano-drawer-modal.png" });
    await p.keyboard.press("Escape"); await sleep(250);
    check(`${cloud}/${v}: Esc closes`, (await p.locator("#vy-modal.open").count()) === 0);
  }
  check(`${cloud}: no page errors`, errs.filter(e => !/ResizeObserver/.test(e)).length === 0, JSON.stringify(errs.slice(0, 2)));
  await ctx.close();
}
// fresh session lands on Spaces
const p2 = await (await b.newContext()).newPage(); await p2.goto(base + "/clouds.html"); await sleep(4000);
check("fresh session: Spaces view visible", await p2.locator("#view-spaces").isVisible());
console.log(`${ok} pass / ${bad} fail`); await b.close(); server.close(); process.exit(bad ? 1 : 0);
