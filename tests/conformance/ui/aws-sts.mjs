/* AWS STS console (offline appliance): open STS, assume a role with the form
 * defaults, every grid column filled, detail tabs render, revoke the session.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-sts.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";
import { runServiceFlow } from "./service-flow.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};

const browser = await chromium.launch();
const page = await browser.newPage();
try {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await runServiceFlow(page, { service: "STS", label: "STS", listLabel: "Sessions", check });
} catch (e) {
  check(false, "STS console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
