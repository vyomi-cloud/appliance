/* UI-conformance fixtures for Container registries (ARM control plane + the registry's own
 * OCI v2 / ACR v1 REST data plane). See storage/fixtures.mjs-equivalent note in
 * aws/services/s3/fixtures.mjs. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const REG = "uicacr";
const REPO = "uicrepo";
const regPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ContainerRegistry/registries/${name}?api-version=2023-07-01`;
const MANIFEST_CT = "application/vnd.docker.distribution.manifest.v2+json";

async function ensureRegistry(wire) {
  await wire("PUT", regPath(REG), { svc: null, body: { location: "eastus" } }).catch(() => {});
}
async function ensureRepo(wire) {
  await wire("PUT", `/v2/${REPO}/manifests/latest`, { svc: null, headers: { "content-type": MANIFEST_CT }, body: '{"schemaVersion":2}' }).catch(() => {});
}

export default {
  "az-acr": async (wire) => { await ensureRegistry(wire); },
  "az-acr-repo": async (wire) => { await ensureRepo(wire); },

  "live-registry": async (wire, uniq) => { await wire("PUT", regPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-lock": async (wire, uniq) => {
    await ensureRegistry(wire);
    await wire("PUT", `${regPath(REG).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared "uicacr" registry is a real ARM mutation, so it lands on the
  // unified Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME
  // becomes the activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureRegistry(wire);
    await wire("PUT", `${regPath(REG).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  "live-webhook": async (wire, uniq) => {
    await ensureRegistry(wire);
    await wire("PUT", `${regPath(REG).split("?")[0]}/webhooks/${uniq}?api-version=2023-07-01`,
      { svc: null, body: { location: "eastus", properties: { serviceUri: "https://example.com/hook", scope: "*", status: "enabled", actions: ["push"] } } });
    return uniq;
  },

  // A fresh, uniquely-named repository (not the shared "uicrepo") so the Repositories list
  // shows a name the test just created, over the real OCI v2 push wire.
  "live-repo": async (wire, uniq) => {
    await wire("PUT", `/v2/${uniq}/manifests/latest`, { svc: null, headers: { "content-type": MANIFEST_CT }, body: '{"schemaVersion":2}' });
    return uniq;
  },

  // A uniquely-named TAG pushed into the shared "uicrepo" repository, so repository-detail's
  // Tags table shows something the test just created (the repo itself stays "uicrepo" so the
  // page's static route — scoped to that repo — doesn't need to change per run).
  "live-tag": async (wire, uniq) => {
    await ensureRepo(wire);
    await wire("PUT", `/v2/${REPO}/manifests/${uniq}`, { svc: null, headers: { "content-type": MANIFEST_CT }, body: '{"schemaVersion":2}' });
    return uniq;
  },
};
