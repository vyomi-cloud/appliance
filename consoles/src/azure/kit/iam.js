/* Access control (IAM) over the native Azure wire (Microsoft.Authorization, core/azure_iam_core.py):
 * role assignments / definitions / checkAccess scoped to ANY resource id — shared by every
 * service's Access control (IAM) blade. */
import { restJson } from "../../common/wire.js";
import { getSubscription } from "./arm.js";

const AUTHZ_API = "2022-04-01";
const authzPath = (p) => `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/${p}`;
export const listRoleAssignments = async () => (await restJson("GET", authzPath("roleAssignments"), { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () => (await restJson("GET", authzPath("roleDefinitions"), { query: { "api-version": AUTHZ_API } })).value || [];
export const putRoleAssignment = (name, body) => restJson("PUT", authzPath(`roleAssignments/${encodeURIComponent(name)}`), { query: { "api-version": AUTHZ_API }, body });
export const deleteRoleAssignment = (name) => restJson("DELETE", authzPath(`roleAssignments/${encodeURIComponent(name)}`), { query: { "api-version": AUTHZ_API } });
export const checkAccess = (principalId, action, scope) =>
  restJson("POST", authzPath("checkAccess"), { query: { "api-version": AUTHZ_API }, body: { principalId, actions: [{ id: action }], resource: { id: scope } } });
/** Scope inheritance (mirrors core/azure_iam_core.py's `_scope_covers`): an assignment at a
 * broader scope (subscription/resource group) covers this account too. */
export const scopeCovers = (assignmentScope, resourceId) => {
  const a = (assignmentScope || "/").replace(/\/$/, "") || "/";
  const r = (resourceId || "/").replace(/\/$/, "") || "/";
  return a === "/" || a === r || r.startsWith(a + "/");
};

