/* UI-conformance fixtures for Kubernetes services (AKS: ARM control plane + the nested
 * agentPools resource). See storage/fixtures.mjs-equivalent note in aws/services/s3/fixtures.mjs. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const CLUSTER = "uicaks";
const AV = "2024-09-02-preview";
const clusterPath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.ContainerService/managedClusters/${name}?api-version=${AV}`;

async function ensureCluster(wire) {
  await wire("PUT", clusterPath(CLUSTER), { svc: null, body: { location: "eastus" } }).catch(() => {});
}

export default {
  "az-aks": async (wire) => { await ensureCluster(wire); },

  "live-cluster": async (wire, uniq) => { await wire("PUT", clusterPath(uniq), { svc: null, body: { location: "eastus" } }); return uniq; },

  "live-namespace": async (wire, uniq) => {
    await ensureCluster(wire);
    const got = await wire("GET", clusterPath(CLUSTER), { svc: null });
    const current = (got.properties?.namespaces) || [];
    const namespaces = [...current, { name: uniq, status: "Active" }];
    await wire("PATCH", clusterPath(CLUSTER), { svc: null, body: { properties: { namespaces } } });
    return uniq;
  },

  "live-nodepool": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("PUT", `${clusterPath(CLUSTER).split("?")[0]}/agentPools/${uniq}?api-version=${AV}`,
      { svc: null, body: { properties: { count: 1, vmSize: "Standard_DS2_v2", mode: "User" } } });
    return uniq;
  },

  "live-lock": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("PUT", `${clusterPath(CLUSTER).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return uniq;
  },

  // A lock write on the shared "uicaks" cluster is a real ARM mutation, so it lands on the
  // unified Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME
  // becomes the activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("PUT", `${clusterPath(CLUSTER).split("?")[0]}/providers/Microsoft.Authorization/locks/${uniq}?api-version=2020-05-01`,
      { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return uniq;
  },

  // Kubernetes objects: applied with kubectl through the native runCommand action (the same call
  // `az aks command invoke` makes) — a uniquely named object the Workloads / Services and ingresses
  // / Configuration blades must then list.
  "live-workload": async (wire, uniq) => {
    await ensureCluster(wire);
    const y = `apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ${uniq}\n  namespace: default\nspec:\n  selector:\n    matchLabels: {app: ${uniq}}\n  template:\n    metadata:\n      labels: {app: ${uniq}}\n    spec:\n      containers:\n      - name: c\n        image: nginx:1.25\n`;
    await wire("POST", `${clusterPath(CLUSTER).split("?")[0]}/runCommand?api-version=${AV}`, { svc: null, body: { command: `kubectl apply -f - <<EOF\n${y}EOF` } });
    return uniq;
  },

  "live-service": async (wire, uniq) => {
    await ensureCluster(wire);
    const y = `apiVersion: v1\nkind: Service\nmetadata:\n  name: ${uniq}\n  namespace: default\nspec:\n  ports:\n  - port: 80\n`;
    await wire("POST", `${clusterPath(CLUSTER).split("?")[0]}/runCommand?api-version=${AV}`, { svc: null, body: { command: `kubectl apply -f - <<EOF\n${y}EOF` } });
    return uniq;
  },

  "live-configmap": async (wire, uniq) => {
    await ensureCluster(wire);
    await wire("POST", `${clusterPath(CLUSTER).split("?")[0]}/runCommand?api-version=${AV}`,
      { svc: null, body: { command: `kubectl apply -f - <<EOF\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: ${uniq}\n  namespace: default\ndata:\n  k: v\nEOF` } });
    return uniq;
  },
};
