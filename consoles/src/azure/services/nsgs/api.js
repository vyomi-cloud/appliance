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

// ── create-NSG form model → ARM body ────────────────────────────────────────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {},
  };
}
