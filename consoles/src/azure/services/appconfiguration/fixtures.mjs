/* UI-conformance fixtures for App Configuration (ARM control plane + the store's own data
 * plane — /kv, /labels, /locks). See keyvaults/fixtures.mjs for the shared-relay pattern this
 * follows (the store identity rides on `x-vyomi-store`, Key Vault's `x-vyomi-vault` analogue). */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const STORE = "uicappconfig";
const storePath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.AppConfiguration/configurationStores/${name}?api-version=2024-05-01`;

async function ensureStore(wire) {
  await wire("PUT", storePath(STORE), { svc: null, body: { location: "eastus" } }).catch(() => {});
}
const dataHeaders = (store) => ({ "x-vyomi-store": store });
async function ensureKv(wire) {
  await ensureStore(wire);
  await wire("PUT", "/kv/uic-key?api-version=2023-11-01", { svc: null, headers: dataHeaders(STORE), body: { value: "uic-value" } }).catch(() => {});
}

export default {
  "az-appconfig": async (wire) => { await ensureStore(wire); },
  "az-appconfig-kv": async (wire) => { await ensureKv(wire); },

  "live-store": async (wire, uniq) => { await wire("PUT", storePath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-kv": async (wire, uniq) => {
    await ensureStore(wire);
    await wire("PUT", `/kv/${uniq}?api-version=2023-11-01`, { svc: null, headers: dataHeaders(STORE), body: { value: "live" } });
    return uniq;
  },

  "live-kv-detail": async (wire, uniq) => {
    await ensureStore(wire);
    await wire("PUT", `/kv/${uniq}?api-version=2023-11-01`, { svc: null, headers: dataHeaders(STORE), body: { value: "live" } });
    return uniq;
  },

  "live-feature-flag": async (wire, uniq) => {
    await ensureStore(wire);
    const body = { value: JSON.stringify({ id: uniq, description: "", enabled: true, conditions: { client_filters: [] } }), content_type: "application/vnd.microsoft.appconfig.ff+json;charset=utf-8" };
    await wire("PUT", `/kv/.appconfig.featureflag%2F${uniq}?api-version=2023-11-01`, { svc: null, headers: dataHeaders(STORE), body });
    return uniq;
  },

  "live-replica": async (wire, uniq) => {
    await ensureStore(wire);
    await wire("PUT", `${storePath(STORE).split("?")[0]}/replicas/${uniq}?api-version=2024-05-01`, { svc: null, body: { location: "westus" } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureStore(wire);
    await wire("PUT", `${storePath(STORE).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared "uicappconfig" store is a real ARM mutation (generic
  // Microsoft.Authorization/locks handling, independent of the owning resource's namespace),
  // so it lands on the activity feed the same way Key Vault's live-activity fixture proves —
  // the lock NAME becomes the activity entry's "detail", so it is the uniquely-named thing to
  // look for.
  "live-activity": async (wire, uniq) => {
    await ensureStore(wire);
    await wire("PUT", `${storePath(STORE).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },
};
