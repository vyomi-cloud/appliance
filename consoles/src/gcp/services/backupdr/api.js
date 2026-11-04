/* Backup and DR over the NATIVE backupdr.googleapis.com v1 REST API (core/gcp_backupdr_core.py). */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
export const DEFAULT_REGION = "us-central1";
const base = (region = DEFAULT_REGION) => `/v1/projects/${e(getProject())}/locations/${e(region)}`;
export const tail = (name) => String(name || "").split("/").pop();
export const regionOf = (name) => String(name || "").split("/")[3];
const unwrap = (op) => op?.response || op;

export const listVaults = async () => (await restJson("GET", `${base("-")}/backupVaults`)).backupVaults || [];
export const createVault = (id, body, r = DEFAULT_REGION) => restJson("POST", `${base(r)}/backupVaults`, { query: { backupVaultId: id }, body });
export const deleteVault = (name, force) => restJson("DELETE", `/v1/${name}`, { query: force ? { force: "true" } : {} });
export const listPlans = async () => (await restJson("GET", `${base("-")}/backupPlans`)).backupPlans || [];
export const createPlan = (id, body, r = DEFAULT_REGION) => restJson("POST", `${base(r)}/backupPlans`, { query: { backupPlanId: id }, body });
export const deletePlan = (name) => restJson("DELETE", `/v1/${name}`);
export const listAssociations = async () => (await restJson("GET", `${base("-")}/backupPlanAssociations`)).backupPlanAssociations || [];
export const createAssociation = (id, body, r = DEFAULT_REGION) => restJson("POST", `${base(r)}/backupPlanAssociations`, { query: { backupPlanAssociationId: id }, body });
export const deleteAssociation = (name) => restJson("DELETE", `/v1/${name}`);
export const triggerBackup = (assocName, ruleId) => restJson("POST", `/v1/${assocName}:triggerBackup`, { body: { ruleId } });
export const listDataSources = async (vault) => (await restJson("GET", `/v1/${vault}/dataSources`)).dataSources || [];
export const listBackups = async (ds) => (await restJson("GET", `/v1/${ds}/backups`)).backups || [];
export const deleteBackup = (name) => restJson("DELETE", `/v1/${name}`);
export const restoreBackup = (name, body) => restJson("POST", `/v1/${name}:restore`, { body });
export const listAllBackups = async () => {
  const out = [];
  for (const v of await listVaults()) for (const ds of await listDataSources(v.name)) for (const b of await listBackups(ds.name)) out.push(b);
  return out.sort((a, b) => String(b.createTime).localeCompare(String(a.createTime)));
};
export { unwrap };
