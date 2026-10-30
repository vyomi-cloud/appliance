/* UI-conformance fixtures for Key vaults (ARM control plane + Key Vault Keys/Secrets REST
 * data planes). See storage/fixtures.mjs-equivalent note in aws/services/s3/fixtures.mjs. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const VAULT = "uickv";
const vaultPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.KeyVault/vaults/${name}?api-version=2023-07-01`;

async function ensureVault(wire) {
  await wire("PUT", vaultPath(VAULT), { svc: null, body: { location: "eastus" } }).catch(() => {});
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
};
