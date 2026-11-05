/* GCP-04/05: VM Manager (Patch, OS policies, VM extension policies), BYOIP, VPC connectivity (Interconnect + VLAN attachments),
 * Cloud Run/Functions networking + Custom URLs, Memorystore Monitoring tab, Application monitoring (App Hub).
 *   BASE=http://127.0.0.1:9044 node consoles/tests/smoke-gcp-vmm-hybrid.mjs      (offline / dev_server)
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
let pw;
try { pw = require(process.env.PW || "playwright"); } catch { pw = require("/Users/sudhirganti/Applications/simulator/portal/node_modules/playwright"); }
const BASE = process.env.BASE || "http://127.0.0.1:9044";
const UI = `${BASE}${process.env.UI_PATH || "/v4/gcp/"}`;
const WIRE = `${BASE}${process.env.WIRE_PATH || "/_wire"}`;
const OUT = process.env.OUT || "smoke-out-gcp-vmm";
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
const gaps = () => page.locator("[data-vyomi-not-simulated]").count();
const P = process.env.NANO === "1" ? "nano-project" : "vyomi-project";

try {
  await page.goto(UI, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 120000 });
  const go = async (hash, heading) => { await page.goto(UI + hash); await page.getByRole("heading", { name: heading }).first().waitFor(); };
  const dlg = () => page.getByRole("dialog");
  const submit = async (label) => { await dlg().getByRole("button", { name: label, exact: true }).click(); await dlg().waitFor({ state: "detached" }); };

  // seed: two VMs (one opted into OS Config)
  for (const [n, osc] of [[`vm-a-${N}`, true], [`vm-b-${N}`, false]]) {
    await wj(`/compute/v1/projects/${P}/zones/us-central1-a/instances`, "POST", { name: n, machineType: "zones/us-central1-a/machineTypes/e2-micro", labels: { env: "smoke" },
      disks: [{ boot: true, autoDelete: true, initializeParams: { sourceImage: "projects/debian-cloud/global/images/family/debian-12" } }], networkInterfaces: [{ network: "global/networks/default" }],
      ...(osc ? { metadata: { items: [{ key: "enable-osconfig", value: "TRUE" }] } } : {}) });
  }

  // ── Patch ──
  await go("#/compute/patch", "Patch");
  check("Patch is a real page, not a Not simulated panel", (await gaps()) === 0);
  await page.getByRole("button", { name: "Execute patch job" }).click();
  await dlg().getByLabel("Display name").fill(`smoke-job-${N}`);
  await submit("Create");
  await page.getByText(`smoke-job-${N}`).first().waitFor();
  const jobs = (await wj(`/v1/projects/${P}/patchJobs`)).patchJobs || [];
  const job = jobs.find((j) => j.displayName === `smoke-job-${N}`);
  check("patch job executed on the OS Config wire against both VMs", job && Object.values(job.instanceDetailsSummary).reduce((a, b) => a + b, 0) >= 2, JSON.stringify(job?.instanceDetailsSummary));
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByText("COMPLETED_WITH_ERRORS").first().waitFor();
  check("job settles with the no-agent VM reported honestly", true);
  await shot("01-patch-jobs");
  await page.getByRole("tab", { name: "Patch deployments" }).click();
  await page.getByRole("button", { name: "Create patch deployment" }).click();
  await dlg().getByLabel("Name", { exact: true }).fill(`weekly-${N}`);
  await submit("Create");
  await page.getByText(`weekly-${N}`).first().waitFor();
  const dep = await wj(`/v1/projects/${P}/patchDeployments/weekly-${N}`);
  check("patch deployment stored with computed next run", dep.state === "ACTIVE" && !!dep.recurringSchedule?.nextExecuteTime, JSON.stringify(dep.recurringSchedule));
  await page.getByRole("row", { name: new RegExp(`weekly-${N}`) }).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Pause" }).click();
  await page.getByText("PAUSED").first().waitFor();
  check("pause reflected on the wire", (await wj(`/v1/projects/${P}/patchDeployments/weekly-${N}`)).state === "PAUSED");
  await shot("02-patch-deployments");

  // ── OS policies ──
  await go("#/compute/os-policies", "OS policies");
  check("OS policies is a real page", (await gaps()) === 0);
  await page.getByRole("button", { name: "Create OS policy assignment" }).click();
  await dlg().getByLabel("Assignment ID").fill(`nginx-${N}`);
  await submit("Create");
  await page.getByText(`nginx-${N}`).first().waitFor();
  const asg = await wj(`/v1/projects/${P}/locations/us-central1-a/osPolicyAssignments/nginx-${N}`);
  check("OS policy assignment on the wire with a revision id", asg.osPolicies?.[0]?.resourceGroups?.[0]?.resources?.[0]?.pkg?.apt?.name === "nginx" && !!asg.revisionId);
  await shot("03-os-policies");

  // ── VM extension policies ──
  await go("#/compute/vm-extension-policies", "VM extension policies");
  await page.getByRole("button", { name: "Create policy" }).click();
  await dlg().getByLabel("Name", { exact: true }).fill(`ops-${N}`);
  await dlg().getByLabel("Label value").fill("smoke");
  await submit("Create");
  await page.getByText(`ops-${N}`).first().waitFor();
  const vx = await wj(`/compute/beta/projects/${P}/global/vmExtensionPolicies/ops-${N}`);
  check("VM extension policy on the Compute wire", vx.extensionPolicies?.["ops-agent"] && vx.instanceSelectors?.[0]?.labelSelector?.inclusionLabels?.env === "smoke");
  await shot("04-vm-extension-policies");

  // ── BYOIP ──
  await go("#/networking/bring-your-own-ip", "Bring your own IP");
  check("BYOIP is a real page", (await gaps()) === 0);
  await page.getByRole("button", { name: "Add prefix" }).click();
  const oct = `45.${N % 250}.${Math.floor(N / 250) % 250}`;
  await dlg().getByLabel("Name", { exact: true }).fill(`byo-${N}`);
  await dlg().getByLabel("IP range (CIDR)").fill(`${oct}.0/24`);
  await dlg().getByLabel("DNS verification IP (inside the range)").fill(`${oct}.5`);
  await submit("Create");
  await page.getByText(`byo-${N}`).first().waitFor();
  await page.getByRole("row", { name: new RegExp(`byo-${N}`) }).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Announce" }).click();
  await page.getByText("ANNOUNCED_TO_INTERNET").first().waitFor();
  check("prefix announced on the Compute wire", (await wj(`/compute/v1/projects/${P}/global/publicAdvertisedPrefixes/byo-${N}`)).status === "ANNOUNCED_TO_INTERNET");
  await page.getByRole("tab", { name: "Delegated prefixes" }).click();
  await page.getByRole("button", { name: "Create delegated prefix" }).click();
  await dlg().getByLabel("Name", { exact: true }).fill(`pdp-${N}`);
  await dlg().getByRole("combobox", { name: /Parent advertised prefix/ }).click();
  await page.getByRole("option", { name: new RegExp(`byo-${N}`) }).click();
  await dlg().getByLabel("IP range (CIDR, inside the parent)").fill(`${oct}.0/25`);
  await submit("Create");
  await page.getByText(`pdp-${N}`).first().waitFor();
  check("delegated prefix created under the parent", (await wj(`/compute/v1/projects/${P}/global/publicAdvertisedPrefixes/byo-${N}`)).publicDelegatedPrefixs?.length === 1);
  await shot("05-byoip");

  // ── VPC connectivity: Interconnect then VLAN attachment (needs a Cloud Router) ──
  await wj(`/compute/v1/projects/${P}/global/networks`, "POST", { name: `hyb-${N}`, autoCreateSubnetworks: false });
  await wj(`/compute/v1/projects/${P}/regions/us-central1/routers`, "POST", { name: `rtr-${N}`, network: `global/networks/hyb-${N}` });
  await go("#/networking/vpc-connectivity", "VPC connectivity");
  check("VPC connectivity is a real page", (await gaps()) === 0);
  await page.getByRole("tab", { name: "Interconnects" }).click();
  await page.getByRole("button", { name: "Order Interconnect" }).click();
  await dlg().getByLabel("Name", { exact: true }).fill(`ic-${N}`);
  await submit("Create");
  await page.getByText(`ic-${N}`).first().waitFor();
  check("Interconnect ACTIVE on the wire", (await wj(`/compute/v1/projects/${P}/global/interconnects/ic-${N}`)).state === "ACTIVE");
  await page.getByRole("tab", { name: "VLAN attachments" }).click();
  await page.getByRole("button", { name: "Create VLAN attachment" }).click();
  await dlg().getByLabel("Name", { exact: true }).fill(`vlan-${N}`);
  await dlg().getByLabel("Cloud Router name (same region)").fill(`rtr-${N}`);
  await submit("Create");
  await page.getByText(`vlan-${N}`).first().waitFor();
  const att = await wj(`/compute/v1/projects/${P}/regions/us-central1/interconnectAttachments/vlan-${N}`);
  check("VLAN attachment ACTIVE with a link-local /29 pair", att.state === "ACTIVE" && att.cloudRouterIpAddress?.startsWith("169.254."), JSON.stringify(att).slice(0, 160));
  await shot("06-vpc-connectivity");
  await go("#/networking/vpc-flow-logs", "VPC flow logs");
  await page.getByRole("tab", { name: "VLAN attachments" }).click();
  await page.getByText(`vlan-${N}`).first().waitFor();
  check("flow-logs VLAN attachments tab lists the real attachment", true);

  // ── Create instance: Install Ops Agent ──
  await page.goto(UI + "#/compute/instances/create");
  await page.getByLabel("Name", { exact: true }).first().fill(`ops-vm-${N}`);
  await page.getByLabel("Install Ops Agent for Monitoring and Logging").check();
  check("create-instance Ops Agent control is real (no Not-simulated panel for it)", (await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated")))).every((t) => !/Ops Agent/.test(t)));
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.waitForURL(/#\/compute\/instances\/us-central1-a\//, { timeout: 30000 });
  const opsVm = await wj(`/compute/v1/projects/${P}/zones/us-central1-a/instances/ops-vm-${N}`);
  check("VM opted into OS Config and labelled for the Ops Agent policy", opsVm.labels?.["goog-ops-agent-policy"] === "v2-x86-template-1-4-0" && opsVm.metadata?.items?.some((i) => i.key === "enable-osconfig" && i.value === "TRUE"));
  const opsPol = await wj(`/v1/projects/${P}/locations/us-central1-a/osPolicyAssignments/goog-ops-agent-v2x-template-1-4-0-us-central1-a`);
  check("Ops Agent OS policy assignment created for the zone", opsPol.osPolicies?.[0]?.resourceGroups?.[0]?.resources?.some((r) => r.pkg?.apt?.name === "google-cloud-ops-agent"));

  // ── Cloud Run + Functions networking / custom URLs ──
  for (const kind of ["run", "functions"]) {
    const name = `net-${kind}-${N}`;
    await page.goto(UI + `#/${kind}/create`);
    await page.getByLabel("Service name").fill(name);
    await page.getByText("Containers, Networking, Security").click();
    await page.getByLabel("Use HTTP/2 end-to-end (container port is h2c)").check();
    await page.getByLabel("Session affinity").check();
    await page.getByLabel("Disable the default run.app URL").check();
    await page.getByLabel("Custom audiences").fill("https://api.example.com");
    check(`${kind}: no Not-simulated networking/custom-URL panel`, (await page.locator("[data-vyomi-not-simulated]").evaluateAll((els) => els.map((e) => e.getAttribute("data-vyomi-not-simulated")))).every((t) => !/HTTP\/2|Custom URLs/.test(t)));
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await page.waitForURL(new RegExp(`#/${kind}/detail/`), { timeout: 20000 });
    const svc = await wj(`/v2/projects/${P}/locations/us-central1/services/${name}`);
    check(`${kind}: h2c + affinity + default URL off + audiences stored`, svc.template?.containers?.[0]?.ports?.[0]?.name === "h2c" && svc.template?.sessionAffinity === true
      && svc.defaultUriDisabled === true && svc.customAudiences?.[0] === "https://api.example.com", JSON.stringify([svc.template?.containers?.[0]?.ports, svc.defaultUriDisabled, svc.customAudiences]));
  }

  // ── Memorystore Monitoring tab ──
  await wj(`/v1/projects/${P}/locations/us-central1/instances?instanceId=cache-${N}`, "POST", { tier: "STANDARD_HA", memorySizeGb: 2, replicaCount: 1 });
  await go(`#/memorystore/instances/us-central1/cache-${N}/overview`, `cache-${N}`);
  await page.getByText("primary").first().waitFor();
  check("Memorystore Monitoring tab shows real node rows (2 GiB, primary + replica)", (await page.getByText("2 GiB").count()) >= 2 && (await page.getByText("replica").count()) >= 1);
  check("usage / clients are shown as no data, not invented", (await page.getByText("No data").count()) >= 3);
  await shot("07-memorystore-monitoring");

  // ── Application monitoring ──
  await wj(`/v2/projects/${P}/locations/us-central1/services?serviceId=hub-api-${N}`, "POST", { template: { containers: [{ image: "gcr.io/x/app:1" }] } });
  await go("#/monitoring/application-monitoring", "Application monitoring");
  check("Application monitoring is a real page", (await gaps()) === 0);
  await page.getByRole("button", { name: "Create application" }).click();
  await dlg().getByLabel("Application ID").fill(`shop-${N}`);
  await submit("Create");
  await page.getByRole("button", { name: `shop-${N}` }).click();
  await page.getByRole("button", { name: "Register service" }).click();
  await submit("Create");
  await page.getByText(`//run.googleapis.com/projects/${P}/locations/us-central1/services/hub-api-${N}`).first().waitFor();
  const reg = await wj(`/v1/projects/${P}/locations/us-central1/applications/shop-${N}/services`);
  check("Cloud Run service registered into the application over App Hub", (reg.services || []).length === 1);
  await shot("08-application-monitoring");
  await go("#/monitoring/alerting/policies/create", "Create alerting policy");
} catch (e) {
  check("smoke ran to completion", false, e.message);
  await shot("zz-failure").catch(() => {});
}
check("no unexpected console / page errors", errors.length === 0, errors.slice(0, 3).join(" | "));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
