// Captures REAL screenshots of the v4 consoles for every Labs setup step (never mock-ups).
// usage: node capture_steps.mjs <baseUrl serving wasm/> [cloud ...]   needs playwright + system Chrome
import { createRequire } from "node:module";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright");
const here = dirname(fileURLToPath(import.meta.url)), labs = join(here, "..", "..", "wasm", "labs");
const base = process.argv[2] || "http://127.0.0.1:8770", clouds = process.argv.slice(3).length ? process.argv.slice(3) : ["aws", "gcp", "azure"];
mkdirSync(join(labs, "img", "steps"), { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch({ channel: "chrome", headless: true });
for (const cloud of clouds) {
  const course = JSON.parse(readFileSync(join(labs, "data", cloud + ".json"), "utf8"));
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.goto(`${base}/v4/${cloud}/`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker?.controller && document.body.innerText.length > 200, null, { timeout: 180000, polling: 500 });
  await page.addStyleTag({ content: "#vy-appbar,#vy-modal,#vy-mesh-drawer,.vy-appbar,.vy-modal{display:none!important}" }).catch(() => {});
  for (const l of course.layers) for (const st of l.setup || []) {
    if (!st.route) continue;
    const out = join(labs, "img", "steps", `${cloud}-${l.id}-${st.n}.jpg`);
    try {
      await page.evaluate((r) => { location.hash = r; }, st.route);
      const ready = () => page.waitForFunction(() => document.body.innerText.length > 250 && !/Loading/i.test(document.body.innerText.slice(0, 4000)), null, { timeout: 12000, polling: 300 }).catch(() => {});
      await sleep(1500); await ready();
      if (st.click) { try { await page.getByRole("button", { name: /^(\+ )?(create|new|deploy|add)\b/i }).first().click({ timeout: 2500 }); await sleep(1500); await ready(); } catch (_) {} }
      const filled = [];
      for (const [label, value] of Object.entries(st.fill || {})) {
        const tries = [() => page.getByLabel(label, { exact: false }).first(), () => page.getByRole("textbox", { name: label }).first(),
          () => page.locator(`xpath=(//*[self::label or self::span or self::div or self::h4][normalize-space(text())="${label}"]/following::input[not(@type="radio") and not(@type="checkbox")])[1]`)];
        for (const t of tries) { try { await t().fill(value, { timeout: 1200 }); filled.push(label); break; } catch (_) {} }
      }
      await sleep(400);
      if ((await page.evaluate(() => document.body.innerText.length)) < 250) { await page.evaluate((r) => { location.hash = "#/"; setTimeout(() => { location.hash = r; }, 300); }, st.route); await sleep(4000); await ready(); }
      await page.screenshot({ path: out, type: "jpeg", quality: 72, clip: { x: 0, y: 0, width: 1440, height: 812 } });
      console.log(`ok   ${cloud} ${l.id}.${st.n} ${st.route} filled=[${filled.join(",")}]`);
    } catch (e) { console.log(`FAIL ${cloud} ${l.id}.${st.n} ${st.route}: ${String(e.message).slice(0, 90)}`); }
  }
  await page.context().close();
}
await browser.close();
