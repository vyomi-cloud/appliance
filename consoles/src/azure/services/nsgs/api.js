/* Network security groups over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkSecurityGroups/{name}
 *   Security rules: a nested, same-namespace ARM child resource (NOT an extension resource
 *   like locks) — .../networkSecurityGroups/{nsg}/securityRules/{rule}, the same shape every
 *   azure-mgmt-network client / `az network nsg rule` call uses. Inbound and outbound rules
 *   share this one collection; `properties.direction` tells them apart. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.Network", "networkSecurityGroups", "2023-11-01");
const RULE_API_VERSION = "2023-11-01";
const NIC_ARM = armType("Microsoft.Network", "networkInterfaces", "2023-11-01");
const VNET_ARM = armType("Microsoft.Network", "virtualNetworks", "2023-11-01");
const VM_ARM = armType("Microsoft.Compute", "virtualMachines", "2023-09-01");
const NW_ARM = armType("Microsoft.Network", "networkWatchers", "2023-11-01");
const ARM_WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listNsgs = async () => (await ARM.list()).map(shape);
export const getNsg = async (rg, name) => shape(await ARM.get(rg, name));
export const createNsg = (rg, name, body) => ARM.put(rg, name, body);
export const updateNsg = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteNsg = (rg, name) => ARM.remove(rg, name);

// ── Security rules (Microsoft.Network/networkSecurityGroups/{nsg}/securityRules) ──────
const rulePath = (rg, name, ruleName) => `${ARM.path(rg, name)}/securityRules${ruleName ? `/${encodeURIComponent(ruleName)}` : ""}`;

export const listSecurityRules = async (rg, name) =>
  (await restJson("GET", rulePath(rg, name), { query: { "api-version": RULE_API_VERSION } })).value || [];
export const putSecurityRule = (rg, name, ruleName, body) =>
  restJson("PUT", rulePath(rg, name, ruleName), { query: { "api-version": RULE_API_VERSION }, body });
export const deleteSecurityRule = (rg, name, ruleName) =>
  restJson("DELETE", rulePath(rg, name, ruleName), { query: { "api-version": RULE_API_VERSION } });

/** The 3 default rules every real NSG ships in each direction — fixed, never editable or
 *  deletable, and not backed by a stored resource (same as the real portal's "Default rules"
 *  rows), so they're synthesized here rather than round-tripped through ARM. */
export const DEFAULT_RULES = [
  { name: "AllowVNetInBound", priority: 65000, direction: "Inbound", access: "Allow", protocol: "Any", source: "VirtualNetwork", destination: "VirtualNetwork", port: "Any" },
  { name: "AllowAzureLoadBalancerInBound", priority: 65001, direction: "Inbound", access: "Allow", protocol: "Any", source: "AzureLoadBalancer", destination: "Any", port: "Any" },
  { name: "DenyAllInBound", priority: 65500, direction: "Inbound", access: "Deny", protocol: "Any", source: "Any", destination: "Any", port: "Any" },
  { name: "AllowVNetOutBound", priority: 65000, direction: "Outbound", access: "Allow", protocol: "Any", source: "VirtualNetwork", destination: "VirtualNetwork", port: "Any" },
  { name: "AllowInternetOutBound", priority: 65001, direction: "Outbound", access: "Allow", protocol: "Any", source: "Any", destination: "Internet", port: "Any" },
  { name: "DenyAllOutBound", priority: 65500, direction: "Outbound", access: "Deny", protocol: "Any", source: "Any", destination: "Any", port: "Any" },
];

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this NSG) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Associations (Network interfaces / Subnets) — real ARM reads, no dedicated service
// owns these resource types in this lens yet, so the console can't offer an "Associate"
// picker, but any networkInterface or subnet an external tool pointed at this NSG shows up
// here (subscription-wide scan, matched by properties.networkSecurityGroup.id). ──────────
const sameNsg = (nsgId) => {
  const target = nsgId.toLowerCase();
  return (r) => (r.properties?.networkSecurityGroup?.id || "").toLowerCase() === target;
};

export const listNetworkInterfacesForNsg = async (nsgId) => (await NIC_ARM.list()).filter(sameNsg(nsgId));

export const listSubnetsForNsg = async (nsgId) => {
  const vnets = await VNET_ARM.list();
  const out = [];
  for (const vnet of vnets) {
    const { resourceGroup, name } = parseId(vnet.id);
    const subnets = (await restJson("GET", `${VNET_ARM.path(resourceGroup, name)}/subnets`, { query: { "api-version": "2023-11-01" } })).value || [];
    out.push(...subnets.filter(sameNsg(nsgId)).map((s) => ({ ...s, vnetName: name })));
  }
  return out;
};

/** "Associate" picker candidates: every network interface / subnet in the subscription
 *  that has no network security group of its own yet (same real-Azure constraint the
 *  portal's Associate dialog enforces — you dissociate the old one before picking a new
 *  one), so the console can finally offer the picker the NIC/Subnet lists above couldn't. */
/** Every network interface this NSG's rules apply to — associated directly, or through a
 *  subnet that carries this NSG — for the Effective security rules picker (azure.nsgs.effective_rules). */
export const listInterfacesInScope = async (nsgId) => {
  const [nics, subnets] = await Promise.all([NIC_ARM.list(), listSubnetsForNsg(nsgId)]);
  const subnetIds = new Set(subnets.map((s) => s.id.toLowerCase()));
  return nics.filter((n) => sameNsg(nsgId)(n) || subnetIds.has((n.properties?.ipConfigurations?.[0]?.properties?.subnet?.id || "").toLowerCase()));
};

const SUBNET_ID_RE = /\/resourceGroups\/([^/]+)\/providers\/Microsoft\.Network\/virtualNetworks\/([^/]+)\/subnets\/([^/]+)/i;
const getSubnetOfNic = async (nic) => {
  const m = (nic.properties?.ipConfigurations?.[0]?.properties?.subnet?.id || "").match(SUBNET_ID_RE);
  if (!m) return null;
  const [, rg, vnet, subnet] = m;
  return restJson("GET", `${VNET_ARM.path(rg, vnet)}/subnets/${encodeURIComponent(subnet)}`, { query: { "api-version": "2023-11-01" } });
};

const listSecurityRulesForNsgId = async (nsgId) => {
  if (!nsgId) return [];
  const { resourceGroup, name } = parseId(nsgId);
  return listSecurityRules(resourceGroup, name);
};

/** Effective security rules (azure.nsgs.effective_rules): the merged custom + default rule
 *  sets from both the NIC's own network security group and its subnet's — real ARM reads,
 *  same two-NSG picture `az network nic show-effective-nsg` / the real portal's page shows. */
export const loadEffectiveSecurityRules = async (nic) => {
  const subnet = await getSubnetOfNic(nic);
  const nicNsgId = nic.properties?.networkSecurityGroup?.id || "";
  const subnetNsgId = subnet?.properties?.networkSecurityGroup?.id || "";
  const [nicRules, subnetRules] = await Promise.all([listSecurityRulesForNsgId(nicNsgId), listSecurityRulesForNsgId(subnetNsgId)]);
  return {
    nicNsgName: nicNsgId ? parseId(nicNsgId).name : "",
    subnetNsgName: subnetNsgId ? parseId(subnetNsgId).name : "",
    nicRules, subnetRules,
  };
};

export const listUnassociatedNics = async () => (await NIC_ARM.list()).filter((r) => !r.properties?.networkSecurityGroup?.id);
export const associateNic = (nic, nsgId) => {
  const { resourceGroup, name } = parseId(nic.id);
  return NIC_ARM.patch(resourceGroup, name, { properties: { networkSecurityGroup: { id: nsgId } } });
};

export const listUnassociatedSubnets = async () => {
  const vnets = await VNET_ARM.list();
  const out = [];
  for (const vnet of vnets) {
    const { resourceGroup, name } = parseId(vnet.id);
    const subnets = (await restJson("GET", `${VNET_ARM.path(resourceGroup, name)}/subnets`, { query: { "api-version": "2023-11-01" } })).value || [];
    out.push(...subnets.filter((s) => !s.properties?.networkSecurityGroup?.id).map((s) => ({ ...s, vnetName: name, resourceGroup })));
  }
  return out;
};
export const associateSubnet = (subnet, nsgId) =>
  restJson("PUT", `${VNET_ARM.path(subnet.resourceGroup, subnet.vnetName)}/subnets/${encodeURIComponent(subnet.name)}`, {
    query: { "api-version": "2023-11-01" }, body: { properties: { ...subnet.properties, networkSecurityGroup: { id: nsgId } } },
  });

// ── Access control (IAM): Microsoft.Authorization/roleAssignments + roleDefinitions +
// checkAccess, all real ARM resources/actions resource-scoped to this NSG (plus its
// subscription/resource-group ancestors — real Azure's inherited-access view) ────────────
const AUTHZ_API = "2022-04-01";
export const listRoleAssignments = async (nsgId) =>
  (await restJson("GET", `${nsgId}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API } })).value || [];
export const checkAccess = async (nsgId, principalId, action) =>
  (await restJson("POST", `${nsgId}/providers/Microsoft.Authorization/checkAccess`, { query: { "api-version": AUTHZ_API }, body: { principalId, action } })).value || [];

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension
// resource scoped to this NSG's own id — same generic mechanism core/azure_arm_core.py's
// AzureArm._diagnostic_settings exposes for every lens resource). Logs/metrics are stored
// and validated exactly as the real resource requires, but never delivered anywhere. ─────
const DIAG_API = "2021-05-01-preview";
const diagPath = (nsgId, setting) => `${nsgId}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (nsgId) => (await restJson("GET", diagPath(nsgId), { query: { "api-version": DIAG_API } })).value || [];
export const putDiagnosticSetting = (nsgId, setting, body) => restJson("PUT", diagPath(nsgId, setting), { query: { "api-version": DIAG_API }, body });
export const deleteDiagnosticSetting = (nsgId, setting) => restJson("DELETE", diagPath(nsgId, setting), { query: { "api-version": DIAG_API } });
export const listWorkspaces = async () => (await ARM_WORKSPACES.list()).map((w) => ({ id: w.id, name: w.name }));

// ── Network Watcher: IP flow verify / Next hop (Microsoft.Network/networkWatchers/{nw}/
// ipFlowVerify|nextHop, answered by the shared netsim evaluator — core/azure_arm_core.py
// _network_watcher). Reached from this NSG's "Diagnose and solve problems" blade, same as
// the real portal; the tool itself is a subscription/region-wide Network Watcher action, not
// scoped to this NSG, so it lists every VM in the subscription like the real picker does. ──
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

// ── create-NSG form model → ARM body ────────────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {},
  };
}
