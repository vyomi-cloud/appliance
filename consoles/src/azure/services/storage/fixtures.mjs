/* UI-conformance fixtures for Storage accounts (ARM control plane + Blob/Queue data-plane
 * REST). See keyvaults/fixtures.mjs for the pattern this follows. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const ACCOUNT = "uicstorage";
const X_MS_VERSION = "2021-12-02";
const acctPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Storage/storageAccounts/${name}?api-version=2023-01-01`;
const blobAuth = (account) => ({ "x-ms-version": X_MS_VERSION, authorization: `SharedKey ${account}:fixture` });

async function ensureAccount(wire, name = ACCOUNT) {
  await wire("PUT", acctPath(name), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  "az-storage-account": async (wire) => { await ensureAccount(wire); },

  "live-account": async (wire, uniq) => { await ensureAccount(wire, uniq); return uniq; },

  // Each of these mints a FRESH account named `uniq` (not the shared "uicstorage") so the
  // page — routed at "#/storage/uic-rg/{live}/…" — resolves {resource-name} to the same
  // string the liveness check searches for; a container/lock/queue inside the shared
  // account would leave the title showing "uicstorage", not the unique live value.
  "live-container": async (wire, uniq) => {
    await ensureAccount(wire, uniq);
    await wire("PUT", `/${uniq}/${uniq}?restype=container`, { svc: null, headers: blobAuth(uniq) });
    return uniq;
  },

  "live-blob": async (wire, uniq) => {
    await ensureAccount(wire);
    await wire("PUT", `/${ACCOUNT}/uiccontainer?restype=container`, { svc: null, headers: blobAuth(ACCOUNT) });
    await wire("PUT", `/${ACCOUNT}/uiccontainer/${uniq}`, { svc: null, headers: { ...blobAuth(ACCOUNT), "x-ms-blob-type": "BlockBlob" }, body: "uic blob contents" });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureAccount(wire, uniq);
    await wire("PUT", `${acctPath(uniq).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the account is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME becomes
  // the activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureAccount(wire, uniq);
    await wire("PUT", `${acctPath(uniq).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  // Queues are a global data plane (no account scoping, like Key Vault keys/secrets) —
  // created with no Authorization header so the router's ambiguous-root heuristic
  // (SharedKey name matching the path segment -> blob) never applies. The account is
  // still minted fresh so the page title ("{live} | Queues") resolves to `uniq`.
  "live-queue": async (wire, uniq) => {
    await ensureAccount(wire, uniq);
    await wire("PUT", `/${uniq}`, { svc: null, headers: { "x-ms-version": X_MS_VERSION } });
    return uniq;
  },

  // Tables are ALSO a global data plane (core/azure_table_core.py, no SharedKey account
  // scoping) — same "reuse `uniq` for both the account and the table" trick as live-queue.
  // Routed by the Accept header (odata), not x-ms-version, so no auth header is needed.
  "live-table": async (wire, uniq) => {
    await ensureAccount(wire, uniq);
    await wire("POST", "/Tables", {
      svc: null, headers: { "content-type": "application/json", accept: "application/json;odata=nometadata" },
      body: { TableName: uniq },
    });
    return uniq;
  },

  // A lifecycle rule is a real nested ARM resource (managementPolicies/default) scoped to
  // the fresh account — the rule's own Name is the uniquely-named thing the List View shows.
  "live-lifecycle": async (wire, uniq) => {
    await ensureAccount(wire, uniq);
    await wire("PUT", `${acctPath(uniq).split("?")[0]}/managementPolicies/default?api-version=2023-01-01`, {
      svc: null,
      body: { properties: { policy: { rules: [{
        name: uniq, enabled: true, type: "Lifecycle",
        definition: { filters: { blobTypes: ["blockBlob"] }, actions: { baseBlob: { tierToCool: { daysAfterModificationGreaterThan: 30 } } } },
      }] } } },
    });
    return uniq;
  },
};
