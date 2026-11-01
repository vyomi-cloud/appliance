/* Nano post-create probe, GCP Compute Engine (twin of tests/conformance/post_create/probes/vm_ssh.py gcp).
 * Create the instance through the console's Compute Engine REST path (what its create form posts),
 * with an ssh-keys metadata entry like `gcloud compute ssh` adds, then hold it to the same contract
 * as EC2: connect-info -> key -> REAL ssh through vyomi-tunnel -> commands -> exec -> stop/start ->
 * delete. Needs RELAY_HTTP = a vyomi-tunnel >= 1.1.0. */
import { openNano, probeVm, reporter } from "./vm-ssh-lib.mjs";
import { sleep } from "./lib.mjs";
const { check, finish } = reporter();
let nano;
try {
  nano = await openNano("/gcp-console.html");
  const { call } = nano;
  const name = "pc-gce-" + (Date.now() % 100000);
  const coll = "/api/gcp/compute/v1/projects/nano-project/zones/us-central1-a/instances";
  const cr = await call("POST", coll, { name, machineType: "zones/us-central1-a/machineTypes/e2-micro",
    metadata: { items: [{ key: "ssh-keys", value: "gcpuser:ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGl0bm90YXJlYWxrZXlqdXN0dGVzdGluZ2EwMTIz gcpuser" }] } });
  check("instance created through the console's Compute Engine API", cr.status === 200 && cr.body && cr.body.ok !== false, `status ${cr.status} ${JSON.stringify(cr.body).slice(0, 160)}`);
  await probeVm(nano, {
    cloud: "gcp", user: "gcpuser",
    ciPath: `/api/gcp/compute/instances/${name}/connect-info`,
    execPath: `/api/console/gce/instances/${name}/exec`,
    stop: () => call("POST", `${coll}/${name}/stop`),
    start: () => call("POST", `${coll}/${name}/start`),
    del: () => call("DELETE", `${coll}/${name}`),
    openConnect: async (page) => {   // Compute Engine -> the instance -> Connect
      await page.goto(nano.base + "/gcp-console.html"); await page.waitForSelector("a.res-l", { timeout: 120000 });
      await page.locator("a.res-l", { hasText: "Compute Engine" }).first().click();
      await sleep(2000);
      await page.locator("#main a.id", { hasText: name }).first().click({ timeout: 15000 });
      await sleep(1500);
      await page.locator("a.nav-item", { hasText: /^\s*\S*\s*Connect\s*$/ }).first().click();
    },
  }, check);
} catch (e) { check("probe ran without error", false, String(e && e.stack || e).split("\n").slice(0, 3).join(" ")); }
if (nano) await nano.close();
finish();
