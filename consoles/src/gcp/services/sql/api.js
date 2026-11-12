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
export const restartInstance = (name) => restJson("POST", `${base()}/${e(name)}/restart`);
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
  restJson("POST", `${base()}/${e(instance)}/restoreBackup`, { body: { restoreBackupContext: { backupRunId: backupId } } });

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

// ── Connections > Security (gcp.sql.connections-security): sslMode + sslCerts ──────────
export const SSL_MODES = [
  ["ALLOW_UNENCRYPTED_AND_ENCRYPTED", "Allow unencrypted and encrypted connections"],
  ["ENCRYPTED_ONLY", "Require encrypted connections only"],
  ["TRUSTED_CLIENT_CERTIFICATE_REQUIRED", "Require trusted client certificates"],
];
export const sslModeLabel = (m) => SSL_MODES.find(([v]) => v === m)?.[1] || m;
export const setSslMode = (instance, sslMode) => patchInstance(instance, { settings: { ipConfiguration: { sslMode } } });
export const listSslCerts = async (instance) => (await restJson("GET", `${base()}/${e(instance)}/sslCerts`)).items || [];
export const insertSslCert = (instance, commonName) => restJson("POST", `${base()}/${e(instance)}/sslCerts`, { body: { commonName } });
export const deleteSslCert = (instance, fingerprint) => restJson("DELETE", `${base()}/${e(instance)}/sslCerts/${e(fingerprint)}`);

// ── Cloud SQL Studio + insights (gcp.sql.insights) — a Vyomi-added data-plane RPC next
// to the real Admin API, the same way core/azure_sql_core.py adds its own `/query` path. ──
export const runQuery = (instance, sql, opts = {}) => restJson("POST", `${base()}/${e(instance)}/query`, { body: { sql, ...opts } });
export const listTables = async (instance) => (await restJson("GET", `${base()}/${e(instance)}/tables`)).tables || [];
export const listQueries = async (instance) => (await restJson("GET", `${base()}/${e(instance)}/queries`)).items || [];
export const getMetrics = (instance) => restJson("GET", `${base()}/${e(instance)}/metrics`);
