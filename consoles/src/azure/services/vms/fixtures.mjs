/* UI-conformance fixtures for Virtual machines (ARM control plane: virtual machines + the
 * network interface / network security group + security rules they reference + the
 * Microsoft.Authorization/locks extension resource — same engines api.js uses). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const VM = "uicvm";
const NIC = `${VM}-nic`;
const NSG = `${VM}-nsg`;
const vmPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Compute/virtualMachines/${name}?api-version=2023-09-01`;
const nicPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${name}?api-version=2023-11-01`;
const nsgPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${name}?api-version=2023-11-01`;

const VM_BODY = {
  location: "eastus",
  properties: {
    hardwareProfile: { vmSize: "Standard_D2s_v5" },
    osProfile: { computerName: VM, adminUsername: "azureuser", linuxConfiguration: { disablePasswordAuthentication: true } },
    storageProfile: { imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts", version: "latest" }, osDisk: { osType: "Linux", createOption: "FromImage", diskSizeGB: 30, managedDisk: { storageAccountType: "Premium_LRS" } }, dataDisks: [] },
    networkProfile: { networkInterfaces: [{ id: nicPath(NIC).split("?")[0], properties: { primary: true } }] },
  },
};

async function ensureVm(wire) {
  await wire("PUT", nsgPath(NSG), { svc: null, body: { location: "eastus" } }).catch(() => {});
  await wire("PUT", nicPath(NIC), { svc: null, body: { location: "eastus", properties: {
    ipConfigurations: [{ name: "ipconfig1", properties: { privateIPAllocationMethod: "Dynamic", privateIPAddress: "10.0.0.4", subnet: { id: `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/uic-vnet/subnets/default` } } }],
    networkSecurityGroup: { id: nsgPath(NSG).split("?")[0] },
  } } }).catch(() => {});
  await wire("PUT", vmPath(VM), { svc: null, body: VM_BODY }).catch(() => {});
}

export default {
  "az-vm": async (wire) => { await ensureVm(wire); },

  "live-vm": async (wire, uniq) => {
    await wire("PUT", nicPath(`${uniq}-nic`), { svc: null, body: { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { privateIPAllocationMethod: "Dynamic", privateIPAddress: "10.0.0.5" } }] } } });
    await wire("PUT", vmPath(uniq), { svc: null, body: { location: "eastus", properties: { hardwareProfile: { vmSize: "Standard_B2s" }, osProfile: { computerName: uniq, adminUsername: "azureuser", linuxConfiguration: { disablePasswordAuthentication: true } }, storageProfile: { imageReference: { publisher: "Canonical", offer: "0001-com-ubuntu-server-jammy", sku: "22_04-lts", version: "latest" }, osDisk: { osType: "Linux", createOption: "FromImage" } }, networkProfile: { networkInterfaces: [{ id: nicPath(`${uniq}-nic`).split("?")[0] }] } } } });
    return uniq;
  },

  // A lock write on the shared "uicvm" VM is a real ARM mutation recorded under the VM's own
  // name (core/azure_arm_core.py's `_locks` records the activity under the SCOPE's name, not
  // the lock's), so it lands on the unified Microsoft.Insights/eventtypes feed — the lock
  // NAME becomes the activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureVm(wire);
    await wire("PUT", `${vmPath(VM).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureVm(wire);
    await wire("PUT", `${vmPath(VM).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  "live-disk": async (wire, uniq) => {
    await ensureVm(wire);
    await wire("PATCH", vmPath(VM), { svc: null, body: { properties: { storageProfile: { dataDisks: [{ lun: 0, name: uniq, diskSizeGB: 64, managedDisk: { storageAccountType: "Premium_LRS" } }] } } } });
    return uniq;
  },

  "live-rule": async (wire, uniq) => {
    await ensureVm(wire);
    await wire("PUT", `${nsgPath(NSG).split("?")[0]}/securityRules/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { priority: 310, direction: "Inbound", access: "Allow", protocol: "Tcp", sourceAddressPrefix: "*", sourcePortRange: "*", destinationAddressPrefix: "*", destinationPortRange: "8080" } },
    });
    return uniq;
  },
};
