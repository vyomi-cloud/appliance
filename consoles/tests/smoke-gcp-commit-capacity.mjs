/* GCP: Committed use discounts, Capacity advisor, Migrate to VMs, TPUs, VM Manager Inventory + Reports.
 *   BASE=http://127.0.0.1:9102 node consoles/tests/smoke-gcp-commit-capacity.mjs   (fresh dev server: python3 consoles/dev_server.py --port 9102) */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9102";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-commit";
const N = Date.now() % 100000;
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project";
let fails = 0;
const check = (name, ok, detail = "") => { if (!ok) fails++; console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " - " + String(detail).slice(0, 200) : ""}`); };
await mkdir(OUT, { recursive: true });
const browser = await pw.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !/status of (40[0-9]|409|412|429|503)/.test(m.text()) && errors.push(m.text()));
const wj = (path, method = "GET", b) => page.evaluate(async ([u, m, body]) => { const r = await fetch(u, { method: m, headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined }); let j = {}; try { j = await r.json(); } catch {} return { status: r.status, j }; }, [WIRE + path, method, b]);
const vm = (name, mt, zone = "us-central1-a") => wj(`/compute/v1/projects/${P}/zones/${zone}/instances`, "POST", { name, machineType: `zones/${zone}/machineTypes/${mt}`,
  disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }], networkInterfaces: [{ network: "global/networks/default" }] });
try {
  await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
  if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
  const go = async (hash, heading) => { await page.goto(UI + hash); await page.getByRole("heading", { name: heading }).first().waitFor(); };
  const dlg = () => page.getByRole("dialog");
  const gaps = () => page.locator("[data-vyomi-not-simulated]").count();

  // CUD
  await vm(`cud-a-${N}`, "e2-standard-4"); await vm(`cud-b-${N}`, "e2-standard-4");
  await go("#/compute/committed-use-discounts", "Committed use discounts");
  await page.getByRole("button", { name: "Purchase commitment" }).click();
  await dlg().getByLabel("Name").fill(`cud${N}`);
  await dlg().getByRole("button", { name: "Create", exact: true }).click();
  await dlg().waitFor({ state: "detached" });
  await page.getByText(`cud${N}`).first().waitFor();
  check("CUD: commitment listed with utilisation and savings", await page.getByText("Net savings across commitments").count() > 0 && await page.getByText("37%").count() > 0);
  check("CUD: no not-simulated panel", await gaps() === 0);

  // Capacity advisor
  await go("#/compute/capacity-advisor", "Capacity advisor");
  await page.getByRole("button", { name: "Check availability" }).click();
  await page.getByTestId("advice").waitFor();
  check("Capacity: advice shows a tiered state", await page.getByTestId("advice").getByText(/HIGH_PROBABILITY|GUARANTEED/).count() > 0);
  await wj(`/compute/v1/projects/${P}/vyomi/capacityPools`, "POST", { zone: "us-east1-b", family: "a2", vcpus: 12 });
  const a = await vm(`gpu-a-${N}`, "a2-highgpu-1g", "us-east1-b"); const b = await vm(`gpu-b-${N}`, "a2-highgpu-1g", "us-east1-b");
  check("Capacity: second GPU VM stocks out", a.status === 200 && b.status === 503 && b.j.error.status === "ZONE_RESOURCE_POOL_EXHAUSTED", JSON.stringify(b.j).slice(0, 150));
  await page.getByLabel("Region").click(); await page.getByRole("option", { name: /us-east1/ }).click();
  await page.getByLabel("Machine type").fill("a2-highgpu-1g");
  await page.getByRole("button", { name: "Check availability" }).click();
  await page.getByTestId("advice").getByText("ZONE_RESOURCE_POOL_EXHAUSTED").first().waitFor();
  check("Capacity: advisor shows the stocked-out zone and alternatives", await page.getByText(/Other zones in the region with room|us-east1-c/).count() > 0);
  check("Capacity: pool utilisation visible", await page.getByText("100%").count() > 0);
  await wj(`/compute/v1/projects/${P}/vyomi/capacityPools?zone=us-east1-b&family=a2`, "DELETE");

  // Migrate
  await go("#/compute/migrate-to-vms", "Migrate to Virtual Machines");
  await page.getByRole("button", { name: "Add source" }).click();
  await dlg().getByLabel("Source ID").fill(`vc${N}`); await dlg().getByLabel(/vCenter IP/).fill("10.1.1.1");
  await dlg().getByRole("button", { name: "Create", exact: true }).click(); await dlg().waitFor({ state: "detached" });
  await page.getByText(`vc${N}`).first().waitFor();
  check("Migrate: source listed", true);
  await wj(`/v1/projects/${P}/locations/us-central1/sources/vc${N}/datacenterConnectors?datacenterConnectorId=dc1`, "POST", {});
  await page.getByRole("tab", { name: "Migrations" }).click();
  await page.getByRole("button", { name: "Add migration" }).click();
  await dlg().getByLabel("Migration ID").fill("m1"); await dlg().getByLabel("Source VM ID").fill("vm-101"); await dlg().getByLabel("Target VM name").fill(`mig-${N}`);
  await dlg().getByRole("button", { name: "Create", exact: true }).click(); await dlg().waitFor({ state: "detached" });
  await page.getByText("READY").first().waitFor();
  await page.getByRole("checkbox").nth(1).check();
  await page.getByRole("button", { name: "Start replication" }).click();
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByText("ACTIVE").first().waitFor();
  check("Migrate: replication reaches ACTIVE", true);
  await page.getByRole("button", { name: "Cycles and jobs" }).click();
  await dlg().getByRole("button", { name: "Cut over" }).click();
  await dlg().getByText("Cutover").first().waitFor();
  const inst = await wj(`/compute/v1/projects/${P}/zones/us-central1-a/instances/mig-${N}`);
  check("Migrate: cutover created a real GCE instance", inst.status === 200 && inst.j.status === "RUNNING");
  await dlg().getByRole("button", { name: "Close" }).click();

  // TPUs
  await go("#/compute/tpus", "TPUs");
  await page.getByRole("button", { name: "Create TPU node" }).click();
  await dlg().getByLabel("Name").fill(`tpu${N}`);
  await dlg().getByRole("button", { name: "Create", exact: true }).click(); await dlg().waitFor({ state: "detached" });
  await page.getByText(`tpu${N}`).first().waitFor();
  check("TPU: node listed; honest no-accelerator note", await page.getByText(/no accelerator exists/).count() > 0 && await gaps() === 0);

  // VM Manager
  await go("#/compute/vm-inventory", "OS inventory");
  await page.getByText(`cud-a-${N}`).first().waitFor({ timeout: 30000 }).catch(() => {});
  check("VM Manager: inventory lists VMs", await page.getByText(`cud-a-${N}`).count() > 0);
  await go("#/compute/vm-reports", "VM Manager reports");
  await page.getByTestId("vmm-report-summary").first().waitFor({ timeout: 30000 }).catch(() => {});
  check("VM Manager: report summary", await page.getByTestId("vmm-report-summary").count() > 0);
  check("no console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
} catch (e) { fails++; console.log("FAIL exception " + e.message); await page.screenshot({ path: `${OUT}/fail.png`, fullPage: true }); }
await browser.close();
process.exit(fails ? 1 : 0);
