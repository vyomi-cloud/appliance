/* Azure Container Apps over the native ARM wire:
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/managedEnvironments/{name}
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/containerApps/{name}
 *   /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/jobs/{name}
 * Served by the same ARM core on every substrate (core/azure_app_core.py via
 * core/azure_arm_core.py), so whatever the console creates an azure-mgmt-appcontainers /
 * `az containerapp` SDK sees, and the reverse. Locks, diagnostic settings, role assignments
 * and the activity log are real ARM extension resources handled generically by
 * core/azure_arm_core.py for ANY resource type (the same engine App Service/Service Bus use). */
import { restJson } from "../../../common/wire.js";
import { armType, DEFAULT_RG, getSubscription, parseId } from "../../kit/arm.js";

export const API_VERSION = "2024-03-01";
export const ENVIRONMENTS = armType("Microsoft.App", "managedEnvironments", API_VERSION);
export const APPS = armType("Microsoft.App", "containerApps", API_VERSION);
export const JOBS = armType("Microsoft.App", "jobs", API_VERSION);
const WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");

const shape = (r) => ({ ...r, resourceGroup: parseId(r.id).resourceGroup });

// ── environments ────────────────────────────────────────────────────────────────────────
export const listEnvironments = async () => (await ENVIRONMENTS.list()).map(shape);
export const getEnvironment = async (rg, name) => shape(await ENVIRONMENTS.get(rg, name));
export const createEnvironment = (rg, name, body) => ENVIRONMENTS.put(rg, name, body);
export const updateEnvironmentTags = (rg, name, tags, env) => ENVIRONMENTS.put(rg, name, { ...env, tags });
export const deleteEnvironment = (rg, name) => ENVIRONMENTS.remove(rg, name);

const envChild = (rg, name, ctype) => `${ENVIRONMENTS.path(rg, name)}/${ctype}`;
export const listDaprComponents = async (rg, name) => (await restJson("GET", envChild(rg, name, "daprComponents"), { query: { "api-version": API_VERSION } })).value || [];
export const putDaprComponent = (rg, name, comp, body) => restJson("PUT", `${envChild(rg, name, "daprComponents")}/${encodeURIComponent(comp)}`, { query: { "api-version": API_VERSION }, body });
export const deleteDaprComponent = (rg, name, comp) => restJson("DELETE", `${envChild(rg, name, "daprComponents")}/${encodeURIComponent(comp)}`, { query: { "api-version": API_VERSION } });

export const listCertificates = async (rg, name) => (await restJson("GET", envChild(rg, name, "certificates"), { query: { "api-version": API_VERSION } })).value || [];
export const putCertificate = (rg, name, cert, body) => restJson("PUT", `${envChild(rg, name, "certificates")}/${encodeURIComponent(cert)}`, { query: { "api-version": API_VERSION }, body });
export const deleteCertificate = (rg, name, cert) => restJson("DELETE", `${envChild(rg, name, "certificates")}/${encodeURIComponent(cert)}`, { query: { "api-version": API_VERSION } });

export const listWorkloadProfileStates = async (rg, name) => (await restJson("GET", envChild(rg, name, "workloadProfileStates"), { query: { "api-version": API_VERSION } })).value || [];
export const updateWorkloadProfiles = (rg, name, env, profiles) => ENVIRONMENTS.put(rg, name, { ...env, properties: { ...env.properties, workloadProfiles: profiles } });

// ── container apps ──────────────────────────────────────────────────────────────────────
export const listApps = async () => (await APPS.list()).map(shape);
export const getApp = async (rg, name) => shape(await APPS.get(rg, name));
export const createApp = (rg, name, body) => APPS.put(rg, name, body);
export const updateApp = (rg, name, body) => APPS.put(rg, name, body);
export const updateAppTags = (rg, name, tags) => APPS.patch(rg, name, { tags });
export const updateAppIdentity = (rg, name, identity) => APPS.patch(rg, name, { identity });
export const deleteApp = (rg, name) => APPS.remove(rg, name);
export const startApp = (rg, name) => APPS.action(rg, name, "start");
export const stopApp = (rg, name) => APPS.action(rg, name, "stop");
export const listAppSecretValues = async (rg, name) => (await APPS.action(rg, name, "listSecrets")).value || [];
export const validateCustomHostname = (rg, name, hostname) => APPS.action(rg, name, "listCustomHostNameAnalysis", { customHostname: hostname });

const revPath = (rg, name, rev) => `${APPS.path(rg, name)}/revisions${rev ? `/${encodeURIComponent(rev)}` : ""}`;
export const listRevisions = async (rg, name) => (await restJson("GET", revPath(rg, name), { query: { "api-version": API_VERSION } })).value || [];
export const getRevision = (rg, name, rev) => restJson("GET", revPath(rg, name, rev), { query: { "api-version": API_VERSION } });
export const activateRevision = (rg, name, rev) => restJson("POST", `${revPath(rg, name, rev)}/activate`, { query: { "api-version": API_VERSION } });
export const deactivateRevision = (rg, name, rev) => restJson("POST", `${revPath(rg, name, rev)}/deactivate`, { query: { "api-version": API_VERSION } });
export const restartRevision = (rg, name, rev) => restJson("POST", `${revPath(rg, name, rev)}/restart`, { query: { "api-version": API_VERSION } });
export const listReplicas = async (rg, name, rev) => (await restJson("GET", `${revPath(rg, name, rev)}/replicas`, { query: { "api-version": API_VERSION } })).value || [];

export const listAuthConfigs = async (rg, name) => (await restJson("GET", `${APPS.path(rg, name)}/authConfigs`, { query: { "api-version": API_VERSION } })).value || [];
export const putAuthConfig = (rg, name, cfg, body) => restJson("PUT", `${APPS.path(rg, name)}/authConfigs/${encodeURIComponent(cfg)}`, { query: { "api-version": API_VERSION }, body });

// ── jobs ─────────────────────────────────────────────────────────────────────────────────
export const listJobs = async () => (await JOBS.list()).map(shape);
export const getJob = async (rg, name) => shape(await JOBS.get(rg, name));
export const createJob = (rg, name, body) => JOBS.put(rg, name, body);
export const deleteJob = (rg, name) => JOBS.remove(rg, name);
export const startJob = (rg, name, body) => JOBS.action(rg, name, "start", body || {});
export const stopJob = (rg, name) => JOBS.action(rg, name, "stop");
export const updateJobTags = (rg, name, tags) => JOBS.patch(rg, name, { tags });
export const listJobSecretValues = async (rg, name) => (await JOBS.action(rg, name, "listSecrets")).value || [];
const execPath = (rg, name, exec) => `${JOBS.path(rg, name)}/executions${exec ? `/${encodeURIComponent(exec)}` : ""}`;
export const listExecutions = async (rg, name) => (await restJson("GET", execPath(rg, name), { query: { "api-version": API_VERSION } })).value || [];
export const stopExecution = (rg, name, exec) => restJson("POST", `${execPath(rg, name, exec)}/stop`, { query: { "api-version": API_VERSION } });

// ── generic ARM extension resources (locks, diagnostic settings, IAM, activity log, export) ──
// Same engine every other Azure blade (App Service, Service Bus, ...) uses: resPath is the
// resource's own ARM id (APPS.path(rg,name) / ENVIRONMENTS.path / JOBS.path), re-entering
// "providers" for the extension namespace, generic over every catalog type.
const LOCKS_API = "2020-05-01";
const locksPath = (resPath) => `${resPath}/providers/Microsoft.Authorization/locks`;
export const listLocks = async (resPath) => (await restJson("GET", locksPath(resPath), { query: { "api-version": LOCKS_API } })).value || [];
export const addLock = (resPath, lockName, level, notes) => restJson("PUT", `${locksPath(resPath)}/${encodeURIComponent(lockName)}`, { query: { "api-version": LOCKS_API }, body: { properties: { level, notes } } });
export const removeLock = (resPath, lockName) => restJson("DELETE", `${locksPath(resPath)}/${encodeURIComponent(lockName)}`, { query: { "api-version": LOCKS_API } });

const DIAG_API = "2021-05-01-preview";
const diagPath = (resPath) => `${resPath}/providers/Microsoft.Insights/diagnosticSettings`;
export const listDiagnosticSettings = async (resPath) => (await restJson("GET", diagPath(resPath), { query: { "api-version": DIAG_API } })).value || [];
export const putDiagnosticSetting = (resPath, dsName, body) => restJson("PUT", `${diagPath(resPath)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API }, body });
export const deleteDiagnosticSetting = (resPath, dsName) => restJson("DELETE", `${diagPath(resPath)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API } });
export const listWorkspaces = async () => (await WORKSPACES.list()).map((w) => ({ ...w, resourceGroup: parseId(w.id).resourceGroup }));

const AUTHZ_API = "2022-04-01";
export const listRoleAssignments = async (resPath) => (await restJson("GET", `${resPath}/providers/Microsoft.Authorization/roleAssignments`, { query: { "api-version": AUTHZ_API } })).value || [];
export const listRoleDefinitions = async () => (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Authorization/roleDefinitions`, { query: { "api-version": AUTHZ_API } })).value || [];

export const listActivityLog = async (resPath) => (await restJson(
  "GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`,
  { query: { "api-version": "2015-04-01", "$filter": `resourceUri eq '${resPath}'` } },
)).value || [];

// ── labels / helpers ─────────────────────────────────────────────────────────────────────
export const CPU_CHOICES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3, 3.25, 3.5, 3.75, 4];
export const memFor = (cpu) => `${cpu * 2}Gi`;
export const envName = (envId = "") => envId.split("/").pop();
export const fmtDuration = (v) => (v ? String(v) : "--");

export { DEFAULT_RG };
