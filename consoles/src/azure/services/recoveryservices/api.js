/* Recovery Services vaults: Azure Backup + Site Recovery over ARM (core/azure_backup_core.py). */
import { restJson } from "../../../common/wire.js";
import { armType, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.RecoveryServices", "vaults", "2024-04-01");
const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });
const Q = { "api-version": "2024-04-01" };
const G = async (path) => (await restJson("GET", path, { query: Q })).value || [];

export const listVaults = async () => (await ARM.list()).map(shape);
export const getVault = async (rg, n) => shape(await ARM.get(rg, n));
export const createVault = (rg, n, body) => ARM.put(rg, n, body);
export const deleteVault = (rg, n) => ARM.remove(rg, n);

const V = (v) => ARM.path(v.resourceGroup, v.name);
export const policies = (v) => G(`${V(v)}/backupPolicies`);
export const putPolicy = (v, name, properties) => restJson("PUT", `${V(v)}/backupPolicies/${encodeURIComponent(name)}`, { query: Q, body: { properties } });
export const deletePolicy = (v, name) => restJson("DELETE", `${V(v)}/backupPolicies/${encodeURIComponent(name)}`, { query: Q });
export const items = (v) => G(`${V(v)}/backupProtectedItems`);
export const jobs = (v) => G(`${V(v)}/backupJobs`);
export const usage = (v) => G(`${V(v)}/backupUsageSummaries`);
export const vaultConfig = async (v) => (await restJson("GET", `${V(v)}/backupconfig/vaultconfig`, { query: Q })).properties || {};
export const putVaultConfig = (v, properties) => restJson("PUT", `${V(v)}/backupconfig/vaultconfig`, { query: Q, body: { properties } });
export const storageConfig = async (v) => (await restJson("GET", `${V(v)}/backupstorageconfig/vaultstorageconfig`, { query: Q })).properties || {};
export const putStorageConfig = (v, properties) => restJson("PUT", `${V(v)}/backupstorageconfig/vaultstorageconfig`, { query: Q, body: { properties } });

/** item.id is the full ARM id of the protected item. */
export const backupNow = (item) => restJson("POST", `${item.id}/backup`, { query: Q, body: { properties: { objectType: item.properties.protectedItemType === "AzureFileShareProtectedItem" ? "AzureFileShareBackupRequest" : "IaasVMBackupRequest" } } });
export const recoveryPoints = (item) => G(`${item.id}/recoveryPoints`);
export const restore = (item, rp, properties) => restJson("POST", `${item.id}/recoveryPoints/${encodeURIComponent(rp)}/restore`, { query: Q, body: { properties } });
export const stopProtection = (item) => restJson("DELETE", item.id, { query: Q });
export const protect = (v, kind, sourceId, rg, name, policyId, shareName) => {
  const c = kind === "vm" ? `iaasvmcontainer;iaasvmcontainerv2;${rg};${name}` : `storagecontainer;Storage;${rg};${name}`;
  const i = kind === "vm" ? `vm;iaasvmcontainerv2;${rg};${name}` : `azurefileshare;${shareName}`;
  return restJson("PUT", `${V(v)}/backupFabrics/Azure/protectionContainers/${c}/protectedItems/${i}`, { query: Q, body: { properties: { protectedItemType: kind === "vm" ? "Microsoft.Compute/virtualMachines" : "AzureFileShareProtectedItem", policyId, sourceResourceId: sourceId } } });
};
export const listVms = async () => (await restJson("GET", `/subscriptions/${parseId(ARM.path("x", "y")).subscription}/providers/Microsoft.Compute/virtualMachines`, { query: { "api-version": "2023-09-01" } })).value || [];

// ── Site Recovery ──
export const fabrics = (v) => G(`${V(v)}/replicationFabrics`);
export const replicated = (v) => G(`${V(v)}/replicationProtectedItems`);
export const rjobs = (v) => G(`${V(v)}/replicationJobs`);
export const putFabric = (v, name, location) => restJson("PUT", `${V(v)}/replicationFabrics/${encodeURIComponent(name)}`, { query: Q, body: { properties: { customDetails: { instanceType: "Azure", location } } } });
export const enableReplication = (v, fabric, name, vmId, targetLocation, targetRgId) => restJson("PUT", `${V(v)}/replicationFabrics/${encodeURIComponent(fabric)}/replicationProtectionContainers/default/replicationProtectedItems/${encodeURIComponent(name)}`, { query: Q, body: { properties: { providerSpecificDetails: { instanceType: "A2A", fabricObjectId: vmId, recoveryAzureLocation: targetLocation, recoveryResourceGroupId: targetRgId } } } });
export const rAction = (item, act, networkId) => restJson("POST", `${item.id}/${act}`, { query: Q, body: { properties: networkId ? { providerSpecificDetails: { instanceType: "A2A", recoveryAzureNetworkId: networkId } } : {} } });
export const disableReplication = (item) => restJson("DELETE", item.id, { query: Q });
export const listVnets = async () => (await restJson("GET", `/subscriptions/${parseId(ARM.path("x", "y")).subscription}/providers/Microsoft.Network/virtualNetworks`, { query: { "api-version": "2023-09-01" } })).value || [];
