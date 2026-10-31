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
  // Nano keeps fetching its in-browser runtime after load, so "networkidle" can take minutes
  // there; wait for the page, then (below) for the backend to be ready.
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
  check("home renders", await page.getByRole("button", { name: /Project picker: / }).isVisible());
  await shot("01-home");

  // Navigation menu opens a product's v4 console (every GCP product now has one) …
  await page.getByRole("button", { name: "Navigation menu" }).click();
  await page.locator(".MuiDrawer-paper").getByText("Cloud SQL", { exact: true }).click();
  await page.waitForFunction(() => location.hash.startsWith("#/sql"), null, { timeout: 5000 });
  await page.waitForTimeout(1500);
  check("navigation menu → product opens its v4 console (no NotSimulated panel)",
    (await page.locator("[data-vyomi-not-simulated]").count()) === 0 || !(await page.getByText(/The v4 Cloud SQL console isn't backed/).count()));
  // … and an address no product owns is still an honest gap, not a blank page.
  await page.goto(UI + "#/no-such-product");
  await page.locator("[data-vyomi-not-simulated]").first().waitFor({ timeout: 5000 });
  check("unknown product → honest NotSimulated panel", true);
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

  // Cleanup policies are ENFORCED, not just stored: an unconditional "Delete artifacts"
  // policy added via the Edit dialog deletes a pushed version immediately.
  const CR = `v4-gcp-ar-cleanup-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/locations/us-central1/repositories?repositoryId=${CR}`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ format: "DOCKER" }) });
  await wire(`/v1/projects/vyomi-project/locations/us-central1/repositories/${CR}:pushSample`,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ image: "cleanup-me", tag: "v1" }) });
  await page.goto(UI + `#/artifacts/repo/us-central1/${CR}`);
  await page.getByRole("link", { name: "cleanup-me" }).waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Edit repository" }).click();
  const editDialog = page.getByRole("dialog", { name: "Edit repository" });
  await editDialog.getByRole("button", { name: "Add a cleanup policy" }).click();
  const policyDialog = page.getByRole("dialog", { name: "Add a cleanup policy" });
  await policyDialog.getByLabel("Policy name").fill("purge-all");
  await policyDialog.getByLabel("Older than (days)").fill("0");   // unconditional: matches regardless of age
  await policyDialog.getByRole("button", { name: "Add" }).click();
  await policyDialog.waitFor({ state: "detached", timeout: 10000 });
  await editDialog.getByRole("button", { name: "Save" }).click();
  await editDialog.waitFor({ state: "detached", timeout: 10000 });
  await page.getByText("No images in this repository yet.").waitFor({ timeout: 10000 });
  const crVersions = await wjson(`/v1/projects/vyomi-project/locations/us-central1/repositories/${CR}/packages/cleanup-me/versions`);
  check("cleanup policy via UI → version actually deleted over native wire", !(crVersions.versions || []).length,
    JSON.stringify(crVersions).slice(0, 160));
  await shot("13b-cleanup-policy-enforced");

  // Virtual repositories aggregate their upstreams — ENFORCED, not just stored config: the
  // UI's Repositories table shows images from two other repositories merged read-only.
  const VSTD1 = `v4-gcp-ar-vstd1-${Date.now() % 100000}`;
  const VSTD2 = `v4-gcp-ar-vstd2-${Date.now() % 100000}`;
  const VIRT = `v4-gcp-ar-virt-${Date.now() % 100000}`;
  for (const [id, image] of [[VSTD1, "from-std1"], [VSTD2, "from-std2"]]) {
    await wire(`/v1/projects/vyomi-project/locations/us-central1/repositories?repositoryId=${id}`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ format: "DOCKER" }) });
    await wire(`/v1/projects/vyomi-project/locations/us-central1/repositories/${id}:pushSample`,
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ image, tag: "v1" }) });
  }
  await page.goto(UI + "#/artifacts/create-repo");
  await page.getByLabel("Name").fill(VIRT);
  await page.getByRole("radio", { name: "Virtual" }).check();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: "Upstream repositories" }).waitFor({ timeout: 10000 });
  check("create virtual repository via UI → native wire", true);

  await page.getByRole("button", { name: "Add repository" }).click();
  let addDialog = page.getByRole("dialog", { name: "Add upstream repository" });
  await addDialog.getByLabel("Repository").click();
  await page.getByRole("option", { name: VSTD1 }).click();
  await addDialog.getByRole("button", { name: "Add" }).click();
  await addDialog.waitFor({ state: "detached", timeout: 10000 });

  await page.getByRole("button", { name: "Add repository" }).click();
  addDialog = page.getByRole("dialog", { name: "Add upstream repository" });
  await addDialog.getByLabel("Repository").click();
  await page.getByRole("option", { name: VSTD2 }).click();
  await addDialog.getByLabel("Priority").fill("5");
  await addDialog.getByRole("button", { name: "Add" }).click();
  await addDialog.waitFor({ state: "detached", timeout: 10000 });

  await page.getByRole("link", { name: "from-std1" }).waitFor({ timeout: 10000 });
  await page.getByRole("link", { name: "from-std2" }).waitFor({ timeout: 10000 });
  check("virtual repository aggregates both upstreams' images in the UI", true);
  check("virtual repository is read-only: no Push sample button", (await page.getByRole("button", { name: /Push sample/ }).count()) === 0);
  const virtImages = await wjson(`/v1/projects/vyomi-project/locations/us-central1/repositories/${VIRT}/dockerImages`);
  const virtNames = (virtImages.dockerImages || []).map((i) => i.name.split("/dockerImages/")[1]);
  check("virtual repository aggregation enforced over native wire (dockerImages)",
    virtNames.some((n) => n.startsWith("from-std1")) && virtNames.some((n) => n.startsWith("from-std2")), JSON.stringify(virtNames));
  await shot("13c-virtual-repository");

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

  // Managed instance group: create an instance template via the UI, then a managed group
  // off it with 2 instances → the group manager really stamps out 2 instances from the
  // template over the native wire. Resize down to 1 deletes one; delete the group cascades.
  const MIG_TPL = `v4-gcp-mig-tpl-${Date.now() % 100000}`;
  const MIG_NAME = `v4-gcp-mig-${Date.now() % 100000}`;
  await page.goto(UI + "#/compute/instance-templates");
  await page.getByRole("button", { name: "Create instance template" }).click();
  await page.getByLabel("Name", { exact: true }).fill(MIG_TPL);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("cell", { name: MIG_TPL, exact: true }).waitFor({ timeout: 10000 });

  await page.goto(UI + "#/compute/instance-groups");
  await page.getByRole("button", { name: "Create instance group" }).click();
  await page.getByRole("radio", { name: "New managed instance group" }).check();
  await page.getByLabel("Name", { exact: true }).fill(MIG_NAME);
  await page.getByRole("combobox", { name: "Instance template" }).click();
  await page.getByRole("option", { name: MIG_TPL }).click();
  await page.getByLabel("Number of instances").fill("2");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("cell", { name: MIG_NAME, exact: true }).waitFor({ timeout: 10000 });

  const migAgg1 = await wjson("/compute/v1/projects/vyomi-project/aggregated/instanceGroupManagers");
  const mig1 = Object.values(migAgg1.items || {}).flatMap((v) => v.instanceGroupManagers || []).find((m) => m.name === MIG_NAME);
  check("create managed instance group via UI → visible over native wire (instanceGroupManagers.get)", mig1?.targetSize === 2);
  const instAgg1 = await wjson("/compute/v1/projects/vyomi-project/aggregated/instances");
  const migMembers1 = Object.values(instAgg1.items || {}).flatMap((v) => v.instances || []).filter((i) => i.name.startsWith(`${MIG_NAME}-`));
  check("managed group stamped out real instances from the template", migMembers1.length === 2);
  await shot("15-managed-instance-group");

  await page.getByRole("button", { name: `Actions for ${MIG_NAME}` }).click();
  await page.getByRole("menuitem", { name: "Edit group size" }).click();
  await page.getByLabel("Number of instances").fill("1");
  await page.getByRole("button", { name: "Resize", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  const instAgg2 = await wjson("/compute/v1/projects/vyomi-project/aggregated/instances");
  const migMembers2 = Object.values(instAgg2.items || {}).flatMap((v) => v.instances || []).filter((i) => i.name.startsWith(`${MIG_NAME}-`));
  check("resize via UI → one member instance deleted over native wire", migMembers2.length === 1);

  await page.getByRole("checkbox", { name: `Select us-central1-a/${MIG_NAME}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(MIG_NAME);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete managed instance group via UI → gone over native wire",
    (await wire(`/compute/v1/projects/vyomi-project/zones/us-central1-a/instanceGroupManagers/${MIG_NAME}`)).status === 404);
  const instAgg3 = await wjson("/compute/v1/projects/vyomi-project/aggregated/instances");
  check("deleting managed instance group deletes its member instances too",
    !Object.values(instAgg3.items || {}).flatMap((v) => v.instances || []).some((i) => i.name.startsWith(`${MIG_NAME}-`)));

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
  await page.getByPlaceholder("Enter property name or value").first().fill(M);   // a long-lived space has >1 page of principals
  await page.getByText(M).first().waitFor({ timeout: 10000 });
  const iamPol = await wjson("/v1/projects/vyomi-project:getIamPolicy", { method: "POST", body: "{}" });
  check("IAM grant access via UI → native getIamPolicy shows binding", (iamPol.bindings || []).some((b) => b.role === "roles/viewer" && b.members.includes(`user:${M}`)));
  await shot("12-iam-allow");

  const SA = `smoke-sa-${Date.now() % 100000}`;
  await wire("/v1/projects/vyomi-project/serviceAccounts", { method: "POST", body: JSON.stringify({ accountId: SA, serviceAccount: { displayName: SA } }) });
  await page.goto(UI + "#/iam-admin/serviceaccounts");
  await page.getByText(`${SA}@vyomi-project.iam.gserviceaccount.com`).waitFor({ timeout: 10000 });
  check("service account created over wire → shown in UI list", true);
  await shot("13-service-accounts");

  // Privileged Access Manager: requesting a grant on an auto-approved entitlement via the
  // UI activates it immediately and really adds the IAM binding (cross-checked over the
  // native wire); an entitlement with an approver leaves the grant pending until the
  // Approve grants tab approves it, and revoking removes the binding again.
  const PAM_AUTO = `pam-auto-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/locations/global/entitlements?entitlementId=${PAM_AUTO}`, {
    method: "POST", body: JSON.stringify({ maxRequestDuration: "3600s", privilegedAccess: { gcpIamAccess: { roleBindings: [{ role: "roles/viewer" }] } } }),
  });
  const PAM_REQUESTER = `user:pam-${Date.now() % 100000}@example.com`;
  await page.goto(UI + "#/iam-admin/pam");
  await page.getByRole("tab", { name: "Grants", exact: true }).click();
  await page.getByRole("button", { name: "Request access" }).click();
  await page.getByLabel("Entitlement").click();
  await page.getByRole("option", { name: PAM_AUTO }).click();
  await page.getByLabel("Requester").fill(PAM_REQUESTER);
  await page.getByRole("button", { name: "Submit request" }).click();
  await page.getByText(PAM_REQUESTER).first().waitFor({ timeout: 10000 });
  const pamPolAfterGrant = await wjson("/v1/projects/vyomi-project:getIamPolicy", { method: "POST", body: "{}" });
  check("PAM request access via UI (auto-approved) → native getIamPolicy shows binding",
    (pamPolAfterGrant.bindings || []).some((b) => b.role === "roles/viewer" && b.members.includes(PAM_REQUESTER)));
  await shot("14-pam-grants");

  const PAM_APPROVAL = `pam-approval-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/locations/global/entitlements?entitlementId=${PAM_APPROVAL}`, {
    method: "POST",
    body: JSON.stringify({
      maxRequestDuration: "3600s", privilegedAccess: { gcpIamAccess: { roleBindings: [{ role: "roles/editor" }] } },
      approvalWorkflow: { manualApprovals: { steps: [{ approvers: [{ principals: ["user:boss@example.com"] }] }] } },
    }),
  });
  const PAM_REQUESTER2 = `user:pam2-${Date.now() % 100000}@example.com`;
  await page.goto(UI + "#/iam-admin/pam");
  await page.getByRole("tab", { name: "Grants", exact: true }).click();
  await page.getByRole("button", { name: "Request access" }).click();
  await page.getByLabel("Entitlement").click();
  await page.getByRole("option", { name: PAM_APPROVAL }).click();
  await page.getByLabel("Requester").fill(PAM_REQUESTER2);
  await page.getByRole("button", { name: "Submit request" }).click();
  await page.getByText(PAM_REQUESTER2).first().waitFor({ timeout: 10000 });
  const pamPolPending = await wjson("/v1/projects/vyomi-project:getIamPolicy", { method: "POST", body: "{}" });
  check("PAM grant awaiting approval → no binding yet", !(pamPolPending.bindings || []).some((b) => b.role === "roles/editor" && b.members.includes(PAM_REQUESTER2)));

  await page.getByRole("tab", { name: "Approve grants" }).click();
  await page.getByText(PAM_REQUESTER2).first().waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByText("No grants awaiting approval").waitFor({ timeout: 10000 });
  const pamPolApproved = await wjson("/v1/projects/vyomi-project:getIamPolicy", { method: "POST", body: "{}" });
  check("approve grant via UI → native getIamPolicy shows the binding",
    (pamPolApproved.bindings || []).some((b) => b.role === "roles/editor" && b.members.includes(PAM_REQUESTER2)));

  await page.getByRole("tab", { name: "Grants", exact: true }).click();
  await page.getByRole("row", { name: new RegExp(PAM_REQUESTER2) }).getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
  await page.waitForTimeout(500);
  const pamPolRevoked = await wjson("/v1/projects/vyomi-project:getIamPolicy", { method: "POST", body: "{}" });
  check("revoke grant via UI → native getIamPolicy drops the binding",
    !(pamPolRevoked.bindings || []).some((b) => b.role === "roles/editor" && b.members.includes(PAM_REQUESTER2)));
  await shot("15-pam-approve-grants");

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
  check("control plane access defaults to DNS + IPv4, public endpoint set",
    cl.controlPlaneEndpointsConfig?.dnsEndpointConfig?.allowExternalTraffic === true
    && cl.controlPlaneEndpointsConfig?.ipEndpointsConfig?.enabled === true && !!cl.endpoint);
  await shot("12-cluster-details");

  // Disable IPv4 control plane access via the Edit dialog — the public endpoint disappears
  // over the native wire; the DNS-based endpoint stays.
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Access using IPv4 addresses").uncheck();
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  const clNoIp = await wjson(`${KL}/clusters/${K}`);
  check("disable IPv4 access via UI → no public endpoint, DNS endpoint kept over native wire",
    clNoIp.controlPlaneEndpointsConfig?.ipEndpointsConfig?.enabled === false && clNoIp.endpoint === ""
    && !!clNoIp.controlPlaneEndpointsConfig?.dnsEndpointConfig?.endpoint);
  check("control plane access shown in Details tab", (await page.getByText("DNS", { exact: true }).count()) > 0);

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
  // Cloud Monitoring: create an uptime check through the UI wizard → visible over the
  // native wire (Cloud Monitoring REST API v3), and the reverse (wire → UI list).
  const UC = `v4-gcp-smoke-uptime-${Date.now() % 100000}`;
  await page.goto(UI + "#/monitoring/uptime/create");
  await page.getByLabel("Hostname").fill("example.com");
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Title").fill(UC);
  await shot("12-monitoring-create-uptime");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: "Uptime checks" }).waitFor({ timeout: 10000 });
  await page.getByText(UC).first().waitFor({ timeout: 10000 });
  const checks = await wjson(`/v3/projects/vyomi-project/uptimeCheckConfigs`);
  check("create uptime check via UI wizard → visible over native wire", (checks.uptimeCheckConfigs || []).some((c) => c.displayName === UC && c.httpCheck?.path === "/"));

  const DASH = `v4-gcp-smoke-dash-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/dashboards`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ displayName: DASH }) });
  await page.goto(UI + "#/monitoring/dashboards");
  await page.getByText(DASH).waitFor({ timeout: 10000 });
  check("dashboard created over wire → shown in UI list", true);
  await shot("13-monitoring-dashboards");

  // Cloud Monitoring depth: a dashboard tile built with a real timeSeriesFilter query
  // renders a live chart from stored time series (not a static shell), and a group's
  // membership is evaluated against the resource instances this project's own time series
  // have reported (not an always-empty stub).
  const METRIC = `custom.googleapis.com/smoke/${Date.now() % 100000}`;
  const dash2 = await wjson(`/v1/projects/vyomi-project/dashboards`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ displayName: `v4-gcp-smoke-dashlive-${Date.now() % 100000}`, mosaicLayout: { columns: 12, tiles: [{
      xPos: 0, yPos: 0, width: 6, height: 4, widget: { title: "Smoke CPU", xyChart: { dataSets: [{
        timeSeriesQuery: { timeSeriesFilter: { filter: `metric.type = "${METRIC}" AND resource.type = "global"` } },
      }] } },
    }] } }),
  });
  await wjson(`/v3/projects/vyomi-project/timeSeries`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ timeSeries: [{
      metric: { type: METRIC }, resource: { type: "global", labels: { project_id: "vyomi-project" } },
      points: [{ interval: { endTime: new Date().toISOString() }, value: { doubleValue: 42 } }],
    }] }),
  });
  await page.goto(UI + `#/monitoring/dashboards/${dash2.name.split("/").pop()}`);
  await page.getByText("Smoke CPU").waitFor({ timeout: 10000 });
  await page.locator("svg").first().waitFor({ timeout: 10000 });
  check("dashboard tile with a real query renders a live chart from stored time series", true);
  await shot("13b-monitoring-dashboard-live-chart");

  const GROUP = `v4-gcp-smoke-group-${Date.now() % 100000}`;
  await page.goto(UI + "#/monitoring/groups");
  await page.getByRole("button", { name: "Create Group" }).click();
  const groupDialog = page.getByRole("dialog");
  await groupDialog.getByLabel("Group name").fill(GROUP);
  await groupDialog.getByLabel("Filter").fill('resource.type = "global"');
  await groupDialog.getByRole("button", { name: "Create" }).click();
  const groupRow = page.getByRole("row", { name: new RegExp(GROUP) });
  await groupRow.waitFor({ timeout: 10000 });
  const groupCells = await groupRow.getByRole("cell").allTextContents();
  check("group membership shows a real resource count (not a static stub)", groupCells[2]?.trim() === "1", JSON.stringify(groupCells));
  await shot("13c-monitoring-group-members");

  // Cloud Run functions: create a service via the UI → visible over the native Cloud Run
  // Admin API v2 wire, then the reverse (a job created over the wire shows up in the UI).
  const FN = `v4-gcp-fn-${Date.now() % 100000}`;
  await page.goto(UI + "#/functions/create");
  await page.getByRole("radio", { name: "Use an inline editor to create a function" }).check();
  await page.getByLabel("Service name").fill(FN);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: FN, exact: true }).waitFor({ timeout: 10000 });
  const fnWire = await wjson(`/v2/projects/vyomi-project/locations/us-central1/services/${FN}`);
  check("create function via UI → visible over native Cloud Run wire", fnWire.name?.endsWith(`/services/${FN}`), JSON.stringify(fnWire).slice(0, 200));
  check("function deploy sets a container image (inline-source placeholder)", !!fnWire.template?.containers?.[0]?.image);
  const fnPolicy = await wjson(`/v2/projects/vyomi-project/locations/us-central1/services/${FN}:getIamPolicy`);
  check("Allow public access → setIamPolicy grants allUsers run.invoker", (fnPolicy.bindings || []).some((b) => b.role === "roles/run.invoker" && b.members?.includes("allUsers")));
  await shot("12-function-created");

  // Editing a function's source and clicking "Save and redeploy" must actually redeploy: the
  // native API cuts a real new revision (not just store the edited text on the service).
  await page.goto(UI + `#/functions/detail/us-central1/${FN}?tab=source`);
  await page.getByRole("button", { name: "Edit source" }).click();
  await page.getByLabel("Source files").fill("exports.handler = (event) => ({ redeployed: true });\n");
  await page.getByRole("button", { name: "Save and redeploy" }).click();
  await page.getByRole("button", { name: "Edit source" }).waitFor({ timeout: 10000 });
  const fnRevs = await wjson(`/v2/projects/vyomi-project/locations/us-central1/services/${FN}/revisions`);
  check("editing function source redeploys a real new revision", (fnRevs.revisions || []).length === 2, JSON.stringify(fnRevs).slice(0, 200));
  await shot("12b-function-source-redeployed");

  const JOB = `v4-gcp-job-${Date.now() % 100000}`;
  await wire("/v2/projects/vyomi-project/locations/us-central1/jobs?jobId=" + JOB, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ template: { template: { containers: [{ image: "us-docker.pkg.dev/cloudrun/container/hello" }] } } }),
  });
  await page.goto(UI + "#/functions/jobs");
  await page.getByRole("cell", { name: JOB, exact: true }).waitFor({ timeout: 10000 });
  check("job created over wire → shown in Jobs UI", true);
  await shot("13-jobs");

  await page.goto(UI + "#/functions/services");
  await page.getByRole("checkbox", { name: `Select ${FN}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(FN);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete function via UI → gone over native wire", (await wire(`/v2/projects/vyomi-project/locations/us-central1/services/${FN}`)).status === 404);

  // Cloud Run: create a service via the UI → visible over the native Cloud Run Admin API v2
  // wire, then the reverse (a job created over the wire shows up in the UI jobs list).
  const RUNSVC = `v4-gcp-run-${Date.now() % 100000}`;
  await page.goto(UI + "#/run/create");
  await page.getByLabel("Service name").fill(RUNSVC);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: RUNSVC, exact: true }).waitFor({ timeout: 10000 });
  const runSvcWire = await wjson(`/v2/projects/vyomi-project/locations/us-central1/services/${RUNSVC}`);
  check("create service via UI → visible over native Cloud Run wire", runSvcWire.name?.endsWith(`/services/${RUNSVC}`), JSON.stringify(runSvcWire).slice(0, 200));
  const runSvcPolicy = await wjson(`/v2/projects/vyomi-project/locations/us-central1/services/${RUNSVC}:getIamPolicy`);
  check("Allow public access → setIamPolicy grants allUsers run.invoker", (runSvcPolicy.bindings || []).some((b) => b.role === "roles/run.invoker" && b.members?.includes("allUsers")));
  await shot("14-run-service-created");

  // Cloud Run depth: editing a function-source service's Source tab and clicking "Save and
  // redeploy" must actually redeploy — the native API cuts a real new revision — not just
  // store the edited text on the service.
  const RUNFN = `v4-gcp-run-fn-${Date.now() % 100000}`;
  await page.goto(UI + "#/run/create");
  await page.getByRole("radio", { name: "Use an inline editor to create a function" }).check();
  await page.getByLabel("Service name").fill(RUNFN);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: RUNFN, exact: true }).waitFor({ timeout: 10000 });
  await page.goto(UI + `#/run/detail/us-central1/${RUNFN}?tab=source`);
  await page.getByRole("button", { name: "Edit source" }).click();
  await page.getByLabel("Source files").fill("exports.handler = (event) => ({ redeployed: true });\n");
  await page.getByRole("button", { name: "Save and redeploy" }).click();
  await page.getByRole("button", { name: "Edit source" }).waitFor({ timeout: 10000 });
  const runFnRevs = await wjson(`/v2/projects/vyomi-project/locations/us-central1/services/${RUNFN}/revisions`);
  check("editing Cloud Run function source redeploys a real new revision", (runFnRevs.revisions || []).length === 2, JSON.stringify(runFnRevs).slice(0, 200));
  await shot("14b-run-source-redeployed");

  const RUNJOB = `v4-gcp-run-job-${Date.now() % 100000}`;
  await wire(`/v2/projects/vyomi-project/locations/us-central1/jobs?jobId=${RUNJOB}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ template: { template: { containers: [{ image: "us-docker.pkg.dev/cloudrun/container/hello" }] } } }),
  });
  await page.goto(UI + "#/run/jobs");
  await page.getByRole("cell", { name: RUNJOB, exact: true }).waitFor({ timeout: 10000 });
  check("job created over wire → shown in Cloud Run Jobs UI", true);
  await shot("14-run-jobs");

  // Cloud Run depth: a Cloud Scheduler trigger added from the Job detail's Triggers tab
  // really fires the job — "Run now" starts a real execution, not just a stored binding.
  await page.goto(UI + `#/run/jobs/details/us-central1/${RUNJOB}?tab=triggers`);
  await page.getByRole("button", { name: "Add trigger" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByRole("button", { name: "Run now" }).waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "Run now" }).click();
  await page.getByRole("cell", { name: "Succeeded" }).waitFor({ timeout: 10000 });
  const runJobAfterTrigger = await wjson(`/v2/projects/vyomi-project/locations/us-central1/jobs/${RUNJOB}`);
  check("Cloud Scheduler trigger really starts a Cloud Run job execution", runJobAfterTrigger.executionCount === 1, JSON.stringify(runJobAfterTrigger).slice(0, 200));
  await shot("14c-run-job-trigger-fired");

  await page.goto(UI + "#/run/services");
  await page.getByRole("checkbox", { name: `Select ${RUNSVC}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(RUNSVC);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete service via UI → gone over native wire", (await wire(`/v2/projects/vyomi-project/locations/us-central1/services/${RUNSVC}`)).status === 404);

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

  // Cloud KMS: create a key ring + key through the UI → native Cloud KMS REST wire, then
  // version lifecycle (rotate, disable, make primary, destroy, restore), labels, rotation
  // period and IAM permissions — all round-tripped back over the wire.
  const KR = `v4-gcp-kms-ring-${Date.now() % 100000}`;
  await page.goto(UI + "#/security/kms/keyring/create");
  await page.getByLabel("Key ring name").fill(KR);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: KR }).waitFor({ timeout: 10000 });
  const krWire = await wjson(`/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}`);
  check("create key ring via UI → visible over native wire (keyRings.get)", krWire.name?.endsWith(`/keyRings/${KR}`));
  await shot("15-kms-keyring-created");

  const KK = `v4-gcp-kms-key-${Date.now() % 100000}`;
  await page.goto(UI + `#/security/kms/key/create?location=us-central1&keyring=${KR}`);
  await page.getByLabel("Key name").fill(KK);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: KK }).waitFor({ timeout: 10000 });
  const keyWire = await wjson(`/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}`);
  check("create key via UI → visible over native wire (cryptoKeys.get)",
    keyWire.name?.endsWith(`/cryptoKeys/${KK}`) && keyWire.purpose === "ENCRYPT_DECRYPT"
      && keyWire.versionTemplate?.algorithm === "GOOGLE_SYMMETRIC_ENCRYPTION" && keyWire.rotationPeriod === "2592000s",
    JSON.stringify(keyWire).slice(0, 200));
  await shot("16-kms-key-created");

  // Reverse direction: a key created over the wire shows up in the Key inventory UI.
  const KK2 = `v4-gcp-kms-key2-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys?cryptoKeyId=${KK2}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ purpose: "ENCRYPT_DECRYPT", versionTemplate: { algorithm: "GOOGLE_SYMMETRIC_ENCRYPTION" } }),
  });
  await page.goto(UI + "#/security/kms/key-inventory");
  await page.getByRole("link", { name: KK2 }).waitFor({ timeout: 10000 });
  check("key created over wire → shown in Key inventory UI", true);
  await shot("17-kms-inventory");

  await page.goto(UI + "#/security/kms/keyrings");
  await page.getByRole("link", { name: KR }).waitFor({ timeout: 10000 });
  check("key ring list shows new key ring", true);

  // Key detail: rotate (new primary version), disable/make-primary/destroy/restore versions.
  await page.goto(UI + `#/security/kms/key/manage/us-central1/${KR}/${KK}`);
  await page.getByRole("heading", { name: KK }).waitFor({ timeout: 10000 });
  await shot("18-kms-key-detail");

  await page.getByRole("button", { name: "Rotate key" }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).primary?.name?.endsWith("/cryptoKeyVersions/2"),
    `${WIRE}/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}`, { timeout: 10000 },
  );
  check("rotate key via UI → primary version advances to 2", true);

  await page.getByRole("button", { name: "Actions for version 2" }).click();
  await page.getByRole("menuitem", { name: "Disable" }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).state === "DISABLED",
    `${WIRE}/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}/cryptoKeyVersions/2`, { timeout: 10000 },
  );
  check("disable version via UI → cryptoKeyVersions.get shows DISABLED", true);

  await page.getByRole("button", { name: "Actions for version 1" }).click();
  await page.getByRole("menuitem", { name: "Make primary" }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).primary?.name?.endsWith("/cryptoKeyVersions/1"),
    `${WIRE}/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}`, { timeout: 10000 },
  );
  check("make primary via UI → primary is version 1", true);

  await page.getByRole("button", { name: "Actions for version 2" }).click();
  await page.getByRole("menuitem", { name: "Destroy" }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).state === "DESTROY_SCHEDULED",
    `${WIRE}/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}/cryptoKeyVersions/2`, { timeout: 10000 },
  );
  check("destroy version via UI → DESTROY_SCHEDULED", true);
  await shot("19-kms-versions");

  await page.getByRole("checkbox", { name: "Select 2" }).check();
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).state === "DISABLED",
    `${WIRE}/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}/cryptoKeyVersions/2`, { timeout: 10000 },
  );
  check("restore version via UI (bulk) → DISABLED", true);

  // Overview: edit labels + rotation period
  await page.getByRole("tab", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Edit labels" }).click();
  await page.getByRole("button", { name: "Add label" }).click();
  await page.getByLabel("Key 1").fill("env");
  await page.getByLabel("Value 1").fill("smoke");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText("env: smoke").waitFor({ timeout: 10000 });
  let kv = await wjson(`/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}`);
  check("edit labels via UI → cryptoKeys.get shows label", kv.labels?.env === "smoke");

  await page.getByRole("button", { name: "Edit rotation period" }).click();
  await page.getByLabel("Key rotation period").click();
  await page.getByRole("option", { name: "365 days" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).rotationPeriod === "31536000s",
    `${WIRE}/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}`, { timeout: 10000 },
  );
  check("edit rotation period via UI → cryptoKeys.get shows new period", true);
  await shot("20-kms-overview");

  // Permissions: grant access via UI → native getIamPolicy shows the binding
  await page.getByRole("tab", { name: "Permissions" }).click();
  await page.getByRole("button", { name: "Grant access" }).click();
  await page.getByLabel("New principals").fill("user:dev@example.com");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText("user:dev@example.com").waitFor({ timeout: 10000 });
  const kmsPol = await wjson(`/v1/projects/vyomi-project/locations/us-central1/keyRings/${KR}/cryptoKeys/${KK}:getIamPolicy`);
  check("grant access via UI → getIamPolicy shows binding",
    (kmsPol.bindings || []).some((b) => b.role === "roles/cloudkms.cryptoKeyEncrypterDecrypter" && b.members.includes("user:dev@example.com")));
  await shot("21-kms-permissions");
  // Secret Manager: create a secret (with an initial value) via the UI → visible over the
  // native wire; add a version from the detail page; a version added over the wire shows up
  // in the UI; delete from the list → gone over the native wire.
  const SM = `v4-gcp-sm-${Date.now() % 100000}`;
  await page.goto(UI + "#/security/secret-manager/create");
  await page.getByLabel("Name").fill(SM);
  await page.getByLabel("Secret value").fill("smoke-value-1");
  await page.getByRole("button", { name: "Create secret", exact: true }).click();
  await page.getByRole("heading", { name: SM }).waitFor({ timeout: 10000 });
  const sec = await wjson(`/v1/projects/vyomi-project/secrets/${SM}`);
  check("create secret via UI → visible over native wire (secrets.get)", sec.name?.endsWith(`/secrets/${SM}`));
  const v1 = await wjson(`/v1/projects/vyomi-project/secrets/${SM}/versions/latest:access`);
  check("initial value accessible over native wire", Buffer.from(v1.payload?.data || "", "base64").toString() === "smoke-value-1");
  await shot("12-secret-detail");

  // Add a version through the UI → the latest value changes over the native wire
  await page.getByRole("button", { name: "New version", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Secret value").fill("smoke-value-2");
  await page.getByRole("dialog").getByRole("button", { name: "Add new version", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  await page.getByRole("cell", { name: "2", exact: true }).waitFor({ timeout: 10000 });
  const v2 = await wjson(`/v1/projects/vyomi-project/secrets/${SM}/versions/latest:access`);
  check("add version via UI → latest value over native wire", Buffer.from(v2.payload?.data || "", "base64").toString() === "smoke-value-2");
  await shot("13-secret-versions");

  // Reverse direction: add a version over the wire → shown in the UI's Versions table
  await wire(`/v1/projects/vyomi-project/secrets/${SM}:addVersion`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ payload: { data: Buffer.from("smoke-value-3").toString("base64") } }),
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("cell", { name: "3", exact: true }).waitFor({ timeout: 10000 });
  check("version added over wire → shown in UI versions table", true);

  // Delete from the list → gone over the native wire
  await page.goto(UI + "#/security/secret-manager");
  await page.getByRole("link", { name: SM }).waitFor({ timeout: 10000 });
  await page.getByRole("checkbox", { name: `Select projects/vyomi-project/secrets/${SM}` }).check();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(SM);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete secret via UI → gone over native wire", (await wire(`/v1/projects/vyomi-project/secrets/${SM}`)).status === 404);

  // Secret Manager DEPTH: Permissions is a real, ENFORCED per-secret IAM policy (unlike KMS/
  // Pub/Sub's store-only policy) — grant access via the UI, then prove the native wire
  // actually denies an ungranted principal and allows the granted one. Logs is real too: an
  // addVersion event over the wire shows up as a log entry in the Logs tab.
  const SM2 = `v4-gcp-sm2-${Date.now() % 100000}`;
  await page.goto(UI + "#/security/secret-manager/create");
  await page.getByLabel("Name").fill(SM2);
  await page.getByRole("button", { name: "Create secret", exact: true }).click();
  await page.getByRole("heading", { name: SM2 }).waitFor({ timeout: 10000 });
  await wire(`/v1/projects/vyomi-project/secrets/${SM2}:addVersion`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ payload: { data: Buffer.from("smoke-value").toString("base64") } }),
  });
  await page.getByRole("tab", { name: "Permissions" }).click();
  await page.getByRole("button", { name: "Grant access" }).click();
  await page.getByLabel("New principals").fill("user:sm-smoke@example.com");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByText("user:sm-smoke@example.com").first().waitFor({ timeout: 10000 });
  const deniedResp = await wire(`/v1/projects/vyomi-project/secrets/${SM2}/versions/latest:access`,
    { headers: { "X-Cloudlearn-Principal": "someone-else@example.com" } });
  const allowedResp = await wire(`/v1/projects/vyomi-project/secrets/${SM2}/versions/latest:access`,
    { headers: { "X-Cloudlearn-Principal": "sm-smoke@example.com" } });
  check("grant access via UI → native wire denies an ungranted principal", deniedResp.status === 403);
  check("grant access via UI → native wire allows the granted principal", allowedResp.status === 200);
  await shot("14-secret-permissions");

  await wire(`/v1/projects/vyomi-project/secrets/${SM2}:addVersion`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ payload: { data: Buffer.from("smoke-value").toString("base64") } }),
  });
  await page.getByRole("tab", { name: "Logs" }).click();
  await page.getByText("Version added").first().waitFor({ timeout: 10000 });
  check("version added over native wire → shown as a real log entry in the Logs tab",
    (await page.getByText("Version added").count()) === 2);
  await shot("15-secret-logs");

  // Cloud SQL: create instance via UI → native Admin API, add a database over the wire →
  // shown in the UI, then delete the instance via UI → gone over the wire.
  const SQLI = `v4-gcp-sql-${Date.now() % 100000}`;
  await page.goto(UI + "#/sql/create/instance?engine=POSTGRES");
  await page.getByLabel("Instance ID").fill(SQLI);
  await page.getByLabel("Password", { exact: true }).fill("Sm0ke-Passw0rd!");
  await page.getByRole("button", { name: "Create instance", exact: true }).click();
  await page.getByRole("heading", { name: SQLI }).waitFor({ timeout: 10000 });
  const sqlInstances = await wjson(`/sql/v1beta4/projects/vyomi-project/instances`);
  check("create instance via UI → visible over native wire (instances.list)", (sqlInstances.items || []).some((i) => i.name === SQLI));
  await shot("15-sql-instance-overview");

  const SQLDB = `wiredb${Date.now() % 100000}`;
  await wire(`/sql/v1beta4/projects/vyomi-project/instances/${SQLI}/databases`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: SQLDB }),
  });
  await page.goto(UI + `#/sql/instances/${SQLI}/databases`);
  await page.getByText(SQLDB, { exact: true }).waitFor({ timeout: 10000 });
  check("database created over wire → shown in Databases UI", true);

  // Read replica created via UI mirrors the primary's existing database immediately
  // (gcp.sql.replicas: control-plane metadata mirrors on every primary write).
  const SQLREP = `${SQLI}-rep`;
  await page.goto(UI + `#/sql/instances/${SQLI}/replicas`);
  await page.getByRole("button", { name: "Create read replica" }).click();
  await page.getByLabel("Replica instance ID").fill(SQLREP);
  await page.getByRole("dialog").getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("link", { name: SQLREP }).waitFor({ timeout: 10000 });
  const repDbs = await wjson(`/sql/v1beta4/projects/vyomi-project/instances/${SQLREP}/databases`);
  check("replica created via UI → seeded with primary's database over native wire", (repDbs.items || []).some((d) => d.name === SQLDB));
  await shot("15b-sql-replica");

  // Backup via UI → delete the database over the wire → Restore via UI brings it back
  // (gcp.sql.backups: backupRun snapshot + instances.restoreBackup).
  await page.goto(UI + `#/sql/instances/${SQLI}/backups`);
  const backupPost = page.waitForResponse((r) => r.request().method() === "POST" && /\/backupRuns$/.test(r.url().split("?")[0]), { timeout: 15000 });
  await page.getByRole("button", { name: "Create backup" }).click();
  await backupPost;
  await page.getByRole("button", { name: "Restore", exact: true }).first().waitFor({ timeout: 10000 });
  await wire(`/sql/v1beta4/projects/vyomi-project/instances/${SQLI}/databases/${SQLDB}`, { method: "DELETE" });
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Restore", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  const restoredDbs = await wjson(`/sql/v1beta4/projects/vyomi-project/instances/${SQLI}/databases`);
  check("restore backup via UI → deleted database reappears over native wire", (restoredDbs.items || []).some((d) => d.name === SQLDB));
  await shot("15c-sql-restore");

  // A primary can't be deleted while it has live replicas (native restriction) —
  // delete the replica over the wire first, then the primary via the UI below.
  await wire(`/sql/v1beta4/projects/vyomi-project/instances/${SQLREP}`, { method: "DELETE" });

  await page.goto(UI + `#/sql/instances/${SQLI}/overview`);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(SQLI);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("heading", { name: "Instances" }).waitFor({ timeout: 10000 });
  check("delete instance via UI → gone over native wire", (await wire(`/sql/v1beta4/projects/vyomi-project/instances/${SQLI}`)).status === 404);
  // Pub/Sub: create a topic via the UI (with its default subscription) → native wire,
  // publish a message via the UI, publish over the wire → pull+ack in the UI, snapshot,
  // then delete both resources via the UI.
  const PST = `v4-gcp-ps-smoke-${Date.now() % 100000}`;
  await page.goto(UI + "#/pubsub/topics/create");
  await page.getByLabel("Topic ID").fill(PST);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: PST }).waitFor({ timeout: 10000 });
  const psTopics = await wjson(`/v1/projects/vyomi-project/topics`);
  check("create topic via UI → visible over native wire (topics.list)", (psTopics.topics || []).some((t) => t.name.endsWith(`/topics/${PST}`)));
  await shot("15-pubsub-topic");

  await page.getByRole("tab", { name: "Subscriptions" }).click();
  await page.getByRole("link", { name: `${PST}-sub` }).waitFor({ timeout: 10000 });
  check("default subscription created alongside topic", true);

  // Publish a message via the UI → readable over the native wire (subscriptions.pull)
  await page.getByRole("tab", { name: "Messages" }).click();
  await page.getByRole("link", { name: "Publish message" }).click();
  const PMSG = `v4 pubsub smoke ${Date.now() % 100000}`;
  await page.getByLabel("Message body").fill(PMSG);
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await page.getByRole("heading", { name: PST }).waitFor({ timeout: 10000 });
  const pulled = await wjson(`/v1/projects/vyomi-project/subscriptions/${PST}-sub:pull`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ maxMessages: 10 }),
  });
  check("publish via UI → readable over native wire (subscriptions.pull)",
    (pulled.receivedMessages || []).some((m) => Buffer.from(m.message.data, "base64").toString() === PMSG));
  await page.getByRole("tab", { name: "Messages" }).click();
  await page.getByText(PMSG).waitFor({ timeout: 10000 });
  check("published message shown in topic's Messages tab", true);
  await shot("16-pubsub-published");

  // Message published over the wire (SDK direction) → pulled + acked in the UI
  const PMSG2 = `v4 pubsub wire-to-ui ${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/topics/${PST}:publish`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [{ data: Buffer.from(PMSG2).toString("base64") }] }),
  });
  await page.goto(UI + `#/pubsub/subscriptions/${PST}-sub`);
  await page.getByRole("tab", { name: "Messages" }).click();
  await page.getByRole("checkbox", { name: "Enable ack messages" }).check();
  await page.getByRole("button", { name: "Pull" }).click();
  await page.getByText(PMSG2).waitFor({ timeout: 10000 });
  check("message published over wire → pulled in the UI", true);
  await shot("17-pubsub-pull");
  const afterAck = await wjson(`/v1/projects/vyomi-project/subscriptions/${PST}-sub:pull`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ maxMessages: 10 }),
  });
  check("auto-ack via UI → message gone over native wire", !(afterAck.receivedMessages || []).length);

  // Snapshot via the UI → visible over the native wire
  await page.goto(UI + "#/pubsub/snapshots");
  await page.getByRole("button", { name: "Create snapshot" }).click();
  const PSNAP = `${PST}-snap`;
  await page.getByLabel("Snapshot ID").fill(PSNAP);
  await page.getByLabel("Subscription").click();
  await page.getByRole("option", { name: `${PST}-sub` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText(PSNAP, { exact: true }).waitFor({ timeout: 10000 });
  const psSnaps = await wjson(`/v1/projects/vyomi-project/snapshots`);
  check("create snapshot via UI → visible over native wire (snapshots.list)", (psSnaps.snapshots || []).some((s) => s.name.endsWith(`/snapshots/${PSNAP}`)));
  await shot("18-pubsub-snapshot");

  // Delete the subscription, then the topic, both via their detail pages
  await page.goto(UI + `#/pubsub/subscriptions/${PST}-sub`);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(`${PST}-sub`);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete subscription via UI → gone over native wire", (await wire(`/v1/projects/vyomi-project/subscriptions/${PST}-sub`)).status === 404);

  await page.goto(UI + `#/pubsub/topics/${PST}`);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByLabel("Confirm deletion").fill(PST);
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").waitFor({ state: "detached", timeout: 10000 });
  check("delete topic via UI → gone over native wire", (await wire(`/v1/projects/vyomi-project/topics/${PST}`)).status === 404);

  // Schemas: create via the UI → visible over the native wire
  await page.goto(UI + "#/pubsub/schemas");
  await page.getByRole("button", { name: "Create schema" }).click();
  const PSCHEMA = `v4-gcp-ps-schema-${Date.now() % 100000}`;
  await page.getByLabel("Schema ID").fill(PSCHEMA);
  await page.getByLabel("Definition").fill('{"type":"record","name":"Smoke","fields":[]}');
  await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.getByText(PSCHEMA, { exact: true }).waitFor({ timeout: 10000 });
  const psSchemas = await wjson(`/v1/projects/vyomi-project/schemas`);
  check("create schema via UI → visible over native wire (schemas.list)", (psSchemas.schemas || []).some((s) => s.name.endsWith(`/schemas/${PSCHEMA}`)));
  await shot("19-pubsub-schema");

  // Subscription filter (DEPTH): a subscription created in the UI with a filter only
  // receives messages (published over the native wire) whose attributes match it.
  const PFTOPIC = `v4-gcp-ps-filter-topic-${Date.now() % 100000}`;
  await wire(`/v1/projects/vyomi-project/topics/${PFTOPIC}`, { method: "PUT", headers: { "content-type": "application/json" }, body: "{}" });
  await page.goto(UI + "#/pubsub/subscriptions/create");
  const PFSUB = `v4-gcp-ps-filter-sub-${Date.now() % 100000}`;
  await page.getByLabel("Subscription ID").fill(PFSUB);
  await page.getByLabel("Select a Cloud Pub/Sub topic").click();
  await page.getByRole("option", { name: PFTOPIC }).click();
  await page.getByLabel("Subscription filter").fill('attributes.kind = "keep"');
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByRole("heading", { name: PFSUB }).waitFor({ timeout: 10000 });
  const pfSub = await wjson(`/v1/projects/vyomi-project/subscriptions/${PFSUB}`);
  check("subscription filter set via UI → stored over native wire", pfSub.filter === 'attributes.kind = "keep"');

  await wire(`/v1/projects/vyomi-project/topics/${PFTOPIC}:publish`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages: [
      { data: Buffer.from("keep-this").toString("base64"), attributes: { kind: "keep" } },
      { data: Buffer.from("drop-this").toString("base64"), attributes: { kind: "drop" } },
    ] }),
  });
  await page.goto(UI + `#/pubsub/subscriptions/${PFSUB}`);
  await page.getByRole("tab", { name: "Messages" }).click();
  await page.getByRole("button", { name: "Pull" }).click();
  await page.getByText("keep-this").waitFor({ timeout: 10000 });
  check("subscription filter: the matching message arrives in the UI", true);
  check("subscription filter: the non-matching message never shows", (await page.getByText("drop-this").count()) === 0);
  await shot("20-pubsub-filter");

  // Dark mode
  await page.goto(UI + "#/storage/browser");
  await page.getByRole("button", { name: "More options" }).click();          // ⋮ menu, as in the native top bar
  await page.getByRole("menuitem", { name: "Use dark theme" }).click();
  await page.waitForTimeout(500);
  check("dark mode persisted", (await page.evaluate(() => localStorage.getItem("vyomi.v4.mode"))) === "dark");
  await shot("11-dark");
  await page.evaluate(() => localStorage.setItem("vyomi.v4.mode", "light"));
} catch (e) {
  const at = ((e.stack || "").match(/(?:smoke|dbg)-[a-z]+\.mjs:(\d+)/) || [])[1];   // the failing step's line
  check("smoke run", false, e.message.split("\n")[0] + (at ? ` (smoke line ${at})` : ""));
  await shot("99-failure").catch(() => {});
} finally {
  check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await browser.close();
}
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
