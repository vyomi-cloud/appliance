/* Vertex AI full section (GCP lens): every page drives the native aiplatform wire; creates/deletes are cross-checked
 * against the same API the SDK/gcloud use.   python3 consoles/dev_server.py --port 9091 -q &
 *   PROJECT=vyomi-project BASE=http://127.0.0.1:9091 SHOTS=/tmp/vx node consoles/tests/smoke-gcp-vertex-pages.mjs
 */
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
const require = createRequire(import.meta.url);
let pw; try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9071";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const NANO = !!process.env.NANO;
const SHOTS = process.env.SHOTS || "";
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const results = [];
const check = (name, ok, d = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${d ? " - " + String(d).slice(0, 160) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
const wait = { waitUntil: NANO ? "domcontentloaded" : "networkidle" };
await page.goto(UI, wait);
if (NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
if (process.env.PROJECT) { await page.evaluate((p) => localStorage.setItem("vyomi.v4.gcp.project", p), process.env.PROJECT); await page.reload(wait); }
const project = await page.evaluate(() => localStorage.getItem("vyomi.v4.gcp.project") || (document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano" ? "nano-project" : "vyomi-project"));
const W = (method, path, body) => page.evaluate(async ([u, m, b]) => { const r = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return { status: r.status, text: await r.text() }; }, [WIRE + path, method, body]);
const J = async (method, path, body) => { const r = await W(method, path, body); try { return { status: r.status, ...JSON.parse(r.text) }; } catch { return { status: r.status, raw: r.text }; } };
const L = `/v1/projects/${project}/locations`;
const go = async (hash, heading) => { await page.evaluate((h) => { location.hash = h; }, hash); await page.getByRole("heading", { name: heading, level: 1 }).waitFor({ timeout: 30000 }); await page.waitForTimeout(400); };
const shot = async (n) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: false }); };
const createVia = async (label) => { await page.getByRole("button", { name: label, exact: true }).first().click(); };
const submit = async (label = "Create") => { await page.getByRole("dialog").getByRole("button", { name: label, exact: true }).click(); };
const rowMenu = async (name, item) => { await page.getByRole("button", { name: `Actions for ${name}` }).click(); await page.getByRole("menuitem", { name: item, exact: true }).click(); };
const confirmDelete = async (name) => { await page.getByLabel("Confirm deletion").fill(name); await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click(); await page.getByRole("dialog").waitFor({ state: "detached", timeout: 15000 }); };

// Nav lists every section
await go("#/vertex-ai", "Vertex AI dashboard");
const nav = await page.locator("nav, #rail, body").first().innerText();
for (const t of ["Model Garden", "Vertex AI Studio", "Endpoints", "Model Registry", "Datasets", "Training", "Pipelines", "Batch predictions", "Workbench", "Vector Search", "Feature Store", "Experiments"])
  check(`nav has ${t}`, new RegExp(t).test(await page.locator("body").innerText()));
await shot("01-dashboard");

// Model Garden -> Deploy
await go("#/vertex-ai/model-garden", "Model Garden");
await page.getByTestId("garden-card").first().waitFor({ timeout: 15000 });
check("Model Garden shows publisher models", (await page.getByTestId("garden-card").count()) >= 10);
await shot("02-model-garden");
const gemma = page.getByTestId("garden-card").filter({ hasText: "Gemma 2 9B" });
await gemma.getByRole("button", { name: "Deploy" }).click();
await submit("Deploy");
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 15000 });
const eps = await J("GET", `${L}/-/endpoints`);
check("Model Garden deploy created an endpoint with a deployed model", (eps.endpoints || []).some((e) => e.deployedModels?.length === 1), JSON.stringify(eps).slice(0, 120));

// Endpoints: create in UI, appears via API, detail, delete
await go("#/vertex-ai/endpoints", "Online prediction: Endpoints");
await createVia("Create endpoint");
await page.getByLabel("Name", { exact: true }).fill("ui-endpoint");
await submit();
await page.getByRole("cell", { name: "ui-endpoint", exact: true }).waitFor({ timeout: 15000 });
check("endpoint created in UI is visible via the API", ((await J("GET", `${L}/-/endpoints`)).endpoints || []).some((e) => e.displayName === "ui-endpoint"));
await shot("03-endpoints");
await page.getByRole("link", { name: "gemma-2-9b-it-endpoint" }).click();
await page.getByText("Deployed models").first().waitFor({ timeout: 15000 });
check("endpoint detail lists the deployed model", await page.getByRole("button", { name: "Undeploy" }).isVisible());
await shot("04-endpoint-detail");
await page.getByRole("button", { name: "Undeploy" }).click();
await page.getByText("No models deployed").waitFor({ timeout: 15000 });
check("undeploy via UI", true);
await go("#/vertex-ai/endpoints", "Online prediction: Endpoints");
await rowMenu("ui-endpoint", "Delete"); await confirmDelete("ui-endpoint");
check("endpoint deleted (API agrees)", !((await J("GET", `${L}/-/endpoints`)).endpoints || []).some((e) => e.displayName === "ui-endpoint"));

// Model Registry
await go("#/vertex-ai/models", "Model Registry");
await createVia("Import model");
await page.getByLabel("Name", { exact: true }).fill("ui-model"); await submit();
await page.getByRole("cell", { name: "ui-model", exact: true }).waitFor({ timeout: 15000 });
check("model imported", ((await J("GET", `${L}/-/models`)).models || []).some((m) => m.displayName === "ui-model"));
await shot("05-models");

// Datasets
await go("#/vertex-ai/datasets", "Datasets");
await createVia("Create dataset");
await page.getByLabel("Name", { exact: true }).fill("ui-dataset"); await submit();
await page.getByRole("cell", { name: "ui-dataset", exact: true }).waitFor({ timeout: 15000 });
await shot("06-datasets");
await rowMenu("ui-dataset", "Delete"); await confirmDelete("ui-dataset");
check("dataset created then deleted", !((await J("GET", `${L}/-/datasets`)).datasets || []).some((m) => m.displayName === "ui-dataset"));

// Training: custom job runs to Succeeded
await go("#/vertex-ai/training", "Training");
await page.getByRole("tab", { name: "Custom jobs" }).click();
await createVia("Create custom job");
await page.getByLabel("Name", { exact: true }).fill("ui-job"); await submit();
await page.getByRole("cell", { name: "ui-job", exact: true }).waitFor({ timeout: 15000 });
await shot("07-training-pending");
await page.getByText("Succeeded").first().waitFor({ timeout: 30000 });
check("custom job progressed to Succeeded", true);
check("job visible via API", ((await J("GET", `${L}/-/customJobs`)).customJobs || []).some((m) => m.displayName === "ui-job"));
await shot("08-training-done");
await page.getByRole("tab", { name: "Training pipelines" }).click();
await createVia("Create training pipeline");
await page.getByLabel("Name", { exact: true }).fill("ui-tp"); await page.getByLabel("Output model name").fill("ui-trained"); await submit();
await page.getByText("Succeeded").first().waitFor({ timeout: 30000 });
check("training pipeline registered its model", ((await J("GET", `${L}/-/models`)).models || []).some((m) => m.displayName === "ui-trained"));

// Pipelines + Batch
await go("#/vertex-ai/pipelines", "Pipelines");
await createVia("Create run"); await page.getByLabel("Name", { exact: true }).fill("ui-run"); await submit();
await page.getByRole("cell", { name: "ui-run", exact: true }).waitFor({ timeout: 15000 });
await shot("09-pipelines");
await go("#/vertex-ai/batch", "Batch predictions");
await createVia("Create batch prediction"); await page.getByLabel("Name", { exact: true }).fill("ui-batch");
await page.getByLabel("Model").click(); await page.getByRole("option").first().click(); await submit();
await page.getByRole("cell", { name: "ui-batch", exact: true }).waitFor({ timeout: 15000 });
await shot("10-batch");
check("batch job exists via API", ((await J("GET", `${L}/-/batchPredictionJobs`)).batchPredictionJobs || []).some((m) => m.displayName === "ui-batch"));

// Workbench
await go("#/vertex-ai/workbench", "Workbench");
await createVia("Create notebook instance"); await page.getByLabel("Instance name").fill("ui-wb"); await submit();
await page.getByRole("cell", { name: "ui-wb", exact: true }).first().waitFor({ timeout: 15000 });
await rowMenu("ui-wb", "Stop");
await page.getByText("Stopped").first().waitFor({ timeout: 15000 });
check("workbench instance created and stopped", ((await J("GET", `/v2/projects/${project}/locations/-/instances`)).instances || []).some((m) => m.state === "STOPPED"));
await shot("11-workbench");

// Vector search
await go("#/vertex-ai/vector-search", "Vector Search");
await createVia("Create index"); await page.getByLabel("Name", { exact: true }).fill("ui-index"); await page.getByLabel("Dimensions").fill("2"); await submit();
await page.getByRole("cell", { name: "ui-index", exact: true }).waitFor({ timeout: 15000 });
await rowMenu("ui-index", "Upsert datapoints");
await page.getByLabel("Datapoints (JSON)").fill('[{"datapointId":"a","featureVector":[1,0]},{"datapointId":"b","featureVector":[0,1]}]');
await submit("Upsert");
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 15000 });
await page.getByRole("tab", { name: "Index endpoints" }).click();
await createVia("Create index endpoint"); await page.getByLabel("Name", { exact: true }).fill("ui-ie"); await submit();
await page.getByRole("cell", { name: "ui-ie", exact: true }).waitFor({ timeout: 15000 });
await rowMenu("ui-ie", "Deploy index");
await page.getByLabel("Deployed index ID").fill("dep1");
await page.getByLabel("Index", { exact: true }).click(); await page.getByRole("option").first().click();
await submit("Deploy");
await page.getByRole("dialog").waitFor({ state: "detached", timeout: 15000 });
await rowMenu("ui-ie", "Query index");
await page.getByLabel("Query vector (JSON)").fill("[1, 0]");
await page.getByRole("button", { name: "Find neighbors" }).click();
await page.getByTestId("neighbors").waitFor({ timeout: 15000 });
check("vector search returns the nearest neighbor first", /^a:/.test((await page.getByTestId("neighbors").innerText()).trim()), await page.getByTestId("neighbors").innerText());
await shot("12-vector-search");
await page.getByRole("button", { name: "Close" }).click();

// Feature store
await go("#/vertex-ai/feature-store", "Feature Store");
await createVia("Create feature group"); await page.getByLabel("Feature group ID").fill("ui_fg"); await submit();
await page.getByRole("cell", { name: "ui_fg", exact: true }).first().waitFor({ timeout: 15000 });
await page.getByRole("tab", { name: "Features" }).click();
await createVia("Create feature"); await page.getByLabel("Feature ID").fill("ui_feat"); await submit();
await page.getByRole("cell", { name: "ui_feat", exact: true }).first().waitFor({ timeout: 15000 });
check("feature under group visible via API", ((await J("GET", `${L}/us-central1/featureGroups/ui_fg/features`)).features || []).length === 1);
await shot("13-feature-store");

// Experiments
await go("#/vertex-ai/experiments", "Experiments");
await createVia("Create experiment"); await page.getByLabel("Experiment name").fill("ui-exp"); await submit();
await page.getByRole("cell", { name: "ui-exp", exact: true }).first().waitFor({ timeout: 15000 });
check("experiment visible via API", ((await J("GET", `${L}/us-central1/metadataStores/default/contexts`)).contexts || []).some((c) => c.displayName === "ui-exp"));
await shot("14-experiments");

// Dashboard counts reflect reality
await go("#/vertex-ai", "Vertex AI dashboard");
await page.waitForTimeout(1500);
check("dashboard counts endpoints", (await page.getByTestId("count-endpoints").innerText()).startsWith("1"), await page.getByTestId("count-endpoints").innerText());
await shot("15-dashboard-final");

// Studio still works at its new route
await go("#/vertex-ai/studio", "Vertex AI Studio");
check("Studio page renders", await page.getByRole("button", { name: "Submit" }).isVisible());
check("no page errors", errs.length === 0, errs[0]);
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
