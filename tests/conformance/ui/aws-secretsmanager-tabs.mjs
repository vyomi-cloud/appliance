/* Offline console conformance — AWS Secrets Manager tabs (against $VYOMI_BASE_URL/console/aws).
 * Versions / Rotation / Replication / Encryption key / Resource policy show this secret's data
 * from the Secrets Manager API; a saved change is still there after reopening the tab.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-secretsmanager-tabs.mjs
 */
import { createRequire } from "node:module";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

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
  return ok;
};
const N = "ui-sm-tabs-" + Math.floor(Math.random() * 1e5);
const J = { "content-type": "application/json" };
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
try {
  const cr = await fetch(`${BASE}/api/aws/secrets`, { method: "POST", headers: J, body: JSON.stringify({ name: N, value: "v1" }) });
  check(cr.ok, "secret created", `HTTP ${cr.status}`);
  await fetch(`${BASE}/api/aws/secrets/${N}`, { method: "PUT", headers: J, body: JSON.stringify({ value: "v2" }) });
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.locator(RAIL_SEL).filter({ hasText: /Secrets Manager/ }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  await page.locator("#main table a.id, #main table td a").filter({ hasText: N }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const openTab = async (name) => {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp("^\\s*" + name + "\\s*$") }).first().click({ timeout: 5000 });
    await page.waitForTimeout(900);
    return page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText : ""; });
  };
  const real = (t) => !/This pane mirrors|Not yet wired|No policies attached/.test(t);

  let t = await openTab("Versions");
  check(real(t) && /AWSCURRENT/.test(t) && /AWSPREVIOUS/.test(t), "Versions tab shows the version staging labels", t.slice(0, 160));
  t = await openTab("Rotation");
  check(real(t) && /Disabled/.test(t), "Rotation tab shows Disabled", t.slice(0, 100));
  await page.fill("[data-testid=sm-rotation-days]", "45");
  await page.click("[data-testid=sm-rotation-toggle]");
  await page.waitForTimeout(1200);
  await openTab("Versions");
  t = await openTab("Rotation");
  check(/Enabled/.test(t) && /\b45\b/.test(t) && /SecretsManagerRotation/.test(t), "rotation on (45 days) survives re-opening", t.slice(0, 200));
  t = await openTab("Replication");
  check(real(t) && /not replicated/.test(t), "Replication tab starts empty", t.slice(0, 100));
  await page.selectOption("[data-testid=sm-replica-region]", "eu-west-1");
  await page.click("[data-testid=sm-replica-add]");
  await page.waitForTimeout(1200);
  await openTab("Versions");
  t = await openTab("Replication");
  check(/eu-west-1/.test(t) && /InSync/.test(t), "replica Region survives re-opening", t.slice(0, 160));
  t = await openTab("Encryption key");
  check(real(t) && /alias\/aws\/secretsmanager/.test(t), "Encryption key tab shows the default key", t.slice(0, 120));
  await page.fill("[data-testid=sm-kms-key]", "alias/my-key");
  await page.click("[data-testid=sm-kms-save]");
  await page.waitForTimeout(1200);
  await openTab("Versions");
  t = await openTab("Encryption key");
  check(/alias\/my-key/.test(t), "saved encryption key survives re-opening", t.slice(0, 120));
  t = await openTab("Resource policy");
  check(real(t) && /No resource policy/.test(t), "Resource policy tab starts empty", t.slice(0, 120));
  const pol = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { AWS: "arn:aws:iam::000000000000:root" }, Action: "secretsmanager:GetSecretValue", Resource: "*" }] });
  await page.fill("[data-testid=sm-policy]", pol);
  await page.click("[data-testid=sm-policy-save]");
  await page.waitForTimeout(1200);
  await openTab("Versions");
  t = await openTab("Resource policy");
  check(/A resource policy is attached/.test(t) && /GetSecretValue/.test(await page.inputValue("[data-testid=sm-policy]")), "saved resource policy survives re-opening", t.slice(0, 160));
} catch (e) {
  check(false, "flow completed", String(e).slice(0, 300));
} finally {
  await fetch(`${BASE}/api/aws/secrets/${N}`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
