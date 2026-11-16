/* Agent Platform pages that were "Coming soon" (Sessions, Memory Bank, RAG Engine, Search, Agent Retrieval, Evaluation, Metadata, Monitoring,
 * Registry, ADK, Topology) + the declared Not-in-scope pages. UI actions are cross-checked against the same native wire the SDK uses.
 *   node consoles/nano_preview.mjs --port 8793 --tier pro &
 *   NANO=1 BASE=http://127.0.0.1:8793 UI_PATH=/nano/v4/gcp/ WIRE_PATH=/nano/_wire SHOTS=/tmp/uigcp node consoles/tests/smoke-uigcp.mjs
 */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9071";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const NANO = !!process.env.NANO;
const SHOTS = process.env.SHOTS || "";
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const wait = { waitUntil: NANO ? "domcontentloaded" : "networkidle" };
await page.goto(UI, wait);
if (NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
const project = await page.evaluate(() => localStorage.getItem("vyomi.v4.gcp.project") || "nano-project");
const J = async (method, path, body) => page.evaluate(async ([u, m, b]) => { const r = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); const t = await r.text(); try { return { status: r.status, ...JSON.parse(t) }; } catch { return { status: r.status, raw: t }; } }, [WIRE + path, method, body]);
const L = `/v1/projects/${project}/locations`;
const go = async (hash, heading) => { await page.evaluate((h) => { location.hash = h; }, hash); await page.getByRole("heading", { name: heading, level: 1 }).first().waitFor({ timeout: 60000 }); await page.waitForTimeout(500); };
const shot = async (n) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${n}.png` }); };
const dlg = () => page.getByRole("dialog");
const body = () => page.locator("body").innerText();

// seed an agent deployment (what Deployments lists) through the real wire
const eng = await J("POST", `${L}/us-central1/reasoningEngines`, { displayName: "facilities-supervisor", spec: { vyomiAgentSpec: { instructions: "Answer briefly.", tools: [{ name: "current_time", type: "builtin", builtin: "current_time" }, { name: "create_work_order", type: "static", result: { ok: true } }] } } });
const en = eng.response?.name; check("seed agent deployment", !!en, JSON.stringify(eng));

// Sessions
await go("#/vertex-ai/sessions", "Sessions");
await page.getByRole("button", { name: "Create session" }).click();
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("user-1").first().waitFor({ timeout: 20000 });
const sl = await J("GET", `/v1beta1/${en}/sessions`);
check("Sessions: created session visible in UI and on the wire", (sl.sessions || []).length === 1);
await shot("sessions");

// Memory Bank
await go("#/vertex-ai/memory-bank", "Memory Bank");
await page.getByRole("button", { name: "Create memory" }).click();
await dlg().getByLabel("Fact").fill("The chiller on level 3 is serviced quarterly");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("serviced quarterly").first().waitFor({ timeout: 20000 });
await page.getByLabel("Search query").fill("chiller service");
await page.getByRole("button", { name: "Search", exact: true }).click();
await page.getByText(/distance/).first().waitFor({ timeout: 20000 });
check("Memory Bank: create + similarity retrieve", true);
await shot("memory-bank");

// RAG Engine
await go("#/vertex-ai/rag-engine", "RAG Engine");
await page.getByRole("button", { name: "Create RAG corpus" }).first().click();
await dlg().getByLabel("Corpus name").fill("facilities-docs");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("facilities-docs").first().waitFor({ timeout: 20000 });
await page.getByText("Manage files").first().click();
await page.getByRole("button", { name: "Upload text file" }).click();
await dlg().getByLabel("Content").fill("Boiler inspection happens every October. The elevator contract renews in March.");
await dlg().getByRole("button", { name: "Upload", exact: true }).click();
await page.getByText("notes.txt").first().waitFor({ timeout: 20000 });
await page.getByLabel("Test retrieval").fill("when is boiler inspection");
await page.getByRole("button", { name: "Retrieve" }).click();
await page.getByText(/Boiler inspection happens/).first().waitFor({ timeout: 20000 });
check("RAG Engine: corpus + file + retrieval", true);
await shot("rag-engine");

// Search + App Builder
await go("#/vertex-ai/search", "Search");
await page.getByRole("button", { name: "Create data store" }).click();
await dlg().getByLabel("Data store ID").fill("manuals");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("manuals").first().waitFor({ timeout: 20000 });
await page.getByRole("link", { name: "manuals" }).first().click();
await page.getByRole("button", { name: "Add document" }).click();
await dlg().getByLabel("Document ID").fill("d1");
await dlg().getByLabel("Title").fill("Boiler manual");
await dlg().getByLabel("Content").fill("Inspect the boiler flue yearly.");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("Boiler manual").first().waitFor({ timeout: 20000 });
await page.getByRole("textbox", { name: "Search", exact: true }).fill("boiler");
await page.getByRole("button", { name: "Search", exact: true }).last().click();
await page.getByText(/1 results/).waitFor({ timeout: 20000 });
check("Search: data store + document + query", true);
await shot("search");
await go("#/vertex-ai/app-builder", "App Builder");
check("App Builder opens on Apps tab", /Create app/.test(await body()));
await page.getByRole("button", { name: "Create app" }).click();
await dlg().getByLabel("App ID").fill("manuals-app");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("manuals-app").first().waitFor({ timeout: 20000 }).catch(() => {});
const apps = await J("GET", `/v1/projects/${project}/locations/global/collections/default_collection/engines`);
check("App Builder: app created on the wire", (apps.engines || []).some((a) => a.name.endsWith("/manuals-app")));
await shot("app-builder");

// Agent Retrieval
await go("#/vertex-ai/agent-retrieval", "Agent Retrieval");
await page.getByLabel("Query").fill("boiler");
await page.getByRole("button", { name: "Retrieve" }).click();
await page.getByText(/RAG corpus ·|Search ·/).first().waitFor({ timeout: 20000 });
check("Agent Retrieval: results from corpora and data stores", true);
await shot("agent-retrieval");

// Evaluation
await go("#/vertex-ai/evaluation", "Evaluation");
await page.getByRole("button", { name: "Create evaluation" }).click();
await dlg().getByLabel("Name").fill("smoke-eval");
await dlg().getByLabel(/Dataset/).fill("say hi | hello world | hello world");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText(/rouge 1\.000/).first().waitFor({ timeout: 20000 });
check("Evaluation: run scored", true);
await shot("evaluation");

// Metadata
await go("#/vertex-ai/metadata", "Metadata");
check("Metadata: tabs", /Artifacts/.test(await body()) && /Executions/.test(await body()));
await page.getByRole("button", { name: /Create artifact/ }).first().click();
await dlg().getByLabel(/Artifact ID/).fill("model-card");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("model-card").first().waitFor({ timeout: 20000 });
check("Metadata: artifact created", true);
await shot("metadata");

// Monitoring (needs an endpoint)
await J("POST", `${L}/us-central1/endpoints`, { displayName: "mon-ep" });
await go("#/vertex-ai/monitoring", "Monitoring");
await page.getByRole("button", { name: /Create monitoring job/ }).first().click();
await dlg().getByLabel("Name").fill("mon-job");
await dlg().getByRole("button", { name: "Create", exact: true }).click();
await page.getByText("mon-job").first().waitFor({ timeout: 20000 });
check("Monitoring: job created", true);
await shot("monitoring");

// Registry, ADK, Topology
await go("#/vertex-ai/agent-registry", "Agent Registry");
check("Registry lists the agent and its tools", /facilities-supervisor/.test(await body()) && /create_work_order/.test(await body()));
await shot("registry");
await go("#/vertex-ai/adk", "Agent Development Kit");
await page.getByRole("button", { name: "Deploy an agent" }).click();
await dlg().getByLabel("Agent name").fill("adk-demo");
await dlg().getByRole("button", { name: "Deploy", exact: true }).click();
await page.getByText("adk-demo").first().waitFor({ timeout: 20000 }).catch(() => {});
const ae = await J("GET", `${L}/us-central1/reasoningEngines`);
check("ADK: agent deployed on the wire", (ae.reasoningEngines || []).some((e) => e.displayName === "adk-demo"));
await shot("adk");
await go("#/vertex-ai/topology", "Topology");
await page.locator("svg[aria-label='Agent topology']").waitFor({ timeout: 20000 });
check("Topology draws the agent and tools", /create_work_order/.test(await page.locator("svg[aria-label='Agent topology']").innerHTML()));
await shot("topology");

// Not in scope: explicit, with a reason and an alternative
for (const [id, title] of [["training-clusters", "Training clusters"], ["provisioned-throughput", "Provisioned Throughput"], ["ray", "Ray on Agent Platform"], ["mcp-servers", "MCP Servers"], ["policies", "Policies"], ["gateways", "Gateways"], ["security", "Security"]]) {
  await go(`#/vertex-ai/${id}`, title);
  const t = await body();
  check(`${id}: declared not in scope (no bare Coming soon)`, /not in scope for Vyomi/i.test(t) && !/Coming soon/.test(t));
}
await shot("not-in-scope");
check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
