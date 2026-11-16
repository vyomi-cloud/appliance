/* Foundry Agents tool toggles (code_interpreter, file_search, vector stores, citations, run steps) on the Nano preview.   BASE=http://127.0.0.1:8841 SHOTS=/tmp/foundry-agents-shots node consoles/tests/smoke-ai-foundry-agents.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8841", SHOTS = process.env.SHOTS || "/tmp/foundry-agents-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 220) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
await page.goto(`${BASE}/nano/v4/azure/#/foundry/agents`);
await page.getByRole("button", { name: "New agent" }).waitFor({ timeout: 120000 });
// an OpenAI account + deployment through ARM (what the console's own create flows send)
const put = (p, b) => page.evaluate(async ([p, b]) => { const base = location.pathname.split("/v4/")[0] + "/_wire"; const r = await fetch(base + p, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(b) }); return r.status; }, [p, b]);
const S = "/subscriptions/00000000-0000-0000-0000-cloudlearn01";

await put(`${S}/resourcegroups/rg1?api-version=2021-04-01`, { location: "eastus" });
const a = await put(`${S}/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1?api-version=2024-10-01`, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: "oai1" } });
const d = await put(`${S}/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/oai1/deployments/chat?api-version=2024-10-01`, { sku: { name: "Standard", capacity: 1 }, properties: { model: { format: "OpenAI", name: "gpt-4o", version: "2024-11-20" } } });
check("account + deployment created through ARM", a < 300 && d < 300, `${a} ${d}`);
await page.reload();
await page.getByRole("button", { name: "New agent" }).waitFor({ timeout: 60000 });
check("Agents page carries the Dev Simplified badge from the registry", (await page.locator('[data-vyomi-capability-id="azure.foundry.agents"]').count()) >= 1);
await page.getByRole("button", { name: "New agent" }).click();
await page.getByLabel("Agent name").fill("facilities-bot");
await page.getByLabel("Instructions").fill("Answer from the documents. Use code to compute.");
await page.getByLabel("Code interpreter", { exact: true }).check().catch(async () => page.getByText("Code interpreter", { exact: true }).click());
await page.getByText("File search", { exact: true }).click();
await page.getByLabel("New vector store name").fill("facilities-vs");
await page.getByLabel("File search files").setInputFiles("/tmp/limconsole/fixt/facilities.txt");
await shot("1-new-agent-toggles");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByRole("table", { name: "Agents" }).getByText("facilities-bot").waitFor({ timeout: 60000 });
const badges = await page.getByTestId("agent-tools").first().innerText();
check("agent row shows both tools as badges", /Code interpreter/i.test(badges) && /File search/i.test(badges), badges);
await page.getByRole("tab", { name: "Vector stores" }).click();
await page.getByRole("table", { name: "Vector stores" }).getByText("facilities-vs").waitFor({ timeout: 30000 });
await page.getByRole("table", { name: "Vector stores" }).getByText("facilities-vs").click();
await page.getByTestId("vector-store-files").waitFor({ timeout: 30000 });
await page.getByTestId("vector-store-files").getByText(/completed/).first().waitFor({ timeout: 90000 }).catch(() => {});
const vsTxt = await page.getByTestId("vector-store-files").innerText();
check("the file was uploaded, parsed and embedded into the vector store (status completed)", /completed/.test(vsTxt), vsTxt.replace(/\s+/g, " "));
await shot("2-vector-store");
await page.getByRole("tab", { name: "Agents" }).click();
await page.getByRole("table", { name: "Agents" }).getByText("facilities-bot").click();
await page.getByLabel("Message").fill("When does the cafeteria close? Also compute 17*3 with code.");
await page.getByLabel("Message").press("Enter");
const done = page.getByTestId("rich-message").first().or(page.getByText(/Run (failed|cancelled|expired)/).first());
await done.waitFor({ timeout: 180000 }).catch(() => {});
await shot("3-agent-run");
const chat = await page.getByTestId("agent-chat").innerText();
const answered = (await page.getByTestId("rich-message").count()) >= 2;
if (answered) {
  check("answer carries file_citation sources from the vector store", (await page.getByTestId("citations").count()) >= 1, chat.slice(-300));
  check("run steps list the tool calls", (await page.getByTestId("run-steps").count()) === 1);
} else {
  // headless Nano has no local model: the honest outcome is the native model-unavailable error, never a canned answer
  check("no model running: the run failure is shown honestly (no fabricated answer)", /Run failed|ServiceUnavailable|model/i.test(chat), chat.slice(-240));
}
check("no page errors", errs.length === 0, errs.join("|"));
console.log(`${results.filter(Boolean).length}/${results.length} passed`);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
