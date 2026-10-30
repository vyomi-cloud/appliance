/* Per-page fixtures for consoles/tests/ui-conformance.mjs — each creates a resource over
 * the native GCP wire (svc: null → no AWS signature) so "live" pages prove they show
 * real, freshly-created data rather than statics. `uniq` is a fresh random string per
 * check; "*-fixed" fixtures are idempotent (safe to call repeatedly against a
 * long-lived dev server — they ignore "already exists"). */
const PROJECT = "vyomi-project";
const SA_EMAIL = `uic-svc@${PROJECT}.iam.gserviceaccount.com`;
const ROLE_NAME = `projects/${PROJECT}/roles/uicRole`;

export default {
  "iam-binding": async (wire, uniq) => {
    const resource = `projects/${PROJECT}`;
    const cur = await wire("POST", `/v1/${resource}:getIamPolicy`, { svc: null, body: {} });
    const member = `user:${uniq}@example.com`;
    const bindings = [...(cur.bindings || []), { role: "roles/viewer", members: [member] }];
    await wire("POST", `/v1/${resource}:setIamPolicy`, { svc: null, body: { policy: { ...cur, bindings } } });
    return `${uniq}@example.com`;
  },

  "deny-policy": async (wire, uniq) => {
    const attach = encodeURIComponent(`cloudresourcemanager.googleapis.com/projects/${PROJECT}`);
    await wire("POST", `/v2/policies/${attach}/denypolicies?policyId=${uniq}`, {
      svc: null,
      body: { displayName: uniq, rules: [{ denyRule: { deniedPrincipals: ["user:bad@example.com"], deniedPermissions: ["storage.objects.delete"] } }] },
    });
    return uniq;
  },

  "service-account": async (wire, uniq) => {
    const r = await wire("POST", `/v1/projects/${PROJECT}/serviceAccounts`, { svc: null, body: { accountId: uniq, serviceAccount: { displayName: uniq } } });
    return r.email;
  },

  "service-account-fixed": async (wire) => {
    try { await wire("POST", `/v1/projects/${PROJECT}/serviceAccounts`, { svc: null, body: { accountId: "uic-svc", serviceAccount: { displayName: "uic-svc" } } }); }
    catch {}
    return SA_EMAIL;
  },

  "service-account-principal": async (wire, uniq) => {
    try { await wire("POST", `/v1/projects/${PROJECT}/serviceAccounts`, { svc: null, body: { accountId: "uic-svc", serviceAccount: { displayName: "uic-svc" } } }); }
    catch {}
    const resource = `projects/${PROJECT}/serviceAccounts/${SA_EMAIL}`;
    const cur = await wire("POST", `/v1/${resource}:getIamPolicy`, { svc: null, body: {} });
    const member = `user:${uniq}@example.com`;
    const bindings = [...(cur.bindings || []), { role: "roles/iam.serviceAccountUser", members: [member] }];
    await wire("POST", `/v1/${resource}:setIamPolicy`, { svc: null, body: { policy: { ...cur, bindings } } });
    return `${uniq}@example.com`;
  },

  "custom-role-fixed": async (wire) => {
    try { await wire("POST", `/v1/projects/${PROJECT}/roles`, { svc: null, body: { roleId: "uicRole", role: { title: "uicRole", description: "fixture role", includedPermissions: ["storage.objects.get"] } } }); }
    catch {}
    return "uicRole";
  },

  "custom-role": async (wire, uniq) => {
    await wire("POST", `/v1/projects/${PROJECT}/roles`, { svc: null, body: { roleId: uniq, role: { title: uniq, description: "live fixture" } } });
    return uniq;
  },

  "role-permission": async (wire, uniq) => {
    try { await wire("POST", `/v1/projects/${PROJECT}/roles`, { svc: null, body: { roleId: "uicRole", role: { title: "uicRole" } } }); }
    catch {}
    const cur = await wire("GET", `/v1/${ROLE_NAME}`, { svc: null });
    const perm = `uic.test.${uniq}`;
    await wire("PATCH", `/v1/${ROLE_NAME}`, { svc: null, body: { role: { includedPermissions: [...(cur.includedPermissions || []), perm] } } });
    return perm;
  },

  "audit-config": async (wire, uniq) => {
    const resource = `projects/${PROJECT}`;
    const cur = await wire("POST", `/v1/${resource}:getIamPolicy`, { svc: null, body: {} });
    const email = `${uniq}@example.com`;
    const auditConfigs = [...(cur.auditConfigs || []).filter((c) => c.service !== "storage.googleapis.com"),
      { service: "storage.googleapis.com", auditLogConfigs: [{ logType: "DATA_WRITE", exemptedMembers: [email] }] }];
    await wire("POST", `/v1/${resource}:setIamPolicy`, { svc: null, body: { policy: { ...cur, auditConfigs } } });
    return email;
  },

  "tag-key": async (wire, uniq) => {
    await wire("POST", "/v3/tagKeys", { svc: null, body: { parent: `projects/${PROJECT}`, shortName: uniq } });
    return uniq;
  },

  "org-policy": async (wire, uniq) => {
    const policyId = `custom.${uniq}`;
    await wire("POST", `/v2/projects/${PROJECT}/policies?policyId=${encodeURIComponent(policyId)}`, { svc: null, body: { spec: { rules: [{ enforce: true }] } } });
    return policyId;
  },

  "pam-entitlement": async (wire, uniq) => {
    await wire("POST", `/v1/projects/${PROJECT}/locations/global/entitlements?entitlementId=${uniq}`, { svc: null, body: { maxRequestDuration: "3600s" } });
    return uniq;
  },

  "essential-contact": async (wire, uniq) => {
    const email = `${uniq}@example.com`;
    await wire("POST", `/v1/projects/${PROJECT}/contacts`, { svc: null, body: { email } });
    return email;
  },

  "workload-pool": async (wire, uniq) => {
    await wire("POST", `/v1/projects/${PROJECT}/locations/global/workloadIdentityPools?workloadIdentityPoolId=${uniq}`, { svc: null, body: { displayName: uniq } });
    return uniq;
  },
};
