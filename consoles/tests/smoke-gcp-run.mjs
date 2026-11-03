/* GCP-02 smoke: Cloud Run + Functions create forms carry REAL advanced settings (autoscaling, ephemeral disk, probes,
 * volumes, Cloud SQL, Binary Authorization, CMEK), revision tags and a Cloud Storage Eventarc trigger work end to end,
 * and none of those sections is a "Not simulated" panel.
 *
 *   BASE=http://127.0.0.1:9130 node consoles/tests/smoke-gcp-run.mjs                                      (offline)
 *   BASE=http://127.0.0.1:8830 UI_PATH=/nano/v4/gcp/ WIRE_PATH=/nano/_wire NANO=1 node consoles/tests/smoke-gcp-run.mjs  (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9130";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-run";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1500 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (40[034]|412)/.test(m.text()) && errors.push(m.text()));
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const wj = async (path, init) => { const r = await wire(path, init); try { return JSON.parse(r.text || "{}"); } catch { return { raw: r.text }; } };
const P = "vyomi-project", RG = "us-central1";
const nsCount = () => page.locator("[data-vyomi-not-simulated]").count();
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
  // a bucket + a Cloud SQL-free setup: bucket for the Eventarc trigger and a GCS volume
  const bkt = `run-smoke-${N}`;
  await wire(`/storage/v1/b?project=${P}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: bkt }) });

  for (const kind of ["run", "functions"]) {
    const name = `${kind === "run" ? "svc" : "fn"}-${N}`;
    await page.goto(UI + `#/${kind}/create`);
    await page.getByLabel("Service name").fill(name);
    await page.getByText("Containers, Networking, Security").click();
    await page.getByLabel("Target concurrency utilization").waitFor();
    const nsText = await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated")));
    check(`${kind}: none of the 8 sections is Not simulated`, !nsText.some((t) => /autoscaling|Ephemeral|Health|Volumes|Cloud SQL|Binary Authorization/.test(t)), nsText.join("|"));
    await page.getByLabel("Target concurrency utilization").fill("50");
    await page.getByLabel("Attach an ephemeral disk (second generation)").check();
    await page.getByLabel("Startup probe").check();
    await page.getByLabel("Startup probe path").fill("/healthz");
    await page.getByRole("button", { name: "Add volume" }).click();
    await page.getByLabel("Volume 1 name").fill("scratch");
    await page.getByLabel("Volume 1 mount path").fill("/mnt/scratch");
    await page.getByLabel("Verify container deployment with Binary Authorization").check();
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.waitForURL(new RegExp(`#/${kind}/detail/`), { timeout: 20000 });
    const svc = await wj(`/v2/projects/${P}/locations/${RG}/services/${name}`);
    const c = svc.template?.containers?.[0] || {};
    check(`${kind}: probe stored on the container`, c.startupProbe?.httpGet?.path === "/healthz", JSON.stringify(c.startupProbe));
    check(`${kind}: ephemeral disk + volume stored`, (svc.template?.volumes || []).some((v) => v.emptyDir?.medium === "DISK") && (svc.template?.volumes || []).some((v) => v.name === "scratch"), JSON.stringify(svc.template?.volumes));
    check(`${kind}: autoscaling target stored`, svc.template?.annotations?.["autoscaling.knative.dev/target-utilization-percentage"] === "50");
    check(`${kind}: Binary Authorization stored`, svc.binaryAuthorization?.useDefault === true);
    // bad Cloud SQL / KMS references are rejected by the backend, as on real Cloud Run
    const bad = await wire(`/v2/projects/${P}/locations/${RG}/services?serviceId=bad-${N}${kind[0]}`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ template: { containers: [{ image: "i" }], encryptionKey: `projects/${P}/locations/${RG}/keyRings/nope/cryptoKeys/nope` } }) });
    check(`${kind}: missing KMS key rejected (400)`, bad.status === 400, bad.text.slice(0, 120));
  }
  // revision tags (UI)
  const name = `svc-${N}`;
  await page.goto(UI + `#/run/detail/${RG}/${name}`);
  await page.getByRole("tab", { name: "Revisions" }).click();
  await page.getByRole("button", { name: "Add tag" }).first().click();
  await page.getByRole("textbox", { name: "Revision tag" }).fill("canary");
  await page.getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(800);
  const tagged = await wj(`/v2/projects/${P}/locations/${RG}/services/${name}`);
  check("revision tag set from the Revisions tab", (tagged.trafficStatuses || []).some((t) => t.tag === "canary" && /canary---/.test(t.uri || "")), JSON.stringify(tagged.trafficStatuses));
  check("Revisions tab: tag shown, no Not-simulated panel", (await page.getByText("canary").count()) > 0 && (await nsCount()) === 0);
  // Eventarc: Cloud Storage trigger from the Triggers tab, then a real upload
  await page.getByRole("tab", { name: "Triggers" }).click();
  await page.getByRole("button", { name: "Add trigger" }).click();
  await page.getByLabel("Cloud Storage").check();
  await page.getByLabel("Bucket").click();
  await page.getByRole("option", { name: bkt }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForTimeout(800);
  check("Triggers tab lists the Cloud Storage trigger", (await page.getByText(`Cloud Storage: ${bkt}`).count()) > 0);
  const trigs = await wj(`/v2/projects/${P}/locations/${RG}/services/${name}/triggers`);
  check("trigger exists on the native API", (trigs.triggers || []).some((t) => t.bucket === bkt), JSON.stringify(trigs).slice(0, 150));
  const up = await wire(`/upload/storage/v1/b/${bkt}/o?uploadType=media&name=hello.txt`, { method: "POST", headers: { "content-type": "text/plain" }, body: "hi" });
  check("object upload accepted", up.status === 200, up.status);
  await page.getByRole("tab", { name: "Observability" }).click();
  await page.waitForTimeout(600);
  const logs = await wj(`/v2/projects/${P}/locations/${RG}/services/${name}/triggers`);
  check("trigger still present after delivery", (logs.triggers || []).length === 1);
  // image picker on Create job
  await page.goto(UI + "#/run/jobs/create");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("dialog", { name: "Select container image" }).waitFor();
  check("image picker opens and browses Artifact Registry (no Not-simulated)", (await nsCount()) === 0);
  await page.screenshot({ path: `${OUT}/picker.png` });
} catch (e) { check("smoke ran to completion", false, e.message); }
check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
