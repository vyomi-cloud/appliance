/* UI-conformance fixtures for Virtual networks (ARM control plane: vnets + nested subnets /
 * virtualNetworkPeerings child resources + Microsoft.Authorization/locks). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const VNET = "uicvnet";
const SUB_ROOT = `/subscriptions/${SUB}/resourceGroups/${RG}`;
const vnetPath = (name) => `${SUB_ROOT}/providers/Microsoft.Network/virtualNetworks/${name}?api-version=2023-11-01`;

async function ensureVnet(wire) {
  await wire("PUT", vnetPath(VNET), { svc: null, body: { location: "eastus", properties: { addressSpace: { addressPrefixes: ["10.0.0.0/16"] } } } }).catch(() => {});
}

export default {
  "az-vnet": async (wire) => { await ensureVnet(wire); },

  "live-vnet": async (wire, uniq) => { await wire("PUT", vnetPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-activity": async (wire, uniq) => {
    await ensureVnet(wire);
    await wire("PUT", `${vnetPath(VNET).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-subnet": async (wire, uniq) => {
    await ensureVnet(wire);
    await wire("PUT", `${vnetPath(VNET).split("?")[0]}/subnets/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { addressPrefix: "10.0.9.0/24" } },
    });
    return uniq;
  },

  "live-peering": async (wire, uniq) => {
    await ensureVnet(wire);
    const remote = `${uniq}-remote`;
    const remotePath = vnetPath(remote).split("?")[0];
    await wire("PUT", vnetPath(remote), { svc: null, body: { location: "eastus" } });
    await wire("PUT", `${vnetPath(VNET).split("?")[0]}/virtualNetworkPeerings/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { remoteVirtualNetwork: { id: remotePath }, peeringState: "Connected", peeringSyncLevel: "FullyInSync" } },
    });
    return uniq;
  },

  "live-service-endpoint": async (wire, uniq) => {
    await ensureVnet(wire);
    await wire("PUT", `${vnetPath(VNET).split("?")[0]}/subnets/${uniq}?api-version=2023-11-01`, {
      svc: null, body: { properties: { addressPrefix: "10.0.50.0/24", serviceEndpoints: [{ service: "Microsoft.Storage", locations: ["*"] }] } },
    });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureVnet(wire);
    await wire("PUT", `${vnetPath(VNET).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  "live-nic": async (wire, uniq) => {
    await ensureVnet(wire);
    const subnetPath = `${vnetPath(VNET).split("?")[0]}/subnets/default`;
    await wire("PUT", `${subnetPath}?api-version=2023-11-01`, { svc: null, body: { properties: { addressPrefix: "10.0.0.0/24" } } });
    const nicPath = `${SUB_ROOT}/providers/Microsoft.Network/networkInterfaces/${uniq}?api-version=2023-11-01`;
    await wire("PUT", nicPath, { svc: null, body: { location: "eastus", properties: { ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: subnetPath } } }] } } });
    return uniq;
  },
};
