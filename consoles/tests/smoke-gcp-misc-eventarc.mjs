/* GCP leftovers smoke: Eventarc triggers on a Cloud Run job (UI create) + real delivery from an audit-log event.
 *   PW=... BASE=http://127.0.0.1:9072 node consoles/tests/smoke-gcp-misc-eventarc.mjs */
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9072";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1300 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const wj = (path, init) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); const t = await r.text(); try { return { status: r.status, ...JSON.parse(t || "{}") }; } catch { return { status: r.status, raw: t }; } }, [WIRE + path, init]);
const J = { "content-type": "application/json" };
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project", L = "us-central1";
const N = Date.now() % 100000;
try {
  await page.goto(UI, { waitUntil: "networkidle" });
  const job = `ev${N}`;
  await wj(`/v2/projects/${P}/locations/${L}/jobs?jobId=${job}`, { method: "POST", headers: J, body: JSON.stringify({ template: { template: { containers: [{ image: "gcr.io/x/y" }] } } }) });
  await page.goto(UI + `#/run/jobs/details/${L}/${job}?tab=triggers`);
  await page.getByRole("button", { name: "Add Eventarc trigger" }).waitFor({ timeout: 20000 });
  check("no Eventarc Not-simulated panel on the job", (await page.locator("[data-vyomi-not-simulated]").count()) === 0);
  await page.getByRole("button", { name: "Add Eventarc trigger" }).click();
  await page.getByRole("dialog").getByRole("combobox", { name: "Event" }).click();
  await page.getByRole("option", { name: "Cloud Audit Logs: log entry written" }).click();
  await page.getByLabel(/Service name/).fill("cloudkms.googleapis.com");
  await page.getByLabel("Method name").fill("google.cloud.kms.v1.KeyManagementService.CreateKeyRing");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText("Eventarc trigger created").first().waitFor({ timeout: 15000 });
  await wj(`/v1/projects/${P}/locations/global/keyRings?keyRingId=r${N}`, { method: "POST", headers: J, body: "{}" });
  const d = await wj(`/v1/projects/${P}/locations/${L}/triggers/${job}-event/deliveries`);
  check("a real KMS call started the job through Eventarc", d.delivered === 1);
  await page.getByRole("button", { name: "Refresh" }).first().click().catch(() => {});
  await page.goto(UI + `#/run/jobs/details/${L}/${job}`);
  await page.getByText("Execution").first().waitFor({ timeout: 15000 }).catch(() => {});
  const ex = await wj(`/v2/projects/${P}/locations/${L}/jobs/${job}/executions`);
  check("an execution exists for the job", (ex.executions || []).length >= 1);
} catch (e) { check("smoke ran", false, e.message); }
check("no page errors", errors.length === 0, errors.join(" | "));
await browser.close();
process.exit(results.every((r) => r.ok) ? 0 : 1);
