/* Offline console conformance — AWS KMS key tabs (against $VYOMI_BASE_URL/console/aws).
 * Aliases / Key rotation / Key policy / Key users / Key administrators / Grants show this key's
 * data from the KMS API and a saved change is still there after reopening the tab.
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-kms-tabs.mjs
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
const ALIAS = "ui-kms-" + Math.floor(Math.random() * 1e5);
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
let keyId = "";
try {
  const cr = await (await fetch(`${BASE}/api/aws/kms/keys`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: ALIAS, description: "ui test" }) })).json();
  keyId = cr.key_id;
  check(!!keyId, "key created", JSON.stringify(cr));
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.locator(RAIL_SEL).filter({ hasText: /KMS/ }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  await page.locator("#main table a.id, #main table td a").filter({ hasText: keyId }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1500);
  const openTab = async (name) => {
    await page.locator("#main .top-tabs button").filter({ hasText: new RegExp("^\\s*" + name + "\\s*$") }).first().click({ timeout: 5000 });
    await page.waitForTimeout(900);
    return page.evaluate(() => { const s = document.querySelector("#main .top-tabs"); const n = s && s.nextElementSibling; return n ? n.innerText : ""; });
  };
  const real = (t) => !/This pane mirrors|Not yet wired|No policies attached/.test(t);

  let t = await openTab("Aliases");
  check(real(t) && t.includes("alias/" + ALIAS), "Aliases tab lists the key's alias", t.slice(0, 120));
  await page.fill("[data-testid=kms-alias-name]", "second-" + ALIAS);
  await page.click("[data-testid=kms-alias-add]");
  await page.waitForTimeout(1000);
  await openTab("Grants");
  t = await openTab("Aliases");
  check(t.includes("alias/second-" + ALIAS), "added alias survives re-opening the tab", t.slice(0, 160));

  t = await openTab("Key rotation");
  check(real(t) && /Disabled/.test(t), "Key rotation tab shows Disabled", t.slice(0, 100));
  await page.click("[data-testid=kms-rotation-toggle]");
  await page.waitForTimeout(1000);
  await openTab("Grants");
  t = await openTab("Key rotation");
  check(/Enabled/.test(t) && /365/.test(t), "rotation enabled (365 days) survives re-opening", t.slice(0, 120));

  t = await openTab("Key policy");
  check(real(t) && (await page.inputValue("[data-testid=kms-policy]")).includes("kms:*"), "Key policy tab shows the key's policy document");
  t = await openTab("Key users");
  check(real(t) && /No key users/.test(t), "Key users tab starts empty", t.slice(0, 100));
  await page.fill("[data-testid=kms-principal-arn]", "arn:aws:iam::000000000000:user/alice");
  await page.click("[data-testid=kms-principal-add]");
  await page.waitForTimeout(1000);
  await openTab("Grants");
  t = await openTab("Key users");
  check(t.includes("user/alice"), "added key user survives re-opening (stored in the key policy)", t.slice(0, 160));
  t = await openTab("Key administrators");
  check(real(t) && !t.includes("user/alice"), "Key administrators tab is separate from key users", t.slice(0, 120));

  t = await openTab("Grants");
  check(real(t) && /no grants/.test(t), "Grants tab starts empty", t.slice(0, 100));
  await page.click("[data-testid=kms-grant-add]");
  await page.waitForTimeout(1000);
  await openTab("Aliases");
  t = await openTab("Grants");
  check(/Encrypt, Decrypt/.test(t) && /role\/app/.test(t), "created grant survives re-opening", t.slice(0, 160));
  await page.click("[data-testid=kms-grant-revoke]");
  await page.waitForTimeout(1000);
  t = await openTab("Grants");
  check(/no grants/.test(t), "revoked grant is gone", t.slice(0, 100));
} catch (e) {
  check(false, "flow completed", String(e).slice(0, 300));
} finally {
  if (keyId) await fetch(`${BASE}/api/aws/kms/keys/${keyId}`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
