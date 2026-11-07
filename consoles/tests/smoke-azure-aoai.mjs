/* Azure OpenAI chat playground (Cognitive Services account blade): UI <-> ARM + /openai data plane.
 *   BASE=http://127.0.0.1:9071 node consoles/tests/smoke-azure-aoai.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9071";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const NANO = process.env.NANO === "1";
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await page.goto(UI);
if (NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await page.waitForTimeout(1500);
const put = (p, b) => page.evaluate(async ([u, p, b]) => { const r = await fetch(u + p, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) }); return r.status; }, [WIRE, p, b]);
const S = "00000000-0000-0000-0000-cloudlearn01";
await put(`/subscriptions/${S}/resourcegroups/aoai-rg?api-version=2021-04-01`, { location: "eastus" });
const a = await put(`/subscriptions/${S}/resourceGroups/aoai-rg/providers/Microsoft.CognitiveServices/accounts/aoai1?api-version=2024-10-01`, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: "aoai1" } });
const d = await put(`/subscriptions/${S}/resourceGroups/aoai-rg/providers/Microsoft.CognitiveServices/accounts/aoai1/deployments/chat?api-version=2024-10-01`, { sku: { name: "Standard", capacity: 10 }, properties: { model: { format: "Alibaba", name: "qwen2.5-3b", version: "1" } } });
check("seed account + deployment", a < 300 && d < 300, `${a}/${d}`);
await page.goto(`${UI}#/cognitiveservices/aoai-rg/aoai1/playground`);
await page.getByLabel("User query").waitFor({ timeout: 30000 });
await page.waitForTimeout(800);
if (NANO && process.env.FAKE_LLM) {   // exercise the Nano bridge end to end with a stand-in browser model (headless has no WebGPU)
  await page.evaluate(() => window.vyomiRegisterLLM({ model: "fake-webllm", chat: async (req) => JSON.stringify({ text: "STUB ANSWER from the in-browser model", input_tokens: 3, output_tokens: 6, finish_reason: "stop" }) }));
}
await page.getByLabel("User query").fill("hello model");
await page.getByRole("button", { name: "Send" }).click();
if (NANO && !process.env.FAKE_LLM) {
  // Nano has no model until the page registers WebLLM: the honest result is a not-ready error, never a canned answer.
  await page.waitForTimeout(4000);
  const t = await page.locator("body").innerText();
  check("Nano: no in-browser model -> honest not-ready state, no canned answer", !/STUB ANSWER/.test(t) && /model|not ready|ModelNotReady|WebLLM/i.test(t));
  check("no page errors", errs.length === 0, errs[0]);
  await browser.close();
  process.exit(results.every(Boolean) ? 0 : 1);
}
await page.getByText(/Assistant:.*STUB ANSWER/).waitFor({ timeout: 15000 });
check("chat/completions answer shown with usage", /tokens\)/.test(await page.getByTestId("aoai-chat").innerText()));
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
