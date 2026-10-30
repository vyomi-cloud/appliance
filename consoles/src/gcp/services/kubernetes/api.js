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
