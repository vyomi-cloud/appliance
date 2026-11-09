/* AWS Backup for Amazon EKS + kubectl: the shared split-screen dashboard (consoles/src/common/kube) driven by the AWS Backup REST wire
 * (vaults, backup jobs, recovery points, restore jobs) and the cluster's kubectl (a Vyomi extension: EKS has no API to run kubectl). */
import { useMemo } from "react";
import BackupDashboard from "../../../common/kube/BackupDashboard.jsx";
import { MOCK_MANIFESTS, MOCK_NS } from "../../../common/kube/mockApp.js";
import { tokenize } from "../../../common/kube/kubectl.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ROLE = "arn:aws:iam::123456789012:role/service-role/AWSBackupDefaultServiceRole";
const ART_BUCKET = "vyomi-aws-backup";

// a real cluster pulls nothing from the internet offline: the mock app uses the pause image that ships inside the k3s image
const REAL_MOCK = MOCK_MANIFESTS.map((m) => (m.kind === "Deployment" ? { ...m, spec: { ...m.spec, template: { ...m.spec.template, spec: { containers: [{ name: "web", image: "rancher/mirrored-pause:3.6", imagePullPolicy: "IfNotPresent" }] } } } } : m));
const DEPLOY = `kubectl apply -f - <<'VYOMI_EOF'\n${REAL_MOCK.map((m) => JSON.stringify(m)).join("\n---\n")}\nVYOMI_EOF`;

function opts(tokens) {
  const o = {};
  for (let i = 0; i < tokens.length; i++) if (tokens[i].startsWith("--")) o[tokens[i].slice(2)] = tokens[++i];
  return o;
}
const need = (o, k) => { if (!o[k]) throw new Error(`the following arguments are required: --${k}`); return o[k]; };

function makeAdapter(cluster) {
  const arn = cluster.arn;
  const mine = (rps) => rps.filter((r) => r.ResourceArn === arn).sort((a, b) => b.CreationDate - a.CreationDate);
  async function poll(get, done, io, label) {
    for (let i = 0; i < 90; i++) {
      const j = await get();
      if (done(j)) return j;
      io.print(`  ${label} in progress...`);
      await io.wait(1000);
    }
    throw new Error(`${label} is still running`);
  }
  async function commands(line, io) {
    const t = tokenize(line);
    if (t[0] !== "aws") return false;
    if (t[1] !== "backup") { io.error(`aws ${t[1] || ""}: only 'aws backup' is available in this terminal; type 'help'.`); return true; }
    const o = opts(t.slice(3));
    try {
      switch (t[2]) {
        case "create-backup-vault": {
          const n = need(o, "backup-vault-name");
          const r = await api.createVault(n);
          io.print(JSON.stringify({ BackupVaultName: r.BackupVaultName, BackupVaultArn: r.BackupVaultArn, CreationDate: r.CreationDate }, null, 2));
          return true;
        }
        case "list-backup-vaults":
          io.print(JSON.stringify({ BackupVaultList: (await api.listVaults()).map((v) => ({ BackupVaultName: v.BackupVaultName, NumberOfRecoveryPoints: v.NumberOfRecoveryPoints })) }, null, 2));
          return true;
        case "start-backup-job": {
          const r = await api.startBackup(need(o, "backup-vault-name"), o["resource-arn"] || arn, o["iam-role-arn"] || ROLE);
          io.print(JSON.stringify(r, null, 2));
          const j = await poll(() => api.describeBackupJob(r.BackupJobId), (x) => x.State !== "RUNNING", io, "backup");
          if (j.State !== "COMPLETED") io.error(`Backup job ${j.State}: ${j.StatusMessage || ""}`);
          else io.print(`Backup job ${j.State}. Recovery point ${j.RecoveryPointArn} (${j.BackupSizeInBytes} bytes of Kubernetes objects stored in ${ART_BUCKET}).`);
          return true;
        }
        case "describe-backup-job":
          io.print(JSON.stringify(await api.describeBackupJob(need(o, "backup-job-id")), null, 2));
          return true;
        case "list-backup-jobs":
          io.print(JSON.stringify({ BackupJobs: (await api.listBackupJobs()).filter((j) => j.ResourceArn === arn).map((j) => ({ BackupJobId: j.BackupJobId, State: j.State, ResourceType: j.ResourceType })) }, null, 2));
          return true;
        case "list-recovery-points-by-resource":
          io.print(JSON.stringify({ RecoveryPoints: mine(await api.listRecoveryPointsByResource(o["resource-arn"] || arn)).map((r) => ({ RecoveryPointArn: r.RecoveryPointArn, Status: r.Status, BackupVaultName: r.BackupVaultName })) }, null, 2));
          return true;
        case "start-restore-job": {
          let rp = o["recovery-point-arn"];
          if (!rp) {
            const rps = mine(await api.listRecoveryPointsByResource(arn));
            if (!rps.length) { io.error("No recovery points exist for this cluster. Run: aws backup start-backup-job --backup-vault-name <vault>"); return true; }
            rp = rps[0].RecoveryPointArn;
            io.print(`No --recovery-point-arn given; using the latest: ${rp}`);
          }
          const md = {};
          (o.metadata || "").split(",").filter(Boolean).forEach((kv) => { const [k, ...v] = kv.split("="); md[k] = v.join("="); });
          const r = await api.startRestore(rp, o["iam-role-arn"] || ROLE, { ClusterName: cluster.name, ...md });
          io.print(JSON.stringify(r, null, 2));
          const j = await poll(() => api.describeRestoreJob(r.RestoreJobId), (x) => x.Status !== "RUNNING", io, "restore");
          if (j.Status !== "COMPLETED") io.error(`Restore job ${j.Status}: ${j.StatusMessage || ""}`);
          else io.print(`Restore job ${j.Status}; objects re-applied to ${j.CreatedResourceArn}.`);
          return true;
        }
        case "list-restore-jobs":
          io.print(JSON.stringify({ RestoreJobs: (await api.listRestoreJobs()).filter((j) => j.CreatedResourceArn === arn || j.RecoveryPointArn).map((j) => ({ RestoreJobId: j.RestoreJobId, Status: j.Status, ResourceType: j.ResourceType })) }, null, 2));
          return true;
        default:
          io.error(`aws backup ${t[2] || ""}: not supported by this terminal; type 'help'.`);
          return true;
      }
    } catch (e) { io.error(`An error occurred (${e.code || "Error"}) when calling the ${t[2]} operation: ${e.message}`); }
    return true;
  }
  return {
    cliName: "aws backup",
    terminalTitle: `${cluster.name} - kubectl + aws backup`,
    banner: `Connected to ${cluster.name}. kubectl runs inside the cluster's real k3s API server; 'aws backup' calls the AWS Backup API.\nType 'help'.\n`,
    help: [
      "aws backup create-backup-vault --backup-vault-name <v>",
      "aws backup start-backup-job --backup-vault-name <v> [--resource-arn <cluster arn>] [--iam-role-arn <arn>]    back up this cluster",
      "aws backup list-recovery-points-by-resource | list-backup-jobs | list-restore-jobs | list-backup-vaults",
      "aws backup start-restore-job [--recovery-point-arn <arn>]    restore the latest (or given) recovery point into this cluster",
      "aws backup describe-backup-job --backup-job-id <id>",
    ],
    labels: { cluster: "EKS cluster", vault: "Backup vault", storage: "Artifact bucket", recoveryPoints: "Recovery points" },
    kubectl: async (cmd) => { const r = await api.kubectl(cluster.name, cmd); return { exitCode: r.exitCode, logs: r.logs || "" }; },
    commands,
    deployCommand: DEPLOY,
    podsNote: "Pods run on the cluster's real k3s nodes.",
    getCluster: async () => { const c = await api.describeCluster(cluster.name); return { name: c.name, state: c.status === "ACTIVE" ? "Running" : c.status, version: c.version, location: c.arn.split(":")[3] }; },
    getBackup: async () => {
      const [vaults, jobs, rjobs] = await Promise.all([api.listVaults(), api.listBackupJobs(), api.listRestoreJobs()]);
      const rps = mine(await api.listRecoveryPointsByResource(arn).catch(() => []));
      const vault = vaults.find((v) => v.BackupVaultName === rps[0]?.BackupVaultName) || vaults[0];
      const myJobs = jobs.filter((j) => j.ResourceArn === arn).map((j) => ({ id: j.BackupJobId, operation: "Backup", status: j.State, start: new Date(j.CreationDate * 1000).toISOString() }));
      const myRestores = rjobs.filter((j) => j.CreatedResourceArn === arn).map((j) => ({ id: j.RestoreJobId, operation: "Restore", status: j.Status, start: new Date(j.CreationDate * 1000).toISOString() }));
      return {
        vault: vault ? { name: vault.BackupVaultName, state: "Available" } : null, instance: null,
        storage: rps.length ? { account: "simulator S3", container: ART_BUCKET, blobs: rps.length } : null,
        recoveryPoints: rps.map((r) => ({ id: r.RecoveryPointArn.split(":").pop(), time: new Date(r.CreationDate * 1000).toISOString(), contents: `${r.BackupSizeInBytes} bytes in vault ${r.BackupVaultName}` })),
        jobs: [...myJobs, ...myRestores].sort((a, b) => b.start.localeCompare(a.start)).slice(0, 8),
        note: vault ? undefined : "No vault yet. In the terminal: aws backup create-backup-vault --backup-vault-name eks-vault",
      };
    },
  };
}

export default function BackupTab({ cluster }) {
  const adapter = useMemo(() => {
    const ad = makeAdapter(cluster);
    ad.footer = (
      <CapabilityContainer id="eks.backup" title="What AWS Backup for EKS captures">
        <div style={{ fontSize: 12.5 }}>User namespaces and their namespaced objects, read from the real API server and stored as a JSON artifact in the simulator's S3. Persistent-volume data is not captured.</div>
      </CapabilityContainer>
    );
    return ad;
  }, [cluster.arn]);
  if (cluster.status !== "ACTIVE") return <div className="vk-card" data-testid="backup-wait" style={{ padding: 12 }}>The cluster is {cluster.status}; the terminal and backup tools are available once it is ACTIVE.</div>;
  return (
    <CapabilityContainer id="eks.kubectl" title="kubectl terminal and AWS Backup">
      <BackupDashboard adapter={adapter} />
    </CapabilityContainer>
  );
}
