/* Azure OpenAI Chat playground against the local-LLM seam.  Needs consoles/tests/fake_llm.py (see its header):
 *   python3 consoles/tests/fake_llm.py 9076 & VYOMI_LLM_ENDPOINT=http://127.0.0.1:9076 python3 consoles/dev_server.py -q --port 9075 &
 *   BASE=http://127.0.0.1:9075 node consoles/tests/smoke-azure-openaichat.mjs      (without the endpoint the honest 503 is asserted instead: NO_LLM=1) */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9075";
const UI = `${BASE}${process.env.UI_PATH || "/v4/azure/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const n = Date.now() % 100000;
const RG = `oai-rg${n}`, AC = `oai${n}`;
let bad = 0;
const check = (name, ok, d = "") => { if (!ok) bad++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.goto(UI, { waitUntil: "networkidle" });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const arm = (m, p, b, av = "2024-10-01") => wire(`/subscriptions/${SUB}${p}?api-version=${av}`, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
await arm("PUT", `/resourceGroups/${RG}`, { location: "eastus" }, "2021-04-01");
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${AC}`, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: AC } });
await arm("PUT", `/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/${AC}/deployments/gpt4o`, { sku: { name: "Standard", capacity: 10 }, properties: { model: { format: "OpenAI", name: "gpt-4o", version: "2024-08-06" } } });
await page.goto(UI + `#/cognitiveservices/${RG}/${AC}/playground`);
await page.getByRole("textbox", { name: "Type user query here" }).waitFor({ timeout: 20000 });
await page.getByRole("combobox", { name: "Deployment" }).locator("option", { hasText: "gpt4o" }).waitFor({ state: "attached", timeout: 10000 });
await page.getByRole("textbox", { name: "Type user query here" }).fill("hello vyomi");
await page.getByRole("button", { name: "Send" }).click();
if (process.env.NO_LLM) {
  await page.getByText(/not reachable|No local LLM|ServiceUnavailable/i).first().waitFor({ timeout: 15000 });
  check("with no model running the playground reports the real 503 (no canned answer)", true);
} else {
  await page.getByText("pong: hello vyomi").waitFor({ timeout: 20000 });
  check("assistant answer comes from the LLM seam", true);
  check("token usage shown", /Tokens: 7 in, 3 out, 10 total/.test(await page.getByTestId("chat-usage").innerText()));
}
check("no page errors", errors.length === 0, errors.join("|"));
await browser.close();
process.exit(bad ? 1 : 0);
