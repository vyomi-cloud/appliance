/* Right-hand help pane "Scope and limits" on AWS Bedrock, GCP Agent Platform and Azure Foundry (Nano preview).
 *   node consoles/nano_preview.mjs --port 8781 --tier pro &   BASE=http://127.0.0.1:8781 SHOTS=/tmp/shots node consoles/tests/smoke-help-panes.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8781", SHOTS = process.env.SHOTS || "/tmp/helppanes-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 140) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));

// [cloud, route, how to open the pane, heading the pane must show, text that must appear in the scope section]
const OPEN = {
  aws: async () => { if (!(await page.locator("#vyomi-help-overlay").getByTestId("scope-limits").count())) { await page.locator("#vyomi-help-toggle").click(); } },
  gcp: async () => { if (!(await page.getByTestId("info-panel").count())) await page.getByRole("button", { name: "How Vyomi runs this service" }).click(); },
  azure: async () => { if (!(await page.locator("aside.vy-drawer").count())) await page.getByRole("button", { name: "Help + support" }).click(); },
};
const CASES = [
  ["aws", "#/bedrock", "aws-overview", /local open models/],
  ["aws", "#/bedrock/models", "aws-models", /vyomiBackedBy/],
  ["aws", "#/bedrock/custom-models", "aws-custom-models", /2000 rows, 5 MB, 20 labels/],
  ["aws", "#/bedrock/provisioned-throughput", "aws-provisioned", /no capacity is reserved/],
  ["aws", "#/bedrock/knowledge-bases/studio", "aws-ragstudio", /token-overlap proxies/],
  ["aws", "#/bedrock/agentcore", "aws-agentcore", /fails closed/],
  ["gcp", "#/vertex-ai", "gcp-overview", /Not simulated/],
  ["gcp", "#/vertex-ai/model-garden", "gcp-model-garden", /not Google's 128/],
  ["gcp", "#/vertex-ai/tuning", "gcp-tuning", /2000 rows, 5 MB, 20 labels/],
  ["gcp", "#/vertex-ai/agent-garden", "gcp-agent-garden", /Eleven agent blueprints/],
  ["gcp", "#/vertex-ai/deployments", "gcp-deployments", /reasoningEngines/],
  ["azure", "#/foundry", "azure-overview", /Foundry project pages/],
  ["azure", "#/foundry/finetuning", "azure-finetuning", /Vyomi extension/],
  ["azure", "#/foundry/openai", "azure-openai", /not by an OpenAI model/],
  ["azure", "#/foundry/search", "azure-search", /azure_search_core/],
];
let lastCloud = "";
for (const [cloud, hash, name, re] of CASES) {
  const url = `${BASE}/nano/v4/${cloud}/${hash}`;
  if (cloud !== lastCloud) { await page.goto(url); lastCloud = cloud; } else await page.evaluate((h) => { location.hash = h; }, hash);
  await page.waitForTimeout(cloud === "aws" && hash.includes("studio") ? 1500 : 700);
  await OPEN[cloud]();
  const sec = page.getByTestId("scope-limits").first();
  await sec.waitFor({ timeout: 20000 }).catch(() => {});
  const txt = await sec.innerText().catch(() => "");
  check(`${name}: Scope and limits shown`, /^Scope and limits/.test(txt) && re.test(txt), txt.slice(0, 80).replace(/\n/g, " | "));
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}
// pages with no entry keep the generic pane (nothing invented)
await page.goto(`${BASE}/nano/v4/aws/#/bedrock/api-keys`); await page.waitForTimeout(800); await OPEN.aws();
check("aws api-keys has its own entry", /bedrock-api-key-/.test(await page.getByTestId("scope-limits").first().innerText()));
check("no page errors", errs.length === 0, errs[0]);
await browser.close(); process.exit(results.every(Boolean) ? 0 : 1);
