/* Virtual machines over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}
 *   Power actions: POST .../start | restart | powerOff | deallocate (metadata-only power state —
 *   see core/azure_arm_core.py's generic VM action handler). Auto-shutdown is ENFORCED lazily on
 *   read (core/azure_arm_core.py's _apply_auto_shutdown): no real scheduler runs, but once the
 *   configured local time has passed today the VM's own powerState really does flip to stopped.
 *   Network interface + (optional) public IP address + network security group + its security
 *   rules are real, separate ARM resources this service also creates at VM-create time
 *   (Microsoft.Network/networkInterfaces, publicIPAddresses, networkSecurityGroups/securityRules)
 *   — the same engine the Network security groups console (../nsgs/) uses, so a rule added here
 *   or there round-trips identically.
 *   Disks (OS + data) are embedded on the VM's own properties.storageProfile, the same shape the
 *   create wizard writes — Azure VMs don't have a standalone Microsoft.Compute/disks resource in
 *   this lens (see core/capabilities/azure/vms.json: azure.vms.disks). */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.Compute", "virtualMachines", "2023-09-01");
const NIC_ARM = armType("Microsoft.Network", "networkInterfaces", "2023-11-01");
const NSG_ARM = armType("Microsoft.Network", "networkSecurityGroups", "2023-11-01");
const PIP_ARM = armType("Microsoft.Network", "publicIPAddresses", "2023-11-01");
const RULE_API_VERSION = "2023-11-01";
const LOCK_API_VERSION = "2020-05-01";

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listVms = async () => (await ARM.list()).map(shape);
export const getVm = async (rg, name) => shape(await ARM.get(rg, name));
export const createVm = (rg, name, body) => ARM.put(rg, name, body);
export const updateVm = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteVm = (rg, name) => ARM.remove(rg, name);
export const vmAction = (rg, name, verb) => ARM.action(rg, name, verb);

// ── Network interface (Microsoft.Network/networkInterfaces) ────────────────────────────
export const getNic = (rg, name) => NIC_ARM.get(rg, name);
export const putNic = (rg, name, body) => NIC_ARM.put(rg, name, body);
export const nicNameFor = (vmName) => `${vmName}-nic`;

/** A short, deterministic-looking private IP in the 10.0.0.0/24 range (no real DHCP). */
export function pseudoIp(seed) {
  let h = 0;
  for (const c of String(seed)) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
  return `10.0.0.${(h % 250) + 2}`;
}

// ── Public IP address (Microsoft.Network/publicIPAddresses), requested at VM-create time ───
// only — a real, separate ARM resource (the same catalog type core/netsim's NAT/public-IP
// engine uses), referenced from the NIC's ipConfigurations[0].properties.publicIPAddress.id
// exactly like the real control plane; attaching one to an EXISTING VM post-create is an
// honest gap (azure.vms.networking — real Azure itself requires a NIC swap for that).
export const publicIpNameFor = (vmName) => `${vmName}-ip`;
export const getPublicIp = (rg, name) => PIP_ARM.get(rg, name);
export const putPublicIp = (rg, name, body) => PIP_ARM.put(rg, name, body);
export function toPublicIpBody(f) {
  return { location: f.location, sku: { name: "Standard", tier: "Regional" }, properties: { publicIPAllocationMethod: "Static" } };
}

// ── Network security group attached to the VM's NIC (Microsoft.Network/networkSecurityGroups) ──
export const nsgNameFor = (vmName) => `${vmName}-nsg`;
export const getNsg = (rg, name) => NSG_ARM.get(rg, name);
export const putNsg = (rg, name, body) => NSG_ARM.put(rg, name, body);
const rulePath = (rg, name, ruleName) => `${NSG_ARM.path(rg, name)}/securityRules${ruleName ? `/${encodeURIComponent(ruleName)}` : ""}`;
export const listSecurityRules = async (rg, name) =>
  (await restJson("GET", rulePath(rg, name), { query: { "api-version": RULE_API_VERSION } })).value || [];
export const putSecurityRule = (rg, name, ruleName, body) =>
  restJson("PUT", rulePath(rg, name, ruleName), { query: { "api-version": RULE_API_VERSION }, body });
export const deleteSecurityRule = (rg, name, ruleName) =>
  restJson("DELETE", rulePath(rg, name, ruleName), { query: { "api-version": RULE_API_VERSION } });

export const DEFAULT_RULES = [
  { name: "AllowVNetInBound", priority: 65000, direction: "Inbound", access: "Allow", protocol: "Any", source: "VirtualNetwork", destination: "VirtualNetwork", port: "Any" },
  { name: "AllowAzureLoadBalancerInBound", priority: 65001, direction: "Inbound", access: "Allow", protocol: "Any", source: "AzureLoadBalancer", destination: "Any", port: "Any" },
  { name: "DenyAllInBound", priority: 65500, direction: "Inbound", access: "Deny", protocol: "Any", source: "Any", destination: "Any", port: "Any" },
  { name: "AllowVNetOutBound", priority: 65000, direction: "Outbound", access: "Allow", protocol: "Any", source: "VirtualNetwork", destination: "VirtualNetwork", port: "Any" },
  { name: "AllowInternetOutBound", priority: 65001, direction: "Outbound", access: "Allow", protocol: "Any", source: "Any", destination: "Internet", port: "Any" },
  { name: "DenyAllOutBound", priority: 65500, direction: "Outbound", access: "Deny", protocol: "Any", source: "Any", destination: "Any", port: "Any" },
];

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this VM) ──
/** sinceIso: ISO timestamp lower bound (the timespan picker) — ENFORCED, narrows the result. */
export const listActivityLog = async (rg, name, sinceIso) => {
  const rid = ARM.path(rg, name);
  const filter = `resourceUri eq '${rid}'` + (sinceIso ? ` and eventTimestamp ge '${sinceIso}'` : "");
  const query = { "api-version": "2015-04-01", "$filter": filter };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Access control (IAM): role assignments scoped to THIS virtual machine (plus its
// subscription/resource-group ancestors, real Azure's "inherited access" view) read over the
// same generic Microsoft.Authorization/roleAssignments extension-resource engine the Cosmos DB
// account blade uses — GET-only; assignments are still created at the subscription scope. ──
const AUTHZ_API_VERSION = "2022-04-01";
export const listRoleAssignments = async (rg, name) =>
  (await restJson("GET", `${ARM.path(rg, name)}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API_VERSION } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API_VERSION } })).value || [];

// ── Size catalog: real ARM Microsoft.Compute/locations/{location}/vmSizes (subscription +
// location scoped) and .../virtualMachines/{vm}/vmSizes (resource-scoped, for an existing
// VM's Resize blade) — core/instance_catalog.py's AZURE sample through the ARM engine; no
// size list in the console itself (azure.vms.size: a curated sample, not the full regional
// catalog). Each entry's shape is real ARM (name, numberOfCores, memoryInMB, maxDataDiskCount,
// osDiskSizeInMB, resourceDiskSizeInMB) plus two reference-only extras (series, maxIops) the
// backend derives from the same catalog for the console's table.
const SIZE_API_VERSION = "2023-09-01";
export const listSizesForLocation = async (location) =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Compute/locations/${location}/vmSizes`, { query: { "api-version": SIZE_API_VERSION } })).value || [];
export const listSizesForVm = async (rg, name) =>
  (await restJson("GET", `${ARM.path(rg, name)}/vmSizes`, { query: { "api-version": SIZE_API_VERSION } })).value || [];
/** A rough, clearly-labelled monthly cost estimate (vCPU + RAM linear model) — not live Azure retail pricing. */
export const estMonthlyCost = (s) => Math.round(s.numberOfCores * 18 + (s.memoryInMB / 1024) * 4.5);

// ── create-VM form model → ARM bodies (VM + NIC + optional NSG) ─────────────────────────
export function toVmBody(f) {
  const nicId = NIC_ARM.path(f.resourceGroup, nicNameFor(f.name));
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    identity: f.identity ? { type: "SystemAssigned" } : undefined,
    properties: {
      hardwareProfile: { vmSize: f.size },
      osProfile: {
        computerName: f.name,
        adminUsername: f.adminUsername,
        ...(f.authType === "Password" ? { adminPassword: f.password } : { linuxConfiguration: { disablePasswordAuthentication: true, ssh: { publicKeys: [{ path: `/home/${f.adminUsername}/.ssh/authorized_keys`, keyData: f.sshKey || "ssh-ed25519 AAAA...generated-by-vyomi" }] } } }),
      },
      storageProfile: {
        imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts", version: "latest" },
        osDisk: { osType: "Linux", createOption: "FromImage", diskSizeGB: 30, managedDisk: { storageAccountType: f.osDiskType } },
        dataDisks: [],
      },
      networkProfile: { networkInterfaces: [{ id: nicId, properties: { primary: true } }] },
      ...(f.autoShutdown ? { autoShutdown: { enabled: true, time: f.autoShutdownTime, timeZone: f.autoShutdownTz } } : {}),
    },
  };
}

export function toNicBody(f) {
  const vnetName = (f.vnet || "vnet").replace(/^\(new\)\s*/, "").trim() || "vnet";
  const subnetId = `/subscriptions/${getSubscription()}/resourceGroups/${f.resourceGroup}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/${f.subnet || "default"}`;
  const ipcProps = { privateIPAllocationMethod: "Dynamic", privateIPAddress: pseudoIp(f.name), subnet: { id: subnetId } };
  if (f.publicIp && f.publicIp !== "None") {
    ipcProps.publicIPAddress = { id: PIP_ARM.path(f.resourceGroup, publicIpNameFor(f.name)) };
  }
  return {
    location: f.location,
    properties: {
      enableAcceleratedNetworking: !!f.acceleratedNetworking,
      ipConfigurations: [{ name: "ipconfig1", properties: ipcProps }],
    },
  };
}

export function toNsgBody(f) {
  return { location: f.location, tags: {}, properties: {} };
}

// ── Run command (POST .../virtualMachines/{vm}/runCommand) — a bounded, deterministic script
// interpreter (core/azure_arm_core.AzureArm._vm_run_command, azure.vms.run_command): echo/
// hostname/whoami/date/uname, and the IMDS-token + Key Vault secret-fetch pattern that
// demonstrates a system-assigned managed identity's token really being checked against a real
// role assignment (azure.vms.identity) — never a fabricated success for an unrecognized script. ──
export const runCommand = (rg, name, script, commandId = "RunShellScript") =>
  ARM.action(rg, name, "runCommand", { commandId, script: script.split("\n") });

// ── Reset password / Redeploy / Reapply — real POST actions that really mutate the VM's own
// ARM properties (azure.vms.tools), not a stored-but-inert stub. ───────────────────────────
export const resetPassword = (rg, name, username, password) => ARM.action(rg, name, "resetPassword", { username, password });
export const redeploy = (rg, name) => ARM.action(rg, name, "redeploy");
export const reapply = (rg, name) => ARM.action(rg, name, "reapply");

// ── Backup (Microsoft.Compute/virtualMachines/{vm}/providers/Microsoft.Compute/restorePoints):
// "backup as a snapshot" of the VM's own ARM properties document — a real, stateful
// sub-resource (core/azure_arm_core.AzureArm._vm_backup, azure.vms.backup), not a stored-but-
// inert stub. restore really overwrites the VM's current properties with the captured ones. ──
const RESTORE_POINT_API_VERSION = "2023-09-01";
const restorePointPath = (rg, name, rpName) => `${ARM.path(rg, name)}/providers/Microsoft.Compute/restorePoints${rpName ? `/${encodeURIComponent(rpName)}` : ""}`;
export const listRestorePoints = async (rg, name) =>
  (await restJson("GET", restorePointPath(rg, name), { query: { "api-version": RESTORE_POINT_API_VERSION } })).value || [];
export const createRestorePoint = (rg, name, rpName) =>
  restJson("PUT", restorePointPath(rg, name, rpName), { query: { "api-version": RESTORE_POINT_API_VERSION }, body: {} });
export const deleteRestorePoint = (rg, name, rpName) =>
  restJson("DELETE", restorePointPath(rg, name, rpName), { query: { "api-version": RESTORE_POINT_API_VERSION } });
export const restoreRestorePoint = (rg, name, rpName) =>
  restJson("POST", `${restorePointPath(rg, name, rpName)}/restore`, { query: { "api-version": RESTORE_POINT_API_VERSION }, body: {} });

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension resource
// scoped to this VM's own id — the SAME generic mechanism core/azure_arm_core.AzureArm.
// _diagnostic_settings exposes for every lens resource, e.g. the ACR/APIM blades' Diagnostic
// settings tab). Logs/metrics are stored and validated exactly as the real resource requires,
// but never delivered anywhere (azure.vms.monitoring). ─────────────────────────────────────
const DIAG_API_VERSION = "2021-05-01-preview";
const diagPath = (vmId, setting) => `${vmId}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (vmId) => (await restJson("GET", diagPath(vmId), { query: { "api-version": DIAG_API_VERSION } })).value || [];
export const putDiagnosticSetting = (vmId, setting, body) => restJson("PUT", diagPath(vmId, setting), { query: { "api-version": DIAG_API_VERSION }, body });
export const deleteDiagnosticSetting = (vmId, setting) => restJson("DELETE", diagPath(vmId, setting), { query: { "api-version": DIAG_API_VERSION } });

// ── Alerts (Microsoft.Insights/metricAlerts + activityLogAlerts, scoped to this VM via
// properties.scopes) — the SAME generic Azure Monitor engine the Monitor service's own Alert
// rules page uses (core/azure_monitor_core.py), just filtered/created with this VM as the
// scope (azure.vms.monitoring). ─────────────────────────────────────────────────────────────
const METRIC_ALERTS = armType("Microsoft.Insights", "metricAlerts", "2018-03-01");
const ACTIVITY_LOG_ALERTS = armType("Microsoft.Insights", "activityLogAlerts", "2020-10-01");
export async function listVmAlertRules(vmId) {
  const [metric, activity] = await Promise.all([METRIC_ALERTS.list(), ACTIVITY_LOG_ALERTS.list()]);
  const mine = (r) => (r.properties?.scopes || []).some((s) => s.toLowerCase() === vmId.toLowerCase());
  return [
    ...metric.filter(mine).map((r) => ({ ...r, kind: "Metric" })),
    ...activity.filter(mine).map((r) => ({ ...r, kind: "Activity Log" })),
  ];
}
export const createVmMetricAlert = (rg, name, vmId, body) => METRIC_ALERTS.put(rg, name, { location: "global", properties: { scopes: [vmId], ...body } });
export const deleteVmMetricAlert = (rg, name) => METRIC_ALERTS.remove(rg, name);

// ── Workbooks (Microsoft.Insights/workbooks) — same generic gallery engine the Monitor
// service's own Workbooks page uses; a workbook's sourceId optionally names this VM. ───────
const WORKBOOKS = armType("Microsoft.Insights", "workbooks", "2022-04-01");
export const listVmWorkbooks = async (vmId) => (await WORKBOOKS.list()).filter((w) => w.properties?.sourceId?.toLowerCase() === vmId.toLowerCase());
export const createVmWorkbook = (rg, name, vmId, displayName) =>
  WORKBOOKS.put(rg, name, { location: "global", kind: "shared", properties: { displayName, category: "workbook", sourceId: vmId, serializedData: "{}" } });
export const deleteVmWorkbook = (rg, name) => WORKBOOKS.remove(rg, name);

// ── Logs (Log Analytics KQL query, core/azure_operationalinsights_core.py) — the first
// workspace in the subscription, pre-filtered to this VM's own Activity log rows, the same
// real bounded KQL subset the Monitor service's own Logs page runs (azure.vms.monitoring). ──
const WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");
export const listWorkspaces = async () => (await WORKSPACES.list()).map((w) => ({ ...w, resourceGroup: parseId(w.id).resourceGroup }));
export const runVmLogQuery = (rg, name, query) =>
  restJson("POST", `${WORKSPACES.path(rg, name)}/api/query`, { query: { "api-version": "2017-10-01" }, body: { query } });

// ── Connection monitor (Microsoft.Network/networkWatchers/{nw}/connectivityCheck) — the SAME
// shared netsim evaluator the Network security groups / Virtual networks consoles' Network
// Watcher connectivity-check tool uses, real NSG rules decide Reachable/Unreachable
// (azure.vms.monitoring). ────────────────────────────────────────────────────────────────
const NW_ARM = armType("Microsoft.Network", "networkWatchers", "2023-11-01");
const NETWORK_WATCHER_RG = "NetworkWatcherRG";
const networkWatcherName = (location) => `NetworkWatcher_${String(location || "eastus").toLowerCase()}`;
async function ensureNetworkWatcher(location) {
  const name = networkWatcherName(location);
  try { await NW_ARM.get(NETWORK_WATCHER_RG, name); }
  catch { await NW_ARM.put(NETWORK_WATCHER_RG, name, { location }); }
  return name;
}
export const connectionCheck = async (location, vmId, destinationAddress, destinationPort, protocol = "TCP") =>
  NW_ARM.action(NETWORK_WATCHER_RG, await ensureNetworkWatcher(location), "connectivityCheck",
    { source: { resourceId: vmId }, destination: { address: destinationAddress, port: Number(destinationPort) }, protocol });

// ── Microsoft Defender for Cloud (Microsoft.Security/assessments, scoped to this VM) — the
// SAME foundational CSPM rule engine (core/azure_security_core.py) the Defender for Cloud
// service's own Recommendations page uses, filtered to this one resource (azure.vms.defender). ──
const SEC_API = "2021-06-01";
export const listVmAssessments = async (vmId) =>
  (await restJson("GET", `${vmId}/providers/Microsoft.Security/assessments`, { query: { "api-version": SEC_API } })).value || [];
