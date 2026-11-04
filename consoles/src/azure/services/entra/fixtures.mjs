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

// Registers a real device (core/azure_graph_core.py's /v1.0/users/{id}/registeredDevices)
// onto a brand-new, uniquely-named user — reusing the SAME unique name for both the user
// (so the page's "{resource-name} | Devices" title still renders correctly, since that
// resource-name resolves to this live check's own return value) and the device it owns
// (so the device genuinely shows up in that user's Devices table, not just the title).
async function liveDevice(wire, uniq) {
  const name = `live-device-${uniq}`;
  const u = await wire("POST", "/v1.0/users", { svc: null, body: { displayName: name, userPrincipalName: `${name}@${DOMAIN}`, passwordProfile: { password: "Vy3omi!2345AB", forceChangePasswordNextSignIn: false } } });
  await wire("POST", `/v1.0/users/${u.id}/registeredDevices`, { svc: null, body: { displayName: name, operatingSystem: "Windows", operatingSystemVersion: "11" } });
  return name;
}

// A real oauth2/v2.0/token client_credentials grant with a freshly-created app's real
// secret — the "no statics" check for Sign-in logs: the app's name must show up in a
// genuine Service principal sign-in row, not a sample one.
async function liveSignIn(wire, uniq) {
  const name = `live-signin-${uniq}`;
  const app = await wire("POST", "/v1.0/applications", { svc: null, body: { displayName: name, signInAudience: "AzureADMyOrg" } });
  const cred = await wire("POST", `/v1.0/applications/${app.id}/addPassword`, { svc: null, body: { passwordCredential: { displayName: "ci" } } });
  await wire("POST", "/00000000-0000-0000-0000-cloudlearn01/oauth2/v2.0/token", {
    svc: null, headers: { "content-type": "application/x-www-form-urlencoded" },
    body: `grant_type=client_credentials&client_id=${encodeURIComponent(app.appId)}&client_secret=${encodeURIComponent(cred.secretText)}`,
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
  "entra-device-live": liveDevice,
  "entra-sign-in-live": liveSignIn,
};
