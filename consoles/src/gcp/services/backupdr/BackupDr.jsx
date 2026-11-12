/* Backup and DR: backup vaults, backup plans, protected resources (plan associations) and backups.
 * Backups are real Compute Engine snapshots; restore creates new disks / a new instance from them. */
import { useState } from "react";
import { Button, Chip, Stack, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const TABS = [["vaults", "Backup vaults"], ["plans", "Backup plans"], ["protected", "Protected resources"], ["backups", "Backups"]];
const empty = (t) => <Typography variant="body2" color="text.secondary">{t}</Typography>;
const days = (s) => Math.round(parseInt(String(s || "0"), 10) / 86400);
const ruleText = (r) => {
  const s = r.standardSchedule || {};
  return `${r.ruleId}: ${s.recurrenceType}${s.recurrenceType === "HOURLY" ? ` every ${s.hourlyFrequency}h` : ""}, keep ${r.backupRetentionDays}d`;
};

export default function BackupDr({ query }) {
  const tab = TABS.some(([k]) => k === query.tab) ? query.tab : "vaults";
  const project = useProject();
  const vaults = useAsync(api.listVaults, [project]);
  const plans = useAsync(api.listPlans, [project]);
  const assocs = useAsync(api.listAssociations, [project]);
  const backups = useAsync(api.listAllBackups, [project, assocs.data?.length]);
  const notify = useNotify();
  const [dlg, setDlg] = useState(null);
  const reload = () => { vaults.reload(); plans.reload(); assocs.reload(); backups.reload(); };
  const act = async (fn, ok) => { try { await fn(); notify.success(ok); reload(); } catch (e) { notify.error(e.message); } };

  const createVault = async (v) => {
    await api.createVault(v.id, { description: v.description, backupMinimumEnforcedRetentionDuration: `${parseInt(v.retentionDays || "1", 10) * 86400}s` });
    notify.success(`Created backup vault ${v.id}`);
  };
  const createPlan = async (v) => {
    const sch = { recurrenceType: v.recurrence, backupWindow: { startHourOfDay: parseInt(v.startHour || "0", 10), endHourOfDay: Math.min(24, parseInt(v.startHour || "0", 10) + 6) } };
    if (v.recurrence === "HOURLY") sch.hourlyFrequency = parseInt(v.hours || "6", 10);
    if (v.recurrence === "WEEKLY") sch.daysOfWeek = v.days.split(",").map((d) => d.trim().toUpperCase()).filter(Boolean);
    if (v.recurrence === "MONTHLY") sch.daysOfMonth = [1];
    await api.createPlan(v.id, { resourceType: v.resourceType, backupVault: v.vault, description: v.description,
      backupRules: [{ ruleId: v.ruleId || "rule-1", backupRetentionDays: parseInt(v.retention || "7", 10), standardSchedule: sch }] });
    notify.success(`Created backup plan ${v.id}`);
  };
  const protect = async (v) => {
    const plan = (plans.data || []).find((p) => p.name === v.plan);
    await api.createAssociation(v.id, { resourceType: plan?.resourceType, resource: v.resource, backupPlan: v.plan });
    notify.success(`Protected ${v.resource.split("/").pop()}`);
  };
  const restore = async (v) => {
    const b = dlg.backup;
    const kind = b.computeInstanceBackupProperties ? "instance" : "disk";
    await api.restoreBackup(b.name, kind === "instance"
      ? { computeInstanceTargetEnvironment: { project, zone: v.zone }, computeInstanceRestoreProperties: { name: v.name } }
      : { diskTargetEnvironment: { project, zone: v.zone }, diskRestoreProperties: { name: v.name } });
    notify.success(`Restored to new ${kind} ${v.name}`);
  };
  const vaultOptions = (vaults.data || []).map((v) => v.name);
  const planOptions = (plans.data || []).map((p) => p.name);

  return (
    <>
      <PageHeader title="Backup and DR" actions={<>
        {tab === "vaults" && <Button startIcon={<AddIcon />} onClick={() => setDlg({ kind: "vault" })}>Create backup vault</Button>}
        {tab === "plans" && <Button startIcon={<AddIcon />} onClick={() => setDlg({ kind: "plan" })}>Create backup plan</Button>}
        {tab === "protected" && <Button startIcon={<AddIcon />} onClick={() => setDlg({ kind: "protect" })}>Protect a resource</Button>}
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = hashHref("backupdr") + (t === "vaults" ? "" : `?tab=${t}`); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }}>
        {TABS.map(([k, l]) => <Tab key={k} value={k} label={l} />)}
      </Tabs>
      <CapabilityContainer id="gcp.backupdr.core" title={TABS.find(([k]) => k === tab)[1]}>
        {tab === "vaults" && (
          <ResourceTable resourceName="backup vaults" items={vaults.data || []} loading={vaults.loading} error={vaults.error} onRetry={vaults.reload} rowKey={(v) => v.name}
            filterPlaceholder="Filter vaults"
            columns={[
              { id: "name", header: "Name", sortValue: (v) => api.tail(v.name), cell: (v) => api.tail(v.name) },
              { id: "region", header: "Location", cell: (v) => api.regionOf(v.name) },
              { id: "state", header: "State", cell: (v) => <Chip size="small" color="success" label={v.state} /> },
              { id: "ret", header: "Minimum enforced retention", cell: (v) => `${days(v.backupMinimumEnforcedRetentionDuration)} day(s)` },
              { id: "count", header: "Backups", cell: (v) => v.backupCount },
              { id: "act", header: "", cell: (v) => <Button size="small" color="error" onClick={() => act(() => api.deleteVault(v.name, true), `Deleted ${api.tail(v.name)}`)}>Delete</Button> },
            ]}
            empty={empty("There are no backup vaults in this project.")} />
        )}
        {tab === "plans" && (
          <ResourceTable resourceName="backup plans" items={plans.data || []} loading={plans.loading} error={plans.error} onRetry={plans.reload} rowKey={(p) => p.name}
            filterPlaceholder="Filter plans"
            columns={[
              { id: "name", header: "Name", sortValue: (p) => api.tail(p.name), cell: (p) => api.tail(p.name) },
              { id: "type", header: "Resource type", cell: (p) => api.tail(p.resourceType) },
              { id: "vault", header: "Backup vault", cell: (p) => api.tail(p.backupVault) },
              { id: "rules", header: "Rules", cell: (p) => (p.backupRules || []).map(ruleText).join("; ") },
              { id: "act", header: "", cell: (p) => <Button size="small" color="error" onClick={() => act(() => api.deletePlan(p.name), `Deleted ${api.tail(p.name)}`)}>Delete</Button> },
            ]}
            empty={empty("There are no backup plans in this project.")} />
        )}
        {tab === "protected" && (
          <ResourceTable resourceName="protected resources" items={assocs.data || []} loading={assocs.loading} error={assocs.error} onRetry={assocs.reload} rowKey={(a) => a.name}
            filterPlaceholder="Filter protected resources"
            columns={[
              { id: "res", header: "Resource", sortValue: (a) => api.tail(a.resource), cell: (a) => api.tail(a.resource) },
              { id: "type", header: "Type", cell: (a) => api.tail(a.resourceType) },
              { id: "plan", header: "Backup plan", cell: (a) => api.tail(a.backupPlan) },
              { id: "state", header: "Last backup", cell: (a) => (a.rulesConfigInfo || []).map((r) => `${r.ruleId}: ${r.lastBackupState}`).join(", ") },
              { id: "act", header: "", cell: (a) => (<Stack direction="row" spacing={1}>
                <Button size="small" onClick={() => act(() => api.triggerBackup(a.name, (a.rulesConfigInfo?.[0] || {}).ruleId), `Backup of ${api.tail(a.resource)} taken`)}>Back up now</Button>
                <Button size="small" color="error" onClick={() => act(() => api.deleteAssociation(a.name), "Stopped protecting resource")}>Remove</Button></Stack>) },
            ]}
            empty={empty("No resources are protected by a backup plan yet.")} />
        )}
        {tab === "backups" && (
          <ResourceTable resourceName="backups" items={backups.data || []} loading={backups.loading} error={backups.error} onRetry={backups.reload} rowKey={(b) => b.name}
            filterPlaceholder="Filter backups"
            columns={[
              { id: "name", header: "Backup", sortValue: (b) => api.tail(b.name), cell: (b) => api.tail(b.name) },
              { id: "res", header: "Resource", cell: (b) => api.tail(b.gcpResourcename) },
              { id: "type", header: "Type", cell: (b) => b.backupType },
              { id: "created", header: "Created", cell: (b) => b.createTime },
              { id: "expire", header: "Expires", cell: (b) => b.expireTime },
              { id: "size", header: "Size", cell: (b) => `${(Number(b.resourceSizeBytes) / 1073741824).toFixed(1)} GiB` },
              { id: "act", header: "", cell: (b) => (<Stack direction="row" spacing={1}>
                <Button size="small" onClick={() => setDlg({ kind: "restore", backup: b })}>Restore</Button>
                <Button size="small" color="error" onClick={() => act(() => api.deleteBackup(b.name), "Backup deleted")}>Delete</Button></Stack>) },
            ]}
            empty={empty("There are no backups yet.")} />
        )}
      </CapabilityContainer>
      <FormDialog open={dlg?.kind === "vault"} title="Create backup vault" onClose={(ok) => { setDlg(null); if (ok) reload(); }} onSubmit={createVault}
        fields={[{ key: "id", label: "Backup vault name" }, { key: "description", label: "Description" },
          { key: "retentionDays", label: "Minimum enforced retention (days)", default: "1", helper: "Backups cannot be deleted before this period ends (min 1 day)" }]} />
      <FormDialog open={dlg?.kind === "plan"} title="Create backup plan" onClose={(ok) => { setDlg(null); if (ok) reload(); }} onSubmit={createPlan}
        fields={[{ key: "id", label: "Backup plan name" }, { key: "description", label: "Description" },
          { key: "resourceType", label: "Resource type", options: ["compute.googleapis.com/Instance", "compute.googleapis.com/Disk"], default: "compute.googleapis.com/Instance" },
          { key: "vault", label: "Backup vault", options: vaultOptions, default: vaultOptions[0] || "" },
          { key: "ruleId", label: "Rule name", default: "rule-1" },
          { key: "recurrence", label: "Recurrence", options: ["HOURLY", "DAILY", "WEEKLY", "MONTHLY"], default: "DAILY" },
          { key: "hours", label: "Every N hours (HOURLY)", default: "6" },
          { key: "days", label: "Days of week (WEEKLY)", default: "MONDAY" },
          { key: "startHour", label: "Window start hour (UTC)", default: "2" },
          { key: "retention", label: "Retention (days)", default: "7" }]} />
      <FormDialog open={dlg?.kind === "protect"} title="Protect a resource" submitLabel="Protect" onClose={(ok) => { setDlg(null); if (ok) reload(); }} onSubmit={protect}
        fields={[{ key: "id", label: "Association name" },
          { key: "plan", label: "Backup plan", options: planOptions, default: planOptions[0] || "" },
          { key: "resource", label: "Resource", helper: "projects/P/zones/Z/instances/NAME  or  projects/P/zones/Z/disks/NAME" }]} />
      <FormDialog open={dlg?.kind === "restore"} title="Restore backup" submitLabel="Restore" onClose={(ok) => { setDlg(null); if (ok) reload(); }} onSubmit={restore}
        fields={[{ key: "name", label: "New resource name" }, { key: "zone", label: "Zone", default: "us-central1-a" }]} />
    </>
  );
}
