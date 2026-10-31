/* UI-conformance fixtures for GKE — native-wire setup run by consoles/tests/ui-conformance.mjs.
 * Each returns the text the page must then show (liveness: proves the page is not static).
 * GCP carries no AWS signature (svc: null — see consoles/AGENT-UI.md). */
const PROJECT = "vyomi-project";
const L = `/v1/projects/${PROJECT}/locations/us-central1`;
const CLUSTER_FULL = `projects/${PROJECT}/locations/us-central1/clusters/uic-cluster`;

export default {
  "gke-cluster": async (wire) => {
    await wire("POST", `${L}/clusters`, { svc: null, body: { cluster: { name: "uic-cluster", initialNodeCount: 1 } } }).catch(() => {});
    return "uic-cluster";
  },
  "live-cluster": async (wire, uniq) => {
    await wire("POST", `${L}/clusters`, { svc: null, body: { cluster: { name: uniq, initialNodeCount: 1 } } });
    return uniq;
  },
  "live-pool": async (wire, uniq) => {
    await wire("POST", `${L}/clusters`, { svc: null, body: { cluster: { name: "uic-cluster", initialNodeCount: 1 } } }).catch(() => {});
    await wire("POST", `${L}/clusters/uic-cluster/nodePools`, { svc: null, body: { nodePool: { name: uniq, initialNodeCount: 1 } } });
    return uniq;
  },
  "live-backup-plan": async (wire, uniq) => {
    await wire("POST", `${L}/clusters`, { svc: null, body: { cluster: { name: "uic-cluster", initialNodeCount: 1 } } }).catch(() => {});
    await wire("POST", `${L}/backupPlans?backupPlanId=${uniq}`, { svc: null, body: { cluster: CLUSTER_FULL } });
    return uniq;
  },
};
