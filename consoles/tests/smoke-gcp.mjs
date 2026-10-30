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

  // Artifact Registry: create repository via UI → native wire, push sample package
  // (Vyomi's own quickstart — no real AR method creates package data), settings, delete
  const R = `v4-gcp-ar-smoke-${Date.now() % 100000}`;
  await page.goto(UI + "#/artifacts/create-repo");
  await page.getByLabel("Name").fill(R);
  await page.getByRole("radio", { name: "npm" }).check();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText(R, { exact: true }).waitFor({ timeout: 10000 });
  const repos = await wjson("/v1/projects/vyomi-project/locations/-/repositories");
  const nr = (repos.repositories || []).find((x) => x.name.endsWith(`/repositories/${R}`));
  check("create repository → visible over native wire (repositories.list, locations/-)", !!nr);
  check("repository format applied", nr?.format === "NPM", JSON.stringify(nr || {}).slice(0, 160));
  await shot("12-repo-detail");

  await page.getByRole("button", { name: "Push sample package" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByRole("link", { name: "sample-package" }).waitFor({ timeout: 10000 });
  check("push sample package via UI → visible in packages table", true);
  await shot("13-repo-packages");

  await page.goto(UI + "#/artifacts");
  await page.getByRole("link", { name: R }).waitFor({ timeout: 10000 });
  check("repositories list shows new repository", true);
  await page.getByRole("checkbox", { name: `Select ${R}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(R);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  const reposAfter = await wjson("/v1/projects/vyomi-project/locations/-/repositories");
  check("delete repository via UI → gone over native wire", !(reposAfter.repositories || []).some((x) => x.name.endsWith(`/repositories/${R}`)));

  // Settings: toggle redirection → native projectSettings round-trip
  await page.goto(UI + "#/artifacts/settings");
  // State persists across runs on a real appliance — start from "disabled".
  const disable = page.getByRole("button", { name: "Disable redirection" });
  if (await disable.waitFor({ timeout: 3000 }).then(() => true, () => false)) {
    await disable.click();
    await page.getByRole("button", { name: "Enable redirection" }).waitFor({ timeout: 10000 });
  }
  await page.getByRole("button", { name: "Enable redirection" }).click();
  await page.getByText("Redirection is enabled for this project.").waitFor({ timeout: 10000 });
  const settings = await wjson("/v1/projects/vyomi-project/projectSettings");
  check("settings toggle via UI → native projectSettings shows it", settings.legacyRedirectionState === "REDIRECTION_FROM_GCR_IO_ENABLED");
  await shot("14-artifacts-settings");
  // Cloud Logging: create a log bucket through the UI → visible over the native entries/buckets wire
  const LB = `v4-gcp-smoke-lb-${Date.now() % 100000}`;
  await page.goto(UI + "#/logs/storage/bucket");
  await page.getByLabel("Name").fill(LB);
  await page.getByRole("button", { name: "Create bucket" }).click();
  await page.getByRole("heading", { name: LB }).waitFor({ timeout: 10000 });
  const buckets = await wjson(`/v2/projects/vyomi-project/locations/-/buckets`);
  check("create log bucket via UI → visible over native wire (buckets.list)", (buckets.buckets || []).some((b) => b.name.endsWith(`/${LB}`)));
  await shot("12-log-bucket-details");

  // Reverse direction: write a log entry over the native wire → shown in the Logs Explorer
  const MSG = `v4 gcp smoke entry ${Date.now() % 100000}`;
  await wire("/v2/entries:write", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ logName: "projects/vyomi-project/logs/smoke", resource: { type: "global" }, entries: [{ severity: "ERROR", textPayload: MSG }] }),
  });
  await page.goto(UI + "#/logs/query");
  await page.getByText(MSG).waitFor({ timeout: 10000 });
  check("entry written over native wire → shown in Logs Explorer", true);
  await shot("13-logs-explorer");

  // Create a sink via the UI → visible over the native sinks wire
  const SINK = `v4-gcp-smoke-sink-${Date.now() % 100000}`;
  await page.goto(UI + "#/logs/router/sink");
  await page.getByLabel("Sink name").fill(SINK);
  await page.getByLabel("Select sink service").click();
  await page.getByRole("option", { name: "Cloud Storage bucket" }).click();
  await page.getByLabel("Sink destination").fill("v4-smoke-sink-bucket");
  await page.getByLabel("Build inclusion filter").fill('severity>="ERROR"');
  await page.getByRole("button", { name: "Create sink" }).click();
  await page.getByRole("link", { name: SINK }).waitFor({ timeout: 10000 });
  const sinks = await wjson(`/v2/projects/vyomi-project/sinks`);
  check("create sink via UI → visible over native wire (sinks.list)", (sinks.sinks || []).some((s) => s.name.endsWith(`/${SINK}`) && s.destination === "storage.googleapis.com/v4-smoke-sink-bucket"));
  await shot("14-log-router");
  // VPC network: create a network through the UI → visible over native wire (networks.list)
  const NET = `v4-gcp-net-${Date.now() % 100000}`;
  await page.goto(UI + "#/networking/networks/add");
  await page.getByLabel("Name").first().fill(NET);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: NET }).waitFor({ timeout: 10000 });
  const nets = await wjson("/compute/v1/projects/vyomi-project/global/networks");
  check("create VPC network → visible over native wire (networks.list)", (nets.items || []).some((n) => n.name === NET));
  await shot("12-network-created");

  // Subnet created over the wire (SDK → UI direction) → shown in the network's Subnets tab
  const SUB = `v4-gcp-sub-${Date.now() % 100000}`;
  await wire("/compute/v1/projects/vyomi-project/regions/us-central1/subnetworks", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: SUB, network: NET, ipCidrRange: "10.9.0.0/24" }),
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("cell", { name: SUB, exact: true }).waitFor({ timeout: 10000 });
  check("subnet created over wire → shown in UI (Subnets tab)", true);

  // Firewall rule created through the UI → visible over native wire, then deleted from the UI
  await page.goto(UI + "#/networking/firewall/add");
  const FW = `v4-gcp-fw-${Date.now() % 100000}`;
  await page.getByLabel("Name").fill(FW);
  await page.getByRole("combobox", { name: "Network" }).click();
  await page.getByRole("option", { name: NET }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("cell", { name: FW, exact: true }).waitFor({ timeout: 10000 });
  const fws = await wjson("/compute/v1/projects/vyomi-project/global/firewalls");
  check("create firewall rule via UI → visible over native wire (firewalls.list)", (fws.items || []).some((f) => f.name === FW));
  await page.getByRole("checkbox", { name: `Select ${FW}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FW);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete firewall rule via UI → gone over native wire", (await wire(`/compute/v1/projects/vyomi-project/global/firewalls/${FW}`)).status === 404);
  await shot("13-networking");

  // Delete the subnet (so the network can be deleted) then the network itself, from the UI
  await page.goto(UI + `#/networking/networks/details/${NET}`);
  await page.getByRole("checkbox", { name: new RegExp(`Select .*${SUB}`) }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("cell", { name: SUB, exact: true }).waitFor({ state: "detached", timeout: 10000 });
  await page.getByRole("button", { name: "Delete VPC network" }).click();
  await page.getByLabel("Confirm deletion").fill(NET);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("heading", { name: "VPC networks" }).waitFor({ timeout: 10000 });
  check("delete VPC network via UI → gone over native wire", (await wire(`/compute/v1/projects/vyomi-project/global/networks/${NET}`)).status === 404);
  // Compute Engine: create an instance via the UI → visible over the native wire (instances.list)
  const VM = `v4-gcp-smoke-vm-${Date.now() % 100000}`;
  await page.goto(UI + "#/compute/instances/create");
  await page.getByLabel("Name", { exact: true }).fill(VM);
  await shot("12-create-instance-filled");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: VM }).waitFor({ timeout: 10000 });
  const inst = await wjson(`/compute/v1/projects/vyomi-project/zones/us-central1-a/instances/${VM}`);
  check("create instance via UI → visible over native wire (instances.get)", inst.name === VM && inst.status === "RUNNING");
  await shot("13-instance-detail");

  // Lifecycle action from the detail page → status change visible over the wire
  await page.getByRole("button", { name: "Stop" }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).status === "TERMINATED",
    `${WIRE}/compute/v1/projects/vyomi-project/zones/us-central1-a/instances/${VM}`, { timeout: 10000 },
  );
  check("stop from instance detail → TERMINATED over native wire", true);

  // Disk created over the wire (SDK direction) → shown in the UI list
  const DISK = `v4-gcp-smoke-disk-${Date.now() % 100000}`;
  await wire("/compute/v1/projects/vyomi-project/zones/us-central1-a/disks", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: DISK, sizeGb: 10 }),
  });
  await page.goto(UI + "#/compute/disks");
  await page.getByText(DISK).waitFor({ timeout: 10000 });
  check("disk created over wire → shown in Disks UI", true);
  await shot("14-disks");

  // Delete the instance via the detail page → gone over the native wire
  await page.goto(UI + `#/compute/instances/us-central1-a/${VM}`);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(VM);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.waitForURL(/#\/compute\/instances$/, { timeout: 10000 });
  check("delete instance via UI → gone over native wire", (await wire(`/compute/v1/projects/vyomi-project/zones/us-central1-a/instances/${VM}`)).status === 404);
  // IAM & Admin: grant access via UI → native getIamPolicy shows it; create a service
  // account over the wire → shown in the UI list (both round-trip directions).
  const M = `smoke-${Date.now() % 100000}@example.com`;
  await page.goto(UI + "#/iam-admin/iam");
  await page.getByRole("button", { name: "Grant access" }).click();
  await page.getByLabel("New principals").fill(M);
  await page.getByLabel("Select a role").click();
  await page.getByRole("option", { name: "Viewer", exact: true }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText(M).waitFor({ timeout: 10000 });
  const iamPol = await wjson("/v1/projects/vyomi-project:getIamPolicy", { method: "POST", body: "{}" });
  check("IAM grant access via UI → native getIamPolicy shows binding", (iamPol.bindings || []).some((b) => b.role === "roles/viewer" && b.members.includes(`user:${M}`)));
  await shot("12-iam-allow");

  const SA = `smoke-sa-${Date.now() % 100000}`;
  await wire("/v1/projects/vyomi-project/serviceAccounts", { method: "POST", body: JSON.stringify({ accountId: SA, serviceAccount: { displayName: SA } }) });
  await page.goto(UI + "#/iam-admin/serviceaccounts");
  await page.getByText(`${SA}@vyomi-project.iam.gserviceaccount.com`).waitFor({ timeout: 10000 });
  check("service account created over wire → shown in UI list", true);
  await shot("13-service-accounts");

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

  // Cloud Scheduler: create a job through the wizard → visible over native jobs.list
  const J = `v4-gcp-job-${Date.now() % 100000}`;
  await page.goto(UI + "#/cloudscheduler/jobs/new");
  await page.getByLabel("Name").fill(J);
  await page.getByLabel("Frequency").fill("0 * * * *");
  await page.getByLabel("URL").fill("https://example.com/handler");
  await shot("12-scheduler-create-filled");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: J }).waitFor({ timeout: 10000 });
  const job = await wjson(`/v1/projects/vyomi-project/locations/us-central1/jobs/${J}`);
  check("create job → visible over native wire (jobs.get)", job.name?.endsWith(`/jobs/${J}`) && job.httpTarget?.uri === "https://example.com/handler");
  await shot("13-scheduler-detail");

  // Pause / resume / force run over the UI, each checked back over the wire
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await page.getByRole("button", { name: "Resume", exact: true }).waitFor({ timeout: 10000 });
  check("pause via UI → jobs.get shows PAUSED", (await wjson(`/v1/projects/vyomi-project/locations/us-central1/jobs/${J}`)).state === "PAUSED");
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await page.getByRole("button", { name: "Pause", exact: true }).waitFor({ timeout: 10000 });
  check("resume via UI → jobs.get shows ENABLED", (await wjson(`/v1/projects/vyomi-project/locations/us-central1/jobs/${J}`)).state === "ENABLED");
  await page.getByRole("button", { name: "Force run" }).click();
  await page.waitForTimeout(500);
  check("force run via UI → jobs.get shows a lastAttemptTime", !!(await wjson(`/v1/projects/vyomi-project/locations/us-central1/jobs/${J}`)).lastAttemptTime);

  // Edit: switch the target to Pub/Sub (a real topic, created over the wire) and save
  const T = `v4-gcp-topic-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/topics/${T}`, { method: "PUT", headers: { "content-type": "application/json" }, body: "{}" });
  await page.getByRole("link", { name: "Edit" }).click();
  await page.getByLabel("Target type").click();
  await page.getByRole("option", { name: "Pub/Sub" }).click();
  await page.getByLabel("Select a Cloud Pub/Sub topic").click();
  await page.getByRole("option", { name: `projects/vyomi-project/topics/${T}` }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByRole("heading", { name: J }).waitFor({ timeout: 10000 });
  const edited = await wjson(`/v1/projects/vyomi-project/locations/us-central1/jobs/${J}`);
  check("edit job target via UI → jobs.get shows pubsubTarget, httpTarget gone", edited.pubsubTarget?.topicName === `projects/vyomi-project/topics/${T}` && !edited.httpTarget);
  await shot("14-scheduler-edited");

  // Delete from the list
  await page.goto(UI + "#/cloudscheduler/jobs");
  await page.getByRole("link", { name: J }).waitFor({ timeout: 10000 });
  await page.getByRole("checkbox", { name: `Select projects/vyomi-project/locations/us-central1/jobs/${J}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(J);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete job via UI → gone over native wire", (await wire(`/v1/projects/vyomi-project/locations/us-central1/jobs/${J}`)).status === 404);
  // Firestore: create database → start a collection via the UI → cross-check the native wire,
  // then the reverse (a document created over the wire shows up in the Studio UI).
  const FSDB = `smoke-fs-${Date.now() % 100000}`;
  await page.goto(UI + "#/firestore/create-database");
  await page.getByLabel("Database ID").fill(FSDB);
  await page.getByRole("button", { name: "Create Database" }).click();
  await page.getByRole("heading", { name: "Firestore Studio" }).waitFor({ timeout: 10000 });
  check("create database via UI → visible over native wire (databases.list)",
    !!(await wjson(`/v1/projects/vyomi-project/databases`)).databases?.some((d) => d.name.endsWith(`/databases/${FSDB}`)));

  await page.getByRole("button", { name: "Start collection" }).click();
  await page.getByLabel("Collection ID").fill("smoke-items");
  await page.getByLabel("Document ID").fill("item-1");
  await page.getByLabel("Field name").fill("title");
  await page.getByLabel("Field value").fill("Smoke test item");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  await page.getByText("item-1", { exact: true }).waitFor({ timeout: 10000 });
  check("start collection via UI → readable over native wire",
    (await wjson(`/v1/projects/vyomi-project/databases/${FSDB}/documents/smoke-items/item-1`)).fields?.title?.stringValue === "Smoke test item");

  await wire(`/v1/projects/vyomi-project/databases/${FSDB}/documents/wire-coll?documentId=w1`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ fields: { k: { stringValue: "v" } } }),
  });
  // Nano saves to IndexedDB ~400 ms after a write (debounced); a reload inside that window
  // loses the write (known Nano limitation, tracked) — give the save time to land.
  await page.waitForTimeout(1500);
  await page.reload({ waitUntil: "networkidle" });
  // On Nano a reload re-boots the in-tab engine before the list can load — wait, don't sample.
  const wireColl = await page.getByText("wire-coll", { exact: true }).waitFor({ timeout: 20000 }).then(() => true, () => false);
  check("document created over wire → collection shown in Studio UI", wireColl);

  await page.goto(UI + "#/firestore/databases");
  await page.getByRole("link", { name: FSDB }).waitFor({ timeout: 10000 });
  await page.getByRole("checkbox", { name: `Select ${FSDB}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FSDB);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete database via UI → gone over native wire", (await wire(`/v1/projects/vyomi-project/databases/${FSDB}`)).status === 404);

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
