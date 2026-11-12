#!/usr/bin/env node
/* Visit EVERY parameter-free route a console declares (lists, create wizards, settings, config
 * pages — mapped in a spec or not), click its tabs, and run the grid/divider checks.
 *   GRID_AUDIT=out.jsonl BASE=http://127.0.0.1:8795 node consoles/tests/grid-audit.mjs gcp aws
 * Routes with :params are reached by ui-conformance.mjs's fixtures (GRID_AUDIT mode). */
import { createRequire } from "node:module";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gridAudit } from "./grid-audit-probe.mjs";

const require = createRequire(import.meta.url);
let pw; try { pw = require("playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const BASE = process.env.BASE || "http://127.0.0.1:8740";
const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : p.endsWith(".jsx") || p.endsWith(".js") ? [p] : []; });

const browser = await pw.chromium.launch();
for (const cloud of process.argv.slice(2)) {
  const routes = new Set();
  for (const f of walk(join(ROOT, cloud, "services"))) {
    for (const m of readFileSync(f, "utf8").matchAll(/pattern:\s*"(\/[^"]+)"/g)) if (!m[1].includes(":")) routes.add(m[1]);
    for (const m of readFileSync(f, "utf8").matchAll(/href:\s*"#(\/[^"?]+)"/g)) if (!m[1].includes(":") && !m[1].includes("$")) routes.add(m[1]);
  }
  const ctx = await browser.newContext({ viewport: { width: Number(process.env.GRID_AUDIT_WIDTH || 1440), height: 900 } });
  const page = await ctx.newPage();
  let views = 0;
  for (const r of [...routes].sort()) {
    await page.goto(`${BASE}/v4/${cloud}/#${r}`, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(350);
    await gridAudit(page); views++;
    const tabs = page.locator("[role=tab]");
    for (let i = 1, n = Math.min(await tabs.count(), 12); i < n; i++) {
      await tabs.nth(i).click({ timeout: 1500 }).catch(() => {});
      await page.waitForTimeout(200);
      await gridAudit(page); views++;
    }
  }
  console.log(`${cloud}: ${routes.size} routes, ${views} views`);
  await ctx.close();
}
await browser.close();
