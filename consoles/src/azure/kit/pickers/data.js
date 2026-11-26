/* Data layer for the Azure RBAC pickers. Nothing here is typed by the user when a catalog or store can supply it:
 *   roles        built-in: GET /api/iam/azure/catalog/_roles (core/iam_catalog/azure/_roles.json, 507 verbatim roles; served by
 *                routes/iam_enforcement.py on Mesh and answered in the browser on Nano); custom: ARM roleDefinitions (type CustomRole)
 *   permissions  GET /api/iam/azure/catalog/<Microsoft.Provider>  (actions + dataActions, verbatim)
 *   directory    Microsoft Graph /v1.0/users|groups|servicePrincipals (core/azure_graph_core.py) + ARM user-assigned identities
 *   scopes       ARM subscription > resource groups > resources */
import { WIRE_BASE, restJson } from "../../../common/wire.js";
import { iamApi, iamBase } from "../../../common/iamEnforce.js";
import { getSubscription, listResourceGroups } from "../arm.js";
import * as iam from "../iam.js";
import * as entra from "../../services/entra/api.js";

export const iamClient = () => iamApi("azure", { base: iamBase(WIRE_BASE), fetcher: (...a) => (window.__vyomiIamFetch || fetch)(...a) });

/* Namespaces that have a verbatim catalog file in core/iam_catalog/azure (the folder listing). Any other namespace can still be typed;
 * the catalog route then answers 404 and the picker says so. */
export const PROVIDERS = ["Microsoft.ApiManagement", "Microsoft.App", "Microsoft.AppConfiguration", "Microsoft.Authorization", "Microsoft.Cdn",
  "Microsoft.CognitiveServices", "Microsoft.Compute", "Microsoft.ContainerRegistry", "Microsoft.ContainerService", "Microsoft.CostManagement",
  "Microsoft.DocumentDB", "Microsoft.EventGrid", "Microsoft.Insights", "Microsoft.KeyVault", "Microsoft.MachineLearningServices",
  "Microsoft.ManagedIdentity", "Microsoft.Management", "Microsoft.Network", "Microsoft.OperationalInsights", "Microsoft.RecoveryServices",
  "Microsoft.Resources", "Microsoft.Search", "Microsoft.Security", "Microsoft.ServiceBus", "Microsoft.Sql", "Microsoft.Storage",
  "Microsoft.StreamAnalytics", "Microsoft.Web"];

const cache = {};
const memo = (k, f) => (cache[k] ||= f().catch((e) => { delete cache[k]; throw e; }));
export const clearPickerCache = () => { for (const k of Object.keys(cache)) delete cache[k]; };

export const loadProviderCatalog = (provider) => memo(`cat:${provider}`, () => iamClient().catalog(provider));

/** Job function roles vs Privileged administrator roles. Microsoft's documented privileged set (Owner, Contributor, User Access
 * Administrator, Role Based Access Control Administrator) plus any role whose actions include a bare "*" or Microsoft.Authorization/*. */
const PRIV_NAMES = new Set(["Owner", "Contributor", "User Access Administrator", "Role Based Access Control Administrator", "Privileged Role Administrator"]);
export const isPrivileged = (r) => PRIV_NAMES.has(r.roleName) || (r.actions || []).some((a) => a === "*" || /^Microsoft\.Authorization\/(\*|roleAssignments\/\*|roleAssignments\/write)$/i.test(a));

const normBuiltin = (r) => ({ id: r.id, roleName: r.roleName, description: r.description || "", type: "BuiltInRole", category: r.category || "general",
  actions: r.actions || [], notActions: r.notActions || [], dataActions: r.dataActions || [], notDataActions: r.notDataActions || [], assignableScopes: r.assignableScopes || ["/"] });
const normArm = (d) => { const p = d.properties || {}; const perm = p.permissions?.[0] || {};
  return { id: d.name, roleName: p.roleName, description: p.description || "", type: p.type || "CustomRole", category: "custom",
    actions: perm.actions || [], notActions: perm.notActions || [], dataActions: perm.dataActions || [], notDataActions: perm.notDataActions || [], assignableScopes: p.assignableScopes || ["/"] }; };

/** Every role: the full built-in catalog + custom roles from the ARM store (de-duplicated by name). */
export const loadRoles = () => memo("roles", async () => {
  const [cat, arm] = await Promise.all([iamClient().catalog("_roles").catch(() => null), iam.listRoleDefinitions().catch(() => [])]);
  const out = new Map();
  for (const r of Object.values(cat?.roles || {})) out.set(r.roleName, normBuiltin(r));
  for (const d of arm) { const r = normArm(d); if (r.roleName && (!out.has(r.roleName) || r.type === "CustomRole")) out.set(r.roleName, { ...(out.get(r.roleName) || {}), ...r }); }
  return [...out.values()].sort((a, b) => a.roleName.localeCompare(b.roleName));
});
export const reloadRoles = () => { delete cache.roles; return loadRoles(); };
export const roleDefinitionId = (scope, role) => `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions/${role.id}`;

export const CATEGORY_LABEL = (c) => String(c || "general").replace(/-/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());

/* ---------------- directory ---------------- */
const safe = (p) => p.catch(() => []);
export const loadDirectory = () => memo("dir", async () => {
  const [users, groups, sps, mis] = await Promise.all([
    safe(entra.listUsers()), safe(entra.listGroups()), safe(entra.listServicePrincipals()),
    safe(restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.ManagedIdentity/userAssignedIdentities`, { query: { "api-version": "2023-01-31" } }).then((d) => d.value || [])),
  ]);
  return [
    ...users.map((u) => ({ id: u.id, name: u.displayName || u.userPrincipalName, type: "User", principalType: "User", details: u.userPrincipalName || u.mail || "" })),
    ...groups.map((g) => ({ id: g.id, name: g.displayName, type: "Group", principalType: "Group", details: g.description || g.mail || "" })),
    ...sps.map((s) => ({ id: s.id, name: s.displayName || s.appDisplayName, type: "Service principal", principalType: "ServicePrincipal", details: s.appId || "" })),
    ...mis.map((m) => ({ id: m.properties?.principalId || m.name, name: m.name, type: "Managed identity", principalType: "ServicePrincipal", details: `User-assigned managed identity - ${m.location || ""}`, managed: true })),
  ];
});
export const reloadDirectory = () => { delete cache.dir; return loadDirectory(); };

/* ---------------- scopes ---------------- */
export const loadResourceGroups = () => listResourceGroups();
export const loadRgResources = async (rg) =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}/resources`, { query: { "api-version": "2021-04-01" } })).value || [];

/* ---------------- ABAC (documented attribute sources; the evaluator subset is core/iam_engine/azure_eval.py) ---------------- */
const BL = "Microsoft.Storage/storageAccounts/blobServices/containers";
export const ABAC_ATTRIBUTES = [
  { source: "Resource", label: "Container name", name: `${BL}:name`, type: "String" },
  { source: "Resource", label: "Blob path", name: `${BL}/blobs:path`, type: "String" },
  { source: "Resource", label: "Blob index tags [Values in key]", name: `${BL}/blobs/tags:`, type: "String", keyed: true },
  { source: "Resource", label: "Blob index tags [Keys]", name: `${BL}/blobs/tags&$keys$&`, type: "String list" },
  { source: "Resource", label: "Is Current Version", name: `${BL}/blobs:isCurrentVersion`, type: "Boolean" },
  { source: "Resource", label: "Is hierarchical namespace enabled", name: "Microsoft.Storage/storageAccounts:isHnsEnabled", type: "Boolean" },
  { source: "Request", label: "Blob prefix", name: `${BL}/blobs:prefix`, type: "String" },
  { source: "Request", label: "Snapshot", name: `${BL}/blobs:snapshot`, type: "DateTime" },
  { source: "Request", label: "Version ID", name: `${BL}/blobs:versionId`, type: "DateTime" },
  { source: "Request", label: "Blob index tags [Values in key]", name: `${BL}/blobs/tags:`, type: "String", keyed: true },
  { source: "Request", label: "Blob index tags [Keys]", name: `${BL}/blobs/tags&$keys$&`, type: "String list" },
  { source: "Request", label: "Encryption scope name", name: `${BL}/blobs:encryptionScopeName`, type: "String" },
  { source: "Environment", label: "Is private link", name: "isPrivateLink", type: "Boolean" },
  { source: "Environment", label: "Private endpoint", name: "Microsoft.Network/privateEndpoints", type: "String" },
  { source: "Environment", label: "Subnet", name: "Microsoft.Network/virtualNetworks/subnets", type: "String" },
  { source: "Environment", label: "UTC now", name: "UtcNow", type: "DateTime" },
];
const STR = ["StringEquals", "StringNotEquals", "StringEqualsIgnoreCase", "StringNotEqualsIgnoreCase", "StringLike", "StringNotLike", "StringStartsWith", "StringNotStartsWith", "Exists", "NotExists"];
export const ABAC_OPERATORS = {
  String: STR,
  "String list": ["ForAnyOfAnyValues:StringEquals", "ForAllOfAnyValues:StringEquals", "ForAnyOfAllValues:StringEquals", "ForAllOfAllValues:StringEquals", "ForAnyOfAnyValues:StringLike", "ForAllOfAnyValues:StringLike", "Exists", "NotExists"],
  Boolean: ["BoolEquals", "BoolNotEquals", "Exists", "NotExists"],
  DateTime: ["DateTimeEquals", "DateTimeNotEquals", "DateTimeLessThan", "DateTimeLessThanEquals", "DateTimeGreaterThan", "DateTimeGreaterThanEquals", "Exists", "NotExists"],
};
export const attrRef = (e) => `@${e.source}[${e.name}${e.keyed ? `${e.key || ""}<$key_case_sensitive$>` : ""}]`;
const quote = (v) => `'${String(v).replace(/'/g, "''")}'`;
const lit = (e) => (e.type === "Boolean" ? String(e.value === "true" || e.value === true) : /^ForAny|^ForAll/.test(e.operator) ? `{${String(e.value || "").split(",").map((x) => quote(x.trim())).join(", ")}}` : quote(e.value ?? ""));
export const exprCode = (e) => (/^(Not)?Exists$/.test(e.operator) ? `${e.operator} ${attrRef(e)}` : `${attrRef(e)} ${e.operator} ${e.valueKind === "attribute" ? e.valueAttr || "" : lit(e)}`);
/** nodes: [{kind:"expr",...e} | {kind:"group", items:[expr...]}], each with `join` ("AND"|"OR") to the previous node. */
export const nodesCode = (nodes) => nodes.map((n, i) => (i ? ` ${n.join || "AND"} ` : "") + (n.kind === "group" ? `(${nodesCode(n.items)})` : exprCode(n))).join("");
/** Full ARM condition (conditionVersion 2.0): the actions NOT selected are unaffected; the selected ones need the expression. */
export function conditionCode(actions, nodes) {
  if (!actions.length || !nodes.length) return "";
  const am = actions.map((a) => `ActionMatches{${quote(a)}}`).join(" OR ");
  return `((!(${am})) OR (${nodesCode(nodes)}))`;
}
