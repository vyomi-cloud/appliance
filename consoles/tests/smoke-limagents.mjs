/* Bedrock Agents detail page (action groups incl. built-in CodeInterpreter/UserInput, multi-agent collaboration, advanced prompts, test panel with trace toggle)
 * in a browser on the Nano preview.
 *   node consoles/nano_preview.mjs --port 8771 --tier pro &   BASE=http://127.0.0.1:8771 SHOTS=/tmp/shots node consoles/tests/smoke-limagents.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8771", SHOTS = process.env.SHOTS || "/tmp/limagents-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const modal = () => page.locator('[role="dialog"]');
const agentName = "ui-sup-" + Date.now().toString(36), otherName = "ui-col-" + Date.now().toString(36);

async function createAgent(name) {
  await page.goto(`${BASE}/nano/v4/aws/#/bedrock/agents`);
  await page.getByRole("button", { name: "Create agent" }).first().waitFor({ timeout: 300000 });   // Pyodide boot
  await page.getByRole("button", { name: "Create agent" }).first().click();
  await modal().getByLabel("Agent name").fill(name);
  await modal().getByRole("button", { name: "Create" }).last().click();
  await page.getByRole("heading", { name }).first().waitFor({ timeout: 60000 });
}
await createAgent(otherName);
await createAgent(agentName);
check("agent detail shows action groups, collaboration and prompts sections", (await page.getByText("Action groups").count()) > 0 && (await page.getByText("Multi-agent collaboration").count()) > 0 && (await page.getByText("Advanced prompts").count()) > 0);

for (const [label, text] of [["Code interpreter", "CodeInterpreterAction"], ["Ask the user", "UserInputAction"]]) {
  await page.getByRole("button", { name: "Add action group" }).first().click();
  await modal().getByLabel("Action group name").fill(text);
  await modal().getByRole("button", { name: /Action group type/ }).click();
  await page.getByRole("option", { name: new RegExp(label) }).first().click();
  await modal().getByRole("button", { name: "Add" }).last().click();
  await page.getByText(text).first().waitFor({ timeout: 30000 });
  check(`built-in action group ${text} added and listed`, true);
}
await shot("agent-action-groups");

await page.getByRole("button", { name: /Collaboration mode/ }).click();
await page.getByRole("option", { name: "Supervisor with routing" }).click();
await page.getByText("Add collaborator").first().waitFor({ timeout: 30000 });
check("choosing a supervisor mode reveals the collaborator editor", true);
await page.getByRole("button", { name: /Collaborator agent/ }).click();
await page.getByRole("option", { name: otherName }).first().click();
await page.getByRole("button", { name: /Agent alias/ }).click();
await page.getByRole("option", { name: /TSTALIASID/ }).first().click();
await page.getByLabel("Collaborator name").fill("helper");
await page.getByLabel("Collaboration instruction").fill("Handles side questions");
await page.getByRole("button", { name: "Add collaborator" }).click();
await page.getByText("Handles side questions").first().waitFor({ timeout: 30000 }).catch(async (e) => { await shot("fail-collab"); console.log((await page.locator("[role=alert],.awsui_flash").allInnerTexts()).join(" | ")); throw e; });
check("collaborator associated through AssociateAgentCollaborator and listed", true);
await shot("agent-collaboration");

await page.getByText("Advanced prompts").first().click();
await page.getByLabel("Prompt override JSON").waitFor();
await page.getByRole("button", { name: "Save" }).first().click();
await page.getByText("Prompt configuration saved").first().waitFor({ timeout: 30000 });
check("prompt override saved and validated by the backend", true);

await page.getByRole("button", { name: "Prepare" }).first().click();
await page.getByText("Agent prepared").first().waitFor({ timeout: 30000 });
await page.getByLabel("Message").fill("hello");
await page.getByRole("button", { name: "Send" }).click();
await page.getByTestId("chat").getByText(/Error:|Agent:/).first().waitFor({ timeout: 120000 }).catch(() => {});
const chat = await page.getByTestId("chat").innerText();
check("test panel round-trips InvokeAgent (no local model in headless: honest model error shown)", /You: hello/.test(chat) && (/Error:/.test(chat) || /Agent:/.test(chat)), chat);
await shot("agent-test-panel");
check("no uncaught page errors", errs.length === 0, errs.join("|"));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
