/* Container registries over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ContainerRegistry/registries/{name}
 *                  + the nested Microsoft.ContainerRegistry/registries/{name}/webhooks/{name} extension type
 *                    (generic ARM child-resource CRUD — core/azure_arm_core.py needs no extra
 *                    wiring for it, only the top-level "registries" type is in the catalog)
 *                  + POST .../listCredentials / .../regenerateCredential (admin user credentials)
 *   Data plane:    the registry's own host (`{name}.azurecr.io`) — the OCI/Docker Registry v2
 *                  read API + the ACR REST extension (`/acr/v1/...`) the portal's Repositories
 *                  blade and `az acr repository` use (core/azure_acr_core.py). */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.ContainerRegistry", "registries", "2023-07-01");
const LOCK_API_VERSION = "2020-05-01";

const shape = (r) => ({ ...r, resourceGroup: parseId(r.id).resourceGroup });

export const listRegistries = async () => (await ARM.list()).map(shape);
export const getRegistry = async (rg, name) => shape(await ARM.get(rg, name));
export const createRegistry = (rg, name, body) => ARM.put(rg, name, body);
export const updateRegistry = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteRegistry = (rg, name) => ARM.remove(rg, name);

export const loginServer = (name) => `${(name || "").toLowerCase()}.azurecr.io`;
export const skuLabel = (sku) => sku?.name || "Standard";

// ── Admin user credentials (listCredentials / regenerateCredential ARM actions) ────────
export const listCredentials = (rg, name) => ARM.action(rg, name, "listCredentials");
export const regenerateCredential = (rg, name, passwordName) => ARM.action(rg, name, "regenerateCredential", { name: passwordName });

// ── Webhooks (Microsoft.ContainerRegistry/registries/webhooks, generic nested ARM type) ─
const webhookPath = (rg, name, whName) => `${ARM.path(rg, name)}/webhooks${whName ? `/${encodeURIComponent(whName)}` : ""}`;

export const listWebhooks = async (rg, name) => (await restJson("GET", webhookPath(rg, name), { query: { "api-version": ARM.apiVersion } })).value || [];
export const putWebhook = (rg, name, whName, body) => restJson("PUT", webhookPath(rg, name, whName), { query: { "api-version": ARM.apiVersion }, body });
export const deleteWebhook = (rg, name, whName) => restJson("DELETE", webhookPath(rg, name, whName), { query: { "api-version": ARM.apiVersion } });

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Access control (IAM): role assignments scoped to THIS registry (plus its subscription/
// resource-group ancestors, real Azure's "inherited access" view) read over the same generic
// Microsoft.Authorization/roleAssignments extension-resource engine the VM/NSG/Cosmos blades
// use — GET-only; assignments are still created at the subscription scope. ─────────────────
const AUTHZ_API_VERSION = "2022-04-01";
export const listRoleAssignments = async (rg, name) =>
  (await restJson("GET", `${ARM.path(rg, name)}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API_VERSION } })).value || [];
export const listRoleDefinitions = async () =>
  (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API_VERSION } })).value || [];

// ── Diagnostic settings (Microsoft.Insights/diagnosticSettings, a real ARM extension resource
// scoped to this registry's own id — same generic mechanism core/azure_arm_core.py's
// AzureArm._diagnostic_settings exposes for every lens resource). Logs/metrics are stored and
// validated exactly as the real resource requires, but never delivered anywhere. ────────────
const ARM_WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");
const DIAG_API_VERSION = "2021-05-01-preview";
const diagPath = (regId, setting) => `${regId}/providers/Microsoft.Insights/diagnosticSettings${setting ? `/${encodeURIComponent(setting)}` : ""}`;
export const listDiagnosticSettings = async (regId) => (await restJson("GET", diagPath(regId), { query: { "api-version": DIAG_API_VERSION } })).value || [];
export const putDiagnosticSetting = (regId, setting, body) => restJson("PUT", diagPath(regId, setting), { query: { "api-version": DIAG_API_VERSION }, body });
export const deleteDiagnosticSetting = (regId, setting) => restJson("DELETE", diagPath(regId, setting), { query: { "api-version": DIAG_API_VERSION } });
export const listWorkspaces = async () => (await ARM_WORKSPACES.list()).map((w) => ({ id: w.id, name: w.name }));

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this registry) ──
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Repositories / tags data plane (OCI v2 reads + the ACR v1 REST extension) ──────────
// Which registry the blade currently showing is calling for — real ACR learns this from the
// registry's own hostname ({registry}.azurecr.io); Vyomi's one shared relay has no per-registry
// host, so the console carries it as a header instead (azure.acr.networking's public-network-
// access enforcement and azure.acr.retention's untagged-manifest purge in
// core/aws_wire_router.py / core/wire_ingress.py read it — same mechanism as Key Vault's
// x-vyomi-vault / keyvaults/api.js setActiveVault).
let activeRegistry = "";
export const setActiveRegistry = (name) => { activeRegistry = name || ""; };
const acr = (method, path) => restJson(method, path, { headers: activeRegistry ? { "x-vyomi-registry": activeRegistry } : {} });

export const listRepositories = async () => (await acr("GET", "/acr/v1/_catalog")).repositories || [];
export const getRepository = (repo) => acr("GET", `/acr/v1/${repo}`);
export const deleteRepository = (repo) => acr("DELETE", `/acr/v1/${repo}`);
export const listTags = async (repo) => (await acr("GET", `/acr/v1/${repo}/_tags`)).tags || [];
export const deleteTag = (repo, tag) => acr("DELETE", `/acr/v1/${repo}/_tags/${encodeURIComponent(tag)}`);

// ── Identity / Encryption / Networking / Retention — real ARM properties on the registry
// itself (core/azure_arm_core.py's generic engine), enforced for real: SystemAssigned identity
// mints a stable principalId; CMK encryption / zone redundancy / disabling public network
// access / IP network rules are Premium-only (azure_arm_core.AzureArm._acr_validate_block);
// disabling public network access actually blocks this registry's own data-plane calls
// (acr_network_denied, wired through the x-vyomi-registry header above). ─────────────────────
export const updateIdentity = (rg, name, identity) => ARM.patch(rg, name, { identity });
export const updateEncryption = (rg, name, encryption) => ARM.patch(rg, name, { properties: { encryption } });
export const updateNetworking = (rg, name, props) => ARM.patch(rg, name, { properties: props });
export const updateRetention = (rg, name, retentionPolicy) => ARM.patch(rg, name, { properties: { policies: { retentionPolicy } } });

// ── Geo-replications / Tasks (+ Runs) / Cache / Connected registries / Tokens / Scope maps —
// real nested Microsoft.ContainerRegistry/registries/{child} ARM resources (the SAME generic
// nested-child-resource engine webhooks/locks already use — no catalog entry of its own needed
// beyond the top-level "registries" type). Premium-/Standard-gated and cross-validated for real
// by azure_arm_core.AzureArm._acr_validate_block (region/target uniqueness, well-formed scope-map
// actions, a token's scopeMapId must reference a real scope map) — not just stored config. ────
const childPath = (rg, name, kind, child) => `${ARM.path(rg, name)}/${kind}${child ? `/${encodeURIComponent(child)}` : ""}`;
const listChild = async (rg, name, kind) => (await restJson("GET", childPath(rg, name, kind), { query: { "api-version": ARM.apiVersion } })).value || [];
const putChild = (rg, name, kind, child, body) => restJson("PUT", childPath(rg, name, kind, child), { query: { "api-version": ARM.apiVersion }, body });
const deleteChild = (rg, name, kind, child) => restJson("DELETE", childPath(rg, name, kind, child), { query: { "api-version": ARM.apiVersion } });

export const listReplications = (rg, name) => listChild(rg, name, "replications");
export const putReplication = (rg, name, region, body) => putChild(rg, name, "replications", region, body);
export const deleteReplication = (rg, name, region) => deleteChild(rg, name, "replications", region);

export const listTasks = (rg, name) => listChild(rg, name, "tasks");
export const putTask = (rg, name, task, body) => putChild(rg, name, "tasks", task, body);
export const deleteTask = (rg, name, task) => deleteChild(rg, name, "tasks", task);
export const listRuns = (rg, name) => listChild(rg, name, "runs");
export const putRun = (rg, name, runId, body) => putChild(rg, name, "runs", runId, body);

export const listCacheRules = (rg, name) => listChild(rg, name, "cacheRules");
export const putCacheRule = (rg, name, rule, body) => putChild(rg, name, "cacheRules", rule, body);
export const deleteCacheRule = (rg, name, rule) => deleteChild(rg, name, "cacheRules", rule);

export const listConnectedRegistries = (rg, name) => listChild(rg, name, "connectedRegistries");
export const putConnectedRegistry = (rg, name, cr, body) => putChild(rg, name, "connectedRegistries", cr, body);
export const deleteConnectedRegistry = (rg, name, cr) => deleteChild(rg, name, "connectedRegistries", cr);

export const listScopeMaps = (rg, name) => listChild(rg, name, "scopeMaps");
export const putScopeMap = (rg, name, sm, body) => putChild(rg, name, "scopeMaps", sm, body);
export const deleteScopeMap = (rg, name, sm) => deleteChild(rg, name, "scopeMaps", sm);

export const listTokens = (rg, name) => listChild(rg, name, "tokens");
export const putToken = (rg, name, t, body) => putChild(rg, name, "tokens", t, body);
export const deleteToken = (rg, name, t) => deleteChild(rg, name, "tokens", t);

// ── Resource Graph ("Open query" on the registries list) — a real, minimal KQL subset
// evaluated over the ARM engine's own resource store (azure_arm_core.AzureArm._resource_graph),
// tenant-scoped like real Resource Graph (no /subscriptions/{sub}/ prefix). ───────────────────
export const queryResourceGraph = (query) => restJson("POST", "/providers/Microsoft.ResourceGraph/resources",
  { query: { "api-version": "2021-03-01" }, body: { subscriptions: [getSubscription()], query } });

// ── Events — real Microsoft.EventGrid/systemTopics (the SAME already-shipped generic ARM
// catalog type the Event Grid service itself uses), filtered to this registry's resource id as
// their `source`. Vyomi never actually fires a push/delete event at the subscription's
// endpoint (matching Webhooks' own honest gap). ──────────────────────────────────────────────
const EVENTGRID_SYSTEMTOPIC = armType("Microsoft.EventGrid", "systemTopics", "2022-06-15");
export const listEventSystemTopics = (rg) => EVENTGRID_SYSTEMTOPIC.list(rg);
export const putEventSystemTopic = (rg, name, sourceId) => EVENTGRID_SYSTEMTOPIC.put(rg, name,
  { location: "global", properties: { source: sourceId, topicType: "Microsoft.ContainerRegistry.Registries" } });
export const deleteEventSystemTopic = (rg, name) => EVENTGRID_SYSTEMTOPIC.remove(rg, name);

// ── create-registry form model → ARM body ───────────────────────────────────────────────
// Domain name label scope / Role assignment permissions mode (azure.acr.create_fields) are
// stored as real ARM properties — round-tripped through GET, shown in Properties/Essentials
// and included in Export template, not dropped on the floor for "fidelity only".
export function toArmBody(f) {
  return {
    location: f.location,
    sku: { name: f.pricingPlan },
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      adminUserEnabled: false,
      publicNetworkAccess: f.connectivity === "Private access" ? "Disabled" : "Enabled",
      zoneRedundancy: f.availabilityZones ? "Enabled" : "Disabled",
      encryption: { status: f.customerManagedKey ? "enabled" : "disabled" },
      domainNameLabelScope: f.domainNameLabelScope,
      roleAssignmentMode: f.roleAssignmentMode,
    },
  };
}
