/* Virtual networks over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{name}
 *   Subnets, peerings: nested, same-namespace ARM child resources (NOT extension resources
 *   like locks) — .../virtualNetworks/{vnet}/subnets/{subnet} and .../virtualNetworkPeerings/{peering},
 *   the same shape every azure-mgmt-network client / `az network vnet subnet|peering` call uses. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.Network", "virtualNetworks", "2023-11-01");
const NSG_ARM = armType("Microsoft.Network", "networkSecurityGroups", "2023-11-01");
const NIC_ARM = armType("Microsoft.Network", "networkInterfaces", "2023-11-01");
const CHILD_API_VERSION = "2023-11-01";

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listVnets = async () => (await ARM.list()).map(shape);
export const getVnet = async (rg, name) => shape(await ARM.get(rg, name));
export const createVnet = (rg, name, body) => ARM.put(rg, name, body);
export const updateVnet = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteVnet = (rg, name) => ARM.remove(rg, name);

// ── Subnets (Microsoft.Network/virtualNetworks/{vnet}/subnets) ────────────────────────
const subnetPath = (rg, name, subnetName) => `${ARM.path(rg, name)}/subnets${subnetName ? `/${encodeURIComponent(subnetName)}` : ""}`;

export const listSubnets = async (rg, name) =>
  (await restJson("GET", subnetPath(rg, name), { query: { "api-version": CHILD_API_VERSION } })).value || [];
export const putSubnet = (rg, name, subnetName, body) =>
  restJson("PUT", subnetPath(rg, name, subnetName), { query: { "api-version": CHILD_API_VERSION }, body });
export const deleteSubnet = (rg, name, subnetName) =>
  restJson("DELETE", subnetPath(rg, name, subnetName), { query: { "api-version": CHILD_API_VERSION } });

// ── Peerings (Microsoft.Network/virtualNetworks/{vnet}/virtualNetworkPeerings) ─────────
const peeringPath = (rg, name, peerName) => `${ARM.path(rg, name)}/virtualNetworkPeerings${peerName ? `/${encodeURIComponent(peerName)}` : ""}`;

export const listPeerings = async (rg, name) =>
  (await restJson("GET", peeringPath(rg, name), { query: { "api-version": CHILD_API_VERSION } })).value || [];
export const putPeering = (rg, name, peerName, body) =>
  restJson("PUT", peeringPath(rg, name, peerName), { query: { "api-version": CHILD_API_VERSION }, body });
export const deletePeering = (rg, name, peerName) =>
  restJson("DELETE", peeringPath(rg, name, peerName), { query: { "api-version": CHILD_API_VERSION } });

/** The portal's "Add" peering blade provisions a peering object on BOTH virtual networks it
 *  connects (so each side sees the connection) — same real ARM write, done twice. */
export async function addPeeringBothSides(rg, name, peerName, remoteRg, remoteName, remotePeerName, opts) {
  const localId = ARM.path(rg, name);
  const remoteId = ARM.path(remoteRg, remoteName);
  const props = (selfId, otherId) => ({
    properties: {
      remoteVirtualNetwork: { id: otherId },
      peeringState: "Connected", peeringSyncLevel: "FullyInSync",
      allowForwardedTraffic: !!opts.allowForwardedTraffic,
      allowGatewayTransit: !!opts.allowGatewayTransit,
      useRemoteGateways: !!opts.useRemoteGateways,
      allowVirtualNetworkAccess: true,
    },
  });
  await putPeering(rg, name, peerName, props(localId, remoteId));
  await putPeering(remoteRg, remoteName, remotePeerName, props(remoteId, localId));
}

// ── Service endpoints — a {service, locations} entry on a subnet's properties.serviceEndpoints,
// same shape real ARM uses; set via PATCH on the owning subnet. ─────────────────────────
export async function addServiceEndpoint(rg, name, subnetName, subnet, service) {
  const existing = subnet.properties?.serviceEndpoints || [];
  const endpoints = [...existing, { service, locations: ["*"], provisioningState: "Succeeded" }];
  return putSubnet(rg, name, subnetName, { properties: { ...subnet.properties, serviceEndpoints: endpoints } });
}
export async function removeServiceEndpoint(rg, name, subnetName, subnet, service) {
  const endpoints = (subnet.properties?.serviceEndpoints || []).filter((e) => e.service !== service);
  return putSubnet(rg, name, subnetName, { properties: { ...subnet.properties, serviceEndpoints: endpoints } });
}

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this vnet) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Network security groups — for the Subnets "Network security group" picker ──────────
export const listNsgs = async () => (await NSG_ARM.list()).map(shape);

// ── Connected devices — any Microsoft.Network/networkInterfaces resource in the
// subscription whose ipConfigurations[].subnet.id points at one of this vnet's subnets
// (a subscription-wide scan, same mechanic as the NSG lens's association tabs: no dedicated
// "network interface" console in this lens yet to create/attach a NIC from, but one created
// over ARM/CLI/another tool shows up here). ────────────────────────────────────────────────
export const listConnectedDevices = async (rg, name) => {
  const prefix = `${ARM.path(rg, name)}/subnets/`.toLowerCase();
  const nics = await NIC_ARM.list();
  return nics.filter((n) => (n.properties?.ipConfigurations || []).some((c) => (c.properties?.subnet?.id || "").toLowerCase().startsWith(prefix)));
};

// ── create-vnet form model → ARM body ───────────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      addressSpace: { addressPrefixes: f.addressPrefixes.filter(Boolean) },
      encryption: { enabled: f.encryption, enforcement: "AllowUnencrypted" },
    },
  };
}
