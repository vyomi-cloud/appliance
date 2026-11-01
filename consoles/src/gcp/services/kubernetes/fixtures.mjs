/* UI-conformance fixtures for GKE — native-wire setup run by consoles/tests/ui-conformance.mjs.
 * Each returns the text the page must then show (liveness: proves the page is not static).
 * GCP carries no AWS signature (svc: null — see consoles/AGENT-UI.md). */
const PROJECT = "vyomi-project";
const L = `/v1/projects/${PROJECT}/locations/us-central1`;
const CLUSTER_FULL = `projects/${PROJECT}/locations/us-central1/clusters/uic-cluster`;
const K = `${L}/clusters/uic-cluster/k8s`;
const ensureCluster = (wire) => wire("POST", `${L}/clusters`, { svc: null, body: { cluster: { name: "uic-cluster", initialNodeCount: 1 } } }).catch(() => {});

export default {
  "gke-cluster": async (wire) => {
    await ensureCluster(wire);
    return "uic-cluster";
  },
  "live-cluster": async (wire, uniq) => {
    await wire("POST", `${L}/clusters`, { svc: null, body: { cluster: { name: uniq, initialNodeCount: 1 } } });
    return uniq;
  },
  "live-pool": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${L}/clusters/uic-cluster/nodePools`, { svc: null, body: { nodePool: { name: uniq, initialNodeCount: 1 } } });
    return uniq;
  },
  "live-backup-plan": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${L}/backupPlans?backupPlanId=${uniq}`, { svc: null, body: { cluster: CLUSTER_FULL } });
    return uniq;
  },
  // Kubernetes data plane (core/gcp_gke_dataplane_core.py) — every call below is the
  // literal real Kubernetes REST path/body shape, over `clusters/uic-cluster/k8s/...`.
  "live-workload": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${K}/apis/apps/v1/namespaces/default/deployments`, {
      svc: null, body: { metadata: { name: uniq, labels: { app: uniq } },
        spec: { replicas: 1, template: { metadata: { labels: { app: uniq } }, spec: { containers: [{ name: "c", image: "nginx:latest" }] } } } },
    });
    return uniq;
  },
  "live-applications": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${K}/apis/apps/v1/namespaces/default/deployments`, {
      svc: null, body: { metadata: { name: uniq, labels: { app: uniq } },
        spec: { replicas: 1, template: { metadata: { labels: { app: uniq } }, spec: { containers: [{ name: "c", image: "nginx:latest" }] } } } },
    });
    return uniq;
  },
  "live-discovery": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${K}/api/v1/namespaces/default/services`, {
      svc: null, body: { metadata: { name: uniq }, spec: { selector: { app: "x" }, ports: [{ port: 80, targetPort: 80 }] } },
    });
    return uniq;
  },
  "live-secret-configmap": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${K}/api/v1/namespaces/default/configmaps`, { svc: null, body: { metadata: { name: uniq }, data: { k: "v" } } });
    return uniq;
  },
  "live-storage": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${K}/api/v1/namespaces/default/persistentvolumeclaims`, {
      svc: null, body: { metadata: { name: uniq }, spec: { resources: { requests: { storage: "1Gi" } } } },
    });
    return uniq;
  },
};
