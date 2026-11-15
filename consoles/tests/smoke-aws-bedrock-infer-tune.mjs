/* Bedrock Infer + Tune pages (inference profiles, batch, provisioned, custom models, prompt routers, marketplace) in a browser on the Nano preview.
 *   node consoles/nano_preview.mjs --port 8761 --tier pro &   BASE=http://127.0.0.1:8761 SHOTS=/tmp/shots node consoles/tests/smoke-aws-bedrock-infer-tune.mjs */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8761", SHOTS = process.env.SHOTS || "/tmp/bedrock-it-shots";
mkdirSync(SHOTS, { recursive: true });
const results = [], check = (n, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch(), page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const go = async (p, h) => { await page.goto(`${BASE}/nano/v4/aws/#/bedrock/${p}`); await page.getByRole("heading", { name: h }).first().waitFor({ timeout: 90000 }); };
const tab = (name) => page.getByRole("tab", { name }).click();
const modal = () => page.locator('[role="dialog"]');
const pick = async (label, text) => { await modal().getByRole("button", { name: new RegExp(label) }).first().click(); await page.getByRole("option", { name: new RegExp(text) }).first().click(); };

await go("inference-profiles", "Inference profiles");
await page.getByText("Loading system-defined").first().waitFor({ state: "detached", timeout: 300000 });   // Pyodide boot
await page.waitForTimeout(800);
check("profiles: system-defined table has rows + counter", (await page.locator("table tbody tr").count()) >= 5 && (await page.getByText(/\(\d{2,}\)/).count()) > 0);
await shot("011-system");
await tab("Application");
await page.getByText("No base models").waitFor({ timeout: 60000 });
await page.getByRole("button", { name: "Create inference profile" }).click();
await modal().getByLabel("Inference profile name").fill("ui-haiku");
await pick("Choose a model", "US Anthropic Claude 3 Haiku");
await modal().getByRole("button", { name: "Create" }).last().click();
await page.getByText("ui-haiku").first().waitFor({ timeout: 30000 });
check("profiles: application profile created and listed", true);
await shot("011-application");

await go("batch-inference", "Batch inference");
await page.getByText("No batch inference models").waitFor({ timeout: 30000 });
check("batch: empty state", true); await shot("012-batch");

await go("provisioned-throughput", "Provisioned Throughput");
await page.getByText("Overview").first().waitFor();
await page.getByRole("button", { name: "Purchase Provisioned Throughput" }).first().click();
await modal().getByLabel("Provisioned Throughput name").fill("ui-pt");
await pick("Choose a model", "Nova Lite");
await modal().getByRole("button", { name: "Purchase" }).last().click();
await page.getByText("ui-pt").first().waitFor({ timeout: 30000 });
check("provisioned: purchased and listed Active", (await page.getByText("Active").count()) > 0);
await shot("013-provisioned");

await go("custom-models", "Custom models");
await page.getByText("No custom models").first().waitFor({ timeout: 30000 });
check("custom: empty models + shared-with-you card", (await page.getByText("Models shared with you").count()) > 0);
await shot("014-models"); await tab("Jobs");
await page.getByText("No active jobs").waitFor(); await shot("014-jobs");

await go("prompt-routers", "Prompt Routers");
await page.getByText("No prompt routers").first().waitFor({ timeout: 30000 }); await shot("015-configured");
await tab("Default");
await page.getByText("Nova Prompt Router").first().waitFor({ timeout: 30000 });
check("routers: default routers hidden unless aliases opted in", (await page.getByText("Anthropic Prompt Router").count()) === 0); await shot("015-default");

await go("marketplace-deployments", "Marketplace deployments");
await page.getByText("No deployments").first().waitFor({ timeout: 30000 }); await shot("016-marketplace");
check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();
console.log(`${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
