/* GCP: Cloud Deploy (pipelines/targets/releases/rollouts), Cloud Build (triggers/history/logs), Security Command Center findings.
 *   BASE=http://127.0.0.1:9083 node consoles/tests/smoke-gcp-cicd-scc.mjs      (offline / dev_server; fresh server)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9083";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-cicd";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (40[0-9]|409|412)/.test(m.text()) && errors.push(m.text()));
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const wj = async (path, method = "GET", b) => { const r = await wire(path, { method, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); try { return JSON.parse(r.text || "{}"); } catch { return {}; } };
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project", L = "us-central1";
const B = `/v1/projects/${P}/locations/${L}`;

try {
  await page.goto(UI, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
  const go = async (hash, heading) => { await page.goto(UI + hash); await page.getByRole("heading", { name: heading }).first().waitFor(); };
  const dlg = () => page.getByRole("dialog");

  // ── Cloud Deploy ──
  const pl = `smoke-${N}`;
  await wj(`${B}/targets?targetId=dev-${N}`, "POST", { run: { location: `projects/${P}/locations/${L}` } });
  await wj(`${B}/targets?targetId=prod-${N}`, "POST", { run: { location: `projects/${P}/locations/${L}` }, requireApproval: true });
  await wj(`${B}/deliveryPipelines?deliveryPipelineId=${pl}`, "POST", { serialPipeline: { stages: [{ targetId: `dev-${N}` }, { targetId: `prod-${N}` }] }, deployParameters: { service: `svc-${N}` } });
  await go("#/clouddeploy", "Delivery pipelines");
  check("Cloud Deploy lists the pipeline", await page.getByRole("link", { name: pl }).isVisible());
  await page.getByRole("link", { name: pl }).click();
  await page.getByRole("heading", { name: pl }).first().waitFor();
  check("stage flow shows both targets", (await page.getByTestId("stage-flow").innerText()).includes(`prod-${N}`));
  await page.getByRole("button", { name: "Create release" }).click();
  await dlg().getByLabel("Release name").fill("rel-1");
  await dlg().getByLabel("Image to deploy (full reference)").fill(`us-central1-docker.pkg.dev/${P}/app/web:v1`);
  await dlg().getByRole("button", { name: "Create", exact: true }).click();
  await dlg().waitFor({ state: "detached" });
  await page.getByRole("button", { name: "rel-1" }).click();
  await page.getByText("SUCCEEDED").first().waitFor();
  const svc = await wj(`/v2/projects/${P}/locations/${L}/services/svc-${N}`);
  check("release rollout really deployed a Cloud Run service", svc.template?.containers?.[0]?.image?.endsWith("/web:v1"), JSON.stringify(svc).slice(0, 150));
  await page.getByRole("button", { name: `Promote to prod-${N}` }).click();
  await page.getByText("PENDING_APPROVAL").first().waitFor();
  await shot("01-pending-approval");
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await page.waitForFunction(() => document.body.innerText.split("SUCCEEDED").length > 2);
  check("approval promoted to prod", true);
  check("no Not-simulated gap on Cloud Deploy", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  await shot("02-deploy-detail");

  // ── Cloud Build ──
  await wj("/v1/projects/" + P + "/triggers", "POST", { name: `trig-${N}`, triggerTemplate: { repoName: `repo-${N}`, branchName: "^main$" },
    build: { steps: [{ name: "gcr.io/cloud-builders/docker", args: ["build", "-t", `${L}-docker.pkg.dev/${P}/ghost/x:1`, "."] }] } });
  await wj("/v1/projects/" + P + "/triggers:vyomiPush", "POST", { repoName: `repo-${N}`, branch: "main", files: { Dockerfile: "FROM scratch\n" }, message: "go" });
  await go("#/cloudbuild", "Cloud Build");
  await page.getByText(`trig-${N}`).first().waitFor();
  check("push-triggered build is in History (honest status from the real builder)", await page.getByText(/SUCCESS|FAILURE/).first().isVisible());
  await page.getByRole("button", { name: /^[0-9a-f]{8}$/ }).first().click();
  await page.getByTestId("build-logs").waitFor();
  check("build logs rendered", (await page.getByTestId("build-logs").innerText()).length > 0);
  await shot("03-build-detail");
  await page.goto(UI + "#/cloudbuild?tab=triggers");
  await page.getByText(`trig-${N}`).first().waitFor();
  check("trigger listed", true);
  check("no Not-simulated gap on Cloud Build", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);

  // ── Security Command Center ──
  await go("#/security/scc", "Security Command Center");
  await page.getByTestId("scc-summary").waitFor();
  check("SCC findings page renders the severity summary", (await page.getByTestId("scc-summary").innerText()).includes("CRITICAL"));
  await page.getByRole("tab", { name: "Sources" }).click();
  await page.getByText("Security Health Analytics").first().waitFor();
  check("SCC sources listed", true);
  await shot("04-scc");
  check("no console errors", errors.length === 0, errors.join(" | "));
} catch (e) { check("smoke run", false, e.message); await shot("fail").catch(() => {}); }
await browser.close();
const bad = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - bad}/${results.length} passed`);
process.exit(bad ? 1 : 0);
