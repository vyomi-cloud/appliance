/* Import-model pages on all three clouds (lane limconsole): Bedrock Imported models, Vertex Model Registry import, Foundry Custom models.
 *   node consoles/nano_preview.mjs --port 8841 --tier max &   BASE=http://127.0.0.1:8841 SHOTS=/tmp/limconsole/import node consoles/tests/smoke-ai-import.mjs
 * Uses the real fixture adapter (tests/conformance/fixtures/nanoimport/adapter.gguf, SmolLM2-135M r=8). A bad file is rejected with the reason.
 * By default the model generation is LIVE: the browser downloads the Q8_0 base from Hugging Face (145 MB, cached in OPFS) and wllama runs it.
 * IMPORT_LIVE=0 skips generation (registration, validation, progress UI only). Needs internet for the live part. */
import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8841", SHOTS = process.env.SHOTS || "/tmp/limconsole/import", LIVE = process.env.IMPORT_LIVE !== "0";
const FIX = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "tests", "conformance", "fixtures", "nanoimport");
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 220) : ""}`); };
const browser = await pw.chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const errs = [];
const open = async (cloud, hash) => {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errs.push(`${cloud}: ${e}`));
  await page.goto(`${BASE}/nano/v4/${cloud}/#${hash}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  return page;
};
const txt = (p) => p.locator("body").innerText();
const bad = join(SHOTS, "not-a-gguf.gguf"); writeFileSync(bad, "this is not a gguf file");
const adapter = join(FIX, "adapter.gguf"), meta = join(FIX, "adapter_meta.json");

/* ───────── AWS Bedrock: Imported models ───────── */
{
  const page = await open("aws", "/bedrock/imported-models");
  await page.getByRole("heading", { name: "Imported models" }).first().waitFor({ timeout: 90000 });
  check("AWS nav lists Imported models and the page is real (honest framing, no Coming soon)", /Coming soon/i.test(await txt(page)) === false && (await page.getByRole("link", { name: "Imported models" }).count()) > 0);
  await page.screenshot({ path: `${SHOTS}/aws-1-list.png`, fullPage: true });
  await page.getByRole("button", { name: "Import model" }).first().click();
  await page.getByLabel("Imported model name").fill("facilities-tuned");
  await page.getByTestId("adapter-input").setInputFiles(bad);
  await page.getByTestId("adapter-error").waitFor();
  check("AWS wizard rejects a non-GGUF file with the reason before any request", /not a GGUF/.test(await page.getByTestId("adapter-error").innerText()));
  await page.getByTestId("adapter-input").setInputFiles(adapter);
  await page.getByTestId("adapter-ok").waitFor();
  await page.getByTestId("meta-input").setInputFiles(meta);
  await page.screenshot({ path: `${SHOTS}/aws-2-wizard.png` });
  await page.getByRole("dialog").getByRole("button", { name: "Import model" }).click();
  await page.getByTestId("job-status").waitFor({ timeout: 60000 });
  await page.waitForFunction(() => /Completed/.test(document.querySelector('[data-testid="job-status"]')?.innerText || ""), null, { timeout: 30000 });
  check("AWS import job Completed through CreateModelImportJob (job detail page)", /Completed/.test(await page.getByTestId("job-status").innerText()) && /s3:\/\/vyomi-models\/uploads\//.test(await page.getByTestId("job-source").innerText()));
  await page.screenshot({ path: `${SHOTS}/aws-3-job.png`, fullPage: true });
  await page.getByRole("link", { name: /Open facilities-tuned/ }).click();
  await page.getByTestId("m-base").waitFor();
  check("AWS model detail shows base, rank/alpha and the honest note", /smollm2-135m-instruct/.test(await page.getByTestId("m-base").innerText()) && /8 \/ 16/.test(await page.getByTestId("m-rank").innerText()) && /Not a vendor model/i.test(await txt(page)));
  await page.screenshot({ path: `${SHOTS}/aws-4-model.png`, fullPage: true });
  if (LIVE) {
    await page.getByTestId("warm-up").click();
    await page.waitForFunction(() => /Downloading|Loading/.test(document.querySelector('[data-testid="serving-bar"]')?.innerText || ""), null, { timeout: 60000 }).catch(() => {});
    await page.screenshot({ path: `${SHOTS}/aws-5-progress.png` });
    const sawProgress = /Downloading|Loading|Ready/.test(await page.getByTestId("serving-bar").innerText());
    await page.waitForFunction(() => /Ready/.test(document.querySelector('[data-testid="serving-bar"]')?.innerText || ""), null, { timeout: 420000 });
    check("AWS in-browser engine progress (download -> load -> ready) is shown", sawProgress && /Ready/.test(await page.getByTestId("serving-bar").innerText()));
    await page.getByLabel("Prompt", { exact: true }).fill("compressor on the roof is leaking oil");
    await page.getByTestId("try-run").click();
    await page.getByTestId("try-output").waitFor({ timeout: 120000 });
    const a = (await page.getByTestId("try-output").innerText()).trim();
    check("AWS try-it: Converse on the imported ARN answers from the LoRA model", a.length > 0 && !/ModelNotReady/.test(a), a);
    await page.screenshot({ path: `${SHOTS}/aws-6-answer.png`, fullPage: true });
    // Playground
    await page.goto(`${BASE}/nano/v4/aws/#/bedrock/playground`);
    await page.getByRole("button", { name: "Select model" }).click();
    await page.getByRole("dialog").getByRole("button", { name: /Choose a model/ }).click();
    await page.getByRole("option", { name: /facilities-tuned/ }).first().click();
    await page.getByRole("button", { name: "Apply" }).click();
    await page.getByLabel("Prompt", { exact: true }).fill("tap is dripping in the 3rd floor kitchen");
    await page.getByRole("button", { name: "Run" }).click();
    await page.getByTestId("converse-output").waitFor({ timeout: 120000 });
    check("AWS playground lists the imported model and answers from it", (await page.getByTestId("converse-output").innerText()).trim().length > 0);
    await page.screenshot({ path: `${SHOTS}/aws-7-playground.png`, fullPage: true });
  }
  await page.goto(`${BASE}/nano/v4/aws/#/bedrock/imported-models`);
  await page.getByText("facilities-tuned").first().waitFor({ timeout: 30000 });
  check("AWS Models tab lists the imported model", /facilities-tuned/.test(await txt(page)));
  await page.close();
}

/* ───────── GCP Vertex: Model Registry import ───────── */
{
  const page = await open("gcp", "/vertex-ai/models");
  await page.getByRole("heading", { name: "Model Registry" }).first().waitFor({ timeout: 90000 });
  await page.screenshot({ path: `${SHOTS}/gcp-1-registry.png`, fullPage: true });
  await page.getByRole("button", { name: "Import chat model" }).click();
  await page.getByTestId("adapter-input").setInputFiles(bad);
  await page.getByTestId("adapter-error").waitFor();
  check("GCP import dialog rejects a non-GGUF with the reason", /not a GGUF/.test(await page.getByTestId("adapter-error").innerText()));
  await page.getByTestId("adapter-input").setInputFiles(adapter);
  await page.getByTestId("adapter-ok").waitFor();
  await page.getByTestId("meta-input").setInputFiles(meta);
  await page.getByLabel("Name", { exact: true }).fill("facilities-tuned-vtx");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden", timeout: 90000 }).catch(async () => { console.log("dialog still open:", (await page.getByTestId("import-error").allInnerTexts()).join(" | ")); });
  await page.getByRole("cell", { name: "facilities-tuned-vtx" }).first().waitFor({ timeout: 30000 });
  check("GCP models:upload registers the model; registry row is labelled Chat (LoRA adapter)", /Chat \(LoRA adapter\)/.test(await txt(page)));
  await page.screenshot({ path: `${SHOTS}/gcp-2-registered.png`, fullPage: true });
  await page.getByRole("button", { name: "Actions for facilities-tuned-vtx" }).click();
  await page.getByRole("menuitem", { name: "Chat with model" }).click();
  await page.getByTestId("chat-endpoint").waitFor({ timeout: 60000 });
  check("GCP chat dialog deploys the model to an endpoint on demand", /endpoints\//.test(await page.getByTestId("chat-endpoint").innerText()));
  if (LIVE) {
    await page.getByTestId("warm-up").click();
    await page.getByTestId("chat-answer").first().waitFor({ timeout: 420000 }).catch(() => {});
    await page.screenshot({ path: `${SHOTS}/gcp-3-chat-loaded.png` });
    await page.getByLabel("Message").fill("chiller alarm on level 2");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="chat-answer"]').length >= 2, null, { timeout: 120000 });
    check("GCP endpoint :generateContent answers from the imported model", /tokens/.test(await page.getByTestId("chat-answer").last().locator("xpath=..").innerText()));
    await page.screenshot({ path: `${SHOTS}/gcp-4-chat.png` });
    await page.keyboard.press("Escape");
    await page.goto(`${BASE}/nano/v4/gcp/#/vertex-ai/studio/prompt`);
    await page.getByRole("heading", { name: "Vertex AI Studio" }).first().waitFor();
    await page.getByTestId("chat-history").waitFor();
    const sel = page.locator('div[role="combobox"]').nth(1);
    await sel.click();
    check("GCP Studio chat model list includes the imported model", (await page.getByRole("option", { name: /facilities-tuned-vtx/ }).count()) > 0);
    await page.keyboard.press("Escape");
  }
  await page.close();
}

/* ───────── Azure Foundry: Custom models ───────── */
{
  const page = await open("azure", "/foundry/custommodels");
  await page.getByRole("button", { name: "Import custom model" }).first().waitFor({ timeout: 90000 });
  check("Azure menu lists Custom models; page states the Vyomi extension", /Custom models/.test(await txt(page)) && /Vyomi extension/.test(await txt(page)));
  // an Azure OpenAI resource is needed to deploy on
  await page.evaluate(async () => {
    const S = "00000000-0000-0000-0000-cloudlearn01", put = (p, b) => fetch(`/nano/_wire${p}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });
    await put(`/subscriptions/${S}/resourcegroups/aoai-rg?api-version=2021-04-01`, { location: "eastus" });
    await put(`/subscriptions/${S}/resourceGroups/aoai-rg/providers/Microsoft.CognitiveServices/accounts/aoai1?api-version=2024-10-01`, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: "aoai1" } });
  });
  await page.getByRole("button", { name: "Import custom model" }).first().click();
  await page.getByTestId("adapter-input").setInputFiles(bad);
  await page.getByTestId("adapter-error").waitFor();
  check("Azure form rejects a non-GGUF with the reason", /not a GGUF/.test(await page.getByTestId("adapter-error").innerText()));
  await page.getByTestId("adapter-input").setInputFiles(adapter);
  await page.getByTestId("adapter-ok").waitFor();
  await page.getByTestId("meta-input").setInputFiles(meta);
  await page.getByLabel("Model name").fill("facilities-tuned-az");
  await page.screenshot({ path: `${SHOTS}/azure-1-form.png`, fullPage: true });
  await page.getByRole("button", { name: "Import model" }).click();
  await page.getByText("vyomi.import.").first().waitFor({ timeout: 60000 });
  check("Azure custom model registered (POST /openai/vyomi/custom-models) and listed", /facilities-tuned-az/.test(await txt(page)));
  await page.screenshot({ path: `${SHOTS}/azure-2-registered.png`, fullPage: true });
  await page.getByTestId("deploy-chat").waitFor();
  await page.getByRole("button", { name: "Deploy", exact: true }).click();
  await page.getByTestId("deployed-as").waitFor({ timeout: 60000 });
  check("Azure custom model deployed on the OpenAI resource through ARM (format Vyomi)", /Deployed as/.test(await page.getByTestId("deployed-as").innerText()));
  if (LIVE) {
    await page.getByTestId("warm-up").click();
    await page.getByTestId("chat-answer").first().waitFor({ timeout: 420000 });
    await page.getByLabel("Message").fill("fire alarm test in lobby");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid="chat-answer"]').length >= 2, null, { timeout: 120000 });
    check("Azure chat/completions on the deployment answers from the imported model", /tokens/.test(await page.getByTestId("chat-answer").last().locator("xpath=..").innerText()));
    await page.screenshot({ path: `${SHOTS}/azure-3-chat.png`, fullPage: true });
    await page.goto(`${BASE}/nano/v4/azure/#/cognitiveservices/aoai-rg/aoai1/playground`);
    await page.getByLabel("User query").waitFor({ timeout: 60000 });
    await page.waitForTimeout(3000); await page.screenshot({ path: `${SHOTS}/azure-4-playground.png`, fullPage: true });
    check("Azure account Chat playground lists the imported deployment", (await page.getByLabel("Deployment", { exact: true }).first().innerText()).includes("facilities"));
  }
  await page.close();
}
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
