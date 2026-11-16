/* Azure AI "finish the Coming soon pages": AI Search blade (indexes + explorer + indexer), Foundry Agents, Content filters (enforced on a
 * deployment), explicit Not-in-scope panels, and Locks at resource group / subscription scope. Nano with a stand-in browser model.
 *   node consoles/nano_preview.mjs --port 8793 --tier pro &   BASE=http://127.0.0.1:8793 SHOTS=/tmp/uiazure node consoles/tests/smoke-uiazure.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8793", SHOTS = process.env.SHOTS || "/tmp/uiazure";
mkdirSync(SHOTS, { recursive: true });
const UI = `${BASE}/nano/v4/azure/`, WIRE = `${BASE}/nano/_wire`;
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
await page.goto(UI);
await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await page.waitForTimeout(1500);
await page.evaluate(() => window.vyomiRegisterLLM({ model: "fake-webllm", chat: async (req) => JSON.stringify({ text: "STUB ANSWER from the in-browser model", input_tokens: 3, output_tokens: 6, finish_reason: "stop" }) }));
const call = (m, p, b) => page.evaluate(async ([u, m, p, b]) => { const r = await fetch(u + p, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return [r.status, await r.text()]; }, [WIRE, m, p, b]);
const S = "00000000-0000-0000-0000-cloudlearn01", RG = "ui-rg";
await call("PUT", `/subscriptions/${S}/resourcegroups/${RG}?api-version=2021-04-01`, { location: "eastus" });
const AC = `/subscriptions/${S}/resourceGroups/${RG}/providers/Microsoft.CognitiveServices/accounts/uiaoai`;
await call("PUT", `${AC}?api-version=2024-10-01`, { location: "eastus", kind: "OpenAI", sku: { name: "S0" }, properties: { customSubDomainName: "uiaoai" } });
const d = await call("PUT", `${AC}/deployments/chat?api-version=2024-10-01`, { sku: { name: "Standard", capacity: 10 }, properties: { model: { format: "OpenAI", name: "gpt-4o", version: "2024-11-20" } } });
check("seed account + deployment", d[0] < 300, d[1]);
const go = async (h) => { await page.goto(`${UI}${h}`); await page.waitForTimeout(700); };
const txt = () => page.locator("body").innerText();

// AI Search: create service from the browse blade, then an index, documents, a search and an indexer run
await go("#/aisearch");
await page.getByRole("button", { name: /^Create/ }).first().click();
await page.getByLabel("Service name").fill("uisearch");
await page.getByLabel("Resource group").selectOption(RG);
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("Usage", { exact: true }).waitFor({ timeout: 30000 });
check("search: service blade opened after create", /uisearch/.test(await txt()) && /Usage/.test(await txt()));
await shot("search-overview");
await page.getByRole("link", { name: "Indexes" }).first().click(); await page.getByRole("button", { name: "Add index" }).waitFor();
await page.getByRole("button", { name: "Add index" }).click(); await page.getByLabel("Index name").fill("docs");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click(); await page.getByRole("button", { name: "docs", exact: true }).waitFor({ timeout: 20000 });
check("search: index created and listed", true);
await page.getByRole("button", { name: "docs", exact: true }).click(); await page.getByTestId("search-explorer").waitFor();
await page.getByRole("button", { name: "Upload", exact: true }).click(); await page.waitForTimeout(800);
await page.getByLabel("Query string").fill("vyomi"); await page.getByRole("button", { name: "Search", exact: true }).click();
await page.getByTestId("search-results").waitFor({ timeout: 20000 });
check("search: uploaded document found by the explorer", /Hello Vyomi/.test(await page.getByTestId("search-results").innerText()));
await shot("search-explorer");
await page.getByRole("link", { name: "Keys" }).first().click(); await page.getByText("Manage admin keys").waitFor();
await page.waitForFunction(() => (document.querySelector('[aria-label="Primary admin key"]')?.value || "").length > 10, null, { timeout: 20000 }).catch(() => {});
check("search: admin keys shown", (await page.getByLabel("Primary admin key").inputValue()).length > 10);
await page.getByLabel("Query key name").fill("ro"); await page.getByRole("button", { name: "Add", exact: true }).click(); await page.getByText("ro", { exact: true }).waitFor({ timeout: 15000 });
check("search: query key created", true);
await go("#/foundry/search"); await page.waitForTimeout(1000);
check("foundry AI Search list links to the blade", await page.getByRole("link", { name: "uisearch" }).count() > 0);

// Foundry Agents: create and chat (thread + message + run through the Assistants API)
await go("#/foundry/agents"); await page.getByRole("button", { name: "New agent" }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "New agent" }).click(); await page.getByLabel("Agent name").fill("helper");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click(); await page.getByRole("button", { name: "helper", exact: true }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "helper", exact: true }).click(); await page.getByLabel("Message").fill("hi agent");
await page.getByRole("button", { name: "Send" }).click(); await page.getByText(/STUB ANSWER/).first().waitFor({ timeout: 30000 });
check("agents: agent answered through thread/run", true); await shot("agents");

// Content filters: create, assign to a deployment, see it enforced
await go("#/foundry/filters"); await page.getByRole("button", { name: "Create content filter" }).waitFor({ timeout: 20000 });
await page.getByRole("button", { name: "Create content filter" }).click(); await page.getByLabel("Filter name").fill("strict");
await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click(); await page.getByRole("cell", { name: "strict", exact: true }).waitFor({ timeout: 20000 });
check("filters: custom filter listed with its rules", /Violence/.test(await txt())); await shot("filters");
await page.getByRole("button", { name: "Assign", exact: true }).click();
await page.getByRole("dialog").getByRole("combobox").selectOption("chat"); await page.getByRole("dialog").getByRole("button", { name: "Assign", exact: true }).click();
await page.getByText("now uses the content filter").waitFor({ timeout: 20000 });
const blocked = await call("POST", `${AC}/openai/deployments/chat/chat/completions?api-version=2024-10-21`, { messages: [{ role: "user", content: "how to murder and torture and bomb" }] });
check("filters: violent prompt blocked with content_filter", blocked[0] === 400 && /content_filter/.test(blocked[1]), blocked[1]);

// Not-in-scope panels (explicit reason, no "Coming soon")
for (const [h, t] of [["evaluations", "Evaluations"], ["promptflow", "Prompt flow"], ["ml", "Machine Learning"]]) {
  await go(`#/foundry/${h}`); await page.getByTestId("not-in-scope").waitFor({ timeout: 20000 });
  const b = await txt(); check(`not in scope: ${t} has reason + alternative, no Coming soon`, /not in scope for Vyomi/.test(b) && /Use instead/.test(b) && !/Coming soon/.test(b));
}
await shot("not-in-scope");

// Cognitive Services blade: every menu panel renders without a Coming soon badge; locks at wider scopes
let soon = [];
for (const p of ["alerts", "metrics", "diagnosticsettings", "logs", "tasks", "resourcehealth", "support", "diagnose", "locks", "playground", "deployments"]) {
  await go(`#/cognitiveservices/${RG}/uiaoai/${p}`); await page.waitForTimeout(800);
  if (/Coming soon|isn't backed by a Vyomi backend/.test(await txt())) soon.push(p);
}
check("account blade: no Coming soon on any panel", soon.length === 0, soon.join(","));
await go(`#/cognitiveservices/${RG}/uiaoai/locks`); const rgBtn = page.getByLabel("Command bar").getByRole("button", { name: "Resource group", exact: true });
await rgBtn.waitFor({ timeout: 20000 }); await rgBtn.click(); await page.getByLabel("Lock name").fill("rglock");
await page.getByRole("button", { name: "OK" }).click(); await page.getByRole("cell", { name: "rglock", exact: true }).waitFor({ timeout: 20000 });
check("locks: resource group lock created and listed here", /rglock/.test(await txt()) && new RegExp(RG).test(await txt()));
await shot("locks");
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
const bad = results.filter((x) => !x).length; console.log(`${results.length - bad}/${results.length} passed`); process.exit(bad ? 1 : 0);
