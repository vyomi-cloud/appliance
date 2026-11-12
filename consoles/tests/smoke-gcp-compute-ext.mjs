/* GCP-01 Compute A: drives the real Compute Advisor / schedules / instant snapshots / reservations / sole-tenant /
 * storage pools / NEGs / consistency groups / multi-NIC + LB-health-check create flow, cross-checks the native
 * Compute v1 + Recommender v1 wire, asserts none of them is a "Not simulated" panel.
 *
 *   BASE=http://127.0.0.1:9120 node consoles/tests/smoke-gcp-compute-ext.mjs                                       (offline)
 *   BASE=http://127.0.0.1:8820 UI_PATH=/nano/v4/gcp/ WIRE_PATH=/nano/_wire NANO=1 node consoles/tests/smoke-gcp-compute-ext.mjs   (Nano)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9120";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-compute";
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
const body = () => page.locator("body").innerText();
const wire = (path, init = {}) => page.evaluate(async ([u, i]) => { const r = await fetch(u, i); return { status: r.status, text: await r.text() }; }, [WIRE + path, init]);
const wj = async (path, method = "GET", b) => { const r = await wire(path, { method, headers: { "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); try { return JSON.parse(r.text || "{}"); } catch { return {}; } };

await page.goto(UI, { waitUntil: process.env.NANO ? "domcontentloaded" : "networkidle" });
if (process.env.NANO) await page.waitForFunction(() => navigator.serviceWorker?.controller && window.__vyomiNanoReady, null, { timeout: 240000, polling: 500 });
await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
const project = await page.evaluate(() => { try { return localStorage.getItem("vyomi.v4.gcp.project") || (process.env.NANO === "1" ? "nano-project" : "vyomi-project"); } catch { return "vyomi-project"; } });
const C = (p) => `/compute/v1/projects/${project}${p}`;
const go = async (hash, heading) => { await page.goto(UI + hash); await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 60000 }); };
const pick = async (label, option) => { await page.getByRole("combobox", { name: label }).click(); await page.getByRole("option", { name: option, exact: false }).first().click(); };
const nsPanel = async () => (await page.locator("[data-vyomi-not-simulated]").count()) === 0;

// ── data prerequisites over the native wire ───────────────────────────────
const disk = `smk-disk-${N}`, vm = `smk-vm-${N}`;
await wj(C("/zones/us-central1-a/disks"), "POST", { name: disk, sizeGb: "12" });
await wj(C("/zones/us-central1-a/instances"), "POST", { name: vm, machineType: "e2-medium", disks: [{ boot: true, initializeParams: { diskSizeGb: "10" } }] });

// ── Compute Advisor ───────────────────────────────────────────────────────
await go("#/compute/compute-advisor", "Compute Advisor");
await page.getByText(new RegExp(`unattached .* disk '${disk}'`)).first().waitFor({ timeout: 60000 });
check("Compute Advisor lists a real idle-disk recommendation", true);
check("Compute Advisor is not a Not-simulated panel", await nsPanel());
const claimBtn = page.getByRole("row", { name: new RegExp(disk) }).getByRole("button", { name: "Claim" });
await claimBtn.click();
await page.getByRole("row", { name: new RegExp(disk) }).getByText("CLAIMED").waitFor({ timeout: 60000 });
const recs = await wj(`/v1/projects/${project}/locations/us-central1-a/recommenders/google.compute.disk.IdleResourceRecommender/recommendations`);
check("markClaimed persisted on the Recommender wire", (recs.recommendations || []).some((r) => r.targetResources[0].endsWith(`/${disk}`) && r.stateInfo.state === "CLAIMED"));
await shot("01-advisor");

// ── dashboard Recommendations tab ─────────────────────────────────────────
await page.goto(UI + "#/dashboard");
await page.getByRole("tab", { name: "Recommendations" }).click();
await page.getByText(new RegExp(disk)).first().waitFor({ timeout: 60000 });
check("dashboard Recommendations tab shows the recommendation", true);

// ── instance schedules ────────────────────────────────────────────────────
const sch = `smk-sched-${N}`;
await go("#/compute/instances", "VM instances");
await page.getByRole("tab", { name: "Instance schedules" }).click();
await page.getByRole("button", { name: "Create schedule" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(sch);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: sch, exact: true }).waitFor({ timeout: 60000 });
check("instance schedule created in the UI", true);
const pols = await wj(C("/regions/us-central1/resourcePolicies"));
check("instance schedule visible on the Compute wire", (pols.items || []).some((p) => p.name === sch && p.instanceSchedulePolicy.vmStartSchedule.schedule === "0 8 * * 1-5"));
await page.getByRole("row", { name: new RegExp(sch) }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Attach to VMs" }).click();
await pick("VM instance in us-central1", vm);
await page.getByRole("dialog").getByRole("button", { name: "Attach" }).click();
await page.getByRole("cell", { name: vm, exact: true }).waitFor({ timeout: 60000 });
check("schedule attached to the VM (shown + on wire)", ((await wj(C(`/zones/us-central1-a/instances/${vm}`))).resourcePolicies || []).some((l) => l.endsWith(`/${sch}`)));
await shot("02-instance-schedules");

// ── snapshot schedules + instant snapshots ───────────────────────────────
const ssch = `smk-snap-${N}`, isn = `smk-isn-${N}`;
await go("#/compute/snapshots", "Snapshots");
await page.getByRole("tab", { name: "Snapshot schedules" }).click();
await page.getByRole("button", { name: "Create snapshot schedule" }).last().click();
await page.getByRole("dialog").getByLabel("Name").fill(ssch);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: ssch, exact: true }).waitFor({ timeout: 60000 });
check("snapshot schedule created", true);
await page.getByRole("tab", { name: "Instant snapshots" }).click();
await page.getByRole("button", { name: "Create instant snapshot" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(isn);
await pick("Source disk", disk);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: isn, exact: true }).waitFor({ timeout: 60000 });
check("instant snapshot created from the disk", ((await wj(C("/zones/us-central1-a/instantSnapshots"))).items || []).some((s) => s.name === isn && s.diskSizeGb === "12"));
await shot("03-snapshots");

// ── reservations ──────────────────────────────────────────────────────────
const rsv = `smk-rsv-${N}`;
await go("#/compute/reservations", "Reservations");
check("Reservations is not a Not-simulated panel", await nsPanel());
await page.getByRole("button", { name: "Create reservation" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(rsv);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: rsv, exact: true }).waitFor({ timeout: 60000 });
const rv = await wj(C(`/zones/us-central1-a/reservations/${rsv}`));
check("reservation counts the running e2-medium VM as a consumer", rv.specificReservation?.inUseCount === "1", JSON.stringify(rv.specificReservation));

// ── sole-tenant ───────────────────────────────────────────────────────────
const ntpl = `smk-nt-${N}`, ng = `smk-ng-${N}`;
await go("#/compute/sole-tenant-nodes", "Sole-tenant nodes");
await page.getByRole("tab", { name: "Node templates" }).click();
await page.getByRole("button", { name: "Create node template" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(ntpl);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: ntpl, exact: true }).waitFor({ timeout: 60000 });
await page.getByRole("tab", { name: "Node groups" }).click();
await page.getByRole("button", { name: "Create node group" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(ng);
await pick("Node template", ntpl);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: ng, exact: true }).waitFor({ timeout: 60000 });
check("node group created with 1 node", (await wj(C(`/zones/us-central1-a/nodeGroups/${ng}`))).size === 1);
await shot("04-sole-tenant");

// ── storage pools / async replication / consistency groups / NEGs ─────────
const sp = `smk-sp-${N}`, cg = `smk-cg-${N}`, neg = `smk-neg-${N}`;
await go("#/compute/storage-pools", "Storage Pools");
await page.getByRole("button", { name: "Create storage pool" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(sp);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: sp, exact: true }).waitFor({ timeout: 60000 });
check("storage pool created", ((await wj(C("/zones/us-central1-a/storagePools"))).items || []).some((p) => p.name === sp && p.poolProvisionedCapacityGb === "10240"));
await go("#/compute/async-replication", "Async Replication");
check("Async Replication is not a Not-simulated panel", await nsPanel());
await go("#/compute/consistency-groups", "Consistency Groups");
await page.getByRole("button", { name: "Create consistency group" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(cg);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: cg, exact: true }).waitFor({ timeout: 60000 });
check("consistency group created", true);
await go("#/compute/network-endpoint-groups", "Network endpoint groups");
await page.getByRole("button", { name: "Create network endpoint group" }).click();
await page.getByRole("dialog").getByLabel("Name").fill(neg);
await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: neg, exact: true }).waitFor({ timeout: 60000 });
await page.getByRole("row", { name: new RegExp(neg) }).getByRole("checkbox").check();
await page.getByRole("button", { name: "Manage endpoints" }).click();
await page.getByRole("button", { name: "Add network endpoint" }).click();
await page.getByLabel("VM instance name").fill(vm);
await page.getByRole("dialog").last().getByRole("button", { name: "Create" }).click();
await page.getByRole("cell", { name: vm, exact: true }).first().waitFor({ timeout: 60000 });
check("NEG endpoint attached to the VM (validated against real instances)", ((await wj(C(`/zones/us-central1-a/networkEndpointGroups/${neg}`))).size) === 1);
await shot("05-neg");

// ── create instance: multiple NICs + LB health-check firewall + extra disk ─
const nb = `smk-net-${N}`, vm2 = `smk-vm2-${N}`;
if (!((await wj(C("/global/networks"))).items || []).some((n) => n.name === "default")) await wj(C("/global/networks"), "POST", { name: "default", autoCreateSubnetworks: true });
await wj(C("/global/networks"), "POST", { name: nb, autoCreateSubnetworks: true });
await go("#/compute/instances/create", "Create an instance");
await page.getByLabel("Name", { exact: true }).fill(vm2);
await page.getByRole("button", { name: "Add new disk" }).click();
await page.getByRole("button", { name: "Add a network interface" }).click();
check("second network interface row appears", await page.getByLabel("Network interface 1", { exact: true }).isVisible());
await page.getByLabel("Allow Load Balancer Health Checks").check();
await page.getByRole("button", { name: /^Create$/ }).click();
await page.waitForFunction(() => location.hash.includes("/compute/instances/us-central1-a/"), null, { timeout: 60000 });
const v2 = await wj(C(`/zones/us-central1-a/instances/${vm2}`));
check("instance has 2 NICs and the extra disk", (v2.networkInterfaces || []).length === 2 && (v2.disks || []).length === 2, JSON.stringify((v2.networkInterfaces || []).map((n) => n.name)));
check("LB health-check tag set + firewall rule created", (v2.tags?.items || []).includes("lb-health-check") && ((await wj(C("/global/firewalls"))).items || []).some((f) => f.name === "default-allow-health-check"));
await shot("06-create-instance");

// ── cleanup (best effort) ─────────────────────────────────────────────────
for (const [p] of [[`/zones/us-central1-a/instances/${vm2}`], [`/zones/us-central1-a/instances/${vm}`]]) await wj(C(p), "DELETE");
check("no page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
