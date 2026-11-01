/* Kubernetes Engine (GKE) over the NATIVE Kubernetes Engine REST API v1
 * (container.googleapis.com/v1) — the same wire google-cloud-container, gcloud container
 * clusters ... and Terraform speak. Control plane only: clusters, node pools, operations,
 * server config. No Kubernetes API server runs behind a cluster's endpoint in Vyomi, so
 * workloads/services/secrets (data-plane objects) are not reachable here — see the honest
 * gaps in index.jsx. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = (location) => `/v1/projects/${e(getProject())}/locations/${e(location)}`;

export async function listClusters() {
  const r = await restJson("GET", `${base("-")}/clusters`);
  return (r.clusters || []).map(view);
}
export const getCluster = async (location, name) => view(await restJson("GET", `${base(location)}/clusters/${e(name)}`));
export const createCluster = (location, cluster) => restJson("POST", `${base(location)}/clusters`, { body: { cluster } });
export const updateCluster = (location, name, update) => restJson("PUT", `${base(location)}/clusters/${e(name)}`, { body: { update } });
export const deleteCluster = (location, name) => restJson("DELETE", `${base(location)}/clusters/${e(name)}`);
export const setResourceLabels = (location, name, resourceLabels, labelFingerprint) =>
  restJson("POST", `${base(location)}/clusters/${e(name)}:setResourceLabels`, { body: { resourceLabels, labelFingerprint } });
export const setLoggingMonitoring = (location, name, body) => restJson("PUT", `${base(location)}/clusters/${e(name)}`, { body: { update: body } });

export const createNodePool = (location, cluster, nodePool) => restJson("POST", `${base(location)}/clusters/${e(cluster)}/nodePools`, { body: { nodePool } });
export const deleteNodePool = (location, cluster, pool) => restJson("DELETE", `${base(location)}/clusters/${e(cluster)}/nodePools/${e(pool)}`);
export const setNodePoolSize = (location, cluster, pool, nodeCount) =>
  restJson("POST", `${base(location)}/clusters/${e(cluster)}/nodePools/${e(pool)}:setSize`, { body: { nodeCount } });
export const setNodePoolAutoscaling = (location, cluster, pool, autoscaling) =>
  restJson("POST", `${base(location)}/clusters/${e(cluster)}/nodePools/${e(pool)}:setAutoscaling`, { body: { autoscaling } });

export const serverConfig = (location) => restJson("GET", `${base(location)}/serverConfig`);

export async function listOperations(location = "-") {
  const r = await restJson("GET", `${base(location)}/operations`);
  return r.operations || [];
}

/* Backup for GKE (gkebackup.googleapis.com shape) — real create/list/get/delete over the
 * native REST API; see core/gcp_container_core.py's "Backup for GKE" section. */
export async function listBackupPlans(location = "-") {
  const r = await restJson("GET", `${base(location)}/backupPlans`);
  return r.backupPlans || [];
}
export const getBackupPlan = (location, id) => restJson("GET", `${base(location)}/backupPlans/${e(id)}`);
export const createBackupPlan = (location, id, plan) => restJson("POST", `${base(location)}/backupPlans`, { query: { backupPlanId: id }, body: plan });
export const deleteBackupPlan = (location, id, force) => restJson("DELETE", `${base(location)}/backupPlans/${e(id)}`, { query: force ? { force: "true" } : undefined });
export async function listBackups(location, planId) {
  const r = await restJson("GET", `${base(location)}/backupPlans/${e(planId)}/backups`);
  return r.backups || [];
}
export const createBackup = (location, planId, id) => restJson("POST", `${base(location)}/backupPlans/${e(planId)}/backups`, { query: { backupId: id }, body: {} });
export const deleteBackup = (location, planId, id) => restJson("DELETE", `${base(location)}/backupPlans/${e(planId)}/backups/${e(id)}`);
export const backupPlanId = (fullName) => fullName.split("/").pop();

export const REGIONS = [
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"], ["us-east4", "us-east4 (Northern Virginia)"],
  ["us-west1", "us-west1 (Oregon)"], ["europe-west1", "europe-west1 (Belgium)"], ["europe-west4", "europe-west4 (Netherlands)"],
  ["asia-south1", "asia-south1 (Mumbai)"], ["asia-southeast1", "asia-southeast1 (Singapore)"], ["asia-northeast1", "asia-northeast1 (Tokyo)"],
];
export const CHANNELS = [["RAPID", "Rapid channel"], ["REGULAR", "Regular channel"], ["STABLE", "Stable channel"], ["EXTENDED", "Extended channel"]];
export const channelLabel = (c) => CHANNELS.find(([v]) => v === c)?.[1] || (c ? c : "No channel");

export function controlPlaneAccessLabel(c) {
  const cpe = c.controlPlaneEndpointsConfig || {};
  const dns = (cpe.dnsEndpointConfig || {}).allowExternalTraffic !== false;
  const ipv4 = (cpe.ipEndpointsConfig || {}).enabled !== false;
  return [dns && "DNS", ipv4 && "IPv4"].filter(Boolean).join(" + ") || "None";
}

export const statusLabel = (s) => ({ RUNNING: "Running", PROVISIONING: "Provisioning", STOPPING: "Stopping", RECONCILING: "Reconciling", ERROR: "Error", DEGRADED: "Degraded" }[s] || s);

/** vCPU/memory for a machine type — mirrors core.gcp_container_core.shape() for display. */
const SHAPES = { "e2-micro": [2, 1], "e2-small": [2, 2], "e2-medium": [2, 4], "f1-micro": [1, 0.6], "g1-small": [1, 1.7], "n1-standard-1": [1, 3.75], "n1-standard-2": [2, 7.5] };
export function shape(machineType) {
  if (SHAPES[machineType]) return SHAPES[machineType];
  const m = /-([0-9]+)$/.exec(machineType || "");
  const n = m ? Number(m[1]) : 2;
  return [n, n * (machineType?.startsWith("n1-") ? 3.75 : 4)];
}

/** The console list/detail columns the Kubernetes Engine REST API itself doesn't carry
 * (mode, node/vCPU/memory totals, location) — derived client-side from the real Cluster
 * resource, exactly as the native console's frontend does. */
export function view(c) {
  const pools = c.nodePools || [];
  const autopilot = !!(c.autopilot || {}).enabled;
  let nodes = 0, cpus = 0, mem = 0;
  for (const p of pools) {
    const n = p.initialNodeCount || 0;
    const [cpu, gb] = shape(p.config?.machineType);
    nodes += n; cpus += cpu * n; mem += gb * n;
  }
  return {
    ...c,
    location: c.location || c.zone,
    mode: autopilot ? "Autopilot" : "Standard",
    nodes: autopilot ? "Autopilot-managed" : nodes,
    vcpus: autopilot ? "Autopilot-managed" : String(cpus),
    memory: autopilot ? "Autopilot-managed" : `${mem} GB`,
    notifications: "Disabled",
  };
}

export const validClusterName = (n) => {
  if (!n) return "Name is required.";
  if (n.length > 40) return "Name must be 40 characters or fewer.";
  if (!/^[a-z]([-a-z0-9]{0,38}[a-z0-9])?$/.test(n)) return "Use lowercase letters, numbers and hyphens. Start with a letter, end with a letter or number.";
  return null;
};

/* ── Kubernetes data plane (clusters/{c}/k8s/{real Kubernetes REST path}) — every call below
 * is the literal path/body shape a real kubectl/client-go request carries; see
 * core/gcp_gke_dataplane_core.py's docstring for why the `/k8s/` prefix exists. */
const k8sBase = (location, cluster) => `${base(location)}/clusters/${e(cluster)}/k8s`;
const nsSeg = (ns) => (ns ? `/namespaces/${e(ns)}` : "");

/** Runs `fn(location, name)` against every cluster in the project and flattens the
 * results, tagging each item with the cluster it came from — the Workloads/Discovery/
 * Secrets & ConfigMaps/Storage/Applications/Object Browser pages are project-wide, not
 * per-cluster, exactly like the real console's federated views. */
export async function overAllClusters(fn) {
  const clusters = await listClusters();
  const lists = await Promise.all(clusters.map(async (c) => {
    try {
      const items = await fn(c.location, c.name);
      return items.map((it) => ({ ...it, _location: c.location, _cluster: c.name }));
    } catch { return []; }
  }));
  return lists.flat();
}

export const validNsName = (n) => (n && /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/.test(n)) ? null : "Use lowercase letters, numbers and hyphens.";

export async function listNamespaces(location, cluster) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1/namespaces`);
  return r.items || [];
}
export const createNamespace = (location, cluster, name) => restJson("POST", `${k8sBase(location, cluster)}/api/v1/namespaces`, { body: { metadata: { name } } });
export const deleteNamespace = (location, cluster, name) => restJson("DELETE", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(name)}`);

// Workloads: Deployments / StatefulSets (scalable) + Jobs (run-to-completion) + their Pods.
export async function listDeployments(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/apps/v1${nsSeg(ns)}/deployments`);
  return r.items || [];
}
export async function listStatefulSets(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/apps/v1${nsSeg(ns)}/statefulsets`);
  return r.items || [];
}
export async function listJobs(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/batch/v1${nsSeg(ns)}/jobs`);
  return r.items || [];
}
export async function listWorkloads(location, cluster, ns) {
  const [d, s, j] = await Promise.all([listDeployments(location, cluster, ns), listStatefulSets(location, cluster, ns), listJobs(location, cluster, ns)]);
  return [...d, ...s, ...j];
}
export const createDeployment = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/apis/apps/v1/namespaces/${e(ns)}/deployments`, { body });
export const createStatefulSet = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/apis/apps/v1/namespaces/${e(ns)}/statefulsets`, { body });
export const createJob = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/apis/batch/v1/namespaces/${e(ns)}/jobs`, { body });
export const scaleWorkload = (location, cluster, plural, ns, name, replicas) =>
  restJson("PUT", `${k8sBase(location, cluster)}/apis/apps/v1/namespaces/${e(ns)}/${plural}/${e(name)}`, { body: { spec: { replicas } } });
export const deleteDeployment = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/apis/apps/v1/namespaces/${e(ns)}/deployments/${e(name)}`);
export const deleteStatefulSet = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/apis/apps/v1/namespaces/${e(ns)}/statefulsets/${e(name)}`);
export const deleteJob = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/apis/batch/v1/namespaces/${e(ns)}/jobs/${e(name)}`);
export const deleteWorkload = (location, cluster, kind, ns, name) => ({
  Deployment: deleteDeployment, StatefulSet: deleteStatefulSet, Job: deleteJob,
})[kind](location, cluster, ns, name);

export async function listPods(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1${nsSeg(ns)}/pods`);
  return r.items || [];
}
export const deletePod = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/pods/${e(name)}`);

// Discovery: Services / Ingress / Gateways.
export async function listServices(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1${nsSeg(ns)}/services`);
  return r.items || [];
}
export const createService = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/services`, { body });
export const deleteService = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/services/${e(name)}`);

export async function listIngresses(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/networking.k8s.io/v1${nsSeg(ns)}/ingresses`);
  return r.items || [];
}
export const createIngress = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/apis/networking.k8s.io/v1/namespaces/${e(ns)}/ingresses`, { body });
export const deleteIngress = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/apis/networking.k8s.io/v1/namespaces/${e(ns)}/ingresses/${e(name)}`);

export async function listGateways(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/gateway.networking.k8s.io/v1${nsSeg(ns)}/gateways`);
  return r.items || [];
}
export const createGateway = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/apis/gateway.networking.k8s.io/v1/namespaces/${e(ns)}/gateways`, { body });
export const deleteGateway = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/apis/gateway.networking.k8s.io/v1/namespaces/${e(ns)}/gateways/${e(name)}`);

// Secrets & ConfigMaps.
export async function listSecrets(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1${nsSeg(ns)}/secrets`);
  return r.items || [];
}
export const createSecret = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/secrets`, { body });
export const deleteSecret = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/secrets/${e(name)}`);
export async function listConfigMaps(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1${nsSeg(ns)}/configmaps`);
  return r.items || [];
}
export const createConfigMap = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/configmaps`, { body });
export const deleteConfigMap = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/configmaps/${e(name)}`);

// Storage: StorageClasses (seeded) + PersistentVolumeClaims/Volumes.
export async function listStorageClasses(location, cluster) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/storage.k8s.io/v1/storageclasses`);
  return r.items || [];
}
export async function listPvcs(location, cluster, ns) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1${nsSeg(ns)}/persistentvolumeclaims`);
  return r.items || [];
}
export const createPvc = (location, cluster, ns, body) => restJson("POST", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/persistentvolumeclaims`, { body });
export const deletePvc = (location, cluster, ns, name) => restJson("DELETE", `${k8sBase(location, cluster)}/api/v1/namespaces/${e(ns)}/persistentvolumeclaims/${e(name)}`);
export async function listPvs(location, cluster) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1/persistentvolumes`);
  return r.items || [];
}

export async function listK8sNodes(location, cluster) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/api/v1/nodes`);
  return r.items || [];
}

// Config: Config Sync + Policy Controller (real, enforced — see capability notes).
export const getConfigManagement = (location, cluster) => restJson("GET", `${k8sBase(location, cluster)}/apis/configmanagement.gke.io/v1/configmanagements/config-management`);
export const applyConfigManagement = (location, cluster, spec) =>
  restJson("PUT", `${k8sBase(location, cluster)}/apis/configmanagement.gke.io/v1/configmanagements/config-management`, { body: { spec } });
export async function listConstraints(location, cluster) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/apis/constraints.gatekeeper.sh/v1beta1/k8srequiredlabels`);
  return r.items || [];
}
export const createConstraint = (location, cluster, body) => restJson("POST", `${k8sBase(location, cluster)}/apis/constraints.gatekeeper.sh/v1beta1/k8srequiredlabels`, { body });
export const deleteConstraint = (location, cluster, name) => restJson("DELETE", `${k8sBase(location, cluster)}/apis/constraints.gatekeeper.sh/v1beta1/k8srequiredlabels/${e(name)}`);

// Observability (real, derived-only counts) + Applications (real grouping by app label).
export const getObservability = (location, cluster) => restJson("GET", `${k8sBase(location, cluster)}/observability`);
export async function listApplications(location, cluster) {
  const r = await restJson("GET", `${k8sBase(location, cluster)}/applications`);
  return r.items || [];
}

/* ── GKE Hub fleet registration (gkehub.googleapis.com shape) — independent of the k8s data
 * plane: a Membership just names a cluster into the project's fleet. */
const membershipsBase = () => `/v1/projects/${e(getProject())}/locations/global/memberships`;
export async function listMemberships() {
  const r = await restJson("GET", membershipsBase());
  return r.resources || [];
}
export const createMembership = (id, clusterLocation, clusterName) => restJson("POST", membershipsBase(), {
  query: { membershipId: id },
  body: { endpoint: { gkeCluster: { resourceLink: `//container.googleapis.com/projects/${getProject()}/locations/${clusterLocation}/clusters/${clusterName}` } } },
});
export const deleteMembership = (id) => restJson("DELETE", `${membershipsBase()}/${e(id)}`);
export function findMembership(memberships, project, location, clusterName) {
  const link = `//container.googleapis.com/projects/${project}/locations/${location}/clusters/${clusterName}`;
  return memberships.find((m) => m.endpoint?.gkeCluster?.resourceLink === link) || null;
}
export const membershipId = (m) => m.name.split("/").pop();
