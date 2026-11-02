/* Nano: the bottom drawer (vyomi-appbar.js) on all three consoles — each icon opens its appliance page in a
 * modal (clouds.html?embed=1) without leaving the console; Esc/✕ close it; no appliance chrome inside; the
 * console's own back-to-spaces / api / usage links are gone; a a session opened on #spaces shows Spaces.
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
  check(`${cloud}: drawer has 5 items (no separate Default cloud)`, (await p.locator("#vy-appbar .vy-notch a[data-v]").count()) === 5);
  check(`${cloud}: old back-to-spaces/api/usage header links removed`,
    (await p.locator("header .back-spaces, header .az-back-spaces, header a[href$='#api'], header a[href$='#usage']").count()) === 0);
  const url0 = p.url();
  check(`${cloud}: drawer holds no account items; account button is in the header's top-right`, (await p.locator("#vy-appbar a[data-act], #vy-appbar a[href*='github.com']").count()) === 0 && await (async () => { const hb = await p.locator("#vy-acct-btn").boundingBox(); return !!hb && hb.y < 60 && hb.x + hb.width > p.viewportSize().width - 80; })());
  await p.click("#vy-acct-btn");
  check(`${cloud}: menu has Activate appliance + GitHub; Sign out hidden when signed out`, (await p.locator('#vy-acct-menu.open a[data-act="activate"], #vy-acct-menu.open a[data-act="upgrade"]').count()) === 1 && (await p.locator('#vy-acct-menu.open a[href="https://github.com/vyomi-cloud/appliance"]').count()) === 1 && !(await p.locator('#vy-acct-menu a[data-act="signout"]').isVisible()));
  if ((await p.locator('#vy-acct-menu a[data-act="activate"]').count()) === 1) {
    await p.click('#vy-acct-menu a[data-act="activate"]');
    let ok = false; try { await p.frameLocator("#vy-modal iframe").locator("#activate-modal.open .am-card").waitFor({ state: "visible", timeout: 45000 }); ok = true; } catch (_) {}
    check(`${cloud}: Activate opens the real activation dialog in a modal`, ok && p.url() === url0);
    await p.keyboard.press("Escape"); await sleep(250);
  } else await p.keyboard.press("Escape");
  await p.click("a.vy-co"); let lv = false; try { await p.frameLocator("#vy-modal iframe").locator("#view-spaces").waitFor({ state: "visible", timeout: 45000 }); lv = true; } catch (_) {}
  check(`${cloud}: vyomi logo opens the Spaces dialog, console not navigated`, lv && p.url() === url0, p.url());
  await p.keyboard.press("Escape"); await sleep(250);
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
// a session opened on #spaces shows Spaces
const p2 = await (await b.newContext()).newPage(); await p2.goto(base + "/clouds.html#spaces"); await sleep(4000);
check("opening #spaces shows the Spaces view", await p2.locator("#view-spaces").isVisible());
console.log(`${ok} pass / ${bad} fail`); await b.close(); server.close(); process.exit(bad ? 1 : 0);
