/* Offline console: CloudWatch Logs — open the service, create with defaults,
 * every column filled, detail tabs render, delete.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-logs.mjs
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { runLogsFlow } from "./_aws_logs_flow.mjs";

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
};

const browser = await chromium.launch();
try {
  // the AWS console works against an AWS space
  const sp = await (await fetch(`${BASE}/api/spaces`)).json().catch(() => ({}));
  const sid = (sp.spaces || []).find((s) => s.provider === "aws");
  if (sid) await fetch(`${BASE}/api/spaces/${sid.space_id || sid.id}/switch`, { method: "POST" }).catch(() => {});
  const page = await browser.newPage();
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelectorAll("#rail a, #rail button, #rail li, #rail [data-service], #rail .svc, #rail .service").length > 0, null, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await runLogsFlow(page, check);
} catch (e) {
  check(false, "CloudWatch Logs console flow ran", String(e.message || e).split("\n")[0]);
}
await browser.close();
process.exit(fails ? 1 : 0);
