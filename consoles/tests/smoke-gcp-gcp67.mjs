/* GCP-06/07: folders (Manage resources), inventory reports + Rapid Cache (Storage), Asset Inventory query,
 * image import/export history + Import VM (Compute), and the registered unbuildable-gap pages.
 *   BASE=http://127.0.0.1:9045 node consoles/tests/smoke-gcp-gcp67.mjs                                       (offline / dev_server)
 *   BASE=http://127.0.0.1:8820 UI_PATH=/nano/v4/gcp/ WIRE_PATH=/nano/_wire NANO=1 node consoles/tests/smoke-gcp-gcp67.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9045";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp67";
const N = Date.now() % 100000;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
page.setDefaultTimeout(60000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (40[034]|409|412)/.test(m.text()) && errors.push(m.text()));
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const wj = async (path, method = "GET", b) => { const r = await wire(path, { method, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); try { return JSON.parse(r.text || "{}"); } catch { return {}; } };
const nsPanel = async () => (await page.locator("[data-vyomi-not-simulated]").count()) > 0;

await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
const project = await page.evaluate((nano) => { try { return localStorage.getItem("vyomi.v4.gcp.project") || (nano ? "nano-project" : "vyomi-project"); } catch { return nano ? "nano-project" : "vyomi-project"; } }, process.env.NANO === "1");
const go = async (hash, heading) => { await page.goto(UI + hash); await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 60000 }); };

// ── folders ──────────────────────────────────────────────────────────────
const fname = `Smoke Folder ${N}`;
await wj(`/v3/projects/${project}`);   // Resource Manager materialises the project on first read
await go("#/resource-manager", "Manage resources");
await page.getByRole("button", { name: "Create Folder" }).click();
await page.getByRole("dialog").getByLabel("Folder name").fill(fname);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("link", { name: fname }).waitFor();
check("folder created in the UI and shown in the tree", true);
const found = await wj(`/v3/folders:search?query=${encodeURIComponent("displayName=" + fname)}`);
check("folder visible on the Resource Manager v3 wire", (found.folders || []).some((f) => f.displayName === fname));
const fid = found.folders[0].name;
// move the current project into the folder via the row menu
await page.getByRole("button", { name: `Actions for ${project}` }).click();
await page.getByRole("menuitem", { name: "Move" }).click();
await page.getByRole("option", { name: fname }).click();
await page.getByRole("dialog").getByRole("button", { name: "Move" }).click();
await page.getByRole("link", { name: fname }).waitFor();
const pj = await wj(`/v3/projects/${project}`);
check("project moved under the folder (wire parent)", pj.parent && pj.parent.type === "folder" && fid.endsWith(pj.parent.id), JSON.stringify(pj.parent));
await page.getByRole("link", { name: fname }).click();
const pjLabel = pj.displayName || project;   // the row link shows the display name, not the id
await page.getByRole("link", { name: pjLabel, exact: true }).waitFor();
check("drilling into the folder lists the moved project", true);
await shot("01-folders");
await wj(`/v3/projects/${project}:move`, "POST", { destinationParent: (await wj("/v3/organizations:search")).organizations[0].name });
const del = await wire(`/v3/${fid}`, { method: "DELETE" });
check("empty folder deletes (after project moved back)", del.status === 200);

// ── inventory reports + Rapid Cache ─────────────────────────────────────
const src = `smk-inv-src-${N}`, dst = `smk-inv-dst-${N}`;
for (const b of [src, dst]) await wj(`/storage/v1/b?project=${project}`, "POST", { name: b, location: "US-CENTRAL1" });
await wire(`/upload/storage/v1/b/${src}/o?uploadType=media&name=hello.txt`, { method: "POST", headers: { "content-type": "text/plain" }, body: "hi" });
await page.goto(UI + `#/storage/browser/${src}?tab=inventory`);
await page.getByRole("heading", { name: "Inventory report configurations" }).waitFor();
await page.getByRole("button", { name: "Create configuration" }).first().click();
await page.getByRole("combobox", { name: "Destination bucket" }).click();
await page.getByRole("option", { name: dst }).click();
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("heading", { name: /Reports from/ }).waitFor();
await page.getByRole("cell", { name: /gs:\/\/smk-inv-dst/ }).first().waitFor();
check("inventory report config created and its first report listed", true);
const list = await wire(`/storage/v1/b/${dst}/o`);
check("report CSV object exists in the destination bucket", /inventory\//.test(list.text) && /_0\.csv/.test(list.text), list.text.slice(0, 120));
await shot("02-inventory");
await go("#/storage/monitoring", "Monitoring");
await page.getByRole("tab", { name: "Rapid Cache" }).click();
await page.getByRole("button", { name: "Create cache" }).click();
await page.getByRole("combobox", { name: "Bucket" }).click();
await page.getByRole("option", { name: src }).click();
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: "us-central1-a" }).first().waitFor();
check("Anywhere Cache created via the UI", ((await wj(`/storage/v1/b/${src}/anywhereCaches`)).items || []).some((c) => c.zone === "us-central1-a"));
check("Rapid Cache is not a Not-simulated panel", !(await nsPanel()));
await shot("03-rapid-cache");

// ── Asset Inventory query ────────────────────────────────────────────────
await go("#/iam-admin/asset-inventory", "Asset Inventory").catch(async () => { await page.goto(UI + "#/iam-admin/analyzer"); });
const hasQuery = await page.getByLabel("Query").count();
if (hasQuery) {
  await page.getByLabel("Query").fill("assetType:Project AND state=ACTIVE");
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByText("cloudresourcemanager.googleapis.com/Project").first().waitFor();
  check("Asset Inventory query language filters in the UI", (await page.getByText("iam.googleapis.com/ServiceAccount").count()) === 0);
} else check("Asset Inventory page reachable", false);

// ── image import / export + Import VM ────────────────────────────────────
const bkt = `smk-img-${N}`;
await wj(`/storage/v1/b?project=${project}`, "POST", { name: bkt });
await wire(`/upload/storage/v1/b/${bkt}/o?uploadType=media&name=disk.tar.gz`, { method: "POST", headers: { "content-type": "application/gzip" }, body: "not-really-gz-but-bytes" });
await go("#/compute/images", "Images");
await page.getByRole("button", { name: "Import image" }).click();
await page.getByLabel("Import source").fill(`gs://${bkt}/disk.tar.gz`);
await page.getByLabel("Imported image name").fill(`smk-img-${N}`);
await page.getByRole("dialog").getByRole("button", { name: "Import" }).click();
await page.getByRole("cell", { name: `smk-img-${N}`, exact: true }).first().waitFor();
check("image imported from GCS (shown in Images)", true);
await page.getByRole("tab", { name: "Image import history" }).click();
await page.getByRole("cell", { name: `gs://${bkt}/disk.tar.gz` }).first().waitFor();
check("import history lists the job (not a Not-simulated panel)", !(await nsPanel()));
await go("#/compute/instances", "VM instances");
await page.getByRole("button", { name: "Import VM" }).click();
await page.getByLabel("VM import source").fill(`gs://${bkt}/disk.tar.gz`);
await page.getByLabel("Imported instance name").fill(`smk-vm-${N}`);
await page.getByRole("dialog").getByRole("button", { name: "Import" }).click();
await page.getByRole("link", { name: `smk-vm-${N}` }).first().waitFor();
const inst = await wj(`/compute/v1/projects/${project}/zones/us-central1-a/instances/smk-vm-${N}`);
const bootDisk = await wj(`/compute/v1/projects/${project}/zones/us-central1-a/disks/smk-vm-${N}`);
check("Import VM created an instance booting from the imported image", inst.name === `smk-vm-${N}` && String(bootDisk.sourceImage || "").endsWith(`smk-vm-${N}-imported`), JSON.stringify(bootDisk).slice(0, 160));
await shot("04-import-vm");

// ── registered unbuildable gaps still honest (TPUs + Migrate to Virtual Machines are real, limited pages now) ─────────────────────────────
for (const [hash, h] of [["#/compute/bms/servers", "Servers"]]) {
  await go(hash, h);
  check(`${h} is an honest, registered Not-simulated panel`, await nsPanel());
}
check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
