/* Azure Kubernetes Service (AKS) over the native wire.
 *   Control plane:  ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ContainerService/managedClusters/{name}
 *   Node pools:      ARM extension-shaped nested resource …/managedClusters/{name}/agentPools/{pool}
 *   Namespaces:      modelled as a stateful array on properties.namespaces (see
 *                     core/capabilities/azure/aks.json "azure.aks.namespaces") — there is no ARM
 *                     surface for live Kubernetes objects in the real service either; those are
 *                     read from the cluster's own Kubernetes API server, which Vyomi does not run.
 */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const ARM = armType("Microsoft.ContainerService", "managedClusters", "2024-09-02-preview");

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });

export const listClusters = async () => (await ARM.list()).map(shape);
export const getCluster = async (rg, name) => shape(await ARM.get(rg, name));
export const createCluster = (rg, name, body) => ARM.put(rg, name, body);
export const updateCluster = (rg, name, body) => ARM.patch(rg, name, body);
export const deleteCluster = (rg, name) => ARM.remove(rg, name);

export const startCluster = (rg, name) => ARM.action(rg, name, "start");
export const stopCluster = (rg, name) => ARM.action(rg, name, "stop");
export const runCommand = (rg, name, command) => ARM.action(rg, name, "runCommand", { command });
export const listClusterUserCredential = (rg, name) => ARM.action(rg, name, "listClusterUserCredential");

/** base64 kubeconfig -> decoded YAML text. */
export const decodeKubeconfig = (b64) => atob(b64);

// ── Node pools (Microsoft.ContainerService/managedClusters/{cluster}/agentPools/{pool}) ────
const poolsPath = (rg, cluster, pool) => `${ARM.path(rg, cluster)}/agentPools${pool ? `/${encodeURIComponent(pool)}` : ""}`;

export const listNodePools = async (rg, cluster) =>
  (await restJson("GET", poolsPath(rg, cluster), { query: { "api-version": ARM.apiVersion } })).value || [];
export const getNodePool = (rg, cluster, pool) => restJson("GET", poolsPath(rg, cluster, pool), { query: { "api-version": ARM.apiVersion } });
export const putNodePool = (rg, cluster, pool, body) => restJson("PUT", poolsPath(rg, cluster, pool), { query: { "api-version": ARM.apiVersion }, body });
export const patchNodePool = (rg, cluster, pool, body) => restJson("PATCH", poolsPath(rg, cluster, pool), { query: { "api-version": ARM.apiVersion }, body });
export const deleteNodePool = (rg, cluster, pool) => restJson("DELETE", poolsPath(rg, cluster, pool), { query: { "api-version": ARM.apiVersion } });

/** Flatten node pools into the synthetic per-node rows the portal's "Nodes" tab shows — a
 *  deterministic rollup of each pool's own (real) properties, not fabricated telemetry. */
export function flattenNodes(pools) {
  return pools.flatMap((p) => {
    const count = p.properties?.count || 0;
    return Array.from({ length: count }, (_, i) => ({
      name: `aks-${(p.name || "pool").slice(0, 8)}-${10000000 + i}-vmss${i}`,
      pool: p.name,
      status: p.properties?.powerState?.code === "Stopped" ? "NotReady" : "Ready",
      role: p.properties?.mode === "System" ? "Agent" : "Agent",
      kubernetesVersion: p.properties?.orchestratorVersion || p.properties?.currentOrchestratorVersion,
      os: p.properties?.osType,
      vmSize: p.properties?.vmSize,
    }));
  });
}

// ── Namespaces (stateful list on properties.namespaces — see module doc) ───────────────────
export const listNamespaces = (a) => a.properties?.namespaces || [];
export const addNamespace = async (rg, name, nsName) => {
  const a = await getCluster(rg, name);
  const namespaces = [...listNamespaces(a), { name: nsName, status: "Active", createdAt: new Date().toISOString() }];
  return updateCluster(rg, name, { properties: { namespaces } });
};
export const deleteNamespace = async (rg, name, nsName) => {
  const a = await getCluster(rg, name);
  const namespaces = listNamespaces(a).filter((n) => n.name !== nsName);
  return updateCluster(rg, name, { properties: { namespaces } });
};

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────────
const LOCK_API_VERSION = "2020-05-01";
const lockPath = (rg, name, lockName) => `${ARM.path(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;

export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this cluster) ─
export const listActivityLog = async (rg, name) => {
  const rid = ARM.path(rg, name);
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${rid}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── create-cluster form model → ARM body (cluster + the initial node pool) ─────────────────
export function toArmBody(f) {
  return {
    location: f.location,
    tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])),
    properties: {
      kubernetesVersion: f.kubernetesVersion || undefined,
      dnsPrefix: f.dnsPrefix,
      enableRBAC: true,
      agentPoolProfiles: f.nodePools.map((p) => ({
        name: p.name, mode: p.mode, vmSize: p.vmSize, osSKU: p.osSku, count: p.count,
        availabilityZones: p.zones ? p.zones.split(",").map((z) => z.trim()).filter(Boolean) : undefined,
        maxPods: p.maxPods, type: "VirtualMachineScaleSets",
      })),
      autoUpgradeProfile: { upgradeChannel: { "Enabled with patch (recommended)": "patch", "Enabled with stable": "stable", "Enabled with rapid": "rapid", "Enabled with node image": "node-image", "Disabled": "none" }[f.autoUpgrade] || "patch" },
      nodeResourceGroup: f.infraResourceGroup || undefined,
      apiServerAccessProfile: { enablePrivateCluster: f.privateCluster, authorizedIPRanges: f.authorizedIpRanges ? f.authorizedIpRanges.split(",").map((s) => s.trim()).filter(Boolean) : [] },
      networkProfile: {
        networkPlugin: "azure",
        networkPluginMode: f.networkConfig === "Azure CNI Overlay" ? "overlay" : undefined,
        networkPolicy: f.cilium ? "cilium" : undefined,
        loadBalancerSku: "standard",
      },
      addonProfiles: {
        omsagent: { enabled: f.containerInsights },
        azurepolicy: { enabled: f.azurePolicy },
      },
      azureMonitorProfile: { metrics: { enabled: f.prometheus } },
      enableImageCleaner: f.imageCleaner,
      oidcIssuerProfile: { enabled: f.oidcIssuer },
      securityProfile: { workloadIdentity: { enabled: f.workloadIdentity }, defender: { securityMonitoring: { enabled: f.defender } } },
      podIdentityProfile: {},
      virtualNodesProfile: { enabled: f.virtualNodes },
      serviceMeshProfile: f.istio ? { mode: "Istio" } : undefined,
      dnsPrefixDnsName: f.dnsPrefix,
      disableLocalAccounts: f.authMode !== "Local accounts with Kubernetes RBAC",
    },
  };
}
