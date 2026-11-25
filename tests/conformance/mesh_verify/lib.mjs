import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
export const { chromium } = require(process.env.PW_PATH || "/Users/sudhirganti/Applications/simulator/appliance-v4nightaws/.ci-node/node_modules/playwright");
export const BASE = process.env.MESH_BASE || "http://127.0.0.1:18741";
export const SHOTS = process.env.SHOTS || "/tmp/mesh-verify-shots";
import { mkdirSync } from "node:fs"; mkdirSync(SHOTS, { recursive: true });
export const results = [];
export const check = (n, ok, d = "") => { results.push(!!ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 300) : ""}`); };
export async function open() {
  const browser = await chromium.launch({ channel: "chrome" }).catch(() => chromium.launch());
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  // The built consoles are substrate=nano (headless 4.0): they default to Nano's fixed project; a real Mesh server's project is vyomi-project.
  await ctx.addInitScript(() => { try { localStorage.setItem('vyomi.v4.gcp.project', 'vyomi-project'); } catch {} });
  const page = await ctx.newPage(); const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
  // Nano boot scripts have no meaning against the real server (it answers /_wire itself): neutralise only those.
  await page.route(/\/(nano-boot|mesh-link|nano-kernel|nano-[a-z-]+|vyomi-appbar|mesh-widget|vyomi-dl-card)\.js/, (r) => r.fulfill({ status: 200, contentType: "text/javascript", body: "" }));
  return { browser, page, errs };
}
export const done = async (browser) => { await browser.close(); const bad = results.filter((r) => !r).length; console.log(`\n${results.length - bad}/${results.length} checks passed`); process.exit(bad ? 1 : 0); };
