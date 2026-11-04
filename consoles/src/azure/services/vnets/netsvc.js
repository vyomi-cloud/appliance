/* Network services over the native ARM wire (core/azure_netsvc_core.py): private endpoints, Bastion hosts,
 * Azure Firewall + firewall policies, DDoS protection plans, NSG / vnet flow logs.
 * Real ARM calls only; the engine validates (subnet names/sizes, tiers, regions, quotas) and answers with the
 * real error codes, which the panels surface. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription } from "../../kit/arm.js";

const V = "2023-11-01";
export const PE = armType("Microsoft.Network", "privateEndpoints", V);
export const BASTION = armType("Microsoft.Network", "bastionHosts", V);
export const FIREWALL = armType("Microsoft.Network", "azureFirewalls", V);
export const POLICY = armType("Microsoft.Network", "firewallPolicies", V);
export const DDOS = armType("Microsoft.Network", "ddosProtectionPlans", V);
export const PIP = armType("Microsoft.Network", "publicIPAddresses", V);
export const NW = armType("Microsoft.Network", "networkWatchers", V);
const VNET = armType("Microsoft.Network", "virtualNetworks", V);
const STORAGE = armType("Microsoft.Storage", "storageAccounts", "2023-01-01");
const sub = () => `/subscriptions/${getSubscription()}`;

export const rgOf = (id = "") => (id.match(/resourceGroups\/([^/]+)/i) || [])[1];
const same = (a, b) => String(a || "").toLowerCase() === String(b || "").toLowerCase();

// ── CIDR helpers ─────────────────────────────────────────────────────────────────────────
const ip2n = (ip) => ip.split(".").reduce((a, o) => a * 256 + Number(o), 0);
const n2ip = (n) => [24, 16, 8, 0].map((s) => Math.floor(n / 2 ** s) % 256).join(".");
const parse = (c) => { const [ip, l] = c.split("/"); const len = Number(l); const size = 2 ** (32 - len); const base = Math.floor(ip2n(ip) / size) * size; return { base, size, len }; };
/** First free block of `len` bits inside the vnet's address space not overlapping any existing subnet. */
export function freeBlock(vnet, subnets, len) {
  const taken = (subnets || []).flatMap((s) => (s.properties?.addressPrefixes || [s.properties?.addressPrefix]).filter(Boolean)).map(parse);
  const size = 2 ** (32 - len);
  for (const space of vnet.properties?.addressSpace?.addressPrefixes || []) {
    const sp = parse(space);
    for (let b = sp.base; b + size <= sp.base + sp.size; b += size) {
      if (!taken.some((t) => b < t.base + t.size && t.base < b + size)) return `${n2ip(b)}/${len}`;
    }
  }
  return "";
}

// ── listings ──────────────────────────────────────────────────────────────────────────────
const inVnet = (vnetId, subnetId) => String(subnetId || "").toLowerCase().startsWith(String(vnetId).toLowerCase() + "/subnets/");
export async function listPrivateEndpoints(vnetId) {
  return (await PE.list()).filter((p) => inVnet(vnetId, p.properties?.subnet?.id));
}
export async function listBastions(vnetId) {
  return (await BASTION.list()).filter((b) => (b.properties?.ipConfigurations || []).some((c) => inVnet(vnetId, c.properties?.subnet?.id)) || same(b.properties?.virtualNetwork?.id, vnetId));
}
export async function listFirewalls(vnetId) {
  return (await FIREWALL.list()).filter((f) => (f.properties?.ipConfigurations || []).some((c) => inVnet(vnetId, c.properties?.subnet?.id)));
}

// ── deployments (what the portal's wizards do: ensure subnet + public IP, then the resource) ──
async function ensureSubnet(rg, vnetName, name, prefix) {
  const path = `${VNET.path(rg, vnetName)}/subnets/${name}`;
  try { return await restJson("GET", path, { query: { "api-version": V } }); } catch { /* create */ }
  return restJson("PUT", path, { query: { "api-version": V }, body: { properties: { addressPrefix: prefix } } });
}
async function newPip(rg, name, location) {
  return PIP.put(rg, name, { location, sku: { name: "Standard" }, properties: { publicIPAllocationMethod: "Static" } });
}
export async function deployBastion(vnet, { name, sku = "Standard", prefix, tunneling = false, ipConnect = false, shareableLink = false, scaleUnits }) {
  const rg = rgOf(vnet.id);
  const subnet = await ensureSubnet(rg, vnet.name, "AzureBastionSubnet", prefix);
  if (sku === "Developer") return BASTION.put(rg, name, { location: vnet.location, sku: { name: sku }, properties: { virtualNetwork: { id: vnet.id } } });
  const pip = await newPip(rg, `${name}-pip`, vnet.location);
  const props = { ipConfigurations: [{ name: "IpConf", properties: { subnet: { id: subnet.id }, publicIPAddress: { id: pip.id } } }] };
  if (sku !== "Basic") Object.assign(props, { enableTunneling: tunneling, enableIpConnect: ipConnect, enableShareableLink: shareableLink, scaleUnits: scaleUnits || 2 });
  return BASTION.put(rg, name, { location: vnet.location, sku: { name: sku }, properties: props });
}
export async function deployFirewall(vnet, { name, tier = "Standard", prefix, mgmtPrefix, policyId }) {
  const rg = rgOf(vnet.id);
  const subnet = await ensureSubnet(rg, vnet.name, "AzureFirewallSubnet", prefix);
  const pip = await newPip(rg, `${name}-pip`, vnet.location);
  const props = { sku: { name: "AZFW_VNet", tier }, ipConfigurations: [{ name: "ipconfig1", properties: { subnet: { id: subnet.id }, publicIPAddress: { id: pip.id } } }] };
  if (policyId) props.firewallPolicy = { id: policyId };
  if (tier === "Basic") {
    const msub = await ensureSubnet(rg, vnet.name, "AzureFirewallManagementSubnet", mgmtPrefix);
    const mpip = await newPip(rg, `${name}-mgmt-pip`, vnet.location);
    props.managementIpConfiguration = { name: "mgmt", properties: { subnet: { id: msub.id }, publicIPAddress: { id: mpip.id } } };
  }
  return FIREWALL.put(rg, name, { location: vnet.location, properties: props });
}
export const setDdos = (vnet, planId) => VNET.patch(rgOf(vnet.id), vnet.name, { properties: planId ? { enableDdosProtection: true, ddosProtectionPlan: { id: planId } } : { enableDdosProtection: false } });

export const GROUPS = {
  "Microsoft.Storage/storageAccounts": ["blob", "file", "queue", "table", "web", "dfs"],
  "Microsoft.KeyVault/vaults": ["vault"],
  "Microsoft.Sql/servers": ["sqlServer"],
  "Microsoft.DocumentDB/databaseAccounts": ["Sql", "MongoDB", "Cassandra", "Gremlin", "Table"],
  "Microsoft.ContainerRegistry/registries": ["registry"],
  "Microsoft.Cache/redis": ["redisCache"],
  "Microsoft.AppConfiguration/configurationStores": ["configurationStores"],
  "Microsoft.CognitiveServices/accounts": ["account"],
};
export async function listTargets() {
  const out = [];
  for (const type of Object.keys(GROUPS)) {
    try {
      const [ns, t] = type.split("/");
      const api = { "Microsoft.Storage": "2023-01-01", "Microsoft.KeyVault": "2023-07-01", "Microsoft.Sql": "2023-05-01-preview", "Microsoft.DocumentDB": "2024-05-15", "Microsoft.ContainerRegistry": "2023-07-01", "Microsoft.Cache": "2024-03-01", "Microsoft.AppConfiguration": "2023-03-01", "Microsoft.CognitiveServices": "2023-05-01" }[ns];
      const rows = (await restJson("GET", `${sub()}/providers/${ns}/${t}`, { query: { "api-version": api } })).value || [];
      rows.forEach((r) => out.push({ id: r.id, name: r.name, type }));
    } catch { /* type not present */ }
  }
  return out;
}
export const createPrivateEndpoint = (rg, name, location, subnetId, targetId, groupId, manual) =>
  PE.put(rg, name, { location, properties: { subnet: { id: subnetId }, [manual ? "manualPrivateLinkServiceConnections" : "privateLinkServiceConnections"]: [{ name: `${name}-conn`, properties: { privateLinkServiceId: targetId, groupIds: [groupId], ...(manual ? { requestMessage: "Please approve my connection" } : {}) } }] } });
export const connectionsOf = (pe) => [...(pe.properties?.privateLinkServiceConnections || []), ...(pe.properties?.manualPrivateLinkServiceConnections || [])];

// ── flow logs (Microsoft.Network/networkWatchers/{nw}/flowLogs) ──────────────────────────────
export async function listFlowLogs(targetId) {
  const out = [];
  for (const nw of await NW.list()) {
    const rg = rgOf(nw.id);
    const rows = (await restJson("GET", `${NW.path(rg, nw.name)}/flowLogs`, { query: { "api-version": V } })).value || [];
    rows.filter((f) => !targetId || same(f.properties?.targetResourceId, targetId)).forEach((f) => out.push({ ...f, networkWatcher: nw.name, nwRg: rg }));
  }
  return out;
}
export async function putFlowLog(target, name, props) {
  const loc = target.location;
  let nw = (await NW.list()).find((w) => same(w.location, loc));
  if (!nw) {
    const rg = "NetworkWatcherRG";
    try { await restJson("PUT", `${sub()}/resourceGroups/${rg}`, { query: { "api-version": "2021-04-01" }, body: { location: loc } }); } catch { /* exists */ }
    nw = await NW.put(rg, `NetworkWatcher_${loc}`, { location: loc });
  }
  return restJson("PUT", `${NW.path(rgOf(nw.id), nw.name)}/flowLogs/${encodeURIComponent(name)}`, { query: { "api-version": V }, body: { location: loc, properties: { targetResourceId: target.id, ...props } } });
}
export const deleteFlowLog = (f) => restJson("DELETE", `${NW.path(f.nwRg, f.networkWatcher)}/flowLogs/${encodeURIComponent(f.name)}`, { query: { "api-version": V } });
export const listStorage = async () => STORAGE.list();
