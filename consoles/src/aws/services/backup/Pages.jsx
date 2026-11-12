/* AWS Backup console: dashboard, vaults (+detail: recovery points, access policy, vault lock), backup plans (+rules, resource
 * assignments), jobs, restore jobs, protected resources, restore wizard. Everything is a real call on the backup wire. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate, useRoute } from "../../../common/router.js";
import * as api from "./api.js";

const ROLE = "arn:aws:iam::123456789012:role/service-role/AWSBackupDefaultServiceRole";
const stat = (s) => <StatusIndicator type={/COMPLETED/.test(s) ? "success" : /FAILED|EXPIRED/.test(s) ? "error" : /ABORT/.test(s) ? "stopped" : "in-progress"}>{s}</StatusIndicator>;

/* ── Dashboard ─────────────────────────────────────────────────────────────── */
export function Dashboard() {
  const v = useAsync(() => api.listVaults(), []);
  const p = useAsync(() => api.listPlans(), []);
  const j = useAsync(() => api.listBackupJobs(), []);
  const r = useAsync(() => api.listRestoreJobs(), []);
  const pr = useAsync(() => api.listProtected(), []);
  const n = (x) => (x.data ? x.data.length : "-");
  const jobs = j.data || [];
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button variant="primary" onClick={() => navigate("backup", "create-plan")}>Create backup plan</Button>}>AWS Backup dashboard</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Summary</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            {[["Backup plans", n(p), "plans"], ["Backup vaults", n(v), "vaults"], ["Protected resources", n(pr), "protected-resources"], ["Restore jobs", n(r), "restore-jobs"]].map(([l, c, route]) => (
              <div key={l}><Box variant="awsui-key-label">{l}</Box><Box variant="awsui-value-large"><Link href={`#/backup/${route}`} onFollow={follow}>{c}</Link></Box></div>))}
          </ColumnLayout>
        </Container>
        <Container header={<Header variant="h2" description="Backup jobs in this Region">Job status</Header>}>
          <ColumnLayout columns={4} variant="text-grid">
            {["COMPLETED", "RUNNING", "FAILED", "ABORTED"].map((s) => (
              <div key={s}><Box variant="awsui-key-label">{stat(s)}</Box><Box variant="awsui-value-large">{jobs.filter((x) => x.State === s).length}</Box></div>))}
          </ColumnLayout>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}

/* ── Vaults ────────────────────────────────────────────────────────────────── */
export function Vaults() {
  const notify = useNotify();
  const t = useAsync(() => api.listVaults(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [err, setErr] = useState(null);
  return (
    <>
      <ResourceTable resourceName="Backup vaults" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload}
        trackBy="BackupVaultName" selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search backup vaults"
        empty={{ title: "No backup vaults" }}
        columns={[
          { id: "n", header: "Backup vault name", isRowHeader: true, sortingField: "BackupVaultName", cell: (v) => <Link href={`#/backup/vaults/view?name=${encodeURIComponent(v.BackupVaultName)}`} onFollow={follow}>{v.BackupVaultName}</Link> },
          { id: "rp", header: "Recovery points", cell: (v) => v.NumberOfRecoveryPoints },
          { id: "lock", header: "Vault Lock", cell: (v) => (v.Locked ? <StatusIndicator type="success">Locked</StatusIndicator> : "Not locked") },
          { id: "k", header: "Encryption key", cell: (v) => (v.EncryptionKeyArn || "").split("/").pop() },
          { id: "c", header: "Creation date", cell: (v) => fmtDate(v.CreationDate) },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length || sel[0].BackupVaultName === "Default"} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => { setErr(null); setCreate(true); }}>Create backup vault</Button>
        </SpaceBetween>} />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Create backup vault"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await api.createVault(name); notify.success(`Created backup vault "${name}".`); setCreate(false); setName(""); t.reload(); } catch (e) { setErr(e); } }}>Create backup vault</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Backup vault name" description="2-50 characters: letters, digits, hyphens and underscores."><Input value={name} onChange={({ detail }) => setName(detail.value)} /></FormField></SpaceBetween>
      </Modal>
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="backup vault" names={sel.map((v) => v.BackupVaultName)}
        onConfirm={async () => { await api.deleteVault(sel[0].BackupVaultName); notify.success("Deleted backup vault."); setSel([]); t.reload(); }} />
    </>
  );
}

function RestoreModal({ rp, onDismiss, onDone }) {
  const notify = useNotify();
  const md = useAsync(() => (rp ? api.getRestoreMetadata(rp.RecoveryPointArn) : Promise.resolve(null)), [rp?.RecoveryPointArn]);
  const [vals, setVals] = useState({});
  const [err, setErr] = useState(null);
  const meta = { ...(md.data?.RestoreMetadata || {}), ...vals };
  return (
    <Modal visible={!!rp} onDismiss={onDismiss} size="large" header="Restore backup"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" onClick={async () => {
          try { const r = await api.startRestoreJob({ RecoveryPointArn: rp.RecoveryPointArn, IamRoleArn: ROLE, Metadata: meta, ResourceType: rp.ResourceType });
            notify.success(`Restore job ${r.RestoreJobId} started.`); onDismiss(); onDone?.(); } catch (e) { setErr(e); } }}>Restore backup</Button></SpaceBetween></Box>}>
      {rp && <SpaceBetween size="m"><ErrorAlert error={err} />
        <KeyValue columns={2} items={[["Recovery point ARN", rp.RecoveryPointArn], ["Resource type", rp.ResourceType], ["Resource", rp.ResourceName], ["Size", fmtBytes(rp.BackupSizeInBytes)]]} />
        <Container header={<Header variant="h3">Restore settings</Header>}><SpaceBetween size="s">
          {Object.entries(md.data?.RestoreMetadata || {}).map(([k, d]) => (
            <FormField key={k} label={k}><Input value={meta[k] ?? ""} onChange={({ detail }) => setVals((o) => ({ ...o, [k]: detail.value }))} /></FormField>))}
        </SpaceBetween></Container></SpaceBetween>}
    </Modal>
  );
}

const rpCols = (vault) => [
  { id: "a", header: "Recovery point", isRowHeader: true, cell: (r) => r.RecoveryPointArn.split(":").slice(-1)[0].slice(-24) },
  { id: "r", header: "Resource", cell: (r) => r.ResourceName },
  { id: "t", header: "Resource type", cell: (r) => r.ResourceType },
  { id: "s", header: "Status", cell: (r) => stat(r.Status) },
  { id: "z", header: "Size", cell: (r) => fmtBytes(r.BackupSizeInBytes) },
  { id: "c", header: "Created", cell: (r) => fmtDate(r.CreationDate) },
  { id: "e", header: "Expiry", cell: (r) => fmtDate(r.CalculatedLifecycle?.DeleteAt) || "Never" },
];

export function VaultDetail() {
  const notify = useNotify();
  const { query } = useRoute();
  const name = query.name;
  const v = useAsync(() => api.getVault(name), [name]);
  const rps = useAsync(() => api.listRecoveryPoints(name), [name]);
  const pol = useAsync(() => api.getVaultAccessPolicy(name), [name]);
  const [sel, setSel] = useState([]);
  const [restore, setRestore] = useState(null);
  const [del, setDel] = useState(false);
  const [lock, setLock] = useState(false);
  const [lk, setLk] = useState({ min: "7", max: "365", days: "" });
  const [policy, setPolicy] = useState(null);
  const [err, setErr] = useState(null);
  const [onDemand, setOnDemand] = useState(false);
  const [od, setOd] = useState({ arn: "", ttl: "" });
  const x = v.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => { v.reload(); rps.reload(); }}>Refresh</Button>}>{name}</Header>}>
      <SpaceBetween size="l">
        <ErrorAlert error={v.error} />
        {x && <KeyValue title="Details" items={[["Backup vault ARN", x.BackupVaultArn], ["Encryption key", x.EncryptionKeyArn], ["Recovery points", x.NumberOfRecoveryPoints],
          ["Vault Lock", x.Locked ? `Locked - retention ${x.MinRetentionDays ?? "-"} to ${x.MaxRetentionDays ?? "-"} days${x.LockDate ? `, compliance from ${fmtDate(x.LockDate)}` : " (governance)"}` : "Not locked"], ["Creation date", fmtDate(x.CreationDate)]]} />}
        <Tabs tabs={[
          { id: "rp", label: "Recovery points", content: (
            <ResourceTable resourceName="Recovery points" items={rps.data || []} loading={rps.loading} error={rps.error} onRefresh={rps.reload} trackBy="RecoveryPointArn"
              selectionType="single" selectedItems={sel} onSelectionChange={setSel} columns={rpCols(name)} empty={{ title: "No recovery points" }}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={!sel.length} onClick={() => setRestore(sel[0])}>Restore</Button>
                <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
                <Button variant="primary" onClick={() => { setErr(null); setOnDemand(true); }}>Create on-demand backup</Button></SpaceBetween>} />) },
          { id: "lock", label: "Vault Lock", content: (
            <Container header={<Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs">
              {x?.Locked && <Button onClick={async () => { try { await api.deleteVaultLock(name); notify.success("Vault Lock removed."); v.reload(); } catch (e) { notify.error(e); } }}>Remove lock</Button>}
              <Button variant="primary" onClick={() => { setErr(null); setLock(true); }}>{x?.Locked ? "Update Vault Lock" : "Create Vault Lock"}</Button></SpaceBetween>}>Vault Lock</Header>}>
              {x?.Locked ? `Locked. Min retention ${x.MinRetentionDays ?? "-"} days, max ${x.MaxRetentionDays ?? "-"} days.` : "Vault Lock is not configured. Recovery points can be deleted at any time."}
            </Container>) },
          { id: "pol", label: "Access policy", content: (
            <Container header={<Header variant="h2" actions={<Button onClick={() => setPolicy(pol.data?.Policy || '{"Version":"2012-10-17","Statement":[]}')}>Edit policy</Button>}>Backup vault access policy</Header>}>
              <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{pol.data?.Policy || "No access policy is set on this vault."}</pre></Box></Container>) },
        ]} />
      </SpaceBetween>
      <RestoreModal rp={restore} onDismiss={() => setRestore(null)} onDone={() => navigate("backup", "restore-jobs")} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="recovery point" names={["delete"]} confirmText="delete"
        onConfirm={async () => { await api.deleteRecoveryPoint(name, sel[0].RecoveryPointArn); notify.success("Recovery point deleted."); setSel([]); rps.reload(); v.reload(); }} />
      <Modal visible={lock} onDismiss={() => setLock(false)} header="Vault Lock"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setLock(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try {
            await api.putVaultLock(name, { MinRetentionDays: Number(lk.min) || undefined, MaxRetentionDays: Number(lk.max) || undefined, ...(lk.days ? { ChangeableForDays: Number(lk.days) } : {}) });
            notify.success("Vault Lock updated."); setLock(false); v.reload(); } catch (e) { setErr(e); } }}>Save</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Minimum retention (days)"><Input value={lk.min} onChange={({ detail }) => setLk({ ...lk, min: detail.value })} /></FormField>
          <FormField label="Maximum retention (days)"><Input value={lk.max} onChange={({ detail }) => setLk({ ...lk, max: detail.value })} /></FormField>
          <FormField label="Lock in compliance mode after (days)" description="Leave empty for governance mode (lock can still be removed). 3-365 days enables compliance mode."><Input value={lk.days} onChange={({ detail }) => setLk({ ...lk, days: detail.value })} /></FormField></SpaceBetween>
      </Modal>
      <Modal visible={policy !== null} onDismiss={() => setPolicy(null)} size="large" header="Edit access policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setPolicy(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try { await api.putVaultAccessPolicy(name, policy); notify.success("Access policy saved."); setPolicy(null); pol.reload(); } catch (e) { notify.error(e); } }}>Save policy</Button></SpaceBetween></Box>}>
        <Textarea rows={12} value={policy || ""} onChange={({ detail }) => setPolicy(detail.value)} spellcheck={false} /></Modal>
      <Modal visible={onDemand} onDismiss={() => setOnDemand(false)} header="Create on-demand backup"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setOnDemand(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try {
            await api.startBackupJob({ BackupVaultName: name, ResourceArn: od.arn, IamRoleArn: ROLE, ...(od.ttl ? { Lifecycle: { DeleteAfterDays: Number(od.ttl) } } : {}) });
            notify.success("Backup job started."); setOnDemand(false); rps.reload(); v.reload(); } catch (e) { setErr(e); } }}>Create on-demand backup</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Resource ARN" description="DynamoDB table, RDS instance, S3 bucket or EBS volume ARN."><Input value={od.arn} onChange={({ detail }) => setOd({ ...od, arn: detail.value })} placeholder="arn:aws:dynamodb:us-east-1:123456789012:table/my-table" /></FormField>
          <FormField label="Retention (days, optional)"><Input value={od.ttl} onChange={({ detail }) => setOd({ ...od, ttl: detail.value })} /></FormField></SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

/* ── Plans ─────────────────────────────────────────────────────────────────── */
export function Plans() {
  const notify = useNotify();
  const t = useAsync(() => api.listPlans(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  return (
    <>
      <ResourceTable resourceName="Backup plans" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="BackupPlanId"
        selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search backup plans" empty={{ title: "No backup plans", action: <Button onClick={() => navigate("backup", "create-plan")}>Create backup plan</Button> }}
        columns={[
          { id: "n", header: "Backup plan", isRowHeader: true, sortingField: "BackupPlanName", cell: (p) => <Link href={`#/backup/plans/view?id=${p.BackupPlanId}`} onFollow={follow}>{p.BackupPlanName}</Link> },
          { id: "i", header: "Backup plan ID", cell: (p) => p.BackupPlanId },
          { id: "c", header: "Creation date", cell: (p) => fmtDate(p.CreationDate) },
        ]}
        actions={<SpaceBetween direction="horizontal" size="xs"><Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => navigate("backup", "create-plan")}>Create backup plan</Button></SpaceBetween>} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="backup plan" names={sel.map((p) => p.BackupPlanName)}
        onConfirm={async () => { await api.deletePlan(sel[0].BackupPlanId); notify.success("Deleted backup plan."); setSel([]); t.reload(); }} />
    </>
  );
}

export function CreatePlan() {
  const notify = useNotify();
  const vaults = useAsync(() => api.listVaults(), []);
  const [f, setF] = useState({ name: "", rule: "DailyBackups", vault: "Default", schedule: "cron(0 5 ? * * *)", start: "480", comp: "10080", del: "35", cold: "" });
  const [err, setErr] = useState(null);
  const set = (k) => ({ detail }) => setF((o) => ({ ...o, [k]: detail.value }));
  const go = async () => {
    setErr(null);
    try {
      const lc = { ...(f.del ? { DeleteAfterDays: Number(f.del) } : {}), ...(f.cold ? { MoveToColdStorageAfterDays: Number(f.cold) } : {}) };
      const r = await api.createPlan({ BackupPlanName: f.name, Rules: [{ RuleName: f.rule, TargetBackupVaultName: f.vault, ScheduleExpression: f.schedule,
        StartWindowMinutes: Number(f.start), CompletionWindowMinutes: Number(f.comp), ...(Object.keys(lc).length ? { Lifecycle: lc } : {}) }] });
      notify.success(`Backup plan "${f.name}" created.`);
      location.hash = `#/backup/plans/view?id=${r.BackupPlanId}`;
    } catch (e) { setErr(e); }
  };
  return (
    <ContentLayout header={<Header variant="h1">Create Backup plan</Header>}>
      <SpaceBetween size="l"><ErrorAlert error={err} />
        <Container header={<Header variant="h2">Backup plan name</Header>}><FormField label="Backup plan name"><Input value={f.name} onChange={set("name")} ariaLabel="Backup plan name" /></FormField></Container>
        <Container header={<Header variant="h2">Backup rule configuration</Header>}><SpaceBetween size="m">
          <FormField label="Backup rule name"><Input value={f.rule} onChange={set("rule")} /></FormField>
          <FormField label="Backup vault"><Select selectedOption={{ label: f.vault, value: f.vault }} onChange={({ detail }) => setF((o) => ({ ...o, vault: detail.selectedOption.value }))}
            options={(vaults.data || []).map((v) => ({ label: v.BackupVaultName, value: v.BackupVaultName }))} /></FormField>
          <FormField label="Schedule expression" description="cron(...) or rate(...)"><Input value={f.schedule} onChange={set("schedule")} /></FormField>
          <ColumnLayout columns={2}>
            <FormField label="Start within (minutes)"><Input value={f.start} onChange={set("start")} /></FormField>
            <FormField label="Complete within (minutes)"><Input value={f.comp} onChange={set("comp")} /></FormField>
            <FormField label="Transition to cold storage after (days)"><Input value={f.cold} onChange={set("cold")} /></FormField>
            <FormField label="Retention - delete after (days)"><Input value={f.del} onChange={set("del")} /></FormField></ColumnLayout>
        </SpaceBetween></Container>
        <Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" href="#/backup/plans" onFollow={follow}>Cancel</Button><Button variant="primary" onClick={go}>Create plan</Button></SpaceBetween></Box>
      </SpaceBetween>
    </ContentLayout>
  );
}

export function PlanDetail() {
  const notify = useNotify();
  const { query } = useRoute();
  const id = query.id;
  const p = useAsync(() => api.getPlan(id), [id]);
  const s = useAsync(() => api.listSelections(id), [id]);
  const [sel, setSel] = useState([]);
  const [assign, setAssign] = useState(false);
  const [a, setA] = useState({ name: "", arn: "", tagK: "", tagV: "" });
  const [err, setErr] = useState(null);
  const plan = p.data?.BackupPlan;
  return (
    <ContentLayout header={<Header variant="h1">{plan?.BackupPlanName || id}</Header>}>
      <SpaceBetween size="l"><ErrorAlert error={p.error} />
        {p.data && <KeyValue title="Details" items={[["Backup plan ARN", p.data.BackupPlanArn], ["Backup plan ID", id], ["Version ID", p.data.VersionId], ["Creation date", fmtDate(p.data.CreationDate)]]} />}
        <Table variant="container" header={<Header variant="h2" counter={`(${plan?.Rules?.length || 0})`}>Backup rules</Header>} items={plan?.Rules || []} trackBy="RuleId"
          columnDefinitions={[{ id: "n", header: "Rule name", cell: (r) => r.RuleName }, { id: "v", header: "Backup vault", cell: (r) => r.TargetBackupVaultName },
            { id: "s", header: "Frequency", cell: (r) => r.ScheduleExpression }, { id: "w", header: "Start / complete window", cell: (r) => `${r.StartWindowMinutes} / ${r.CompletionWindowMinutes} min` },
            { id: "l", header: "Retention", cell: (r) => (r.Lifecycle?.DeleteAfterDays ? `${r.Lifecycle.DeleteAfterDays} days` : "Forever") }]} />
        <Table variant="container" header={<Header variant="h2" counter={`(${(s.data || []).length})`} actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={async () => { try { await api.deleteSelection(id, sel[0].SelectionId); notify.success("Resource assignment deleted."); setSel([]); s.reload(); } catch (e) { notify.error(e); } }}>Delete</Button>
          <Button variant="primary" onClick={() => { setErr(null); setAssign(true); }}>Assign resources</Button></SpaceBetween>}>Resource assignments</Header>}
          items={s.data || []} trackBy="SelectionId" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          columnDefinitions={[{ id: "n", header: "Assignment name", cell: (x) => x.SelectionName }, { id: "r", header: "IAM role", cell: (x) => x.IamRoleArn }, { id: "c", header: "Created", cell: (x) => fmtDate(x.CreationDate) }]}
          empty={<Box textAlign="center">No resource assignments</Box>} />
      </SpaceBetween>
      <Modal visible={assign} onDismiss={() => setAssign(false)} header="Assign resources"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setAssign(false)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { try {
            await api.createSelection(id, { SelectionName: a.name, IamRoleArn: ROLE, ...(a.arn ? { Resources: [a.arn] } : {}), ...(a.tagK ? { ListOfTags: [{ ConditionType: "STRINGEQUALS", ConditionKey: a.tagK, ConditionValue: a.tagV }] } : {}) });
            notify.success("Resources assigned."); setAssign(false); s.reload(); } catch (e) { setErr(e); } }}>Assign resources</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Resource assignment name"><Input value={a.name} onChange={({ detail }) => setA({ ...a, name: detail.value })} /></FormField>
          <FormField label="Resource ARN"><Input value={a.arn} onChange={({ detail }) => setA({ ...a, arn: detail.value })} /></FormField>
          <ColumnLayout columns={2}><FormField label="Or tag key"><Input value={a.tagK} onChange={({ detail }) => setA({ ...a, tagK: detail.value })} /></FormField>
            <FormField label="Tag value"><Input value={a.tagV} onChange={({ detail }) => setA({ ...a, tagV: detail.value })} /></FormField></ColumnLayout></SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

/* ── Jobs / protected resources ───────────────────────────────────────────── */
export function Jobs() {
  const notify = useNotify();
  const t = useAsync(() => api.listBackupJobs(), []);
  const [sel, setSel] = useState([]);
  return (
    <ResourceTable resourceName="Backup jobs" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="BackupJobId"
      selectionType="single" selectedItems={sel} onSelectionChange={setSel} filterPlaceholder="Search backup jobs" empty={{ title: "No backup jobs" }}
      columns={[{ id: "i", header: "Backup job ID", isRowHeader: true, cell: (j) => j.BackupJobId }, { id: "s", header: "Status", cell: (j) => stat(j.State) },
        { id: "t", header: "Resource type", cell: (j) => j.ResourceType }, { id: "r", header: "Resource name", cell: (j) => j.ResourceName }, { id: "v", header: "Backup vault", cell: (j) => j.BackupVaultName },
        { id: "z", header: "Size", cell: (j) => fmtBytes(j.BackupSizeInBytes) }, { id: "c", header: "Created", cell: (j) => fmtDate(j.CreationDate) }, { id: "m", header: "Message", cell: (j) => j.StatusMessage || "-" }]}
      actions={<Button disabled={!sel.length || sel[0].State !== "RUNNING"} onClick={async () => { try { await api.stopBackupJob(sel[0].BackupJobId); notify.success("Backup job stopped."); t.reload(); } catch (e) { notify.error(e); } }}>Stop</Button>} />
  );
}

export function RestoreJobs() {
  const t = useAsync(() => api.listRestoreJobs(), []);
  return (
    <ResourceTable resourceName="Restore jobs" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="RestoreJobId" filterPlaceholder="Search restore jobs" empty={{ title: "No restore jobs" }}
      columns={[{ id: "i", header: "Restore job ID", isRowHeader: true, cell: (j) => j.RestoreJobId }, { id: "s", header: "Status", cell: (j) => stat(j.Status) }, { id: "t", header: "Resource type", cell: (j) => j.ResourceType },
        { id: "a", header: "Created resource", cell: (j) => j.CreatedResourceArn || "-" }, { id: "c", header: "Created", cell: (j) => fmtDate(j.CreationDate) }, { id: "m", header: "Message", cell: (j) => j.StatusMessage || "-" }]} />
  );
}

export function Protected() {
  const t = useAsync(() => api.listProtected(), []);
  return (
    <ResourceTable resourceName="Protected resources" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="ResourceArn" filterPlaceholder="Search protected resources" empty={{ title: "No protected resources" }}
      columns={[{ id: "n", header: "Resource name", isRowHeader: true, cell: (r) => r.ResourceName }, { id: "t", header: "Resource type", cell: (r) => r.ResourceType },
        { id: "a", header: "Resource ARN", cell: (r) => r.ResourceArn }, { id: "l", header: "Last backup", cell: (r) => fmtDate(r.LastBackupTime) }]} />
  );
}
