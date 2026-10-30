/* UI-conformance fixtures for Secret Manager — native-wire setup run by
 * consoles/tests/ui-conformance.mjs. Each returns the text the page must then show
 * (liveness: proves the page is not static). */
const PROJECT = "vyomi-project";
const SECRETS = `/v1/projects/${PROJECT}/secrets`;
const b64 = (s) => Buffer.from(s, "utf8").toString("base64");

async function ensureSecret(wire) {
  await wire("POST", `${SECRETS}?secretId=uic-secret`, { svc: null, body: { replication: { automatic: {} }, labels: { env: "demo" } } }).catch(() => {});
  await wire("POST", `${SECRETS}/uic-secret:addVersion`, { svc: null, body: { payload: { data: b64("uic-secret-value") } } }).catch(() => {});
}

export default {
  "sm-secret": async (wire) => { await ensureSecret(wire); return "uic-secret"; },
  "live-secret": async (wire, uniq) => { await wire("POST", `${SECRETS}?secretId=${uniq}`, { svc: null, body: { replication: { automatic: {} } } }); return uniq; },
  // Proves the secret-details page isn't static: patch a fresh label onto the fixed
  // secret right before load, the Overview tab's Labels chips must show it.
  "live-detail-label": async (wire, uniq) => {
    await ensureSecret(wire);
    await wire("PATCH", `${SECRETS}/uic-secret?updateMask=labels`, { svc: null, body: { labels: { env: "demo", [uniq]: "1" } } });
    return uniq;
  },
};
