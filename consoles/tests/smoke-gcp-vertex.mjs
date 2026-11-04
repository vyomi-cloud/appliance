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
await page.goto(`${BASE}/v4/gcp/#/vertex-ai`);
await page.getByRole("button", { name: "Submit" }).waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Submit" }).click();
await page.getByTestId("gemini-output").waitFor({ timeout: 15000 });
check("generateContent answer shown", /STUB ANSWER/.test(await page.getByTestId("gemini-output").innerText()));
check("token usage shown", /input \/ .* output tokens; countTokens: \d+/.test(await page.locator("body").innerText()));
await page.getByRole("button", { name: "Embed" }).click();
await page.getByTestId("embedding-dim").waitFor({ timeout: 10000 });
check("embedContent returns a vector", /\d+ dimensions/.test(await page.getByTestId("embedding-dim").innerText()));
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
