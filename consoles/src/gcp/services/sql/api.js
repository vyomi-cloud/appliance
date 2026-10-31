/* Cloud SQL over the NATIVE Cloud SQL Admin REST API v1beta4 (the same wire
 * google-cloud-sql-admin / gcloud sql / raw REST speak). Every call here is a real
 * Cloud SQL Admin API operation against /sql/v1beta4/projects/{project}/instances... */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = () => `/sql/v1beta4/projects/${e(getProject())}/instances`;

export const listInstances = async () => (await restJson("GET", base())).items || [];
export const getInstance = (name) => restJson("GET", `${base()}/${e(name)}`);
export const insertInstance = (body) => restJson("POST", base(), { body });
export const patchInstance = (name, body) => restJson("PATCH", `${base()}/${e(name)}`, { body });
export const deleteInstance = (name) => restJson("DELETE", `${base()}/${e(name)}`);
export const restartInstance = (name) => restJson("POST", `${base()}/${e(name)}:restart`);
export const stopInstance = (name) => patchInstance(name, { settings: { activationPolicy: "NEVER" } });
export const startInstance = (name) => patchInstance(name, { settings: { activationPolicy: "ALWAYS" } });

export const listDatabases = async (instance) => (await restJson("GET", `${base()}/${e(instance)}/databases`)).items || [];
export const insertDatabase = (instance, body) => restJson("POST", `${base()}/${e(instance)}/databases`, { body });
export const deleteDatabase = (instance, name) => restJson("DELETE", `${base()}/${e(instance)}/databases/${e(name)}`);

export const listUsers = async (instance) => (await restJson("GET", `${base()}/${e(instance)}/users`)).items || [];
export const insertUser = (instance, body) => restJson("POST", `${base()}/${e(instance)}/users`, { body });
export const updateUser = (instance, name, host, body) => restJson("PUT", `${base()}/${e(instance)}/users`, { query: { name, host }, body });
export const deleteUser = (instance, name, host) => restJson("DELETE", `${base()}/${e(instance)}/users`, { query: { name, host } });

export const listBackups = async (instance) => (await restJson("GET", `${base()}/${e(instance)}/backupRuns`)).items || [];
export const insertBackup = (instance, body = {}) => restJson("POST", `${base()}/${e(instance)}/backupRuns`, { body });
export const deleteBackup = (instance, id) => restJson("DELETE", `${base()}/${e(instance)}/backupRuns/${e(id)}`);
export const restoreBackup = (instance, backupId) =>
  restJson("POST", `${base()}/${e(instance)}:restoreBackup`, { body: { restoreBackupContext: { backupRunId: backupId } } });

export const listOperations = async (instance) => (await restJson("GET", `/sql/v1beta4/projects/${e(getProject())}/operations`, { query: { instance } })).items || [];

export const listReplicas = async (masterName) => (await listInstances()).filter((i) => i.masterInstanceName === masterName);
export const createReplica = (masterName, name) => insertInstance({ name, masterInstanceName: masterName });

export const ENGINES = [
  ["MySQL", "MYSQL"], ["PostgreSQL", "POSTGRES"], ["SQL Server", "SQLSERVER"],
];
export const VERSIONS = {
  MYSQL: ["MYSQL_8_4", "MYSQL_8_0", "MYSQL_5_7"],
  POSTGRES: ["POSTGRES_17", "POSTGRES_16", "POSTGRES_15", "POSTGRES_14"],
  SQLSERVER: ["SQLSERVER_2022_STANDARD", "SQLSERVER_2019_STANDARD"],
};
export const versionLabel = (v) => String(v || "").replace(/_/g, " ");
export const REGIONS = [
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"], ["us-east4", "us-east4 (Northern Virginia)"],
  ["us-west1", "us-west1 (Oregon)"], ["europe-west1", "europe-west1 (Belgium)"], ["europe-west4", "europe-west4 (Netherlands)"],
  ["asia-south1", "asia-south1 (Mumbai)"], ["asia-southeast1", "asia-southeast1 (Singapore)"], ["asia-northeast1", "asia-northeast1 (Tokyo)"],
];

export const editionLabel = () => "Enterprise";
export const stateLabel = (s) => ({ RUNNABLE: "Runnable", STOPPED: "Stopped", PENDING_CREATE: "Creating…" }[s] || s);
export const publicIp = (i) => i.ipAddresses?.find((a) => a.type === "PRIMARY")?.ipAddress || "—";
export const privateIp = (i) => i.ipAddresses?.find((a) => a.type === "PRIVATE")?.ipAddress || "—";
export const diskGb = (i) => `${i.settings?.dataDiskSizeGb ?? "10"} GB`;
