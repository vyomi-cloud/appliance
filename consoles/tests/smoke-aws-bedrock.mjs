/* Amazon Bedrock console: model catalog + Chat playground (Converse) on the local-LLM seam. Needs consoles/tests/fake_llm.py (see its header);
 * NO_LLM=1 asserts the honest ModelNotReady error instead.   BASE=http://127.0.0.1:9075 node consoles/tests/smoke-aws-bedrock.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9075";
const UI = `${BASE}${process.env.UI_PATH || "/v4/aws/"}`;
let bad = 0;
const check = (n, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI + "#/bedrock");
await page.getByText("Claude Sonnet 4").first().waitFor({ timeout: 20000 });
check("model catalog lists the foundation models", await page.getByText("Titan Text Embeddings V2").first().isVisible());
await page.goto(UI + "#/bedrock/playground");
await page.getByRole("textbox", { name: "Write a prompt" }).waitFor({ timeout: 20000 });
await page.getByRole("textbox", { name: "Write a prompt" }).fill("hello bedrock");
await page.getByRole("button", { name: "Run" }).click();
if (process.env.NO_LLM) {
  await page.getByText(/ModelNotReady|not been started|not reachable/i).first().waitFor({ timeout: 15000 });
  check("no model running -> the real ModelNotReady error (no canned answer)", true);
} else {
  await page.getByText("pong: hello bedrock").waitFor({ timeout: 20000 });
  check("Converse answer comes from the LLM seam", true);
  check("usage + latency shown", /Input tokens \d+, output tokens \d+/.test(await page.getByTestId("bedrock-usage").innerText()));
}
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
