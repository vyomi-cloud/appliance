/* Virtual machines over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}
 *   Power actions: POST .../start | restart | powerOff | deallocate (metadata-only power state —
 *   see core/azure_arm_core.py's generic VM action handler).
 *   Network interface + (optional) network security group + its security rules are real, separate
 *   ARM resources this service also creates at VM-create time (Microsoft.Network/networkInterfaces,
 *   Microsoft.Network/networkSecurityGroups/securityRules) — the same engine the Network security
 *   groups console (../nsgs/) uses, so a rule added here or there round-trips identically.
 *   Disks (OS + data) are embedded on the VM's own properties.storageProfile, the same shape the
 *   create wizard writes — Azure VMs don't have a standalone Microsoft.Compute/disks resource in
 *   this lens (see core/capabilities/azure/vms.json: azure.vms.disks). */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.Compute", "virtualMachines", "2023-09-01");
const NIC_ARM = armType("Microsoft.Network", "networkInterfaces", "2023-11-01");
const NSG_ARM = armType("Microsoft.Network", "networkSecurityGroups", "2023-11-01");
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
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

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
  return {
    location: f.location,
    properties: {
      enableAcceleratedNetworking: !!f.acceleratedNetworking,
      ipConfigurations: [{ name: "ipconfig1", properties: { privateIPAllocationMethod: "Dynamic", privateIPAddress: pseudoIp(f.name), subnet: { id: subnetId } } }],
    },
  };
}

export function toNsgBody(f) {
  return { location: f.location, tags: {}, properties: {} };
}
