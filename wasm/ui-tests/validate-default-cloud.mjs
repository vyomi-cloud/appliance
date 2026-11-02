/* Nano: first launch shows the forced "default cloud" dialog on clouds.html; after a pick the browser remembers
 * it and clouds.html opens straight into that cloud's console; an explicit #spaces view isn't redirected; the
 * drawer's "Default cloud" item reopens the dialog (dismissible) and changes it.
 * Run: NANO_DIR=<worktree>/wasm node validate-default-cloud.mjs */
import { startServer, bootConsole, chromium, sleep } from "./lib.mjs";
const { server, base } = await startServer();
const b = await chromium.launch(); let ok = 0, bad = 0;
const check = (n, c, note = "") => { console.log(`[${c ? "PASS" : "FAIL"}] ${n}${c ? "" : " " + note}`); c ? ok++ : bad++; };
const ctx = await b.newContext({ viewport: { width: 1440, height: 860 } });
const p = await ctx.newPage(); const errs = []; p.on("pageerror", e => errs.push(String(e)));
await p.goto(base + "/clouds.html"); await p.waitForSelector("#vy-pick .tile", { timeout: 60000 });
check("first launch shows the dialog with 3 tiles", (await p.locator("#vy-pick .tile").count()) === 3);
check("no Cancel when forced; Continue disabled", (await p.locator("#vy-pick .cancel").count()) === 0 && await p.locator("#vy-pick .go").isDisabled());
await p.keyboard.press("Escape"); await p.mouse.click(8, 8); await sleep(300);
check("Esc / backdrop do not close it", await p.locator("#vy-pick").isVisible());
await p.click('#vy-pick .tile[data-c="gcp"]'); await p.click("#vy-pick .go");
await p.waitForURL(/gcp-console\.html/, { timeout: 60000 });
check("Continue opens the GCP console", /gcp-console\.html/.test(p.url()), p.url());
check("default remembered", (await p.evaluate(() => localStorage.getItem("vyomi.defaultCloud"))) === "gcp");
const p2 = await ctx.newPage(); await p2.goto(base + "/clouds.html"); await p2.waitForURL(/gcp-console\.html/, { timeout: 60000 });
check("a later launch goes straight to the default cloud", /gcp-console\.html/.test(p2.url()) && (await p2.locator("#vy-pick").count()) === 0, p2.url());
const p3 = await ctx.newPage(); await p3.goto(base + "/clouds.html#spaces"); await sleep(3000);
check("clouds.html#spaces is not redirected", /clouds\.html/.test(p3.url()) && (await p3.locator("#vy-pick").count()) === 0, p3.url());
await p.waitForSelector("#vy-appbar .vy-notch a", { timeout: 60000 }); await p.click('#vy-appbar a[data-v="default"]'); await p.waitForSelector("#vy-pick .tile");
check("drawer: dialog is cancellable and badges the current default", (await p.locator("#vy-pick .cancel").count()) === 1 && (await p.locator('#vy-pick .tile[data-c="gcp"] .badge').count()) === 1);
await p.keyboard.press("Escape"); await sleep(200);
check("drawer: Esc closes it", (await p.locator("#vy-pick").count()) === 0);
await p.click('#vy-appbar a[data-v="default"]'); await p.waitForSelector("#vy-pick .tile");
await p.click('#vy-pick .tile[data-c="azure"]'); await p.click("#vy-pick .go"); await p.waitForURL(/azure-console\.html/, { timeout: 60000 });
check("changing the default opens that cloud and saves it", /azure-console\.html/.test(p.url()) && (await p.evaluate(() => localStorage.getItem("vyomi.defaultCloud"))) === "azure", p.url());
check("no page errors", errs.filter(e => !/ResizeObserver/.test(e)).length === 0, JSON.stringify(errs.slice(0, 2)));
console.log(`${ok} pass / ${bad} fail`); await b.close(); server.close(); process.exit(bad ? 1 : 0);
