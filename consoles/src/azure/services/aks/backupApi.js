/* Azure Backup for AKS over the native wire: ARM Microsoft.DataProtection (backupVaults / backupPolicies / backupInstances /
 * backup / restore / recoveryPoints / backupJobs) + the AKS runCommand action for kubectl. No bespoke /api/* call.
 * Builds the adapter the shared kube backup dashboard (consoles/src/common/kube/README.md) expects. */
import { restJson } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";
import { tokenize } from "../../../common/kube/kubectl.js";
import * as aks from "./api.js";

const AV = "2024-04-01";
const AKS_TYPE = "Microsoft.ContainerService/managedClusters";
const q = { "api-version": AV };
const base = (rg) => `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.DataProtection/backupVaults`;
const vaultPath = (rg, v) => `${base(rg)}/${encodeURIComponent(v)}`;
const get = (path) => restJson("GET", path, { query: q });
const put = (path, body) => restJson("PUT", path, { query: q, body });
const post = (path, body = {}) => restJson("POST", path, { query: q, body });

export const listVaults = async () => (await get(`/subscriptions/${getSubscription()}/providers/Microsoft.DataProtection/backupVaults`)).value || [];
const rgOf = (id) => id.split("/")[4];

/** The vault (and instance) protecting this cluster, or null. */
export async function findProtection(cluster) {
  for (const v of await listVaults()) {
    const instances = (await get(`${v.id}/backupInstances`)).value || [];
    const instance = instances.find((i) => String(i.properties?.dataSourceInfo?.resourceID).toLowerCase() === cluster.id.toLowerCase());
    if (instance) return { vault: v, instance };
  }
  return null;
}

async function poll(jobId, io, label) {
  io.print(`${label} job ${jobId.split("/").pop()} started (InProgress)...`);
  for (let i = 0; i < 60; i++) {
    await io.wait(1000);
    const j = await get(jobId);
    if (j.properties.status !== "InProgress") return j;
    io.print(`  ${label.toLowerCase()} in progress...`);
  }
  throw new Error("The job is still running; check it with: az dataprotection job list");
}

function opts(tokens) {
  const o = { _: [] };
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t === "--no-wait") o.noWait = true;
    else if (t.startsWith("--")) o[t.slice(2)] = tokens[++i];
    else if (t === "-g") o["resource-group"] = tokens[++i];
    else if (t === "-l") o.location = tokens[++i];
    else o._.push(t);
  }
  return o;
}
const need = (o, k) => { if (!o[k]) throw new Error(`az: error: the following arguments are required: --${k}`); return o[k]; };

export function makeAdapter(cluster) {
  const rgDefault = cluster.resourceGroup;
  const shown = (v) => JSON.stringify({ id: v.id, name: v.name, location: v.location, type: v.type, properties: { provisioningState: v.properties?.provisioningState, storageSettings: v.properties?.storageSettings } }, null, 2);

  async function commands(line, io) {
    const t = tokenize(line);
    if (t[0] !== "az") return false;
    if (t[1] !== "dataprotection") { io.error(`az ${t[1] || ""}: only 'az dataprotection' (Azure Backup) is simulated in this terminal; type 'help'.`); return true; }
    const group = t[2], verb = t[3];
    const o = opts(t.slice(group === "backup-instance" && verb === "restore" ? 5 : 4));
    const rg = o["resource-group"] || rgDefault;
    try {
      if (group === "backup-vault" && verb === "create") {
        const name = need(o, "vault-name");
        const loc = o.location || cluster.location;
        const instName = o["instance-name"] || "aks-cluster-instance";
        io.print(`Creating backup vault '${name}' in ${rg} (${loc})...`);
        const v = await put(vaultPath(rg, name), { location: loc, properties: { storageSettings: [{ datastoreType: "VaultStore", type: "LocallyRedundant" }] } });
        io.print(shown(v));
        io.print("Creating backup policy 'aks-default-policy' (stored; schedule rules are not executed by Vyomi)...");
        const pol = await put(`${vaultPath(rg, name)}/backupPolicies/aks-default-policy`, { properties: { objectType: "BackupPolicy", datasourceTypes: [AKS_TYPE],
          policyRules: [{ objectType: "AzureBackupRule", name: "BackupDaily", backupParameters: { objectType: "AzureBackupParams", backupType: "Incremental" } },
                        { objectType: "AzureRetentionRule", name: "Default", isDefault: true, lifecycles: [{ deleteAfter: { objectType: "AbsoluteDeleteOption", duration: "P7D" }, sourceDataStore: { dataStoreType: "OperationalStore", objectType: "DataStoreInfoBase" } }] }] } });
        io.print(`Configuring backup instance '${instName}' for cluster ${cluster.name} (vault create in this terminal also protects the cluster)...`);
        await put(`${vaultPath(rg, name)}/backupInstances/${encodeURIComponent(instName)}`, { properties: { objectType: "BackupInstance", friendlyName: instName,
          dataSourceInfo: { objectType: "Datasource", resourceID: cluster.id, resourceName: cluster.name, resourceType: AKS_TYPE, resourceLocation: cluster.location, datasourceType: AKS_TYPE }, policyInfo: { policyId: pol.id } } });
        io.print(`Vault '${name}' is ready; backup instance '${instName}' protects ${cluster.name}.`);
        return true;
      }
      if (group === "backup-vault" && (verb === "show" || verb === "list" || verb === "delete")) {
        if (verb === "list") { io.print(JSON.stringify((await listVaults()).map((v) => ({ name: v.name, location: v.location, resourceGroup: rgOf(v.id) })), null, 2)); return true; }
        const name = need(o, "vault-name");
        if (verb === "delete") { await restJson("DELETE", vaultPath(rg, name), { query: q }); io.print(`Vault '${name}' deleted.`); return true; }
        io.print(shown(await get(vaultPath(rg, name)))); return true;
      }
      if (group === "backup-instance" && verb === "list") {
        io.print(JSON.stringify(((await get(`${vaultPath(rg, need(o, "vault-name"))}/backupInstances`)).value || []).map((i) => ({ name: i.name, protectionStatus: i.properties.protectionStatus.status, dataSource: i.properties.dataSourceInfo.resourceName })), null, 2)); return true;
      }
      if (group === "recovery-point" && verb === "list") {
        const rps = (await get(`${vaultPath(rg, need(o, "vault-name"))}/backupInstances/${need(o, "backup-instance-name")}/recoveryPoints`)).value || [];
        io.print(JSON.stringify(rps.map((r) => ({ name: r.name, time: r.properties.recoveryPointTime, type: r.properties.recoveryPointType })), null, 2)); return true;
      }
      if (group === "job" && verb === "list") {
        io.print(JSON.stringify(((await get(`${vaultPath(rg, need(o, "vault-name"))}/backupJobs`)).value || []).map((j) => ({ name: j.name, operation: j.properties.operation, status: j.properties.status })), null, 2)); return true;
      }
      if (group === "backup-instance" && verb === "adhoc-backup") {
        const inst = `${vaultPath(rg, need(o, "vault-name"))}/backupInstances/${need(o, "instance-name")}`;
        const r = await post(`${inst}/backup`, { backupRuleOptions: { ruleName: o["rule-name"] || "BackupDaily", triggerOption: { retentionTagOverride: "Default" } } });
        if (o.noWait) { io.print(JSON.stringify({ jobId: r.jobId }, null, 2)); return true; }
        const j = await poll(r.jobId, io, "Backup");
        if (j.properties.status !== "Completed") { io.error(`Backup job ${j.properties.status}: ${j.properties.errorDetails?.[0]?.message || ""}`); return true; }
        const c = (await get(`${inst}/recoveryPoints/${j.properties.extendedInfo.sourceRecoverPoint.id}`)).properties;
        io.print(`Backup completed. Recovery point ${c.recoveryPointId} stored in blob container ${c.vyomiArtifact?.container} (${JSON.stringify(c.vyomiContents)}).`);
        return true;
      }
      if (group === "backup-instance" && verb === "restore" && t[4] === "trigger") {
        const inst = `${vaultPath(rg, need(o, "vault-name"))}/backupInstances/${need(o, "instance-name")}`;
        let rpid = o["recovery-point-id"];
        if (!rpid) {
          const rps = (await get(`${inst}/recoveryPoints`)).value || [];
          if (!rps.length) { io.error("No recovery points exist for this backup instance. Run: az dataprotection backup-instance adhoc-backup ..."); return true; }
          rpid = rps[0].name; io.print(`No --recovery-point-id given; using the latest: ${rpid}`);
        }
        const body = { restoreRequestObject: { objectType: "AzureBackupRecoveryPointBasedRestoreRequest", recoveryPointId: rpid, sourceDataStoreType: "VaultStore",
          restoreTargetInfo: { objectType: "RestoreTargetInfo", recoveryOption: "FailIfExists", datasourceInfo: { objectType: "Datasource", resourceID: cluster.id, datasourceType: AKS_TYPE } } } };
        await post(`${inst}/validateRestore`, body);
        io.print("Restore request validated.");
        const r = await post(`${inst}/restore`, body);
        if (o.noWait) { io.print(JSON.stringify({ jobId: r.jobId }, null, 2)); return true; }
        const j = await poll(r.jobId, io, "Restore");
        if (j.properties.status !== "Completed") io.error(`Restore job ${j.properties.status}: ${j.properties.errorDetails?.[0]?.message || ""}`);
        else io.print(`Restore completed:\n${(j.properties.extendedInfo.restoredObjects || []).join("\n")}`);
        return true;
      }
      io.error(`az dataprotection ${group || ""} ${verb || ""}: not supported by this terminal; type 'help'.`);
    } catch (e) { io.error(`ERROR: (${e.code || "Error"}) ${e.message}`); }
    return true;
  }

  return {
    cliName: "az dataprotection",
    cluster: { cloud: "azure", name: cluster.name, resourceGroup: cluster.resourceGroup, location: cluster.location, k8sVersion: cluster.k8sVersion, createdAt: cluster.createdAt },
    terminalTitle: `${cluster.name} - kubectl + az dataprotection`,
    banner: `Connected to ${cluster.name} (current context: ${cluster.name}).\nThis cluster is an EMULATED k3s-flavoured control plane running in your browser (a 64-bit k3s cannot run here): kubectl is answered through the AKS runCommand action, pods are never scheduled, and kubectl/Lens on your own machine cannot connect to it (that needs the booster).\n'az dataprotection' calls Microsoft.DataProtection over ARM. Type 'help'.\n`,
    help: [
      "az dataprotection backup-vault create --vault-name <v> [-g rg] [-l location]   create the vault (+ default policy + backup instance 'aks-cluster-instance')",
      "az dataprotection backup-vault show|list|delete --vault-name <v>",
      "az dataprotection backup-instance adhoc-backup --vault-name <v> --instance-name <i> [--no-wait]",
      "az dataprotection backup-instance restore trigger --vault-name <v> --instance-name <i> [--recovery-point-id <id>] [--no-wait]",
      "az dataprotection backup-instance list --vault-name <v>",
      "az dataprotection recovery-point list --vault-name <v> --backup-instance-name <i>",
      "az dataprotection job list --vault-name <v>",
    ],
    labels: { cluster: "AKS cluster", vault: "Backup vault", storage: "Blob container", recoveryPoints: "Recovery points" },
    kubectl: async (cmd) => { const r = await aks.runCommand(cluster.resourceGroup, cluster.name, cmd); const p = r.properties || r; return { exitCode: p.exitCode, logs: p.logs || "" }; },
    commands,
    getCluster: async () => { const c = await aks.getCluster(cluster.resourceGroup, cluster.name); const p = c.properties || {}; return { name: c.name, state: p.powerState?.code || "Running", version: p.currentKubernetesVersion || p.kubernetesVersion, location: c.location }; },
    getBackup: async () => {
      const prot = await findProtection(cluster);
      if (!prot) return { vault: null, instance: null, storage: null, recoveryPoints: [], jobs: [], note: "No vault protects this cluster yet. In the terminal: az dataprotection backup-vault create --vault-name sim-vault" };
      const { vault, instance } = prot;
      const rps = (await get(`${instance.id}/recoveryPoints`)).value || [];
      const jobs = ((await get(`${vault.id}/backupJobs`)).value || []).filter((j) => String(j.properties.dataSourceId).toLowerCase() === cluster.id.toLowerCase());
      const art = rps[0]?.properties?.vyomiArtifact;
      return { vault: { name: vault.name, state: vault.properties.provisioningState }, instance: { name: instance.name, state: instance.properties.protectionStatus.status },
        storage: { account: art?.account || "vyomiaksbackup", container: art?.container || `aksbackup-${vault.name}`, blobs: rps.filter((r) => r.properties.vyomiArtifact?.blob).length },
        recoveryPoints: rps.map((r) => ({ id: r.name, time: r.properties.recoveryPointTime, contents: Object.entries(r.properties.vyomiContents || {}).map(([k, v]) => `${v} ${k}`).join(", ") })),
        jobs: jobs.map((j) => ({ id: j.name, operation: j.properties.operation, status: j.properties.status, start: j.properties.startTime })).sort((a, b) => b.start.localeCompare(a.start)).slice(0, 8) };
    },
  };
}
