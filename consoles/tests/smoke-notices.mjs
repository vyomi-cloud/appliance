/* Notices & licences + model licence chips on the Nano preview, all three clouds.
 *   node consoles/nano_preview.mjs --port 8861 --tier max &   BASE=http://127.0.0.1:8861 SHOTS=/tmp/notices node consoles/tests/smoke-notices.mjs
 * ENGINEERING DRAFT labelling is asserted too (no legal-advice claim). Screenshots go to $SHOTS. */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8861", SHOTS = process.env.SHOTS || "/tmp/notices";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 240) : ""}`); };
const browser = await pw.chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const errs = [];
const open = async (cloud, hash) => {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errs.push(`${cloud}: ${e}`));
  await page.goto(`${BASE}/nano/v4/${cloud}/#${hash}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  return page;
};
const txt = (p) => p.locator("body").innerText();

async function noticesPage(page, cloud) {
  await page.getByTestId("notices-page").waitFor({ timeout: 60000 });
  const t = await txt(page);
  check(`${cloud}: Notices page shows the engineering-draft banner`, /ENGINEERING DRAFT/.test(t) && /not legal advice/i.test(t));
  check(`${cloud}: disclaimer names non-affiliation and API-compatibility use`, /not affiliated with AWS, Google, Microsoft, Meta, Anthropic or OpenAI/.test(t) && /only to describe API compatibility/.test(t));
  const hrefs = await page.locator('[data-testid="notices-page"] a').evaluateAll((as) => as.map((a) => a.href));
  check(`${cloud}: Gemma prohibited-use link and Llama AUP links are present`, hrefs.some((h) => /ai\.google\.dev\/gemma\/prohibited_use_policy/.test(h)) && hrefs.some((h) => /llama3_1\/USE_POLICY/.test(h)) && hrefs.some((h) => /llama3_2\/USE_POLICY/.test(h)));
  check(`${cloud}: Built with Llama and verbatim Llama/Gemma/Qwen notices render`, /Built with Llama/.test(t) && t.includes("Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights Reserved.")
    && t.includes("Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms") && t.includes("Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT"));
  check(`${cloud}: Qwen2.5 3B shows the non-commercial flag`, /Non-commercial research licence: not for paid use/.test(await page.getByTestId("notices-models").innerText()));
  check(`${cloud}: software list includes MinIO (AGPL) and the vendored cedar-wasm`, /MinIO/.test(await page.getByTestId("notices-components").innerText()) && /cedar-wasm/.test(await page.getByTestId("notices-components").innerText()));
}

/* ───────── AWS ───────── */
{
  const page = await open("aws", "/bedrock/models");
  await page.getByTestId("licence-chip").first().waitFor({ timeout: 90000 });
  const chips = await page.getByTestId("licence-name").allInnerTexts();
  check("AWS Bedrock Model catalog: every row has a licence chip", chips.length >= 5 && chips.every((c) => c.trim().length > 0), chips.join(", "));
  check("AWS Bedrock Model catalog: Llama row shows 'Built with Llama'", (await page.getByTestId("built-with-llama").count()) >= 1);
  check("AWS Bedrock Model catalog says models are not AWS or Amazon models", /not AWS or Amazon models/.test(await txt(page)));
  await page.screenshot({ path: `${SHOTS}/aws-1-models.png`, fullPage: true });
  await page.locator("#vyomi-help-toggle").click();
  await page.getByTestId("help-notices-link").click();
  await noticesPage(page, "AWS");
  await page.screenshot({ path: `${SHOTS}/aws-2-notices.png`, fullPage: true });
  await page.close();
}
/* ───────── GCP ───────── */
{
  const page = await open("gcp", "/vertex-ai/model-garden");
  await page.getByTestId("garden-card").first().waitFor({ timeout: 90000 });
  await page.getByTestId("licence-chip").first().waitFor({ timeout: 30000 });
  const n = await page.getByTestId("garden-card").count();
  check("GCP Model Garden: every model card has a licence chip", (await page.locator('[data-testid="garden-card"] [data-testid="licence-chip"]').count()) === n && n >= 4, `${n} cards`);
  check("GCP Model Garden: Llama card shows 'Built with Llama'", (await page.getByTestId("built-with-llama").count()) >= 1);
  await page.screenshot({ path: `${SHOTS}/gcp-1-garden.png`, fullPage: true });
  await page.getByLabel("More options").click();
  await page.getByTestId("more-notices-link").click();
  await noticesPage(page, "GCP");
  await page.screenshot({ path: `${SHOTS}/gcp-2-notices.png`, fullPage: true });
  await page.close();
}
/* ───────── Azure ───────── */
{
  const page = await open("azure", "/foundry");
  await page.getByTestId("foundry-overview").waitFor({ timeout: 90000 });
  await page.locator(".vy-fdy-models").getByTestId("licence-chip").first().waitFor({ timeout: 30000 });
  const n = await page.locator(".vy-fdy-models > div").count();
  check("Azure Foundry model list: every model tile has a licence chip", (await page.locator(".vy-fdy-models > div [data-testid=licence-chip]").count()) === n && n >= 3, `${n} tiles`);
  check("Azure Foundry model list: Llama tile shows 'Built with Llama'", (await page.locator(".vy-fdy-models").getByTestId("built-with-llama").count()) >= 1);
  await page.screenshot({ path: `${SHOTS}/azure-1-foundry.png`, fullPage: true });
  await page.getByLabel("Help + support").click();
  await page.getByTestId("help-notices-link").click();
  await noticesPage(page, "Azure");
  await page.screenshot({ path: `${SHOTS}/azure-2-notices.png`, fullPage: true });
  await page.close();
}
check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();
const fail = results.filter((r) => !r).length;
console.log(`\n${results.length - fail} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
