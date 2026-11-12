/* UI-conformance fixtures for Key vaults (ARM control plane + Key Vault Keys/Secrets REST
 * data planes). See storage/fixtures.mjs-equivalent note in aws/services/s3/fixtures.mjs. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const VAULT = "uickv";
const vaultPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${name}?api-version=2023-07-01`;

async function ensureVault(wire) {
  // PATCH, not PUT: this runs once per page that needs "uickv" to exist, so after the first
  // (real create) call every later call must be a no-op merge — a repeat PUT is ARM's own
  // full-replace semantics and would reset properties (including the access_configuration /
  // access_policies self-grant azure_arm_core.py's create hook makes) back to the bare
  // defaults on every subsequent page, locking the vault's own data plane out from under it.
  await wire("PATCH", vaultPath(VAULT), { svc: null, body: { location: "eastus" } }).catch(() => {});
}
async function ensureSecret(wire) {
  await ensureVault(wire);
  await wire("PUT", "/secrets/uicsecret?api-version=7.4", { svc: null, body: { value: "uic-secret-value" } }).catch(() => {});
}

export default {
  "az-keyvault": async (wire) => { await ensureVault(wire); },
  "az-keyvault-secret": async (wire) => { await ensureSecret(wire); },

  "live-vault": async (wire, uniq) => { await wire("PUT", vaultPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-key": async (wire, uniq) => {
    await ensureVault(wire);
    await wire("POST", `/keys/${uniq}/create?api-version=7.4`, { svc: null, body: { kty: "RSA", key_size: 2048 } });
    return uniq;
  },

  "live-secret": async (wire, uniq) => {
    await ensureVault(wire);
    await wire("PUT", `/secrets/${uniq}?api-version=7.4`, { svc: null, body: { value: "live" } });
    return uniq;
  },

  "live-secret-version": async (wire, uniq) => {
    await ensureSecret(wire);
    const r = await wire("PUT", "/secrets/uicsecret?api-version=7.4", { svc: null, body: { value: uniq } });
    return r.id.split("/").pop();
  },

  // A fresh per-check vault (not the shared "uickv") — the blade's vault fetch only
  // re-runs on rg/name change, so patching the already-mounted shared vault's
  // accessPolicies would never show up without a reload the harness never triggers.
  "live-policy": async (wire, uniq) => {
    await wire("PUT", vaultPath(uniq), { svc: null, body: { location: "eastus" } });
    await wire("PATCH", vaultPath(uniq), { svc: null, body: { properties: { accessPolicies: [{ tenantId: "00000000-0000-0000-0000-000000000000", objectId: uniq, permissions: { keys: ["get"], secrets: [], certificates: [] } }] } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureVault(wire);
    await wire("PUT", `${vaultPath(VAULT).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  "live-cert": async (wire, uniq) => {
    await ensureVault(wire);
    await wire("POST", `/certificates/${uniq}/create?api-version=7.4`, { svc: null, body: { policy: { x509_certificate_properties: { subject: "CN=uic" } } } });
    return uniq;
  },

  // A lock write on the shared "uickv" vault is a real ARM mutation, so it lands on the
  // unified Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME
  // becomes the activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureVault(wire);
    await wire("PUT", `${vaultPath(VAULT).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },
};
