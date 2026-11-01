/* IAM & Admin over the NATIVE Google APIs: Cloud IAM / Resource Manager v1 (policy
 * bindings, service accounts, custom roles, deny policies, workload identity pools),
 * Resource Manager v3 (project, tag keys), Essential Contacts v1, Org Policy v2 and
 * Privileged Access Manager v1. Every call here is a real API operation the matching
 * google-cloud-* SDK / gcloud command would make. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const projectResource = () => `projects/${getProject()}`;
const attachmentPoint = () => e(`cloudresourcemanager.googleapis.com/projects/${getProject()}`);

// ── resource IAM policy (project-scoped Allow tab) ──────────────────────────
export const getIamPolicy = (resource = projectResource()) => restJson("POST", `/v1/${resource}:getIamPolicy`, { body: {} });
export const setIamPolicy = (policy, resource = projectResource()) => restJson("POST", `/v1/${resource}:setIamPolicy`, { body: { policy } });
export const testIamPermissions = (permissions, member, resource = projectResource()) =>
  restJson("POST", `/v1/${resource}:testIamPermissions`, { body: { permissions, member } });
export async function listPolicyActivity() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/policyActivity`);
  return r.activity || [];
}

// ── service accounts ─────────────────────────────────────────────────────────
export async function listServiceAccounts() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/serviceAccounts`);
  return r.accounts || [];
}
export const createServiceAccount = (accountId, serviceAccount) =>
  restJson("POST", `/v1/projects/${getProject()}/serviceAccounts`, { body: { accountId, serviceAccount } });
export const getServiceAccount = (email) => restJson("GET", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}`);
export const patchServiceAccount = (email, fields) => restJson("PATCH", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}`, { body: { serviceAccount: fields } });
export const disableServiceAccount = (email) => restJson("POST", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}:disable`, { body: {} });
export const enableServiceAccount = (email) => restJson("POST", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}:enable`, { body: {} });
export const deleteServiceAccount = (email) => restJson("DELETE", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}`);
export const serviceAccountResource = (email) => `projects/${getProject()}/serviceAccounts/${email}`;
export async function listServiceAccountActivity(email) {
  const r = await restJson("GET", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}/policyActivity`);
  return r.activity || [];
}
export const getServiceAccountMetrics = (email) => restJson("GET", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}:metrics`);

// ── service account keys ─────────────────────────────────────────────────────
export async function listKeys(email) {
  const r = await restJson("GET", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}/keys`);
  return r.keys || [];
}
export const createKey = (email) =>
  restJson("POST", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}/keys`, { body: { privateKeyType: "TYPE_GOOGLE_CREDENTIALS_FILE" } });
export const deleteKey = (email, keyId) => restJson("DELETE", `/v1/projects/${getProject()}/serviceAccounts/${e(email)}/keys/${e(keyId)}`);

// ── roles ─────────────────────────────────────────────────────────────────────
export async function listPredefinedRoles() {
  const r = await restJson("GET", "/v1/roles");
  return r.roles || [];
}
export async function listCustomRoles() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/roles`);
  return r.roles || [];
}
export const createRole = (roleId, role) => restJson("POST", `/v1/projects/${getProject()}/roles`, { body: { roleId, role } });
export const getRole = (name) => restJson("GET", `/v1/${name}`);
export const patchRole = (name, role) => restJson("PATCH", `/v1/${name}`, { body: { role } });
export const deleteRole = (name) => restJson("DELETE", `/v1/${name}`);

// ── deny policies ─────────────────────────────────────────────────────────────
export async function listDenyPolicies() {
  const r = await restJson("GET", `/v2/policies/${attachmentPoint()}/denypolicies`);
  return r.policies || [];
}
export const createDenyPolicy = (policyId, body) =>
  restJson("POST", `/v2/policies/${attachmentPoint()}/denypolicies`, { query: { policyId }, body });
export const deleteDenyPolicy = (policyId) => restJson("DELETE", `/v2/policies/${attachmentPoint()}/denypolicies/${e(policyId)}`);

// ── workload identity pools ───────────────────────────────────────────────────
export async function listWorkloadIdentityPools() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/locations/global/workloadIdentityPools`);
  return r.workloadIdentityPools || [];
}
export const createWorkloadIdentityPool = (poolId, body) =>
  restJson("POST", `/v1/projects/${getProject()}/locations/global/workloadIdentityPools`, { query: { workloadIdentityPoolId: poolId }, body });
export const deleteWorkloadIdentityPool = (name) => restJson("DELETE", `/v1/${name}`);

// ── Managed Workload Identities (nested under a workload identity pool) ──────
export async function listManagedIdentities(poolName) {
  const r = await restJson("GET", `/v1/${poolName}/managedIdentities`);
  return r.managedIdentities || [];
}
export const createManagedIdentity = (poolName, identityId) =>
  restJson("POST", `/v1/${poolName}/managedIdentities`, { query: { workloadIdentityPoolManagedIdentityId: identityId }, body: {} });
export const rotateManagedIdentityCert = (name) => restJson("POST", `/v1/${name}:rotateCertificate`, { body: {} });
export const deleteManagedIdentity = (name) => restJson("DELETE", `/v1/${name}`);

// ── Asset Inventory ───────────────────────────────────────────────────────────
export async function searchAssets(query) {
  const r = await restJson("GET", `/v1/projects/${getProject()}:searchAllResources`, { query: query ? { query } : {} });
  return r.results || [];
}

// ── Security Insights ─────────────────────────────────────────────────────────
export async function listSecurityInsights() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/locations/global/insights`);
  return r.insights || [];
}

// ── Identity-Aware Proxy ───────────────────────────────────────────────────────
export async function listIapResources() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/iap_web`);
  return r.resources || [];
}
export const createIapResource = (resourceId, displayName) =>
  restJson("POST", `/v1/projects/${getProject()}/iap_web`, { query: { resourceId }, body: { displayName } });
export const setIapEnabled = (name, enabled) => restJson("PATCH", `/v1/${name}`, { body: { enabled } });
export const deleteIapResource = (name) => restJson("DELETE", `/v1/${name}`);
export const checkIapAccess = (name, member) => restJson("POST", `/v1/${name}:checkAccess`, { body: { member } });

// ── Organization (every project has a real backing org) ──────────────────────
export async function getOrganization() {
  const p = await getProjectMeta();
  if (!p.parent || p.parent.type !== "organization") return null;
  return restJson("GET", `/v3/organizations/${p.parent.id}`);
}

// ── Cloud Identity Groups (org-scoped) ────────────────────────────────────────
export async function listGroups() {
  const org = await getOrganization();
  const r = await restJson("GET", "/v1/groups", { query: org ? { parent: org.name } : {} });
  return r.groups || [];
}
export async function createGroup(email, displayName) {
  const org = await getOrganization();
  return restJson("POST", "/v1/groups", { body: { groupKey: { id: email }, displayName, parent: org?.name } });
}
export const deleteGroup = (name) => restJson("DELETE", `/v1/${name}`);
export async function listGroupMemberships(groupName) {
  const r = await restJson("GET", `/v1/${groupName}/memberships`);
  return r.memberships || [];
}
export const addGroupMembership = (groupName, memberId) =>
  restJson("POST", `/v1/${groupName}/memberships`, { body: { preferredMemberKey: { id: memberId } } });
export const removeGroupMembership = (name) => restJson("DELETE", `/v1/${name}`);

// ── Workforce Identity Federation pools (org-scoped) ──────────────────────────
export async function listWorkforcePools() {
  const org = await getOrganization();
  const r = await restJson("GET", "/v1/locations/global/workforcePools", { query: org ? { parent: org.name } : {} });
  return r.workforcePools || [];
}
export async function createWorkforcePool(poolId, displayName) {
  const org = await getOrganization();
  return restJson("POST", "/v1/locations/global/workforcePools", { query: { workforcePoolId: poolId }, body: { displayName, parent: org?.name } });
}
export const deleteWorkforcePool = (name) => restJson("DELETE", `/v1/${name}`);

// ── Principal Access Boundary (org-scoped policies + bindings) ───────────────
export async function listPabPolicies() {
  const org = await getOrganization();
  if (!org) return [];
  const r = await restJson("GET", `/v3/${org.name}/locations/global/principalAccessBoundaryPolicies`);
  return r.principalAccessBoundaryPolicies || [];
}
export async function createPabPolicy(policyId, displayName, resources) {
  const org = await getOrganization();
  return restJson("POST", `/v3/${org.name}/locations/global/principalAccessBoundaryPolicies`,
    { query: { principalAccessBoundaryPolicyId: policyId }, body: { displayName, details: { rules: [{ resources }] } } });
}
export const deletePabPolicy = (name) => restJson("DELETE", `/v3/${name}`);
export async function listPabBindings() {
  const org = await getOrganization();
  if (!org) return [];
  const r = await restJson("GET", `/v3/${org.name}/locations/global/policyBindings`);
  return r.policyBindings || [];
}
export async function createPabBinding(bindingId, policyName, principal) {
  const org = await getOrganization();
  return restJson("POST", `/v3/${org.name}/locations/global/policyBindings`,
    { query: { policyBindingId: bindingId }, body: { policy: policyName, target: { principal } } });
}
export const deletePabBinding = (name) => restJson("DELETE", `/v3/${name}`);

// ── project (Resource Manager v3) ─────────────────────────────────────────────
export const getProjectMeta = () => restJson("GET", `/v3/projects/${getProject()}`);
export const patchProjectMeta = (body) => restJson("PATCH", `/v3/projects/${getProject()}`, { body });

// ── tags (tag keys) ───────────────────────────────────────────────────────────
export async function listTagKeys() {
  const r = await restJson("GET", "/v3/tagKeys", { query: { parent: projectResource() } });
  return r.tagKeys || [];
}
export const createTagKey = (shortName, description) =>
  restJson("POST", "/v3/tagKeys", { body: { parent: projectResource(), shortName, description } });
export const deleteTagKey = (name) => restJson("DELETE", `/v3/${name}`);

// ── essential contacts ────────────────────────────────────────────────────────
export async function listContacts() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/contacts`);
  return r.contacts || [];
}
export const createContact = (body) => restJson("POST", `/v1/projects/${getProject()}/contacts`, { body });
export const deleteContact = (name) => restJson("DELETE", `/v1/${name}`);

// ── organization policies ─────────────────────────────────────────────────────
export async function listOrgPolicies() {
  const r = await restJson("GET", `/v2/projects/${getProject()}/policies`);
  return r.policies || [];
}
export const createOrgPolicy = (policyId, body) =>
  restJson("POST", `/v2/projects/${getProject()}/policies`, { query: { policyId }, body });
export const deleteOrgPolicy = (name) => restJson("DELETE", `/v2/${name}`);

// ── Privileged Access Manager ──────────────────────────────────────────────────
export async function listEntitlements() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/locations/global/entitlements`);
  return r.entitlements || [];
}
export const createEntitlement = (entitlementId, body) =>
  restJson("POST", `/v1/projects/${getProject()}/locations/global/entitlements`, { query: { entitlementId }, body });
export const deleteEntitlement = (name) => restJson("DELETE", `/v1/${name}`);

export async function listGrants(entitlementName) {
  const r = await restJson("GET", `/v1/${entitlementName}/grants`);
  return r.grants || [];
}
export async function listAllGrants() {
  const ents = await listEntitlements();
  const lists = await Promise.all(ents.map((e) => listGrants(e.name)));
  return lists.flat().sort((a, b) => (a.createTime < b.createTime ? 1 : -1));
}
export const createGrant = (entitlementName, body) => restJson("POST", `/v1/${entitlementName}/grants`, { body });
export const approveGrant = (name, body = {}) => restJson("POST", `/v1/${name}:approve`, { body });
export const denyGrant = (name, body = {}) => restJson("POST", `/v1/${name}:deny`, { body });
export const revokeGrant = (name, body = {}) => restJson("POST", `/v1/${name}:revoke`, { body });
export const grantEntitlementId = (grantName) => grantName.split("/grants/")[0].split("/").pop();
export const getPamSettings = () => restJson("GET", `/v1/projects/${getProject()}/locations/global/settings`);
export const patchPamSettings = (body) => restJson("PATCH", `/v1/projects/${getProject()}/locations/global/settings`, { body });
export async function listPamNotifications() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/locations/global/notifications`);
  return r.notifications || [];
}

// ── display helpers ───────────────────────────────────────────────────────────
export const PREDEFINED_ROLE_TITLES = {
  "roles/owner": "Owner", "roles/editor": "Editor", "roles/viewer": "Viewer",
  "roles/storage.admin": "Storage Admin", "roles/storage.objectAdmin": "Storage Object Admin", "roles/storage.objectViewer": "Storage Object Viewer",
  "roles/iam.serviceAccountAdmin": "Service Account Admin", "roles/iam.serviceAccountUser": "Service Account User",
  "roles/iam.securityAdmin": "Security Admin", "roles/resourcemanager.projectIamAdmin": "Project IAM Admin",
  "roles/pubsub.admin": "Pub/Sub Admin", "roles/pubsub.publisher": "Pub/Sub Publisher",
  "roles/cloudsql.admin": "Cloud SQL Admin", "roles/compute.admin": "Compute Admin",
  "roles/logging.viewer": "Logs Viewer", "roles/monitoring.viewer": "Monitoring Viewer",
};
export const roleTitle = (roleId) => PREDEFINED_ROLE_TITLES[roleId] || roleId?.split("/").pop() || roleId;

// Role resource names ("projects/p/roles/x", "roles/x") contain "/" and can't be a
// single hash-route path segment (the router re-joins decoded parts with "/", which
// would then re-split into extra segments) — substitute "~" the way the real GCP
// console encodes compound resource names in its own URLs.
export const roleSlug = (name) => name.replace(/\//g, "~");
export const roleFromSlug = (slug) => slug.replace(/~/g, "/");

/** Parse a GCP IAM member string ("user:a@b.com", "allUsers", …) into {type, display}. */
export function parseMember(member) {
  if (member === "allUsers") return { type: "All users", display: "allUsers" };
  if (member === "allAuthenticatedUsers") return { type: "All authenticated users", display: "allAuthenticatedUsers" };
  const [kind, ...rest] = String(member).split(":");
  const display = rest.join(":");
  const TYPE = { user: "User", serviceAccount: "Service account", group: "Group", domain: "Domain" };
  return { type: TYPE[kind] || kind, display: display || member };
}
