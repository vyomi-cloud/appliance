/* Memorystore for Redis over the NATIVE Memorystore for Redis REST API v1 (the same wire
 * google-cloud-redis / gcloud redis instances ... speak): /v1/projects/{p}/locations/{l}/
 * instances... Every call here is a real redis.googleapis.com v1 operation. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const project = () => getProject();
const base = (location) => `/v1/projects/${e(project())}/locations/${e(location || "-")}/instances`;

export const listInstances = async () => (await restJson("GET", base("-"))).instances || [];
export const getInstance = (location, id) => restJson("GET", `${base(location)}/${e(id)}`);
export const createInstance = (location, id, body) => restJson("POST", base(location), { query: { instanceId: id }, body });
export const patchInstance = (location, id, body, updateMask) => restJson("PATCH", `${base(location)}/${e(id)}`, { query: { updateMask }, body });
export const deleteInstance = (location, id) => restJson("DELETE", `${base(location)}/${e(id)}`);
export const failoverInstance = (location, id, body = {}) => restJson("POST", `${base(location)}/${e(id)}:failover`, { body });
export const upgradeInstance = (location, id, redisVersion) => restJson("POST", `${base(location)}/${e(id)}:upgrade`, { body: { redisVersion } });
export const exportInstance = (location, id, uri) => restJson("POST", `${base(location)}/${e(id)}:export`, { body: { outputConfig: { gcsDestination: { uri } } } });
export const importInstance = (location, id, uri) => restJson("POST", `${base(location)}/${e(id)}:import`, { body: { inputConfig: { gcsSource: { uri } } } });
export const rescheduleMaintenance = (location, id, body) => restJson("POST", `${base(location)}/${e(id)}:rescheduleMaintenance`, { body });
export const getAuthString = (location, id) => restJson("GET", `${base(location)}/${e(id)}/authString`);

export const parseName = (full) => { const seg = String(full || "").split("/"); return { project: seg[1], location: seg[3], id: seg[5] }; };

export const REGIONS = [
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"], ["us-east4", "us-east4 (Northern Virginia)"],
  ["us-west1", "us-west1 (Oregon)"], ["us-west2", "us-west2 (Los Angeles)"],
  ["europe-west1", "europe-west1 (Belgium)"], ["europe-west2", "europe-west2 (London)"],
  ["europe-west3", "europe-west3 (Frankfurt)"], ["europe-west4", "europe-west4 (Netherlands)"],
  ["asia-east1", "asia-east1 (Taiwan)"], ["asia-northeast1", "asia-northeast1 (Tokyo)"],
  ["asia-south1", "asia-south1 (Mumbai)"], ["asia-southeast1", "asia-southeast1 (Singapore)"],
  ["australia-southeast1", "australia-southeast1 (Sydney)"], ["southamerica-east1", "southamerica-east1 (São Paulo)"],
];
export const regionLabel = (l) => (REGIONS.find(([v]) => v === l) || [l, l])[1];

export const VERSIONS = ["REDIS_7_2", "REDIS_7_0", "REDIS_6_X", "REDIS_5_0", "REDIS_4_0", "REDIS_3_2"];
export const versionLabel = (v) => String(v || "").replace("REDIS_", "Redis ").replace("_X", ".x").replace(/_/g, ".");

export const MAXMEMORY_POLICIES = ["volatile-lru", "allkeys-lru", "volatile-lfu", "allkeys-lfu", "volatile-random", "allkeys-random", "volatile-ttl", "noeviction"];
export const SNAPSHOT_PERIODS = [["ONE_HOUR", "Every 1 hour"], ["SIX_HOURS", "Every 6 hours"], ["TWELVE_HOURS", "Every 12 hours"], ["TWENTY_FOUR_HOURS", "Every 24 hours"]];
export const snapshotPeriodLabel = (p) => (SNAPSHOT_PERIODS.find(([v]) => v === p) || [p, p])[1];
export const DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"];

export const tierLabel = (t) => (t === "STANDARD_HA" ? "Standard (HA)" : "Basic");
export const stateLabel = (s) => ({
  READY: "Ready", CREATING: "Creating…", UPDATING: "Updating…", DELETING: "Deleting…",
  REPAIRING: "Repairing", MAINTENANCE: "Under maintenance", IMPORTING: "Importing", FAILING_OVER: "Failing over",
}[s] || s);
export const capacityLabel = (i) => `${i.memorySizeGb} GB`;
export const labelsText = (i) => Object.entries(i.labels || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—";
export const networkName = (i) => String(i.authorizedNetwork || "").split("/").pop();
export const endpoint = (i) => (i.host ? `${i.host}:${i.port}` : "—");
export const readEndpoint = (i) => (i.readEndpoint ? `${i.readEndpoint}:${i.readEndpointPort}` : "Read replicas disabled");
export const connectCommand = (i) => (i.host ? `redis-cli -h ${i.host} -p ${i.port}${i.authEnabled ? " -a <AUTH string>" : ""}` : "—");
export const persistenceLabel = (i) => {
  const p = i.persistenceConfig || {};
  if ((p.persistenceMode || "DISABLED") === "DISABLED") return "Disabled";
  return `RDB snapshot — ${snapshotPeriodLabel(p.rdbSnapshotPeriod)}`;
};
export const maintenanceWindowLabel = (i) => {
  const w = (i.maintenancePolicy?.weeklyMaintenanceWindow || [])[0];
  if (!w) return "Any time (no preference)";
  const h = String(w.startTime?.hours ?? 0).padStart(2, "0"), m = String(w.startTime?.minutes ?? 0).padStart(2, "0");
  return `${w.day.charAt(0)}${w.day.slice(1).toLowerCase()} ${h}:${m}`;
};
