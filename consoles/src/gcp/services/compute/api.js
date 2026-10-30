/* Compute Engine over the NATIVE Compute Engine REST API v1 (the same wire
 * google-cloud-compute / gcloud compute speak). Every call here is a real GCE v1 operation. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = () => `/compute/v1/projects/${e(getProject())}`;

// ── catalogs / reference data ────────────────────────────────────────────────
export const REGIONS = [
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"], ["us-east4", "us-east4 (Northern Virginia)"],
  ["us-west1", "us-west1 (Oregon)"], ["europe-west1", "europe-west1 (Belgium)"], ["europe-west4", "europe-west4 (Netherlands)"],
  ["asia-east1", "asia-east1 (Taiwan)"], ["asia-southeast1", "asia-southeast1 (Singapore)"], ["asia-northeast1", "asia-northeast1 (Tokyo)"],
];
export const ZONES_BY_REGION = {
  "us-central1": ["us-central1-a", "us-central1-b", "us-central1-c"],
  "us-east1": ["us-east1-b", "us-east1-c", "us-east1-d"],
  "us-east4": ["us-east4-a", "us-east4-b", "us-east4-c"],
  "us-west1": ["us-west1-a", "us-west1-b", "us-west1-c"],
  "europe-west1": ["europe-west1-b", "europe-west1-c", "europe-west1-d"],
  "europe-west4": ["europe-west4-a", "europe-west4-b", "europe-west4-c"],
  "asia-east1": ["asia-east1-a", "asia-east1-b", "asia-east1-c"],
  "asia-southeast1": ["asia-southeast1-a", "asia-southeast1-b", "asia-southeast1-c"],
  "asia-northeast1": ["asia-northeast1-a", "asia-northeast1-b", "asia-northeast1-c"],
};
export const DEFAULT_REGION = "us-central1";
export const DEFAULT_ZONE = "us-central1-a";

export const MACHINE_FAMILIES = [
  ["General purpose", ["e2", "n2"]], ["Compute optimized", ["c2"]], ["Memory optimized", ["n2hm", "m2"]],
  ["Storage optimized", []], ["GPUs", ["a2"]],
];
const SERIES_OF = (name) => {
  if (name.startsWith("n2-highmem")) return "n2hm";
  const m = name.match(/^([a-z]+\d*)-/);
  return m ? m[1] : name;
};
export const machineFamilyFor = (name) => MACHINE_FAMILIES.find(([, series]) => series.includes(SERIES_OF(name)))?.[0] || "General purpose";
export const seriesLabel = (s) => ({ e2: "E2", n2: "N2", n2hm: "N2 (highmem)", c2: "C2", m2: "M2", a2: "A2" }[s] || s.toUpperCase());

export const DISK_TYPES = [
  ["pd-balanced", "Balanced persistent disk"], ["pd-extreme", "Extreme persistent disk"], ["pd-ssd", "SSD persistent disk"],
  ["pd-standard", "Standard persistent disk"], ["hyperdisk-balanced", "Hyperdisk Balanced"],
  ["hyperdisk-throughput", "Hyperdisk Throughput"], ["hyperdisk-extreme", "Hyperdisk Extreme"],
];
export const diskTypeLabel = (v) => DISK_TYPES.find(([k]) => k === v)?.[1] || v;

export const OS_IMAGES = [
  ["debian-cloud", "debian-12", "Debian", "Debian GNU/Linux 12 (bookworm)"],
  ["debian-cloud", "debian-11", "Debian", "Debian GNU/Linux 11 (bullseye)"],
  ["ubuntu-os-cloud", "ubuntu-2404-lts-amd64", "Ubuntu", "Ubuntu 24.04 LTS"],
  ["ubuntu-os-cloud", "ubuntu-2204-lts", "Ubuntu", "Ubuntu 22.04 LTS"],
  ["rocky-linux-cloud", "rocky-linux-9", "Rocky Linux", "Rocky Linux 9"],
  ["cos-cloud", "cos-stable", "Container-Optimized OS", "Container-Optimized OS (stable)"],
];
export const osImageSource = (project, family) => `projects/${project}/global/images/family/${family}`;

export const HEALTH_CHECK_TYPES = ["TCP", "HTTP", "HTTPS", "SSL", "HTTP2", "GRPC"];

// ── zones / regions / machine types ──────────────────────────────────────────
export const listZones = async () => (await restJson("GET", `${base()}/zones`)).items || [];
export const listRegions = async () => (await restJson("GET", `${base()}/regions`)).items || [];
export const listMachineTypes = async (zone) => (await restJson("GET", `${base()}/zones/${e(zone)}/machineTypes`)).items || [];

// ── instances ─────────────────────────────────────────────────────────────────
export async function listInstancesAllZones() {
  const r = await restJson("GET", `${base()}/aggregated/instances`);
  return Object.entries(r.items || {}).flatMap(([scope, v]) => (v.instances || []).map((i) => ({ ...i, _zoneScope: scope.replace("zones/", "") })));
}
export const listInstances = async (zone) => (await restJson("GET", `${base()}/zones/${e(zone)}/instances`)).items || [];
export const getInstance = (zone, name) => restJson("GET", `${base()}/zones/${e(zone)}/instances/${e(name)}`);
export const insertInstance = (zone, body) => restJson("POST", `${base()}/zones/${e(zone)}/instances`, { body });
export const deleteInstance = (zone, name) => restJson("DELETE", `${base()}/zones/${e(zone)}/instances/${e(name)}`);
export const instanceAction = (zone, name, action) => restJson("POST", `${base()}/zones/${e(zone)}/instances/${e(name)}:${action}`, { body: {} });
export const setInstanceLabels = (zone, name, labels) => restJson("POST", `${base()}/zones/${e(zone)}/instances/${e(name)}:setLabels`, { body: { labels } });
export const setInstanceDeletionProtection = (zone, name, enabled) =>
  restJson("POST", `${base()}/zones/${e(zone)}/instances/${e(name)}:setDeletionProtection`, { query: { deletionProtection: enabled }, body: {} });
export const setInstanceMachineType = (zone, name, machineType) => restJson("POST", `${base()}/zones/${e(zone)}/instances/${e(name)}:setMachineType`, { body: { machineType } });

// ── disks ─────────────────────────────────────────────────────────────────────
export async function listDisksAllZones() {
  const r = await restJson("GET", `${base()}/aggregated/disks`);
  return Object.entries(r.items || {}).flatMap(([scope, v]) => (v.disks || []).map((d) => ({ ...d, _zoneScope: scope.replace("zones/", "") })));
}
export const listDisks = async (zone) => (await restJson("GET", `${base()}/zones/${e(zone)}/disks`)).items || [];
export const getDisk = (zone, name) => restJson("GET", `${base()}/zones/${e(zone)}/disks/${e(name)}`);
export const insertDisk = (zone, body) => restJson("POST", `${base()}/zones/${e(zone)}/disks`, { body });
export const deleteDisk = (zone, name) => restJson("DELETE", `${base()}/zones/${e(zone)}/disks/${e(name)}`);
export const createSnapshot = (zone, diskName, body) => restJson("POST", `${base()}/zones/${e(zone)}/disks/${e(diskName)}:createSnapshot`, { body });

// ── snapshots ─────────────────────────────────────────────────────────────────
export const listSnapshots = async () => (await restJson("GET", `${base()}/global/snapshots`)).items || [];
export const deleteSnapshot = (name) => restJson("DELETE", `${base()}/global/snapshots/${e(name)}`);

// ── images ────────────────────────────────────────────────────────────────────
export const listImages = async () => (await restJson("GET", `${base()}/global/images`)).items || [];
export const insertImage = (body) => restJson("POST", `${base()}/global/images`, { body });
export const deleteImage = (name) => restJson("DELETE", `${base()}/global/images/${e(name)}`);

// ── machine images ────────────────────────────────────────────────────────────
export const listMachineImages = async () => (await restJson("GET", `${base()}/global/machineImages`)).items || [];
export const insertMachineImage = (body) => restJson("POST", `${base()}/global/machineImages`, { body });
export const deleteMachineImage = (name) => restJson("DELETE", `${base()}/global/machineImages/${e(name)}`);

// ── instance templates ────────────────────────────────────────────────────────
export const listInstanceTemplates = async () => (await restJson("GET", `${base()}/global/instanceTemplates`)).items || [];
export const insertInstanceTemplate = (body) => restJson("POST", `${base()}/global/instanceTemplates`, { body });
export const deleteInstanceTemplate = (name) => restJson("DELETE", `${base()}/global/instanceTemplates/${e(name)}`);

// ── instance groups (unmanaged) ───────────────────────────────────────────────
export async function listInstanceGroupsAllZones() {
  const r = await restJson("GET", `${base()}/aggregated/instanceGroups`);
  return Object.entries(r.items || {}).flatMap(([scope, v]) => (v.instanceGroups || []).map((g) => ({ ...g, _zoneScope: scope.replace("zones/", "") })));
}
export const listInstanceGroups = async (zone) => (await restJson("GET", `${base()}/zones/${e(zone)}/instanceGroups`)).items || [];
export const insertInstanceGroup = (zone, body) => restJson("POST", `${base()}/zones/${e(zone)}/instanceGroups`, { body });
export const deleteInstanceGroup = (zone, name) => restJson("DELETE", `${base()}/zones/${e(zone)}/instanceGroups/${e(name)}`);
export const addGroupInstances = (zone, name, instances) =>
  restJson("POST", `${base()}/zones/${e(zone)}/instanceGroups/${e(name)}:addInstances`, { body: { instances: instances.map((i) => ({ instance: i })) } });
export const removeGroupInstances = (zone, name, instances) =>
  restJson("POST", `${base()}/zones/${e(zone)}/instanceGroups/${e(name)}:removeInstances`, { body: { instances: instances.map((i) => ({ instance: i })) } });

// ── health checks ─────────────────────────────────────────────────────────────
export const listHealthChecks = async () => (await restJson("GET", `${base()}/global/healthChecks`)).items || [];
export const insertHealthCheck = (body) => restJson("POST", `${base()}/global/healthChecks`, { body });
export const deleteHealthCheck = (name) => restJson("DELETE", `${base()}/global/healthChecks/${e(name)}`);

// ── operations ─────────────────────────────────────────────────────────────────
export async function listOperations() {
  const r = await restJson("GET", `${base()}/aggregated/operations`);
  return Object.values(r.items || {}).flatMap((v) => v.operations || []);
}

// ── project / metadata ────────────────────────────────────────────────────────
export const getProjectResource = () => restJson("GET", base());
export const setCommonInstanceMetadata = (items) => restJson("POST", `${base()}/setCommonInstanceMetadata`, { body: { items } });

// ── small display helpers ─────────────────────────────────────────────────────
export const last = (url) => String(url || "").replace(/\/$/, "").split("/").pop();
export const zoneOf = (inst) => last(inst.zone);
export const machineTypeNameOf = (inst) => last(inst.machineType);
export const internalIpOf = (inst) => inst.networkInterfaces?.[0]?.networkIP || "—";
export const externalIpOf = (inst) => inst.networkInterfaces?.[0]?.accessConfigs?.[0]?.natIP || "—";
export const statusChipColor = (status) => ({ RUNNING: "success", TERMINATED: "default", SUSPENDED: "warning", PROVISIONING: "info", STAGING: "info", STOPPING: "warning", SUSPENDING: "warning", REPAIRING: "error" }[status] || "default");

export const validResourceName = (n) => {
  if (!n) return "Name is required.";
  if (!/^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$/.test(n)) return "Use lowercase letters, numbers and hyphens; start with a letter.";
  return null;
};
