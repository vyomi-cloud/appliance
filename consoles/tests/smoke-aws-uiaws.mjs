/* Bedrock Build/Assess/Configure pages (guardrails, prompt management, flows, evaluations, model access, settings, prompt optimization,
 * not-in-scope panels) in a browser on the Nano preview. A stub in-browser model is registered (vyomiRegisterLLM) so model calls answer.
 *   node consoles/nano_preview.mjs --port 8791 --tier pro &   BASE=http://127.0.0.1:8791 SHOTS=/tmp/shots node consoles/tests/smoke-aws-uiaws.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8791", SHOTS = process.env.SHOTS || "/tmp/uiaws-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const go = async (p, h) => { await page.goto(`${BASE}/nano/v4/aws/#/bedrock/${p}`); await page.getByRole("heading", { name: h }).first().waitFor({ timeout: 120000 }); };
const modal = () => page.locator('[role="dialog"]');
const body = () => page.locator("body").innerText();
const pickModel = async (scope, text) => { await scope.getByRole("button", { name: /Choose a model|Model/ }).first().click(); await page.getByRole("option", { name: new RegExp(text) }).first().click(); };

await go("guardrails", "Guardrails");
await page.getByText("No guardrails").waitFor({ timeout: 180000 });
await page.evaluate(() => window.vyomiRegisterLLM({ model: "ui-stub", chat: async (r) => JSON.stringify({ text: "STUB ANSWER: " + (JSON.parse(r).messages.slice(-1)[0].content || "").slice(0, 40), input_tokens: 5, output_tokens: 6 }) }));
check("guardrails: empty state", true); await shot("g1-empty");
await page.getByRole("button", { name: "Create guardrail" }).first().click();
await modal().getByLabel("Name", { exact: true }).fill("ui-guard");
await modal().getByRole("button", { name: /INSULTS strength/ }).click(); await page.getByRole("option", { name: "High" }).click();
await modal().getByRole("tab", { name: "Sensitive information" }).click();
await modal().getByRole("button", { name: /PII types|Choose PII/ }).first().click(); await page.getByRole("option", { name: "EMAIL", exact: true }).click(); await page.keyboard.press("Escape");
await modal().getByRole("button", { name: "Create guardrail" }).click();
await page.getByText("Guardrail overview").waitFor({ timeout: 30000 });
check("guardrails: created and detail opened", /ui-guard/.test(await body())); await shot("g2-detail");
await page.getByPlaceholder("Enter text to test against the guardrail").fill("you are an idiot, mail me at a@b.com");
await page.getByRole("button", { name: "Test guardrail" }).click();
await page.getByTestId("guardrail-result").waitFor({ timeout: 30000 });
const gr = await page.getByTestId("guardrail-result").innerText();
check("guardrails: test panel intervenes (ApplyGuardrail)", /intervened/i.test(gr), gr); await shot("g3-test");
await page.getByRole("button", { name: "Create version" }).click(); await page.getByText("Version 1 created").waitFor({ timeout: 20000 });
check("guardrails: version created", true);

await go("prompt-management", "Prompt management");
await page.getByText("No prompts").waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Create prompt" }).first().click();
await modal().getByLabel("Prompt name").fill("ui-prompt");
await modal().getByRole("button", { name: "Create prompt" }).last().click();
await page.getByText("Prompt overview").waitFor({ timeout: 30000 });
await page.getByRole("button", { name: /Choose a model/ }).first().click(); await page.getByRole("option").first().click();
await page.getByRole("textbox", { name: "audience" }).fill("ops"); await page.getByRole("textbox", { name: "body" }).fill("Pump 3 is leaking");
await page.getByRole("button", { name: "Run", exact: true }).click();
await page.getByTestId("prompt-output").waitFor({ timeout: 60000 });
check("prompts: draft runs through Converse", /STUB ANSWER/.test(await page.getByTestId("prompt-output").innerText())); await shot("p1-detail");
await page.getByRole("button", { name: "Create version" }).click(); await page.getByText("Version 1 created").waitFor({ timeout: 20000 });
check("prompts: version created", true);

await go("flows", "Flows");
await page.getByText("No flows").waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Create flow" }).first().click();
await modal().getByLabel("Flow name").fill("ui-flow");
await modal().getByRole("button", { name: "Create flow" }).last().click();
await page.getByText("Flow overview").waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Prepare" }).click(); await page.getByText("Flow prepared").waitFor({ timeout: 20000 });
await page.getByPlaceholder("Text sent to the input node").fill("hello flow");
await page.getByRole("button", { name: "Run", exact: true }).click();
await page.getByTestId("flow-result").waitFor({ timeout: 60000 });
check("flows: prepared flow runs through InvokeFlow", /STUB ANSWER/.test(await page.getByTestId("flow-result").innerText()) && /SUCCESS/.test(await page.getByTestId("flow-result").innerText())); await shot("f1-detail");

// dataset for the evaluation, written through the S3 wire like any client
await page.evaluate(async () => {
  const h = { Authorization: "AWS4-HMAC-SHA256 Credential=AKIAFAKE/20250101/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=0", "x-amz-date": "20250101T000000Z" };
  const w = location.pathname.split("/v4/")[0] + "/_wire";
  await fetch(`${w}/uievalb`, { method: "PUT", headers: h });
  await fetch(`${w}/uievalb/ds.jsonl`, { method: "PUT", headers: h, body: '{"prompt":"say hi","referenceResponse":"STUB ANSWER say hi","category":"c"}\n{"prompt":"other","referenceResponse":"nope"}\n' });
});
await go("evaluations", "Model evaluations");
await page.getByText("No evaluation jobs").waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Create", exact: true }).first().click();
await modal().getByLabel("Evaluation name").fill("ui-eval");
await modal().getByRole("button", { name: /Choose a model/ }).first().click(); await page.getByRole("option").first().click();
await modal().getByLabel("Prompt dataset (S3 JSONL)").fill("s3://uievalb/ds.jsonl");
await modal().getByLabel("Evaluation results (S3 location)").fill("s3://uievalb/out/");
await modal().getByRole("button", { name: "Create", exact: true }).last().click();
await page.getByText("Evaluation summary").waitFor({ timeout: 90000 });
await page.getByText("Metric summary").waitFor({ timeout: 30000 });
const ev = await body();
check("evaluations: job completed with scored metrics", /Completed/.test(ev) && /Accuracy/.test(ev) && /custom-dataset/.test(ev)); await shot("e1-detail");

await go("model-access", "Model access");
await page.getByText("Access granted").first().waitFor({ timeout: 60000 });
check("model access: models show access granted", (await page.getByText("Access granted").count()) > 3); await shot("m1-access");

await go("settings", "Settings");
await page.getByText("Logging is off").waitFor({ timeout: 30000 });
await page.getByLabel("Amazon S3").check({ force: true }).catch(async () => { await page.getByText("Amazon S3", { exact: true }).click(); });
await page.getByLabel("S3 bucket name").fill("uievalb");
await page.getByRole("button", { name: "Save settings" }).click();
await page.getByText("Logging is on").waitFor({ timeout: 30000 });
check("settings: invocation logging saved", true); await shot("s1-settings");

await go("prompt-optimization", "Advanced prompt optimization");
await page.getByRole("button", { name: /Choose a model/ }).first().click(); await page.getByRole("option").first().click();
await page.getByPlaceholder("Write the prompt to improve").fill("tell me about {{topic}}");
// a usable model reply (keeps the user's {{topic}}) is shown as the optimized prompt
await page.evaluate(() => window.vyomiRegisterLLM({ model: "ui-stub", chat: async () => JSON.stringify({ text: "STUB ANSWER: You are an expert. Explain {{topic}} in three clear bullet points.", input_tokens: 1, output_tokens: 1 }) }));
await page.getByRole("button", { name: "Optimize" }).click();
await page.getByTestId("optimized").waitFor({ timeout: 60000 });
check("prompt optimization: returns optimized prompt", /STUB ANSWER/.test(await page.getByTestId("optimized").innerText())); await shot("o1");
// regression (owner symptom): a tiny model that loops '{{input}}{{output}}' must never reach the result; a rule-based rewrite + note is shown instead
await page.evaluate(() => window.vyomiRegisterLLM({ model: "ui-loop", chat: async () => JSON.stringify({ text: "{{input}}{{output}}".repeat(60), input_tokens: 1, output_tokens: 1 }) }));
await page.getByRole("button", { name: "Optimize" }).click();
await page.getByTestId("optimize-note").waitFor({ timeout: 60000 });
const ot = await page.getByTestId("optimized").innerText();
check("prompt optimization: looping '{{input}}{{output}}' reply never shown, user's {{topic}} kept, honest note", !/\{\{(input|output)\}\}/.test(ot) && /\{\{topic\}\}/.test(ot) && /rule-based/.test(await page.getByTestId("optimize-note").innerText()), ot); await shot("o2-loop");

for (const [h, t] of [["automated-reasoning", "Automated Reasoning"], ["data-automation", "Data Automation"]]) {
  await go(h, t); const b = await body();
  check(`${t}: explicit not-in-scope panel (no Coming soon)`, /Not in scope/.test(b) && !/Coming soon/.test(b)); await shot(`n-${h}`);
}
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
const bad = results.filter((x) => !x).length; console.log(`${results.length - bad}/${results.length} passed`); process.exit(bad ? 1 : 0);
