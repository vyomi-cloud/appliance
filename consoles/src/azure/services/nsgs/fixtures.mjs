/* UI-conformance fixtures for Network security groups (ARM control plane: NSGs + nested
 * securityRules child resources + Microsoft.Authorization/locks). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const NSG = "uicnsg";
const nsgPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkSecurityGroups/${name}?api-version=2023-11-01`;

async function ensureNsg(wire) {
  await wire("PUT", nsgPath(NSG), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  "az-nsg": async (wire) => { await ensureNsg(wire); },

  "live-nsg": async (wire, uniq) => { await wire("PUT", nsgPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-inbound-rule": async (wire, uniq) => {
    await ensureNsg(wire);
    await wire("PUT", `${nsgPath(NSG).split("?")[0]}/securityRules/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { priority: 200, direction: "Inbound", access: "Allow", protocol: "Tcp", sourceAddressPrefix: "*", sourcePortRange: "*", destinationAddressPrefix: "*", destinationPortRange: "22" } },
    });
    return uniq;
  },

  "live-outbound-rule": async (wire, uniq) => {
    await ensureNsg(wire);
    await wire("PUT", `${nsgPath(NSG).split("?")[0]}/securityRules/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { priority: 200, direction: "Outbound", access: "Allow", protocol: "Tcp", sourceAddressPrefix: "*", sourcePortRange: "*", destinationAddressPrefix: "*", destinationPortRange: "443" } },
    });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureNsg(wire);
    await wire("PUT", `${nsgPath(NSG).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared "uicnsg" NSG is a real ARM mutation recorded under the NSG's
  // own name (core/azure_arm_core.py's `_locks` records the activity under the SCOPE's
  // name, not the lock's), so it lands on the unified Microsoft.Insights/eventtypes feed —
  // the lock NAME becomes the activity entry's "detail", so it is the uniquely-named thing
  // to look for.
  "live-activity": async (wire, uniq) => {
    await ensureNsg(wire);
    await wire("PUT", `${nsgPath(NSG).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  // Network interfaces / Subnets tabs: a uniquely named NIC, and a uniquely named vnet +
  // subnet, both pointing at the shared "uicnsg" NSG via properties.networkSecurityGroup.id
  // — the same subscription-wide association scan a real `az network nic/vnet subnet list`
  // would show, filtered client-side by the NSG's id (see api.js).
  "live-nic": async (wire, uniq) => {
    await ensureNsg(wire);
    await wire("PUT", `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/networkInterfaces/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { location: "eastus", properties: { networkSecurityGroup: { id: nsgPath(NSG).split("?")[0] } } },
    });
    return uniq;
  },

  "live-subnet": async (wire, uniq) => {
    await ensureNsg(wire);
    const vnetPath = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${uniq}-vnet?api-version=2023-11-01`;
    await wire("PUT", vnetPath, { svc: null, body: { location: "eastus" } });
    await wire("PUT", `${vnetPath.split("?")[0]}/subnets/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { addressPrefix: "10.0.1.0/24", networkSecurityGroup: { id: nsgPath(NSG).split("?")[0] } } },
    });
    return uniq;
  },
};
