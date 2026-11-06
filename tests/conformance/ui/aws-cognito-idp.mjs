/* Offline console: Amazon Cognito user pools — open the service, create with defaults,
 * every column filled, detail tabs render, sub-resources, delete.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-cognito-idp.mjs
 * One [PASS]/[FAIL] line per check; exit 1 on any failure. */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { runCognitoFlow } from "./_cognito_flow.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { RAIL_SEL } = await import("../../../wasm/ui-tests/lib.mjs");
let chromium;
for (const p of ["playwright", resolve(HERE, "../../../.ci-node/node_modules/playwright")]) {
  try { ({ chromium } = require(p)); break; } catch (_) {}
}
const BASE = (process.env.VYOMI_BASE_URL || "http://localhost:9000").replace(/\/$/, "");
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
};

// start clean: leftovers from an aborted earlier run would hold the default domain prefix
for (const p of (await (await fetch(`${BASE}/api/cognito-idp/user-pools`)).json()).user_pools || []) {
  await fetch(`${BASE}/api/cognito-idp/user-pools/${p.id}`, { method: "DELETE" });
}
const browser = await chromium.launch();
const page = await browser.newPage();
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });
try {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await runCognitoFlow(page, check);
  check(bad.length === 0, "no API 5xx during the flow", bad.join(", "));
} catch (e) {
  check(false, "Cognito console flow", String(e.stack || e).split("\n").slice(0,6).join(" / "));
}
await browser.close();
console.log(fails ? `${fails} check(s) failed` : "all checks passed");
process.exit(fails ? 1 : 0);
