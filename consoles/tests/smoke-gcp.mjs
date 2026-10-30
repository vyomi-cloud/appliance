/* End-to-end smoke of the GCP lens against a running /_wire backend (dev_server.py, the
 * offline appliance, or Nano). Drives the UI like a user; cross-checks state over the
 * native GCS JSON API (what google-cloud-storage / gsutil would see). Screenshots → $OUT.
 *
 *   BASE=http://127.0.0.1:8740 UI_PATH=/v4/gcp/ node consoles/tests/smoke-gcp.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";

const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); }
catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }

const BASE = process.env.BASE || "http://127.0.0.1:8740";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp";
const B = `v4-gcp-smoke-${Date.now() % 100000}`;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
let page;
// Native-wire cross-checks run INSIDE the page (same origin) — on Nano only the service
// worker answers /_wire, and it only sees requests from pages it controls.
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const wjson = async (path, init) => { const r = await wire(path, init); try { return JSON.parse(r.text || "{}"); } catch { return { raw: r.text, status: r.status }; } };

await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// Native 404s / 403s are legitimate API answers (e.g. a retention-protected delete), not page errors.
page.on("console", (m) => m.type() === "error" && !/status of 40[34]/.test(m.text()) && errors.push(m.text()));
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });

try {
  await page.goto(UI, { waitUntil: "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller, null, { timeout: 180000, polling: 500 });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
  check("home renders", await page.getByRole("button", { name: /Project picker: / }).isVisible());
  await shot("01-home");

  // Navigation menu lists products; an unbuilt product is an honest gap.
  await page.getByRole("button", { name: "Navigation menu" }).click();
  await page.locator(".MuiDrawer-paper").getByText("Pub/Sub", { exact: true }).click();
  await page.locator("[data-vyomi-not-simulated]").first().waitFor({ timeout: 5000 });
  check("non-v4 product → NotSimulated panel with classic link", await page.getByRole("link", { name: /classic Vyomi console/ }).isVisible());
  await shot("02-notsimulated-product");

  // Create a bucket through the form
  await page.goto(UI + "#/storage/create-bucket");
  await page.getByLabel("Bucket name").fill(B);
  await page.getByRole("button", { name: "Add label" }).click();
  await page.getByLabel("Key 1").fill("env");
  await page.getByLabel("Value 1").fill("smoke");
  await page.getByRole("radio", { name: /^Region —/ }).check();
  await page.getByRole("radio", { name: /^Nearline —/ }).check();
  await page.getByRole("checkbox", { name: "Set bucket retention policy" }).check();
  await page.getByLabel("Retention period").fill("1");
  await shot("03-create-filled");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: B }).waitFor({ timeout: 10000 });
  const list = await wjson("/storage/v1/b?project=vyomi-project");
  const nb = (list.items || []).find((x) => x.name === B);
  check("create bucket → visible over native wire (buckets.list)", !!nb);
  check("bucket settings applied (location, class, labels, retention, UBLA/PAP)",
    nb && nb.locationType === "region" && nb.location === "US-CENTRAL1" && nb.storageClass === "NEARLINE" && nb.labels?.env === "smoke"
      && nb.retentionPolicy?.retentionPeriod === "86400" && nb.iamConfiguration?.uniformBucketLevelAccess?.enabled === true
      && nb.iamConfiguration?.publicAccessPrevention === "enforced", JSON.stringify(nb || {}).slice(0, 200));
  await shot("04-bucket-objects-empty");

  // Upload via UI → readable via objects.get?alt=media
  await page.locator("input[type=file]").setInputFiles({ name: "hello.txt", mimeType: "text/plain", buffer: Buffer.from("hello gcp v4") });
  await page.getByRole("link", { name: "hello.txt" }).waitFor({ timeout: 10000 });
  const obj = await wire(`/storage/v1/b/${B}/o/hello.txt?alt=media`);
  check("upload → object readable over native wire", obj.text === "hello gcp v4", obj.text);

  // Object created over the wire (SDK → UI direction) + folder via UI
  await wire(`/upload/storage/v1/b/${B}/o?uploadType=media&name=${encodeURIComponent("logs/app.log")}`, { method: "POST", headers: { "content-type": "text/plain" }, body: "line1" });
  await page.getByRole("button", { name: "Create folder" }).click();
  await page.getByLabel("Folder name").fill("reports");
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("link", { name: "reports/" }).waitFor({ timeout: 10000 });
  await page.getByRole("link", { name: "logs/", exact: true }).waitFor({ timeout: 10000 });
  check("object created over wire → folder shown in UI", true);
  const folder = await wire(`/storage/v1/b/${B}/o/${encodeURIComponent("reports/")}`);
  check("UI create folder → placeholder object over wire", folder.status === 200, String(folder.status));
  await shot("05-objects");
  await page.getByRole("link", { name: "logs/", exact: true }).click();
  await page.getByRole("link", { name: "app.log" }).waitFor({ timeout: 10000 });
  check("folder navigation lists nested object", true);
  await page.getByRole("link", { name: "app.log" }).click();
  await page.getByText("gs://" + B + "/logs/app.log").waitFor({ timeout: 10000 });
  await shot("06-object-details");
  check("object details render (objects.get)", true);

  // Retention policy is enforced: deleting hello.txt via UI must fail with the native 403
  await page.goto(UI + `#/storage/browser/${B}`);
  await page.getByRole("checkbox", { name: "Select hello.txt" }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill("DELETE");
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByText(/retention policy/i).waitFor({ timeout: 10000 });
  check("delete under retention policy → native error shown, object kept", (await wire(`/storage/v1/b/${B}/o/hello.txt`)).status === 200);
  await shot("07-retention-blocked");
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

  // Tabs render (and Protection: remove the retention policy through the UI)
  for (const [id, label] of [["configuration", "Configuration"], ["permissions", "Permissions"], ["protection", "Protection"], ["lifecycle", "Lifecycle"], ["observability", "Observability"]]) {
    await page.getByRole("tab", { name: label }).click();
    await page.waitForTimeout(500);
    await shot(`08-tab-${id}`);
  }
  check("detail tabs render", true);

  // Lifecycle: add a rule via UI → lifecycle on the bucket over the wire
  await page.getByRole("tab", { name: "Lifecycle" }).click();
  await page.getByRole("button", { name: "Add a rule" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByText("30+ days since object was created").waitFor({ timeout: 10000 });
  const lc = await wjson(`/storage/v1/b/${B}`);
  check("lifecycle rule added via UI → buckets.get shows it", lc.lifecycle?.rule?.[0]?.action?.type === "Delete" && lc.lifecycle.rule[0].condition.age === 30);

  // Permissions: grant access → getIamPolicy shows the binding
  await page.getByRole("tab", { name: "Permissions" }).click();
  await page.getByRole("button", { name: "Grant access" }).click();
  await page.getByLabel("New principals").fill("user:dev@example.com");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByRole("cell", { name: "user:dev@example.com", exact: true }).waitFor({ timeout: 10000 });
  const pol = await wjson(`/storage/v1/b/${B}/iam`);
  check("grant access via UI → getIamPolicy shows binding", (pol.bindings || []).some((x) => x.role === "roles/storage.objectViewer" && x.members.includes("user:dev@example.com")));
  await shot("09-permissions-granted");

  // Configuration: label set over the wire appears in the UI
  await wire(`/storage/v1/b/${B}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ labels: { team: "core" } }) });
  await page.getByRole("tab", { name: "Configuration" }).click();
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByText("team: core").waitFor({ timeout: 10000 });
  check("label patched over wire → shown in Configuration", true);

  // Protection: remove retention, then delete the bucket from the list (UI)
  await page.getByRole("tab", { name: "Protection" }).click();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  await page.getByText("No retention policy is set on this bucket.").waitFor({ timeout: 10000 });
  check("retention removed via UI → buckets.get has none", !(await wjson(`/storage/v1/b/${B}`)).retentionPolicy);

  await page.goto(UI + "#/storage/browser");
  await page.getByRole("link", { name: B }).waitFor({ timeout: 10000 });
  await shot("10-buckets");
  check("bucket list shows new bucket", true);
  await page.getByRole("checkbox", { name: `Select ${B}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(B);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete bucket via UI → gone over native wire", (await wire(`/storage/v1/b/${B}`)).status === 404);

  // Kubernetes Engine: create an Autopilot cluster through the UI, cross-check over the
  // native Kubernetes Engine REST API, add a node pool over the wire and see it in the UI.
  const K = `v4-gcp-smoke-k8s-${Date.now() % 100000}`;
  const KL = "/v1/projects/vyomi-project/locations/us-central1";
  await page.goto(UI + "#/kubernetes/clusters/create");
  await page.getByLabel("Name").fill(K);
  await page.getByRole("radio", { name: "Stable channel" }).check();
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("heading", { name: K }).waitFor({ timeout: 10000 });
  const cl = await wjson(`${KL}/clusters/${K}`);
  check("create cluster via UI → visible over native wire (clusters.get)", cl.name === K && cl.autopilot?.enabled === true);
  check("release channel applied", cl.releaseChannel?.channel === "STABLE");
  await shot("12-cluster-details");

  // A Standard cluster with a node pool, created directly over the wire (the console only
  // builds the Autopilot create form — Standard clusters still render the same detail page).
  const K2 = `v4-gcp-smoke-std-${Date.now() % 100000}`;
  await wire(`${KL}/clusters`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ cluster: { name: K2, nodePools: [{ name: "wire-pool", initialNodeCount: 2, config: { machineType: "e2-medium" } }] } }) });
  await page.goto(UI + `#/kubernetes/clusters/us-central1/${K2}`);
  await page.getByRole("tab", { name: "Nodes" }).click();
  await page.getByRole("cell", { name: "wire-pool", exact: true }).waitFor({ timeout: 10000 });
  check("cluster + node pool created over wire → shown in UI", true);
  await shot("13-cluster-nodes");
  await wire(`${KL}/clusters/${K2}`, { method: "DELETE" });

  await page.goto(UI + "#/kubernetes/clusters");
  await page.getByRole("link", { name: K }).waitFor({ timeout: 10000 });
  check("cluster list shows new cluster", true);
  await page.getByRole("checkbox", { name: `Select us-central1/${K}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(K);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete cluster via UI → gone over native wire", (await wire(`${KL}/clusters/${K}`)).status === 404);

  // Not-simulated gaps carry the conformance attribute
  await page.goto(UI + "#/storage/monitoring");
  await page.locator("[data-vyomi-not-simulated]").first().waitFor({ timeout: 5000 });
  check("honest gap page carries data-vyomi-not-simulated", true);

  // Dark mode
  await page.goto(UI + "#/storage/browser");
  await page.getByRole("button", { name: "More options" }).click();          // ⋮ menu, as in the native top bar
  await page.getByRole("menuitem", { name: "Use dark theme" }).click();
  await page.waitForTimeout(500);
  check("dark mode persisted", (await page.evaluate(() => localStorage.getItem("vyomi.v4.mode"))) === "dark");
  await shot("11-dark");
  await page.evaluate(() => localStorage.setItem("vyomi.v4.mode", "light"));
} catch (e) {
  check("smoke run", false, e.message.split("\n")[0]);
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
