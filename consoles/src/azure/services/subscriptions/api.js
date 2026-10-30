/* Subscriptions over the native ARM wire: `/_wire/subscriptions/{sub}/…?api-version=…`.
 *   Subscription itself: GET /subscriptions/{sub}                                       (Overview)
 *   Rename:               POST .../providers/Microsoft.Subscription/rename              (header action)
 *   Tags:                 GET/PUT .../providers/Microsoft.Resources/tags/default         (Tags - CreateOrUpdateAtScope)
 *   Resource groups:      GET .../resourcegroups                                        (Settings > Resource groups)
 *   Resources:             GET .../resources                                            (Settings > Resources, every RG at once)
 *   Resource providers:   GET .../providers[/{ns}], POST .../providers/{ns}/register|unregister
 *   Deployments:          CRUD .../providers/Microsoft.Resources/deployments[/{n}]       (Settings > Deployments)
 *   Locks:                CRUD .../providers/Microsoft.Authorization/locks[/{n}]         (Settings > Resource locks)
 *   IAM:                  list .../providers/Microsoft.Authorization/roleAssignments|roleDefinitions
 *   Activity log:         GET .../providers/Microsoft.Insights/eventtypes/management/values (no $filter = subscription-wide)
 *   Cost:                 POST/GET .../providers/Microsoft.CostManagement|Consumption/…
 * Served by core/azure_arm_core.py (+ core/azure_cost_core.py for cost) on every substrate. */
import { restJson } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";

const ARM_API_VERSION = "2021-04-01";
const armQ = { "api-version": ARM_API_VERSION };
const sub = (s) => `/subscriptions/${s || getSubscription()}`;

export const getSubscriptionInfo = (s) => restJson("GET", sub(s), { query: armQ });
export const renameSubscription = (s, subscriptionName) =>
  restJson("POST", `${sub(s)}/providers/Microsoft.Subscription/rename`, { query: { "api-version": "2021-10-01" }, body: { subscriptionName } });

// ── Tags (Microsoft.Resources/tags/default — Tags_CreateOrUpdateAtScope) ───────────────
const TAGS_API_VERSION = "2021-04-01";
const tagsPath = (s) => `${sub(s)}/providers/Microsoft.Resources/tags/default`;
export const getTags = async (s) => (await restJson("GET", tagsPath(s), { query: { "api-version": TAGS_API_VERSION } })).properties?.tags || {};
export const putTags = (s, tags) => restJson("PUT", tagsPath(s), { query: { "api-version": TAGS_API_VERSION }, body: { properties: { tags } } });

// ── Resource groups / resources (subscription-wide) ─────────────────────────────────────
export const listResourceGroups = async (s) => (await restJson("GET", `${sub(s)}/resourcegroups`, { query: armQ })).value || [];
export const listResources = async (s) => (await restJson("GET", `${sub(s)}/resources`, { query: armQ })).value || [];
export const deleteResourceById = (id) => restJson("DELETE", id, { query: armQ });

// ── Resource providers ───────────────────────────────────────────────────────────────────
const PROVIDERS_API_VERSION = "2021-04-01";
export const listProviders = async (s) => (await restJson("GET", `${sub(s)}/providers`, { query: { "api-version": PROVIDERS_API_VERSION } })).value || [];
export const registerProvider = (s, ns) => restJson("POST", `${sub(s)}/providers/${encodeURIComponent(ns)}/register`, { query: { "api-version": PROVIDERS_API_VERSION } });
export const unregisterProvider = (s, ns) => restJson("POST", `${sub(s)}/providers/${encodeURIComponent(ns)}/unregister`, { query: { "api-version": PROVIDERS_API_VERSION } });

// ── Deployments (Microsoft.Resources/deployments, subscription scope) ──────────────────
const deploymentPath = (s, name) => `${sub(s)}/providers/Microsoft.Resources/deployments${name ? `/${encodeURIComponent(name)}` : ""}`;
export const listDeployments = async (s) => (await restJson("GET", deploymentPath(s), { query: armQ })).value || [];
export const putDeployment = (s, name, body) => restJson("PUT", deploymentPath(s, name), { query: armQ, body });
export const deleteDeployment = (s, name) => restJson("DELETE", deploymentPath(s, name), { query: armQ });

// ── Locks (Microsoft.Authorization/locks, scoped directly to the subscription) ─────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (s, name) => `${sub(s)}/providers/Microsoft.Authorization/locks${name ? `/${encodeURIComponent(name)}` : ""}`;
export const listLocks = async (s) => (await restJson("GET", lockPath(s), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (s, name, body) => restJson("PUT", lockPath(s, name), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (s, name) => restJson("DELETE", lockPath(s, name), { query: { "api-version": LOCK_API_VERSION } });

// ── Access control (IAM): generic ARM catalog store, subscription scope ────────────────
const IAM_API_VERSION = "2022-04-01";
export const listRoleAssignments = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": IAM_API_VERSION } })).value || [];
export const listRoleDefinitions = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": IAM_API_VERSION } })).value || [];

// ── Activity log (subscription-wide — no $filter) ───────────────────────────────────────
export const listActivityLog = async (s) => {
  const query = { "api-version": "2015-04-01" };
  return (await restJson("GET", `${sub(s)}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Cost management, subscription scope ─────────────────────────────────────────────────
const COST_API_VERSION = "2023-11-01";
const costQ = { "api-version": COST_API_VERSION };
export const costQuery = (s, body) => restJson("POST", `${sub(s)}/providers/Microsoft.CostManagement/query`, { query: costQ, body });
export const listBudgets = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Consumption/budgets`, { query: costQ })).value || [];
export const listCostAlerts = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.CostManagement/alerts`, { query: costQ })).value || [];
