/* UI-conformance fixtures for Artifact Registry — native-wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). `pushSample` is Vyomi's own console
 * convenience (no real AR method creates package data — see core/gcp_artifactregistry_core.py). */
const PROJECT = "vyomi-project";
const REPOS = `/v1/projects/${PROJECT}/locations/us-central1/repositories`;

async function ensureRepo(wire) {
  await wire("POST", `${REPOS}?repositoryId=uic-repo`, { svc: null, body: { format: "DOCKER" } }).catch(() => {});
}
async function ensureImage(wire) {
  await ensureRepo(wire);
  await wire("POST", `${REPOS}/uic-repo:pushSample`, { svc: null, body: { image: "uic-image", tag: "latest" } }).catch(() => {});
}

export default {
  "ar-repo": async (wire) => { await ensureImage(wire); return "uic-repo"; },
  "live-repo": async (wire, uniq) => { await wire("POST", `${REPOS}?repositoryId=${uniq}`, { svc: null, body: { format: "DOCKER" } }); return uniq; },
  "live-package": async (wire, uniq) => { await ensureRepo(wire); await wire("POST", `${REPOS}/uic-repo:pushSample`, { svc: null, body: { image: uniq, tag: "latest" } }); return uniq; },
  "live-tag": async (wire, uniq) => { await ensureImage(wire); await wire("POST", `${REPOS}/uic-repo:pushSample`, { svc: null, body: { image: "uic-image", tag: uniq } }); return uniq; },
};
