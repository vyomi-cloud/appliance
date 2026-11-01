/* Microsoft Entra ID over the native wire.
 *   Directory objects: Microsoft Graph  /v1.0/...            (core/azure_graph_core.py)
 *   Roles and administrators: Azure RBAC /providers/Microsoft.Authorization/... (core/azure_iam_core.py,
 *     the same checkAccess engine Azure RBAC uses — scope "/" is the tenant root).
 *   Sign-in: POST /{tenant}/oauth2/v2.0/token — real Azure AD sends this to a different
 *     host (login.microsoftonline.com) with no AWS-shaped signature either; form-encoded,
 *     so it goes straight through fetch() rather than restJson's always-JSON body.
 * Neither carries an AWS signature (Azure/Graph send none); routing is by path shape alone. */
import { restJson, WIRE_BASE, WireError } from "../../../common/wire.js";

const graph = (method, path, opts) => restJson(method, `/v1.0${path}`, opts);
const AUTH = "/providers/Microsoft.Authorization";

export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `id${Date.now()}${Math.random().toString(16).slice(2)}`);

// ── Users ─────────────────────────────────────────────────────────────────────────────
export const listUsers = async () => (await graph("GET", "/users")).value || [];
export const getUser = (id) => graph("GET", `/users/${encodeURIComponent(id)}`);
export const createUser = (body) => graph("POST", "/users", { body });
export const updateUser = (id, body) => graph("PATCH", `/users/${encodeURIComponent(id)}`, { body });
export const deleteUser = (id) => graph("DELETE", `/users/${encodeURIComponent(id)}`);
export const userMemberOf = async (id) => (await graph("GET", `/users/${encodeURIComponent(id)}/memberOf`)).value || [];

// ── Groups ────────────────────────────────────────────────────────────────────────────
export const listGroups = async () => (await graph("GET", "/groups")).value || [];
export const getGroup = (id) => graph("GET", `/groups/${encodeURIComponent(id)}`);
export const createGroup = (body) => graph("POST", "/groups", { body });
export const deleteGroup = (id) => graph("DELETE", `/groups/${encodeURIComponent(id)}`);
export const listMembers = async (id) => (await graph("GET", `/groups/${encodeURIComponent(id)}/members`)).value || [];
export const addMember = (groupId, memberId) =>
  graph("POST", `/groups/${encodeURIComponent(groupId)}/members/$ref`, { body: { "@odata.id": `https://graph.microsoft.com/v1.0/directoryObjects/${memberId}` } });
export const removeMember = (groupId, memberId) => graph("DELETE", `/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(memberId)}/$ref`);

// ── Applications (app registrations) + Service principals (enterprise applications) ───
export const listApplications = async () => (await graph("GET", "/applications")).value || [];
export const getApplication = (id) => graph("GET", `/applications/${encodeURIComponent(id)}`);
export const createApplication = (body) => graph("POST", "/applications", { body });
export const updateApplication = (id, body) => graph("PATCH", `/applications/${encodeURIComponent(id)}`, { body });
export const deleteApplication = (id) => graph("DELETE", `/applications/${encodeURIComponent(id)}`);
export const addPassword = (id, displayName, endDateTime) =>
  graph("POST", `/applications/${encodeURIComponent(id)}/addPassword`, { body: { passwordCredential: { displayName, endDateTime } } });
export const removePassword = (id, keyId) => graph("POST", `/applications/${encodeURIComponent(id)}/removePassword`, { body: { keyId } });

export const listServicePrincipals = async () => (await graph("GET", "/servicePrincipals")).value || [];
export const deleteServicePrincipal = (id) => graph("DELETE", `/servicePrincipals/${encodeURIComponent(id)}`);

// ── Domains ───────────────────────────────────────────────────────────────────────────
export const listDomains = async () => (await graph("GET", "/domains")).value || [];
export const addDomain = (name) => graph("POST", "/domains", { body: { id: name } });
export const deleteDomain = (name) => graph("DELETE", `/domains/${encodeURIComponent(name)}`);

// ── Administrative units ─────────────────────────────────────────────────────────────
export const listAdministrativeUnits = async () => (await graph("GET", "/directory/administrativeUnits")).value || [];
export const createAdministrativeUnit = (body) => graph("POST", "/directory/administrativeUnits", { body });
export const deleteAdministrativeUnit = (id) => graph("DELETE", `/directory/administrativeUnits/${encodeURIComponent(id)}`);

// ── Organization (tenant) ─────────────────────────────────────────────────────────────
export const getOrganization = async () => (await graph("GET", "/organization")).value?.[0];
export const updateOrganization = (id, body) => graph("PATCH", `/organization/${encodeURIComponent(id)}`, { body });

// ── Directory (user) settings ───────────────────────────────────────────────────────
export const getDirectorySettings = () => graph("GET", "/settings/directory");
export const updateDirectorySettings = (body) => graph("PATCH", "/settings/directory", { body });

// ── Audit / sign-in logs ──────────────────────────────────────────────────────────────
export const listAuditLogs = async () => (await graph("GET", "/auditLogs/directoryAudits")).value || [];
export const listSignInLogs = async () => (await graph("GET", "/auditLogs/signIns")).value || [];

/** Client-credentials grant with a REAL client secret (the one addPassword returned) —
 * the one authentication Vyomi can model without an interactive browser. Appends a real
 * row to Sign-in logs (success or failure) rather than ever faking one. */
export async function signInWithSecret(appId, clientSecret) {
  const form = new URLSearchParams({ grant_type: "client_credentials", client_id: appId, client_secret: clientSecret, scope: "https://graph.microsoft.com/.default" });
  const res = await fetch(`${WIRE_BASE}/${DEFAULT_TENANT_ID}/oauth2/v2.0/token`, {
    method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: form.toString(),
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new WireError(res.status, data.error, data.error_description, text);
  return data;
}

// ── Devices (a user's "Devices" tab; Devices overview aggregates across all users) ───
export const listDevices = async () => (await graph("GET", "/devices")).value || [];
export const listRegisteredDevices = async (userId) => (await graph("GET", `/users/${encodeURIComponent(userId)}/registeredDevices`)).value || [];
export const registerDevice = (userId, body) => graph("POST", `/users/${encodeURIComponent(userId)}/registeredDevices`, { body });
export const deleteDevice = (id) => graph("DELETE", `/devices/${encodeURIComponent(id)}`);

// ── Security defaults (Properties | "Manage security defaults" panel) ─────────────────
export const getSecurityDefaults = () => graph("GET", "/policies/identitySecurityDefaultsEnforcementPolicy");
export const updateSecurityDefaults = (body) => graph("PATCH", "/policies/identitySecurityDefaultsEnforcementPolicy", { body });

// ── Roles and administrators (Azure RBAC core, tenant-root scope) ─────────────────────
export const listRoleDefinitions = async () => (await restJson("GET", `${AUTH}/roleDefinitions`)).value || [];
export const listRoleAssignments = async () => (await restJson("GET", `${AUTH}/roleAssignments`)).value || [];
export const createCustomRole = (roleName, description) =>
  restJson("PUT", `${AUTH}/roleDefinitions/${encodeURIComponent(roleName)}`, {
    body: { properties: { roleName, description, permissions: [{ actions: ["*/read"], notActions: [] }] } },
  });
export const deleteRoleDefinition = (roleName) => restJson("DELETE", `${AUTH}/roleDefinitions/${encodeURIComponent(roleName)}`);
export const assignRole = (roleName, principalId, scope = "/") =>
  restJson("PUT", `${AUTH}/roleAssignments/${uid()}`, { body: { properties: { roleName, principalId, scope } } });
export const deleteRoleAssignment = (name) => restJson("DELETE", `${AUTH}/roleAssignments/${encodeURIComponent(name)}`);

// "Access management for Azure resources" (Properties page): whether the single caller
// identity Vyomi models holds a real tenant-root "User Access Administrator" assignment.
export const ELEVATED_ADMIN_PRINCIPAL = "global-admin";
export const ELEVATE_ROLE_NAME = "User Access Administrator";

// ── form helpers ──────────────────────────────────────────────────────────────────────
export const DEFAULT_DOMAIN = "vyomilearn.onmicrosoft.com";
export const DEFAULT_TENANT_ID = "00000000-0000-0000-0000-cloudlearn01";   // core/azure_graph_core.py's GraphStore.organization id
export const genPassword = () => `Vy${Math.random().toString(36).slice(2, 8)}!${Math.random().toString(36).slice(2, 6)}A1`;
export const fmtDateTime = (v) => (v ? new Date(v).toLocaleString() : "--");
