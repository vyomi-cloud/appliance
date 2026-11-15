/* Real-training UI (AWS Bedrock Custom models job detail, Vertex Tuning, Azure Foundry Fine-tuning) against the in-process FAKE of the shared contract.
 *   node consoles/nano_preview.mjs --port 8771 --tier pro &   BASE=http://127.0.0.1:8771 SHOTS=<dir> node consoles/tests/smoke-training-ui.mjs
 * Service workers are blocked so Playwright answers /_wire from training-fake.mjs; no Pyodide boot, no backend. Keeps the cloud's own real API calls. */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { installTrainingFake } from "./training-fake.mjs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:8771", SHOTS = process.env.SHOTS || "/tmp/trainui-shots";
mkdirSync(SHOTS, { recursive: true });
let fails = 0;
const check = (n, ok, d = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 }, serviceWorkers: "block" });
await installTrainingFake(ctx);
const page = await ctx.newPage();
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });
const T = (id) => page.getByTestId(id).first();
const waitStatus = (re, ms = 40000) => page.waitForFunction((s) => new RegExp(s).test(document.querySelector('[data-testid="job-status"]')?.innerText || ""), re.source, { timeout: ms });

async function detailChecks(c, { stop = false } = {}) {
  await T("honest-note").waitFor({ timeout: 30000 });
  check(`${c}: honest label`, /not a language model/i.test(await T("honest-note").innerText()));
  await T("train-progress").waitFor();
  check(`${c}: progress bar present`, (await page.locator('[role="progressbar"]').count()) > 0);
  if (stop) return;
  await waitStatus(/Completed/);
  check(`${c}: status Completed`, true);
  await T("train-chart").waitFor();
  check(`${c}: per-epoch chart has 8 points per series`, (await page.locator('[data-testid="train-chart"] circle').count()) === 16);
  check(`${c}: held-out vs baseline`, /91\.7%/.test(await T("heldout").innerText()) && /33\.3%/.test(await T("heldout").innerText()) && /\+58/.test(await T("heldout-delta").innerText()));
  check(`${c}: artifact link`, /head\.json/.test(await T("job-artifact").innerText()));
  check(`${c}: engine shown`, /nano-head-js/.test(await T("job-engine").innerText()));
}
async function tryIt(c, text, expect) {
  await page.getByLabel("Text to classify").first().fill(text);
  await page.getByRole("button", { name: /^(Run|Predict)$/ }).first().click();
  await T("try-label").waitFor({ timeout: 15000 });
  check(`${c}: try-it classifies "${text.slice(0, 20)}" as ${expect}`, new RegExp(expect).test(await page.getByTestId("try-label").first().innerText()));
  check(`${c}: try-it scores + vyomiTrained note`, (await page.locator('[data-testid="try-scores"]').count()) > 0 && /vyomiTrained: true/.test(await page.locator("body").innerText()));
}

// ───────────── AWS ─────────────
await page.goto(`${BASE}/nano/v4/aws/#/bedrock/custom-models`);
await page.getByRole("heading", { name: "Custom models" }).first().waitFor({ timeout: 60000 });
await page.getByRole("button", { name: "Create fine-tuning job" }).first().click();
const modal = page.locator('[role="dialog"]');
await modal.getByLabel("Job name").fill("tickets-job"); await modal.getByLabel("Custom model name").fill("tickets-model");
await modal.getByRole("button", { name: /Choose a model/ }).first().click();
await page.getByRole("option", { name: /Nova Lite/ }).first().click();
check("aws create: non-trainable base says metadata only", /not trainable/i.test(await T("create-meta-only").innerText()));
await modal.getByRole("button", { name: /Nova Lite/ }).first().click();
await page.getByRole("option", { name: /all-MiniLM-L6-v2/ }).first().click();
check("aws create: trainable base shows honest label", /not a language model/i.test(await T("create-honest").innerText()));
await modal.getByRole("button", { name: "Choose bucket" }).click(); await page.getByRole("option", { name: "train-data" }).click();
for (const [f, re] of [["too-many.jsonl", /limit is 2000/], ["one-label.jsonl", /at least 2 distinct labels/], ["bad-rows.jsonl", /Row 2 is missing "label"/]]) {
  await modal.getByRole("button", { name: /Choose \.jsonl object|\.jsonl$/ }).first().click(); await page.getByRole("option", { name: new RegExp(f.replace(".", "\\.")) }).first().click();
  await page.getByText(re).first().waitFor({ timeout: 15000 }).catch(() => {});
  check(`aws create: ${f} rejected with reason`, re.test(await T("data-errors").innerText()), await T("data-errors").innerText());
  check(`aws create: Create disabled for ${f}`, await modal.getByRole("button", { name: "Create", exact: true }).isDisabled());
}
await modal.getByRole("button", { name: /Choose \.jsonl object|\.jsonl$/ }).first().click(); await page.getByRole("option", { name: /tickets\.jsonl/ }).first().click();
await T("data-ok").waitFor({ timeout: 15000 });
check("aws create: valid file accepted (rows/labels)", /60 rows/.test(await T("data-ok").innerText()) && /3 labels/.test(await T("data-ok").innerText()));
await modal.getByLabel("Output data (S3 location)").fill("s3://train-data/models/");
await shot("aws-1-create");
await modal.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForURL(/custom-models\/jobs\//, { timeout: 15000 });
await T("keep-open").waitFor({ timeout: 10000 }).then(() => check("aws: Nano keep-tab-open notice during training", true), () => check("aws: Nano keep-tab-open notice during training", false));
await page.waitForTimeout(2500); await shot("aws-2-training");
await detailChecks("aws");
await tryIt("aws", "the fire door was propped open", "safety");
await shot("aws-3-completed");
// stop flow: second job
await page.goto(`${BASE}/nano/v4/aws/#/bedrock/custom-models`); await page.reload();
await page.getByRole("heading", { name: "Custom models" }).first().waitFor({ timeout: 60000 });
await page.getByRole("button", { name: "Create fine-tuning job" }).first().click();
await modal.getByLabel("Job name").fill("stop-job"); await modal.getByLabel("Custom model name").fill("stop-model");
await modal.getByRole("button", { name: /Choose a model/ }).first().click(); await page.getByRole("option", { name: /nomic-embed-text/ }).first().click();
await modal.getByRole("button", { name: "Choose bucket" }).click(); await page.getByRole("option", { name: "train-data" }).click();
await modal.getByRole("button", { name: /Choose \.jsonl object/ }).click(); await page.getByRole("option", { name: /tickets\.jsonl/ }).first().click();
await T("data-ok").waitFor({ timeout: 15000 });
await modal.getByLabel("Output data (S3 location)").fill("s3://train-data/models/");
await modal.getByRole("button", { name: "Create", exact: true }).click();
await page.waitForURL(/custom-models\/jobs\//, { timeout: 15000 });
await T("train-progress").waitFor(); await page.waitForTimeout(1500);
await page.getByRole("button", { name: "Stop job" }).click();
await waitStatus(/Stopped/, 15000); check("aws: Stop job -> Stopped", true);
check("aws: Try it disabled after stop", (await T("try-disabled").count()) === 1);
await shot("aws-4-stopped");

// ───────────── GCP ─────────────
await page.goto(`${BASE}/nano/v4/gcp/#/vertex-ai/tuning`);
await page.getByRole("heading", { name: "Tuning" }).first().waitFor({ timeout: 60000 });
await page.getByRole("button", { name: "Create tuned model" }).first().click();
const dlg = page.getByRole("dialog");
await dlg.getByLabel("Tuned model name").fill("gcp-tickets");
check("gcp create: honest label", /not a language model/i.test(await T("create-honest").innerText()));
await dlg.getByLabel("Training bucket").click(); await page.getByRole("option", { name: "train-data" }).click();
await dlg.getByLabel("Training object").click(); await page.getByRole("option", { name: "too-many.jsonl" }).click();
await T("data-errors").waitFor({ timeout: 15000 });
check("gcp create: too many rows rejected with reason", /limit is 2000/.test(await T("data-errors").innerText()));
check("gcp create: Start disabled", await dlg.getByRole("button", { name: "Start tuning" }).isDisabled());
await dlg.getByLabel("Training object").click(); await page.getByRole("option", { name: "tickets.jsonl" }).click();
await T("data-ok").waitFor({ timeout: 15000 }); await shot("gcp-1-create");
await dlg.getByRole("button", { name: "Start tuning" }).click();
await page.waitForURL(/vertex-ai\/tuning\/us-central1\//, { timeout: 15000 });
await page.waitForTimeout(2500); await shot("gcp-2-training");
await detailChecks("gcp");
await tryIt("gcp", "invoice shows wrong total", "billing");
await shot("gcp-3-completed");
await page.goto(`${BASE}/nano/v4/gcp/#/vertex-ai/tuning`);
await page.getByText("gcp-tickets").first().waitFor({ timeout: 15000 });
check("gcp list: job listed as Trained head", /Trained head/.test(await page.locator("table").first().innerText()));
await shot("gcp-4-list");

// ───────────── Azure ─────────────
await page.goto(`${BASE}/nano/v4/azure/#/foundry/finetuning`);
await page.getByRole("button", { name: "Fine-tune model" }).waitFor({ timeout: 60000 });
await page.getByRole("button", { name: "Fine-tune model" }).click();
check("azure create: honest label", /not a language model/i.test(await T("create-honest").innerText()));
await page.getByLabel("Uploaded training file").selectOption("file-big");
await T("data-errors").waitFor({ timeout: 15000 });
check("azure create: too many rows rejected with reason", /limit is 2000/.test(await T("data-errors").innerText()));
check("azure create: Start disabled", await page.getByRole("button", { name: "Start fine-tuning" }).isDisabled());
await page.getByLabel("Uploaded training file").selectOption("file-tickets");
await T("data-ok").waitFor({ timeout: 15000 }); await shot("azure-1-create");
await page.getByRole("button", { name: "Start fine-tuning" }).click();
await page.waitForURL(/foundry\/finetuning\/ftjob/, { timeout: 15000 });
await page.waitForTimeout(2500); await shot("azure-2-training");
await detailChecks("azure");
await tryIt("azure", "the fire door was propped open", "safety");
await shot("azure-3-completed");
await page.goto(`${BASE}/nano/v4/azure/#/foundry/finetuning`);
await page.getByText("ftjob-").first().waitFor({ timeout: 15000 });
await shot("azure-4-list");

check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();
console.log(fails ? `${fails} FAILED` : "ALL PASSED");
process.exit(fails ? 1 : 0);
