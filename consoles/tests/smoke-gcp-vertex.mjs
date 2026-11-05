/* Vertex AI Studio (GCP lens): UI <-> native publisher-model wire. Needs the local LLM stub (see smoke-aws-bedrock.mjs).
 *   BASE=http://127.0.0.1:9071 node consoles/tests/smoke-gcp-vertex.mjs
 */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9071";
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
await page.goto(`${BASE}${process.env.UI_PATH || "/v4/gcp/"}#/vertex-ai`);
await page.getByRole("button", { name: "Submit" }).waitFor({ timeout: process.env.NANO === "1" ? 240000 : 30000 });
if (process.env.NANO === "1") {   // Nano answers only through a WebLLM model the page registers (none in headless): the stub-driven checks below need the offline local-LLM seam
  check("Vertex AI Studio renders on Nano (no local-LLM stub: answer checks are offline-only)", true);
  await browser.close();
  process.exit(0);
}
await page.getByRole("button", { name: "Submit" }).click();
await page.getByTestId("gemini-output").waitFor({ timeout: 15000 });
check("generateContent answer shown", /STUB ANSWER/.test(await page.getByTestId("gemini-output").innerText()));
check("token usage shown", /input \/ .* output tokens; countTokens: \d+/.test(await page.locator("body").innerText()));
await page.getByRole("button", { name: "Embed" }).click();
await page.getByTestId("embedding-dim").waitFor({ timeout: 10000 });
check("embedContent returns a vector", /\d+ dimensions/.test(await page.getByTestId("embedding-dim").innerText()));
await page.getByLabel("Message").fill("hello chat");
await page.getByRole("button", { name: "Send" }).click();
await page.waitForFunction(() => /STUB ANSWER/.test(document.querySelector('[data-testid="chat-history"]')?.innerText || ""), null, { timeout: 15000 });
await page.getByLabel("Message").fill("second turn");
await page.getByRole("button", { name: "Send" }).click();
await page.waitForFunction(() => (document.querySelector('[data-testid="chat-history"]')?.innerText.match(/STUB ANSWER/g) || []).length >= 2, null, { timeout: 15000 });
check("multi-turn chat keeps history", /hello chat/.test(await page.getByTestId("chat-history").innerText()) && /second turn/.test(await page.getByTestId("chat-history").innerText()));
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
