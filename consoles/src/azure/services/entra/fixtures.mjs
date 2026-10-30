/* Liveness fixtures for consoles/tests/ui-conformance.mjs — each creates a (fixed-name or
 * uniquely-named) resource over the native Microsoft Graph wire (svc: null — Graph sends
 * no AWS signature) and returns the text the page must show back.
 *
 * Fixed-name fixtures (entra-user / entra-group / entra-app) back the many reference-only
 * sub-pages of a single user/group/app — they are idempotent (swallow the "already
 * exists" conflict) since several pages share one fixture call. The "-live" fixtures take
 * the harness's unique-per-check name and back the "no statics" liveness checks on the
 * list pages. */
const DOMAIN = "vyomilearn.onmicrosoft.com";

async function ensureUser(wire) {
  const upn = `uic-entra-user@${DOMAIN}`;
  try {
    await wire("POST", "/v1.0/users", { svc: null, body: { displayName: "uic-entra-user", userPrincipalName: upn, passwordProfile: { password: "Vy3omi!2345AB", forceChangePasswordNextSignIn: false } } });
  } catch { /* already exists */ }
  return "uic-entra-user";
}

async function ensureGroup(wire) {
  try {
    await wire("POST", "/v1.0/groups", { svc: null, body: { displayName: "uic-entra-group", mailNickname: "uicentragroup", securityEnabled: true, mailEnabled: false, groupTypes: [] } });
  } catch { /* already exists */ }
  return "uic-entra-group";
}

async function ensureApp(wire) {
  try {
    await wire("POST", "/v1.0/applications", { svc: null, body: { displayName: "uic-entra-app", signInAudience: "AzureADMyOrg" } });
  } catch { /* already exists */ }
  return "uic-entra-app";
}

async function liveUser(wire, uniq) {
  const name = `live-user-${uniq}`;
  await wire("POST", "/v1.0/users", { svc: null, body: { displayName: name, userPrincipalName: `${name}@${DOMAIN}`, passwordProfile: { password: "Vy3omi!2345AB", forceChangePasswordNextSignIn: false } } });
  return name;
}

async function liveGroup(wire, uniq) {
  const name = `live-group-${uniq}`;
  await wire("POST", "/v1.0/groups", { svc: null, body: { displayName: name, mailNickname: name.replace(/-/g, ""), securityEnabled: true, mailEnabled: false, groupTypes: [] } });
  return name;
}

async function liveApp(wire, uniq) {
  const name = `live-app-${uniq}`;
  await wire("POST", "/v1.0/applications", { svc: null, body: { displayName: name, signInAudience: "AzureADMyOrg" } });
  return name;
}

async function liveAdminUnit(wire, uniq) {
  const name = `live-au-${uniq}`;
  await wire("POST", "/v1.0/directory/administrativeUnits", { svc: null, body: { displayName: name } });
  return name;
}

async function liveDomain(wire, uniq) {
  const name = `${uniq}.example.com`;
  await wire("POST", "/v1.0/domains", { svc: null, body: { id: name } });
  return name;
}

async function liveRole(wire, uniq) {
  const name = `live-role-${uniq}`;
  await wire("PUT", `/providers/Microsoft.Authorization/roleDefinitions/${name}`, {
    svc: null, body: { properties: { roleName: name, description: "liveness check", permissions: [{ actions: ["*/read"], notActions: [] }] } },
  });
  return name;
}

export default {
  "entra-user": ensureUser,
  "entra-group": ensureGroup,
  "entra-app": ensureApp,
  "entra-user-live": liveUser,
  "entra-group-live": liveGroup,
  "entra-app-live": liveApp,
  "entra-adminunit-live": liveAdminUnit,
  "entra-domain-live": liveDomain,
  "entra-role-live": liveRole,
};
