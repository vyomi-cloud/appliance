/* Nano post-create probe, Azure Virtual Machines (twin of tests/conformance/post_create/probes/vm_ssh.py azure).
 * Create the VM through ARM (the console's own wire: PUT .../Microsoft.Compute/virtualMachines/<name>),
 * then hold it to the same contract as EC2: connect-info -> key -> REAL ssh through vyomi-tunnel as the
 * adminUsername -> commands -> exec -> powerOff/start -> delete. Needs RELAY_HTTP = vyomi-tunnel >= 1.1.0. */
import { openNano, probeVm, reporter } from "./vm-ssh-lib.mjs";
const { check, finish } = reporter();
let nano;
try {
  nano = await openNano("/azure-console.html");
  const { call } = nano;
  const subs = (await call("GET", "/subscriptions?api-version=2020-01-01")).body;
  const sub = subs && subs.value && subs.value[0] && subs.value[0].subscriptionId;
  const name = "pcvm" + (Date.now() % 100000);
  const rg = `/subscriptions/${sub}/resourceGroups/${name}-rg`;
  await call("PUT", `${rg}?api-version=2021-04-01`, { location: "eastus" });
  const vm = `${rg}/providers/Microsoft.Compute/virtualMachines/${name}`;
  const cr = await call("PUT", `${vm}?api-version=2023-09-01`, { location: "eastus", properties: {
    hardwareProfile: { vmSize: "Standard_B1s" },
    storageProfile: { imageReference: { publisher: "Canonical", offer: "ubuntu-24_04-lts", sku: "server", version: "latest" } },
    osProfile: { computerName: name, adminUsername: "azureuser", linuxConfiguration: { disablePasswordAuthentication: true } } } });
  check("VM created through ARM (the console's wire)", [200, 201].includes(cr.status), `status ${cr.status} ${JSON.stringify(cr.body).slice(0, 160)}`);
  await probeVm(nano, {
    cloud: "azure", user: "azureuser",
    ciPath: `/api/azure/vm/${name}/connect-info`,
    execPath: `/api/console/azurevm/instances/${name}/exec`,
    stop: () => call("POST", `${vm}/powerOff?api-version=2023-09-01`),
    start: () => call("POST", `${vm}/start?api-version=2023-09-01`),
    del: async () => { await call("DELETE", `${vm}?api-version=2023-09-01`); await call("DELETE", `${rg}?api-version=2021-04-01`); },
  }, check);
} catch (e) { check("probe ran without error", false, String(e && e.stack || e).split("\n").slice(0, 3).join(" ")); }
if (nano) await nano.close();
finish();
