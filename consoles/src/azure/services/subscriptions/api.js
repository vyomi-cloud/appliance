/* Subscriptions over the native ARM wire: `/_wire/subscriptions/{sub}/…?api-version=…`.
 *   Subscription itself: GET /subscriptions/{sub}                                       (Overview)
 *   Rename:               POST .../providers/Microsoft.Subscription/rename              (header action)
 *   Tags:                 GET/PUT .../providers/Microsoft.Resources/tags/default         (Tags - CreateOrUpdateAtScope)
 *   Resource groups:      GET .../resourcegroups                                        (Settings > Resource groups)
 *   Resources:             GET .../resources                                            (Settings > Resources, every RG at once)
 *   Resource providers:   GET .../providers[/{ns}], POST .../providers/{ns}/register|unregister
 *   Deployments:          CRUD .../providers/Microsoft.Resources/deployments[/{n}]       (Settings > Deployments)
 *   Locks:                CRUD .../providers/Microsoft.Authorization/locks[/{n}]         (Settings > Resource locks)
 *   IAM:                  CRUD + checkAccess .../providers/Microsoft.Authorization/roleAssignments|roleDefinitions|checkAccess
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

// ── Access control (IAM): generic ARM catalog store, subscription scope — role assignments
// created here are real ARM resources scoped to this subscription; checkAccess runs the real
// wildcard + scope-inheritance + notActions/deny algorithm against them (see azure_arm_core's
// _check_access, shared helpers with core/azure_iam_core.py). ───────────────────────────────
const IAM_API_VERSION = "2022-04-01";
const roleAssignmentPath = (s, raName) => `${sub(s)}/providers/Microsoft.Authorization/roleAssignments${raName ? `/${encodeURIComponent(raName)}` : ""}`;
export const listRoleAssignments = async (s) => (await restJson("GET", roleAssignmentPath(s), { query: { "api-version": IAM_API_VERSION } })).value || [];
export const putRoleAssignment = (s, raName, body) => restJson("PUT", roleAssignmentPath(s, raName), { query: { "api-version": IAM_API_VERSION }, body });
export const deleteRoleAssignment = (s, raName) => restJson("DELETE", roleAssignmentPath(s, raName), { query: { "api-version": IAM_API_VERSION } });
export const listRoleDefinitions = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": IAM_API_VERSION } })).value || [];
export const checkAccess = async (s, principalId, action) =>
  (await restJson("POST", `${sub(s)}/providers/Microsoft.Authorization/checkAccess`, { query: { "api-version": IAM_API_VERSION }, body: { principalId, action } })).value || [];
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `id${Date.now()}${Math.random().toString(16).slice(2)}`);

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

// ── Security (Microsoft.Security — Defender for Cloud, reused from the subscription scope) ──
const SECURITY_API_VERSION = "2022-01-01";
export const getSecureScore = (s) => restJson("GET", `${sub(s)}/providers/Microsoft.Security/secureScores/ascScore`, { query: { "api-version": SECURITY_API_VERSION } });
export const listAssessments = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Security/assessments`, { query: { "api-version": SECURITY_API_VERSION } })).value || [];

// ── Usage + quotas (Microsoft.Compute|Network/locations/{location}/usages) ─────────────
const USAGES_API_VERSION = "2024-07-01";
export const listComputeUsages = async (s, location = "eastus") =>
  (await restJson("GET", `${sub(s)}/providers/Microsoft.Compute/locations/${location}/usages`, { query: { "api-version": USAGES_API_VERSION } })).value || [];
export const listNetworkUsages = async (s, location = "eastus") =>
  (await restJson("GET", `${sub(s)}/providers/Microsoft.Network/locations/${location}/usages`, { query: { "api-version": "2023-11-01" } })).value || [];

// ── Preview features (Microsoft.Features/providers/{ns}/features) ──────────────────────
const FEATURES_API_VERSION = "2021-07-01";
export const listPreviewFeatures = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Features/features`, { query: { "api-version": FEATURES_API_VERSION } })).value || [];
export const registerPreviewFeature = (s, full) => restJson("POST", `${sub(s)}/providers/Microsoft.Features/providers/${full.split("/")[0]}/features/${full.split("/")[1]}/register`, { query: { "api-version": FEATURES_API_VERSION } });
export const unregisterPreviewFeature = (s, full) => restJson("POST", `${sub(s)}/providers/Microsoft.Features/providers/${full.split("/")[0]}/features/${full.split("/")[1]}/unregister`, { query: { "api-version": FEATURES_API_VERSION } });

// ── My permissions (Microsoft.Authorization/permissions) ───────────────────────────────
export const myPermissions = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Authorization/permissions`, { query: { "api-version": IAM_API_VERSION } })).value || [];

// ── Policies (Microsoft.Authorization/policyDefinitions|policyAssignments, Microsoft.PolicyInsights) ──
const POLICY_API_VERSION = "2022-06-01";
export const listPolicyAssignments = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Authorization/policyAssignments`, { query: { "api-version": POLICY_API_VERSION } })).value || [];
export const putPolicyAssignment = (s, name, body) => restJson("PUT", `${sub(s)}/providers/Microsoft.Authorization/policyAssignments/${encodeURIComponent(name)}`, { query: { "api-version": POLICY_API_VERSION }, body });
export const deletePolicyAssignment = (s, name) => restJson("DELETE", `${sub(s)}/providers/Microsoft.Authorization/policyAssignments/${encodeURIComponent(name)}`, { query: { "api-version": POLICY_API_VERSION } });
export const policyComplianceStates = async (s) => (await restJson("POST", `${sub(s)}/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults`, { query: { "api-version": "2019-10-01" } })).value || [];
export const ALLOWED_LOCATIONS_POLICY_ID = "/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c";

// ── Deployment stacks (Microsoft.Resources/deploymentStacks) ───────────────────────────
const STACK_API_VERSION = "2024-03-01";
const stackPath = (s, name) => `${sub(s)}/providers/Microsoft.Resources/deploymentStacks${name ? `/${encodeURIComponent(name)}` : ""}`;
export const listDeploymentStacks = async (s) => (await restJson("GET", stackPath(s), { query: { "api-version": STACK_API_VERSION } })).value || [];
export const putDeploymentStack = (s, name, body) => restJson("PUT", stackPath(s, name), { query: { "api-version": STACK_API_VERSION }, body });
export const deleteDeploymentStack = (s, name) => restJson("DELETE", stackPath(s, name), { query: { "api-version": STACK_API_VERSION } });

// ── Invoices (Microsoft.Billing/invoices) ───────────────────────────────────────────────
export const listInvoices = async (s) => (await restJson("GET", `${sub(s)}/providers/Microsoft.Billing/invoices`, { query: { "api-version": "2024-04-01" } })).value || [];

// ── Billing properties (Microsoft.Billing/billingProperties, subscription-scoped in Vyomi) ──
const BILLING_PROPS_API_VERSION = "2017-04-24-preview";
export const getBillingProperties = (s) => restJson("GET", `${sub(s)}/providers/Microsoft.Billing/billingProperties`, { query: { "api-version": BILLING_PROPS_API_VERSION } });
export const patchBillingProperties = (s, body) => restJson("PATCH", `${sub(s)}/providers/Microsoft.Billing/billingProperties`, { query: { "api-version": BILLING_PROPS_API_VERSION }, body });

// ── Programmatic deployment credentials (Microsoft.Authorization/deploymentCredentials) ──
const credPath = (s, name) => `${sub(s)}/providers/Microsoft.Authorization/deploymentCredentials${name ? `/${encodeURIComponent(name)}` : ""}`;
export const listDeploymentCredentials = async (s) => (await restJson("GET", credPath(s), { query: {} })).value || [];
export const createDeploymentCredential = (s) => restJson("POST", credPath(s), { query: {} });
export const deleteDeploymentCredential = (s, name) => restJson("DELETE", credPath(s, name), { query: {} });

// ── Diagnose and solve problems / Advisor recommendations: composed client-side from the
// above real calls (resource providers, locks, quotas, activity log, security, budgets) —
// see SubscriptionBlade.jsx's Diagnostics()/Advisor(). No separate wire calls of their own.
