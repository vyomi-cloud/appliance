/* Bedrock Flows visual canvas (drag-and-drop, wire, save, prepare, run with trace) + Evaluations create flow, in a browser on the Nano preview.
 *   node consoles/nano_preview.mjs --port 8791 --tier pro &   BASE=http://127.0.0.1:8791 SHOTS=/tmp/limflows-shots node consoles/tests/smoke-limflows.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8791", SHOTS = process.env.SHOTS || "/tmp/limflows-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 220) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const go = async (p, h) => { await page.goto(`${BASE}/nano/v4/aws/#/bedrock/${p}`); await page.getByRole("heading", { name: h }).first().waitFor({ timeout: 120000 }); };
const modal = () => page.locator('[role="dialog"]');

// ── Flows: create from the starter, then rebuild the graph on the canvas
await go("flows", "Flows");
await page.getByRole("button", { name: "Create flow" }).first().click();
await modal().getByLabel("Flow name").fill("canvas-flow");
await modal().getByRole("button", { name: "Create flow" }).last().click();
await page.getByTestId("flow-builder").waitFor({ timeout: 90000 });
check("canvas shows the starter nodes", (await page.getByTestId("flownode-Prompt_1").count()) === 1 && (await page.getByTestId("flownode-FlowInputNode").count()) === 1);
check("palette lists the new node types", (await page.getByTestId("flow-palette").locator("[data-testid^=palette-]").count()) >= 10 && (await page.getByTestId("palette-LambdaFunction").count()) === 1 && (await page.getByTestId("palette-Iterator").count()) === 1);
await shot("1-starter");
// remove the Prompt node (select it, Delete node in the side panel)
await page.getByTestId("flownode-Prompt_1").click();
await page.getByTestId("node-config").waitFor();
await page.getByRole("button", { name: "Delete node" }).click();
check("selected node deleted from the canvas", (await page.getByTestId("flownode-Prompt_1").count()) === 0);
// drag Iterator + Collector from the palette onto the canvas (HTML5 drag and drop)
const canvas = page.getByTestId("flow-canvas");
const cb = await canvas.boundingBox();
await page.getByTestId("palette-Iterator").dragTo(canvas, { targetPosition: { x: cb.width * 0.30, y: cb.height * 0.62 } });
await page.getByTestId("palette-Collector").dragTo(canvas, { targetPosition: { x: cb.width * 0.58, y: cb.height * 0.62 } });
await page.getByTestId("flownode-Iterator").waitFor({ timeout: 10000 });
await page.getByTestId("flownode-Collector").waitFor({ timeout: 10000 });
check("palette drag-and-drop adds Iterator and Collector nodes", true);
// also add a Lambda node by drag, and confirm its config panel shows the function picker
await page.getByTestId("palette-LambdaFunction").dragTo(canvas, { targetPosition: { x: cb.width * 0.45, y: cb.height * 0.12 } });
await page.getByTestId("flownode-LambdaFunction").waitFor({ timeout: 10000 });
check("Lambda node config panel offers a function picker", (await page.getByLabel("Function").count()) > 0);
await page.getByRole("button", { name: "Delete node" }).click();   // keep the graph minimal
await page.getByTestId("flow-canvas").click({ position: { x: 10, y: 10 } });
// wire: handle drag with the mouse
const handle = (node, id, type) => page.locator(`[data-testid="flownode-${node}"] .react-flow__handle[data-handleid="${id}"].${type}`).first();
const drag = async (from, to) => {
  const a = await from.boundingBox(), b = await to.boundingBox();
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 }); await page.mouse.up();
};
await page.getByRole("button", { name: "Auto layout" }).click(); await page.waitForTimeout(500);
await drag(handle("FlowInputNode", "document", "source"), handle("Iterator", "array", "target"));
await drag(handle("Iterator", "arrayItem", "source"), handle("Collector", "arrayItem", "target"));
await drag(handle("Collector", "collectedArray", "source"), handle("FlowOutputNode", "document", "target"));
await page.waitForTimeout(400);
check("three connections drawn between ports", (await page.locator(".react-flow__edge").count()) === 3, await page.locator(".react-flow__edge").count());
await page.getByRole("button", { name: "Auto layout" }).click(); await page.waitForTimeout(600);
await shot("2-wired");
await page.getByRole("button", { name: "Save" }).first().click();
await page.getByText("Flow saved").first().waitFor({ timeout: 30000 });
await page.getByRole("tab", { name: "Definition (JSON)" }).click();
const json = await page.getByLabel("Flow definition").inputValue();
const def = JSON.parse(json);
check("saved definition has the Iterator / Collector nodes and 3 Data connections", def.nodes.map((n) => n.type).sort().join() === "Collector,Input,Iterator,Output" && def.connections.length === 3 && def.connections.every((c) => c.type === "Data"), json.slice(0, 200));
await page.getByRole("tab", { name: "Canvas" }).click();
await page.getByRole("button", { name: "Prepare" }).click();
await page.getByText("Flow prepared").first().waitFor({ timeout: 30000 });
await page.getByPlaceholder("Text sent to the input node").fill("[1,2,3]");
await page.getByRole("button", { name: "Run" }).click();
await page.getByTestId("flow-result").waitFor({ timeout: 120000 });
const outTxt = await page.getByTestId("flow-result").innerText();
check("InvokeFlow returns the collected array", /\[1,2,3\]/.test(outTxt.replace(/\s/g, "")), outTxt);
check("execution trace table lists node input and output events", (await page.getByTestId("trace-values").count()) >= 6 && (await page.getByText("Execution trace").count()) > 0, await page.getByTestId("trace-values").count());
check("executed nodes are marked on the canvas", (await page.getByTestId("flownode-Collector").innerText()).includes("✓"));
await shot("3-run-trace");

// ── Evaluations: modal offers the judge / RAG / human types
await go("evaluations", "Evaluations");
await page.getByRole("button", { name: "Create" }).first().click();
await modal().getByRole("button", { name: /Automatic: model evaluation/ }).click();
const opts = (await page.getByRole("option").allInnerTexts()).join("|");
check("evaluation type select lists model / RAG retrieve / RAG generate / human", /RAG retrieve only/.test(opts) && /RAG retrieve and generate/.test(opts) && /Human/.test(opts), opts);
await page.getByRole("option", { name: /RAG retrieve and generate/ }).click();
await modal().getByRole("button", { name: /Choose a knowledge base/ }).waitFor({ timeout: 10000 });
check("RAG type shows the knowledge base picker + judge metrics", (await modal().getByText("Knowledge base").count()) > 0);
await shot("4-eval-modal");
check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();
console.log(`${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
