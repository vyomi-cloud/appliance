/* Offline console conformance — S3 bucket configuration tabs ($VYOMI_BASE_URL/console/aws).
 *
 * For one bucket: Versions, Bucket Versioning, Default encryption, Block Public Access,
 * Bucket Policy, CORS, Lifecycle rules and Event notifications each show the bucket's real
 * setting (no placeholder text), accept an edit, and the edit survives a page reload and is
 * visible through the S3 wire API.
 *
 *   VYOMI_BASE_URL=http://localhost:9000 node tests/conformance/ui/aws-s3-config.mjs
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
const BUCKET = "s3cfg-ui-" + Date.now().toString(36);
let fails = 0;
const check = (ok, what, detail = "") => {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${what}${!ok && detail ? ` :: ${detail}` : ""}`);
  if (!ok) fails++;
  return ok;
};
const POLICY = JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: "*", Action: "s3:GetObject", Resource: `arn:aws:s3:::${BUCKET}/*` }] });

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("dialog", (d) => d.accept().catch(() => {}));
const bad = [];
page.on("response", (r) => { if (r.status() >= 500 && r.url().includes("/api/")) bad.push(`${r.status()} ${r.url().replace(BASE, "")}`); });

async function openBucket() {
  await page.goto(`${BASE}/console/aws`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction((s) => document.querySelectorAll(s).length > 0, RAIL_SEL, { timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.locator(RAIL_SEL).filter({ hasText: /S3\s*$/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1500);
  await page.locator("#main a.id", { hasText: BUCKET }).first().click({ timeout: 8000 });
  await page.waitForTimeout(1500);
}
async function tab(label) {
  await page.locator("#main .top-tabs button").filter({ hasText: label }).first().click({ timeout: 5000 });
  await page.waitForTimeout(1200);
}
const main = () => page.locator("#main").innerText();

try {
  await fetch(`${BASE}/api/s3/buckets/${BUCKET}`, { method: "POST" });
  await openBucket();

  // placeholder + empty-state sweep over every tab touched below
  for (const t of ["Versions", "Bucket Versioning", "Event notifications", "Lifecycle rules", "Default encryption", "Block Public Access", "Bucket Policy", "Cross-origin resource sharing"]) {
    await tab(t);
    const txt = await main();
    check(!/This pane mirrors|Not yet wired|placeholder/i.test(txt), `${t}: no placeholder text`);
    check(txt.includes(BUCKET), `${t}: shows this bucket`);
  }

  // Default encryption: SSE-S3 by default, switch to KMS and save
  await tab("Default encryption");
  check(/AES256|SSE-S3/.test(await page.locator("#main select").first().evaluate((s) => s.value + s.selectedOptions[0].text)), "encryption defaults to SSE-S3");
  await page.locator("#main select").first().selectOption("aws:kms");
  await page.locator("#main input[placeholder^='arn:aws:kms']").fill("alias/my-key");
  await page.locator("#main button", { hasText: "Save changes" }).click();
  await page.waitForTimeout(800);

  // Block Public Access: uncheck all four, save
  await tab("Block Public Access");
  for (const k of ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"]) {
    check(await page.locator(`[data-testid=bpa-${k}]`).isChecked(), `new bucket blocks public access (${k})`);
    await page.locator(`[data-testid=bpa-${k}]`).uncheck();
  }
  await page.locator("#main button", { hasText: "Save changes" }).click();
  await page.waitForTimeout(800);

  // Bucket policy
  await tab("Bucket Policy");
  await page.locator("[data-testid=bucket-policy]").fill(POLICY);
  await page.locator("#main button", { hasText: "Save changes" }).click();
  await page.waitForTimeout(800);

  // CORS rule
  await tab("Cross-origin resource sharing");
  await page.locator("[data-testid=cors-origins]").fill("https://example.com");
  await page.locator("[data-testid=cors-methods]").fill("GET, PUT");
  await page.locator("#main button", { hasText: "Add rule" }).click();
  await page.waitForTimeout(800);

  // Lifecycle rule
  await tab("Lifecycle rules");
  await page.locator("[data-testid=lifecycle-id]").fill("expire-logs");
  await page.locator("[data-testid=lifecycle-prefix]").fill("logs/");
  await page.locator("[data-testid=lifecycle-edays]").fill("30");
  await page.locator("#main button", { hasText: "Create rule" }).click();
  await page.waitForTimeout(800);

  // Event notification
  await tab("Event notifications");
  await page.locator("[data-testid=notification-id]").fill("on-upload");
  await page.locator("[data-testid=notification-dest]").fill("arn:aws:sqs:us-east-1:123456789012:my-queue");
  await page.locator("#main button", { hasText: "Create event notification" }).click();
  await page.waitForTimeout(800);

  // Versioning
  await tab("Bucket Versioning");
  await page.locator("#main button", { hasText: "Enable versioning" }).click();
  await page.waitForTimeout(1000);

  // ---- reload: everything must have persisted
  await openBucket();
  await tab("Default encryption");
  check((await page.locator("#main select").first().inputValue()) === "aws:kms", "encryption survives reload (SSE-KMS)");
  check((await page.locator("#main input[placeholder^='arn:aws:kms']").inputValue()) === "alias/my-key", "KMS key survives reload");
  await tab("Block Public Access");
  check(!(await page.locator("[data-testid=bpa-BlockPublicAcls]").isChecked()), "Block Public Access edit survives reload");
  await tab("Bucket Policy");
  check((await page.locator("[data-testid=bucket-policy]").inputValue()).includes("s3:GetObject"), "bucket policy survives reload");
  await tab("Cross-origin resource sharing");
  check(/https:\/\/example\.com/.test(await main()) && /GET, PUT/.test(await main()), "CORS rule survives reload");
  await tab("Lifecycle rules");
  check(/expire-logs/.test(await main()) && /logs\//.test(await main()), "lifecycle rule survives reload");
  await tab("Event notifications");
  check(/on-upload/.test(await main()) && /my-queue/.test(await main()), "event notification survives reload");
  await tab("Bucket Versioning");
  check((await page.locator("[data-testid=versioning-status]").innerText()).trim() === "Enabled", "versioning survives reload");

  // ---- the same settings through the S3 wire API
  const get = async (q) => (await fetch(`${BASE}/${BUCKET}?${q}`)).text();
  check((await get("encryption")).includes("aws:kms"), "wire GetBucketEncryption returns the console edit");
  check((await get("policy")).includes("s3:GetObject"), "wire GetBucketPolicy returns the console edit");
  check((await get("cors")).includes("https://example.com"), "wire GetBucketCors returns the console edit");
  check((await get("lifecycle")).includes("expire-logs"), "wire GetBucketLifecycle returns the console edit");
  check((await get("publicAccessBlock")).includes("<BlockPublicAcls>false"), "wire GetPublicAccessBlock returns the console edit");

  check(!bad.length, "no API 5xx while using the tabs", bad.join(", "));
} catch (e) {
  check(false, "S3 config flow ran to completion", String(e).split("\n")[0]);
} finally {
  await fetch(`${BASE}/api/s3/buckets/${BUCKET}?force=1`, { method: "DELETE" }).catch(() => {});
  await browser.close();
}
process.exit(fails ? 1 : 0);
