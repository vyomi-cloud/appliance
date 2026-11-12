/* UI-conformance fixtures for Memorystore for Redis (native redis.googleapis.com v1 REST,
 * no SigV4 — svc: null). */
const PROJECT = "vyomi-project";   // consoles/src/gcp/project.js DEFAULT_PROJECT
const base = `/v1/projects/${PROJECT}/locations/us-central1/instances`;

export default {
  "live-instance": async (wire, uniq) => {
    await wire("POST", `${base}?instanceId=${uniq}`, { svc: null, body: { tier: "BASIC", memorySizeGb: 1 } });
    return uniq;
  },
};
