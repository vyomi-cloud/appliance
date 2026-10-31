/* Azure API Management over native ARM.
 *   Control plane: Microsoft.ApiManagement/service
 *     /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ApiManagement/service/{name}
 *   Nested collections (apis, products, subscriptions, namedValues, backends) are real ARM
 *   sub-resources that continue the SAME type/name alternation as the service itself (no
 *   "providers" re-entry, unlike extension resources) — core/azure_arm_core.py's generic
 *   dispatcher is parameterized purely by that alternation, so it handles them with no
 *   service-specific backend code.
 *   Locks (Microsoft.Authorization/locks) ARE a real ARM extension resource, scoped to the
 *   service's own id, like every other Azure lens service. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.ApiManagement", "service", "2023-05-01-preview");

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listServices = async () => (await ARM.list()).map(shape);
export const getService = async (rg, name) => shape(await ARM.get(rg, name));
export const createService = (rg, name, body) => ARM.put(rg, name, body);
export const updateService = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteService = (rg, name) => ARM.remove(rg, name);

export const gatewayUrl = (name) => `https://${name}.azure-api.net`;
export const portalUrl = (name) => `https://${name}.developer.azure-api.net`;

// ── Nested collections (apis, products, subscriptions, namedValues, backends) ──────────
function subResource(kind) {
  const query = { "api-version": ARM.apiVersion };
  const path = (rg, svc, id) => `${ARM.path(rg, svc)}/${kind}${id ? `/${encodeURIComponent(id)}` : ""}`;
  return {
    list: async (rg, svc) => (await restJson("GET", path(rg, svc), { query })).value || [],
    get: (rg, svc, id) => restJson("GET", path(rg, svc, id), { query }),
    put: (rg, svc, id, body) => restJson("PUT", path(rg, svc, id), { query, body }),
    remove: (rg, svc, id) => restJson("DELETE", path(rg, svc, id), { query }),
    path,
  };
}

export const Apis = subResource("apis");
export const Products = subResource("products");
export const Subscriptions = subResource("subscriptions");
export const NamedValues = subResource("namedValues");
export const Backends = subResource("backends");
export const ApiTags = subResource("tags");
export const PolicyFragments = subResource("policyFragments");

// Product ↔ API association (`.../products/{productId}/apis/{apiId}`, empty-body PUT — the
// real ARM shape azure-mgmt-apimanagement / az apim product api add use).
const paQuery = { "api-version": ARM.apiVersion };
export const listProductApis = async (rg, svc, productId) =>
  (await restJson("GET", `${Products.path(rg, svc, productId)}/apis`, { query: paQuery })).value || [];
export const addProductApi = (rg, svc, productId, apiId) =>
  restJson("PUT", `${Products.path(rg, svc, productId)}/apis/${encodeURIComponent(apiId)}`, { query: paQuery });

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this service) ──
// `timespan` is an optional { ge, le } pair of ISO-8601 UTC bounds from the Timespan picker —
// a real `eventTimestamp ge/le` OData predicate (core/azure_arm_core._filter_by_timespan).
export const listActivityLog = async (rg, name, timespan) => {
  const rid = ARM.path(rg, name);
  let filter = `resourceUri eq '${rid}'`;
  if (timespan?.ge) filter += ` and eventTimestamp ge '${timespan.ge}'`;
  if (timespan?.le) filter += ` and eventTimestamp le '${timespan.le}'`;
  const query = { "api-version": "2015-04-01", "$filter": filter };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Access control (IAM): real ARM resources, subscription-wide (see capabilities.json) ────
const AUTHZ_API = "2022-04-01";
export const listRoleAssignments = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API } })).value || [];

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension resource
// scoped to this service's own id — core/azure_arm_core.AzureArm._diagnostic_settings) ──────
const DIAG_API = "2021-05-01-preview";
const diagPath = (rg, name, setting) => `${ARM.path(rg, name)}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (rg, name) => (await restJson("GET", diagPath(rg, name), { query: { "api-version": DIAG_API } })).value || [];
export const putDiagnosticSetting = (rg, name, setting, body) => restJson("PUT", diagPath(rg, name, setting), { query: { "api-version": DIAG_API }, body });
export const deleteDiagnosticSetting = (rg, name, setting) => restJson("DELETE", diagPath(rg, name, setting), { query: { "api-version": DIAG_API } });

// ── Log Analytics workspaces (Microsoft.OperationalInsights/workspaces) — the diagnostic
// setting "Send to Log Analytics workspace" destination picker's source list. ──────────────
export const listWorkspaces = async () => (await ARM_WORKSPACES.list()).map((w) => ({ id: w.id, name: w.name }));
const ARM_WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");

// ── create-service form model → ARM body ────────────────────────────────────────────────
const SKU_NAME = {
  "Basic v2": "BasicV2", "Standard v2": "StandardV2", "Premium v2": "PremiumV2", "Developer (no SLA)": "Developer",
  "Basic": "Basic", "Standard": "Standard", "Premium": "Premium", "Consumption": "Consumption",
};

export function toArmBody(f) {
  return {
    location: f.location,
    sku: { name: SKU_NAME[f.pricingTier] || "Developer", capacity: f.pricingTier === "Consumption" ? 0 : f.units },
    identity: f.systemAssignedIdentity ? { type: "SystemAssigned" } : undefined,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      publisherEmail: f.adminEmail,
      publisherName: f.orgName,
      customProperties: f.protocols,
    },
  };
}

// The well-known customProperties keys the portal's "Protocols + ciphers" / create wizard's
// "Protocol settings" step toggle (a small, representative subset — real APIM has ~20).
export const PROTOCOL_KEYS = [
  ["Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls10", "TLS 1.0", "client"],
  ["Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Tls11", "TLS 1.1", "client"],
  ["Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Protocols.Ssl30", "SSL 3.0", "client"],
  ["Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls10", "TLS 1.0", "backend"],
  ["Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Tls11", "TLS 1.1", "backend"],
  ["Microsoft.WindowsAzure.ApiManagement.Gateway.Security.Backend.Protocols.Ssl30", "SSL 3.0", "backend"],
];
export const defaultProtocols = () => Object.fromEntries(PROTOCOL_KEYS.map(([k]) => [k, "False"]));

/** A simulator secret — the same convention the generic ARM listKeys/regenerateKey action
 *  (core/azure_arm_core.py) uses: a fixed-shape, clearly-fake base64 token, not a real key. */
export const simKey = () => btoa(`sim-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`).replace(/=+$/, "");
