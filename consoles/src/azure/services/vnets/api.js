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
const ROUTE_TABLE_ARM = armType("Microsoft.Network", "routeTables", "2023-11-01");
const NAT_GATEWAY_ARM = armType("Microsoft.Network", "natGateways", "2023-11-01");
const VM_ARM = armType("Microsoft.Compute", "virtualMachines", "2023-09-01");
const NW_ARM = armType("Microsoft.Network", "networkWatchers", "2023-11-01");
const NETWORK_MANAGER_ARM = armType("Microsoft.Network", "networkManagers", "2024-05-01");
const METRIC_ALERTS_ARM = armType("Microsoft.Insights", "metricAlerts", "2018-03-01");
const ACTIVITY_LOG_ALERTS_ARM = armType("Microsoft.Insights", "activityLogAlerts", "2020-10-01");
const ARM_WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");
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

// ── Access control (IAM): Microsoft.Authorization/roleAssignments + roleDefinitions +
// checkAccess, all real ARM resources/actions resource-scoped to this vnet (plus its
// subscription/resource-group ancestors — real Azure's inherited-access view) ────────────────
const AUTHZ_API = "2022-04-01";
export const listRoleAssignments = async (vnetId) =>
  (await restJson("GET", `${vnetId}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API } })).value || [];
export const checkAccess = async (vnetId, principalId, action) =>
  (await restJson("POST", `${vnetId}/providers/Microsoft.Authorization/checkAccess`, { query: { "api-version": AUTHZ_API }, body: { principalId, action } })).value || [];

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this vnet) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Network security groups — for the Subnets "Network security group" picker ──────────
export const listNsgs = async () => (await NSG_ARM.list()).map(shape);

// ── Route tables / NAT gateways — Microsoft.Network/routeTables and natGateways, real ARM
// resource types the shared network engine (core/netsim) evaluates for subnet egress and
// UDR behaviour. No dedicated console creates one yet (same as NSGs' earlier state): a route
// table or NAT gateway created over ARM/CLI shows up here for the Subnets pickers. ──────────
export const listRouteTables = async () => (await ROUTE_TABLE_ARM.list()).map(shape);
export const listNatGateways = async () => (await NAT_GATEWAY_ARM.list()).map(shape);

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

// ── Network Watcher: IP flow verify / Next hop / Connection troubleshoot
// (Microsoft.Network/networkWatchers/{nw}/ipFlowVerify|nextHop|connectivityCheck, answered by
// the shared netsim evaluator — core/azure_arm_core.py _network_watcher). IP flow verify and
// Next hop are reached from this vnet's "Diagnose and solve problems" blade, Connection
// troubleshoot from its own Monitoring menu item, same as the real portal; the tools
// themselves are a subscription/region-wide Network Watcher action, not scoped to this vnet,
// so they list every VM in the subscription like the real picker does. ──────────────────────
const NETWORK_WATCHER_RG = "NetworkWatcherRG";
const networkWatcherName = (location) => `NetworkWatcher_${String(location || "eastus").toLowerCase()}`;

export const listVmsForDiagnostics = async () => (await VM_ARM.list()).map(shape);
export const listNics = async () => (await NIC_ARM.list()).map(shape);

/** Auto-provisions the regional network watcher the first time a location is diagnosed —
 *  the same "Enable Network Watcher" step the real portal does silently on first use. */
async function ensureNetworkWatcher(location) {
  const name = networkWatcherName(location);
  try { await NW_ARM.get(NETWORK_WATCHER_RG, name); }
  catch { await NW_ARM.put(NETWORK_WATCHER_RG, name, { location }); }
  return name;
}
export const ipFlowVerify = async (location, body) => NW_ARM.action(NETWORK_WATCHER_RG, await ensureNetworkWatcher(location), "ipFlowVerify", body);
export const nextHop = async (location, body) => NW_ARM.action(NETWORK_WATCHER_RG, await ensureNetworkWatcher(location), "nextHop", body);
export const connectivityCheck = async (location, body) => NW_ARM.action(NETWORK_WATCHER_RG, await ensureNetworkWatcher(location), "connectivityCheck", body);

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this vnet's own id — same generic mechanism core/azure_arm_core.py's
// AzureArm._diagnostic_settings exposes for every lens resource). Logs/metrics are stored
// and validated exactly as the real resource requires, but never delivered anywhere. ─────
const DIAG_API = "2021-05-01-preview";
const diagPath = (vnetId, setting) => `${vnetId}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (vnetId) => (await restJson("GET", diagPath(vnetId), { query: { "api-version": DIAG_API } })).value || [];
export const putDiagnosticSetting = (vnetId, setting, body) => restJson("PUT", diagPath(vnetId, setting), { query: { "api-version": DIAG_API }, body });
export const deleteDiagnosticSetting = (vnetId, setting) => restJson("DELETE", diagPath(vnetId, setting), { query: { "api-version": DIAG_API } });
export const listWorkspaces = async () => (await ARM_WORKSPACES.list()).map((w) => ({ id: w.id, name: w.name, resourceGroup: parseId(w.id).resourceGroup }));

// ── Logs (Microsoft.OperationalInsights/workspaces/{ws}/api/query) — the same ARM
// pass-through the Azure Portal's resource-scoped Logs blade uses, carrying a small real KQL
// subset (core/azure_operationalinsights_core.py). AzureActivity rows are the real per-
// resource Activity log entries this vnet's own Activity log tab reads. ──────────────────
export const LOG_QUERY_API_VERSION = "2017-10-01";
export const runLogQuery = (rg, name, query) =>
  restJson("POST", `${ARM_WORKSPACES.path(rg, name)}/api/query`, { query: { "api-version": LOG_QUERY_API_VERSION }, body: { query } });

// ── Alerts — metric alert / activity log alert rules (Microsoft.Insights/metricAlerts,
// activityLogAlerts) whose own `scopes` names this vnet, same resources the Monitor service's
// Alerts page lists subscription-wide (core/azure_monitor_core.py); Vyomi stores alert rules
// but runs no live metric-evaluation loop, same honest limitation as azure.monitor.alert_rules. ─
export async function listAlertsForResource(vnetId) {
  const [metric, activity] = await Promise.all([METRIC_ALERTS_ARM.list(), ACTIVITY_LOG_ALERTS_ARM.list()]);
  const scoped = (r) => (r.properties?.scopes || []).some((s) => String(s).toLowerCase() === vnetId.toLowerCase());
  return [
    ...metric.filter(scoped).map((r) => ({ id: r.id, name: r.name, kind: "Metric", severity: r.properties.severity, enabled: r.properties.enabled })),
    ...activity.filter(scoped).map((r) => ({ id: r.id, name: r.name, kind: "Activity Log", severity: null, enabled: r.properties.enabled })),
  ];
}

// ── IP address pools (Microsoft.Network/networkManagers/{nm}/ipamPools) — a nested ARM child
// resource reached through the generic type/name alternation (core/azure_arm_core.py), same
// mechanic as a container registry's webhooks. Allocating a block from a pool for a vnet's
// address space (the "Allocate using IP address pools" checkbox) is ENFORCED server-side —
// AzureArm._allocate_ipam_pool carves a real non-overlapping CIDR block, never a stored label. ─
const IPAM_API_VERSION = "2024-05-01";
export const listNetworkManagers = async () => (await NETWORK_MANAGER_ARM.list()).map(shape);
export const putNetworkManager = (rg, name, body) => NETWORK_MANAGER_ARM.put(rg, name, body);
const ipamPoolPath = (rg, nmName, poolName) => `${NETWORK_MANAGER_ARM.path(rg, nmName)}/ipamPools${poolName ? `/${encodeURIComponent(poolName)}` : ""}`;
export const listIpamPools = async (rg, nmName) => (await restJson("GET", ipamPoolPath(rg, nmName), { query: { "api-version": IPAM_API_VERSION } })).value || [];
export const putIpamPool = (rg, nmName, poolName, body) => restJson("PUT", ipamPoolPath(rg, nmName, poolName), { query: { "api-version": IPAM_API_VERSION }, body });
/** Every IP address pool in the subscription, regardless of which network manager owns it —
 *  there's no dedicated Network Manager console yet (same honest state NAT gateways/route
 *  tables were in before this lens had a console for them): a pool created over ARM/CLI, or
 *  through this wizard's own "Create new" shortcut, shows up in the Create VNet picker. */
export async function listAllIpamPools() {
  const nms = await listNetworkManagers();
  const lists = await Promise.all(nms.map((nm) => listIpamPools(nm.resourceGroup, nm.name).catch(() => [])));
  return nms.flatMap((nm, i) => lists[i].map((p) => ({ ...p, networkManagerName: nm.name, resourceGroup: nm.resourceGroup })));
}

// ── create-vnet form model → ARM body ───────────────────────────────────────────────────
export function toArmBody(f) {
  const addressSpace = f.ipamPool
    ? { ipamPoolPrefixAllocations: [{ pool: { id: f.ipamPool }, numberOfIpAddresses: String(f.ipamPoolSize || 256) }] }
    : { addressPrefixes: f.addressPrefixes.filter(Boolean) };
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      addressSpace,
      encryption: { enabled: f.encryption, enforcement: "AllowUnencrypted" },
    },
  };
}
