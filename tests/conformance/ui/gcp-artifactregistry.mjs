/* GCP Artifact Registry console (offline appliance): open the service, create a
 * repository with the wizard defaults, every grid column filled, detail tabs render
 * (including Images after a sample push), delete.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/gcp-artifactregistry.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { RAIL_SEL } from "../../../wasm/ui-tests/lib.mjs";
import { runGcpServiceFlow } from "./gcp-service-flow.mjs";

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
  await page.goto(`${BASE}/console/gcp`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await runGcpServiceFlow(page, {
    service: "Artifact Registry", label: "Artifact Registry", check,
    pushAction: { tab: "Images", button: /Push sample image/ },
  });
} catch (e) {
  check(false, "Artifact Registry console flow", String(e.message || e).split("\n")[0]);
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
