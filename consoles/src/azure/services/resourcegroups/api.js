/* Resource groups over the native ARM wire: `/_wire/subscriptions/{sub}/…?api-version=…`.
 *   Control plane: PUT/GET/PATCH/DELETE /subscriptions/{sub}/resourceGroups/{name}
 *   Resources:     GET  .../resourceGroups/{name}/resources                           (every type, at once)
 *   Locks:         CRUD    .../resourceGroups/{name}/providers/Microsoft.Authorization/locks[/{n}]
 *   Deployments:   CRUD    .../resourceGroups/{name}/providers/Microsoft.Resources/deployments[/{n}]
 *   IAM:           list    .../providers/Microsoft.Authorization/roleAssignments|roleDefinitions (subscription scope)
 *   Cost:          POST/GET .../resourceGroups/{name}/providers/Microsoft.CostManagement|Consumption/…
 * Served by core/azure_arm_core.py (+ core/azure_cost_core.py for cost) on every substrate. */
import { restJson } from "../../../common/wire.js";
import { getSubscription, listResourceGroups } from "../../kit/arm.js";

const ARM_API_VERSION = "2021-04-01";
const sub = () => `/subscriptions/${getSubscription()}`;
const rgPath = (name) => `${sub()}/resourceGroups/${encodeURIComponent(name)}`;
const armQ = { "api-version": ARM_API_VERSION };

export { listResourceGroups as listGroups };
export const getGroup = (name) => restJson("GET", rgPath(name), { query: armQ });
export const createGroup = (name, body) => restJson("PUT", rgPath(name), { query: armQ, body });
export const updateGroup = (name, body) => restJson("PATCH", rgPath(name), { query: armQ, body });
export const deleteGroup = (name) => restJson("DELETE", rgPath(name), { query: armQ });

export const listResources = async (name) => (await restJson("GET", `${rgPath(name)}/resources`, { query: armQ })).value || [];
// A resource's own `id` is already the full ARM path; the api-version query param is unused
// by DELETE (the backend dispatches purely on path), so one generic delete covers every type.
export const deleteResourceById = (id) => restJson("DELETE", id, { query: armQ });

// ── Locks (Microsoft.Authorization/locks, scoped to the resource group itself) ─────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (name, lockName) => `${rgPath(name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (name) => (await restJson("GET", lockPath(name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (name, lockName, body) => restJson("PUT", lockPath(name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (name, lockName) => restJson("DELETE", lockPath(name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this group) ──
export const listActivityLog = async (name) => {
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rgPath(name)}'` };
  return (await restJson("GET", `${sub()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Deployments (Microsoft.Resources/deployments — generic catalog entry, see azure_arm_data.py) ──
const deploymentPath = (name, depName) => `${rgPath(name)}/providers/Microsoft.Resources/deployments${depName ? `/${encodeURIComponent(depName)}` : ""}`;
export const listDeployments = async (name) => (await restJson("GET", deploymentPath(name), { query: armQ })).value || [];
export const putDeployment = (name, depName, body) => restJson("PUT", deploymentPath(name, depName), { query: armQ, body });
export const deleteDeployment = (name, depName) => restJson("DELETE", deploymentPath(name, depName), { query: armQ });

// ── Access control (IAM): generic ARM catalog store, subscription scope (same pattern the
// Function App / Key vault blades use — Microsoft.Authorization/roleAssignments has no
// resource-group-scoped list in this simulator). ──
const IAM_API_VERSION = "2022-04-01";
export const listRoleAssignments = async () => (await restJson("GET", `${sub()}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": IAM_API_VERSION } })).value || [];
export const listRoleDefinitions = async () => (await restJson("GET", `${sub()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": IAM_API_VERSION } })).value || [];

// ── Cost management, scoped to this resource group ──────────────────────────────────────
const COST_API_VERSION = "2023-11-01";
const costQ = { "api-version": COST_API_VERSION };
export const costQuery = (name, body) => restJson("POST", `${rgPath(name)}/providers/Microsoft.CostManagement/query`, { query: costQ, body });
export const listBudgets = async (name) => (await restJson("GET", `${rgPath(name)}/providers/Microsoft.Consumption/budgets`, { query: costQ })).value || [];
export const listCostAlerts = async (name) => (await restJson("GET", `${rgPath(name)}/providers/Microsoft.CostManagement/alerts`, { query: costQ })).value || [];
