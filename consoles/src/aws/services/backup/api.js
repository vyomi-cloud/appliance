/* AWS Backup over its native REST-JSON wire (SigV4 scope `backup`) -> core/backup_vaults_core.py. */
import { awsRest } from "../../../common/wire.js";

const R = (method, path, opts) => awsRest("backup", method, path, opts);
const enc = encodeURIComponent;

export const listVaults = () => R("GET", "/backup-vaults").then((r) => r.BackupVaultList || []);
export const getVault = (n) => R("GET", `/backup-vaults/${enc(n)}`);
export const createVault = (n, b = {}) => R("PUT", `/backup-vaults/${enc(n)}`, { body: b });
export const deleteVault = (n) => R("DELETE", `/backup-vaults/${enc(n)}`);
export const putVaultLock = (n, b) => R("PUT", `/backup-vaults/${enc(n)}/vault-lock`, { body: b });
export const deleteVaultLock = (n) => R("DELETE", `/backup-vaults/${enc(n)}/vault-lock`);
export const putVaultAccessPolicy = (n, Policy) => R("PUT", `/backup-vaults/${enc(n)}/access-policy`, { body: { Policy } });
export const getVaultAccessPolicy = (n) => R("GET", `/backup-vaults/${enc(n)}/access-policy`).catch(() => null);
export const listRecoveryPoints = (n) => R("GET", `/backup-vaults/${enc(n)}/recovery-points`).then((r) => r.RecoveryPoints || []);
export const deleteRecoveryPoint = (n, arn) => R("DELETE", `/backup-vaults/${enc(n)}/recovery-points/${arn}`);
export const getRestoreMetadata = (arn) => R("GET", `/recovery-points/${arn}/restore-metadata`);

export const listPlans = () => R("GET", "/backup/plans").then((r) => r.BackupPlansList || []);
export const getPlan = (id) => R("GET", `/backup/plans/${enc(id)}`);
export const createPlan = (BackupPlan) => R("PUT", "/backup/plans", { body: { BackupPlan } });
export const deletePlan = (id) => R("DELETE", `/backup/plans/${enc(id)}`);
export const listSelections = (id) => R("GET", `/backup/plans/${enc(id)}/selections`).then((r) => r.BackupSelectionsList || []);
export const getSelection = (id, sid) => R("GET", `/backup/plans/${enc(id)}/selections/${enc(sid)}`);
export const createSelection = (id, BackupSelection) => R("PUT", `/backup/plans/${enc(id)}/selections`, { body: { BackupSelection } });
export const deleteSelection = (id, sid) => R("DELETE", `/backup/plans/${enc(id)}/selections/${enc(sid)}`);

export const listBackupJobs = () => R("GET", "/backup-jobs").then((r) => r.BackupJobs || []);
export const startBackupJob = (b) => R("PUT", "/backup-jobs", { body: b });
export const stopBackupJob = (id) => R("POST", `/backup-jobs/${enc(id)}`);
export const listRestoreJobs = () => R("GET", "/restore-jobs").then((r) => r.RestoreJobs || []);
export const startRestoreJob = (b) => R("PUT", "/restore-jobs", { body: b });
export const listProtected = () => R("GET", "/resources").then((r) => r.Results || []);
export const supportedTypes = () => R("GET", "/supported-resource-types").then((r) => r.ResourceTypes || []);
