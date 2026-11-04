/* VM Manager + VM Extension Manager over core/gcp_osconfig_core (OS Config API v1 + Compute vmExtensionPolicies).
 * Patch (jobs + deployments), OS policies (assignments), VM extension policies. Control plane only: no guest agent applies anything. */
import { useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Tab, Tabs, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";
import { ListPage, ZONE_OPTS } from "./Ext.jsx";

const last = (v) => String(v || "").split("/").pop();
const STATE_COLOR = { SUCCEEDED: "success", COMPLETED_WITH_ERRORS: "warning", CANCELED: "default", STARTED: "info", PATCHING: "info", NO_INSTANCES_FOUND: "default", ACTIVE: "success", PAUSED: "default" };
const StateChip = ({ s }) => <Chip size="small" label={s} color={STATE_COLOR[s] || "default"} />;
const TARGETS = [["all", "All VMs in the project"], ["label", "VMs with a label"], ["zone", "VMs in a zone"], ["prefix", "VMs whose name starts with"]];
const LABELLED = { key: "tk", label: "Label key", show: (v) => v.target === "label" };
const TARGET_FIELDS = [
  { key: "target", label: "Target VMs", options: TARGETS, default: "all" },
  { ...LABELLED, default: "env" },
  { key: "tv", label: "Label value / name prefix", show: (v) => v.target === "label" || v.target === "prefix" },
  { key: "tz", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE, show: (v) => v.target === "zone" },
];
const filterOf = (v) => v.target === "all" ? { all: true } : v.target === "zone" ? { zones: [v.tz] }
  : v.target === "prefix" ? { instanceNamePrefixes: [v.tv] } : { groupLabels: [{ labels: { [v.tk]: v.tv } }] };
const REBOOT = [["DEFAULT", "Reboot if required"], ["ALWAYS", "Always reboot"], ["NEVER", "Never reboot"]];

function JobDetails({ job, onClose }) {
  const { data = [], loading, error } = useAsync(() => api.patchJobInstances(last(job.name)), [job.name]);
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Patch job {job.displayName || last(job.name)}</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 2 }}>Control plane only: no guest agent runs in Vyomi VMs, so no package is changed. SUCCEEDED means an agent-enabled running VM was reached; add the metadata key enable-osconfig=TRUE to opt a VM in.</Alert>
        <ResourceTable resourceName="instance results" items={data} loading={loading} error={error} rowKey={(d) => d.name}
          columns={[
            { id: "n", header: "Instance", cell: (d) => last(d.name) },
            { id: "z", header: "Zone", cell: (d) => d.name.split("/")[3] },
            { id: "s", header: "State", cell: (d) => <StateChip s={d.state} /> },
            { id: "r", header: "Details", cell: (d) => d.failureReason || "—" },
          ]} />
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

function PatchJobs() {
  const notify = useNotify();
  const [detail, setDetail] = useState(null);
  return (
    <>
      <ListPage title="Patch" capId="gcp.compute.vm-manager" sectionTitle="Patch jobs" resourceName="patch jobs" load={api.listPatchJobs}
        rowKey={(j) => j.name} emptyText="No patch jobs. Execute a patch job to patch VMs now."
        extraActions={({ sel, data, reload }) => <>
          <Button disabled={sel.length !== 1} onClick={() => setDetail(data.find((j) => j.name === sel[0]))}>View details</Button>
          <Button disabled={sel.length !== 1} onClick={async () => { try { await api.cancelPatchJob(last(sel[0])); notify.success("Patch job canceled"); reload(); } catch (e) { notify.error?.(e.message); } }}>Cancel job</Button>
        </>}
        create={{ label: "Execute patch job", title: "Execute patch job", fields: [
          { key: "displayName", label: "Display name" }, ...TARGET_FIELDS,
          { key: "reboot", label: "Reboot configuration", options: REBOOT, default: "DEFAULT" },
          { key: "dry", label: "Mode", options: [["false", "Apply patches"], ["true", "Dry run"]], default: "false" },
        ], submit: (v) => api.executePatchJob({ displayName: v.displayName || undefined, instanceFilter: filterOf(v), patchConfig: { rebootConfig: v.reboot }, dryRun: v.dry === "true" }),
        done: () => "Patch job started" }}
        columns={[
          { id: "n", header: "Patch job", sortField: "displayName", cell: (j) => j.displayName || last(j.name) },
          { id: "s", header: "Status", cell: (j) => <StateChip s={j.state} /> },
          { id: "pc", header: "Progress", cell: (j) => `${Math.round(j.percentComplete || 0)}%` },
          { id: "i", header: "Instances (ok / failed / total)", cell: (j) => {
            const s = j.instanceDetailsSummary || {};
            const total = Object.values(s).reduce((a, b) => a + b, 0);
            return `${s.succeededInstanceCount || 0} / ${(s.failedInstanceCount || 0) + (s.noAgentDetectedInstanceCount || 0) + (s.timedOutInstanceCount || 0)} / ${total}`;
          } },
          { id: "dep", header: "Deployment", cell: (j) => (j.patchDeployment ? last(j.patchDeployment) : "On demand") },
          { id: "dry", header: "Dry run", cell: (j) => (j.dryRun ? "Yes" : "No") },
          { id: "c", header: "Created", cell: (j) => fmtDate(j.createTime) },
        ]} />
      {detail && <JobDetails job={detail} onClose={() => setDetail(null)} />}
    </>
  );
}

const DOW = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"].map((d) => [d, d[0] + d.slice(1).toLowerCase()]);

function PatchDeployments() {
  const notify = useNotify();
  return (
    <ListPage title="Patch" capId="gcp.compute.vm-manager" sectionTitle="Patch deployments" resourceName="patch deployments" load={api.listPatchDeployments}
      rowKey={(d) => last(d.name)} deleteTitle={(s) => (s.length === 1 ? "Delete patch deployment?" : `Delete ${s.length} patch deployments?`)}
      deleteFn={(d) => api.deletePatchDeployment(last(d.name))} emptyText="No patch deployments. Create one to patch VMs on a schedule."
      extraActions={({ sel, data, reload }) => {
        const d = sel.length === 1 ? data.find((x) => last(x.name) === sel[0]) : null;
        const run = (verb, msg) => async () => { try { await api.patchDeploymentAction(sel[0], verb); notify.success(msg); reload(); } catch (e) { notify.error?.(e.message); } };
        return <>
          <Button disabled={!d || d.state !== "ACTIVE"} onClick={run("pause", "Patch deployment paused")}>Pause</Button>
          <Button disabled={!d || d.state !== "PAUSED"} onClick={run("resume", "Patch deployment resumed")}>Resume</Button>
        </>;
      }}
      create={{ label: "Create patch deployment", fields: [
        { key: "id", label: "Name", required: true }, ...TARGET_FIELDS,
        { key: "freq", label: "Frequency", options: [["WEEKLY", "Weekly"], ["DAILY", "Daily"], ["MONTHLY", "Monthly (day of month)"], ["ONCE", "One time (in 1 hour)"]], default: "WEEKLY" },
        { key: "dow", label: "Day of week", options: DOW, default: "SUNDAY", show: (v) => v.freq === "WEEKLY" },
        { key: "mday", label: "Day of month (1-31, -1 = last)", type: "number", default: 1, show: (v) => v.freq === "MONTHLY" },
        { key: "hh", label: "Hour (UTC)", type: "number", default: 3, show: (v) => v.freq !== "ONCE" },
        { key: "mm", label: "Minute", type: "number", default: 0, show: (v) => v.freq !== "ONCE" },
        { key: "reboot", label: "Reboot configuration", options: REBOOT, default: "DEFAULT" },
      ], submit: (v) => api.createPatchDeployment(v.id, {
        instanceFilter: filterOf(v), patchConfig: { rebootConfig: v.reboot },
        ...(v.freq === "ONCE" ? { oneTimeSchedule: { executeTime: new Date(Date.now() + 3600e3).toISOString() } } : {
          recurringSchedule: { timeZone: { id: "UTC" }, timeOfDay: { hours: Number(v.hh), minutes: Number(v.mm) }, frequency: v.freq,
            ...(v.freq === "WEEKLY" ? { weekly: { dayOfWeek: v.dow } } : v.freq === "MONTHLY" ? { monthly: { monthDay: Number(v.mday) } } : {}) } }),
      }), done: (v) => `Created patch deployment "${v.id}"` }}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (d) => last(d.name) },
        { id: "s", header: "Status", cell: (d) => <StateChip s={d.state} /> },
        { id: "sch", header: "Schedule", cell: (d) => (d.oneTimeSchedule ? "One time" : `${d.recurringSchedule.frequency[0]}${d.recurringSchedule.frequency.slice(1).toLowerCase()}`) },
        { id: "nx", header: "Next run", cell: (d) => fmtDate(d.oneTimeSchedule?.executeTime || d.recurringSchedule?.nextExecuteTime) || "—" },
        { id: "last", header: "Last run", cell: (d) => (d.lastExecuteTime ? fmtDate(d.lastExecuteTime) : "Never") },
        { id: "f", header: "Targets", cell: (d) => (d.instanceFilter.all ? "All VMs" : JSON.stringify(d.instanceFilter)) },
      ]} />
  );
}

export function Patch() {
  const [tab, setTab] = useState("jobs");
  return (
    <>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }} aria-label="Patch tabs">
        <Tab value="jobs" label="Patch jobs" />
        <Tab value="deployments" label="Patch deployments" />
      </Tabs>
      {tab === "jobs" ? <PatchJobs /> : <PatchDeployments />}
    </>
  );
}

const assignmentBody = (v) => ({
  description: v.desc || undefined,
  osPolicies: [{ id: v.pid, mode: v.mode, resourceGroups: [{ resources: [{ id: "pkg-1", pkg: { desiredState: v.state, apt: { name: v.pkg } } }] }] }],
  instanceFilter: v.target === "all" ? { all: true } : { inclusionLabels: [{ labels: { [v.tk]: v.tv } }] },
  rollout: { disruptionBudget: { fixed: Number(v.budget) }, minWaitDuration: "60s" },
});

export function OsPolicies() {
  return (
    <ListPage title="OS policies" capId="gcp.compute.vm-manager" sectionTitle="OS policy assignments" resourceName="OS policy assignments" load={api.listOsPolicyAssignments}
      rowKey={(a) => `${a.name.split("/")[3]}/${a.name.split("/")[5].split("@")[0]}`}
      deleteTitle={(s) => (s.length === 1 ? "Delete OS policy assignment?" : `Delete ${s.length} OS policy assignments?`)}
      deleteFn={(a) => api.deleteOsPolicyAssignment(a.name.split("/")[3], a.name.split("/")[5].split("@")[0])}
      emptyText="No OS policy assignments. Create one to keep software configuration consistent across VMs."
      create={{ label: "Create OS policy assignment", fields: [
        { key: "id", label: "Assignment ID", required: true },
        { key: "zone", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE },
        { key: "desc", label: "Description" },
        { key: "pid", label: "OS policy ID", default: "policy-1" },
        { key: "mode", label: "Mode", options: [["ENFORCEMENT", "Enforcement"], ["VALIDATION", "Validation"]], default: "ENFORCEMENT" },
        { key: "pkg", label: "apt package name", default: "nginx" },
        { key: "state", label: "Desired state", options: [["INSTALLED", "Installed"], ["REMOVED", "Removed"]], default: "INSTALLED" },
        { key: "target", label: "Target VMs", options: [["all", "All VMs in the zone"], ["label", "VMs with a label"]], default: "all" },
        { key: "tk", label: "Label key", default: "env", show: (v) => v.target === "label" },
        { key: "tv", label: "Label value", show: (v) => v.target === "label" },
        { key: "budget", label: "Max VMs updated at once", type: "number", default: 1 },
      ], submit: (v) => api.createOsPolicyAssignment(v.zone, v.id, assignmentBody(v)), done: (v) => `Created OS policy assignment "${v.id}"` }}
      columns={[
        { id: "n", header: "Assignment", sortField: "name", cell: (a) => a.name.split("/")[5].split("@")[0] },
        { id: "z", header: "Zone", cell: (a) => a.name.split("/")[3] },
        { id: "p", header: "OS policies", cell: (a) => a.osPolicies.map((p) => `${p.id} (${p.mode.toLowerCase()})`).join(", ") },
        { id: "t", header: "Targets", cell: (a) => (a.instanceFilter.all ? "All VMs" : JSON.stringify(a.instanceFilter.inclusionLabels?.map((l) => l.labels))) },
        { id: "r", header: "Rollout", cell: (a) => a.rolloutState },
        { id: "rev", header: "Revision", cell: (a) => <Typography variant="caption">{a.revisionId}</Typography> },
        { id: "c", header: "Updated", cell: (a) => fmtDate(a.revisionCreateTime) },
      ]} />
  );
}

export function VmExtensionPolicies() {
  return (
    <ListPage title="VM extension policies" capId="gcp.compute.vm-manager" sectionTitle="VM extension policies" resourceName="VM extension policies" load={api.listVmExtensionPolicies}
      rowKey={(p) => p.name} deleteTitle={(s) => (s.length === 1 ? "Delete VM extension policy?" : `Delete ${s.length} VM extension policies?`)}
      deleteFn={(p) => api.deleteVmExtensionPolicy(p.name)} emptyText="No VM extension policies."
      create={{ label: "Create policy", fields: [
        { key: "name", label: "Name", required: true },
        { key: "ext", label: "Extension", options: [["ops-agent", "Ops Agent"], ["sap-agent", "Agent for SAP"], ["workloadmanager-agent", "Workload Manager agent"]], default: "ops-agent" },
        { key: "ver", label: "Pinned version (blank = latest)" },
        { key: "tk", label: "Select VMs by label key", default: "env" },
        { key: "tv", label: "Label value", default: "prod" },
        { key: "prio", label: "Priority (0-65535)", type: "number", default: 1000 },
        { key: "plan", label: "Rollout plan", options: [["FAST_ROLLOUT", "Fast rollout"], ["SLOW_ROLLOUT", "Slow rollout"]], default: "FAST_ROLLOUT" },
      ], submit: (v) => api.insertVmExtensionPolicy({
        name: v.name, extensionPolicies: { [v.ext]: v.ver ? { pinnedVersion: v.ver } : {} },
        instanceSelectors: [{ labelSelector: { inclusionLabels: { [v.tk]: v.tv } } }], priority: Number(v.prio),
        rolloutOperation: { rolloutInput: { predefinedRolloutPlan: v.plan } } }), done: (v) => `Created VM extension policy "${v.name}"` }}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (p) => p.name },
        { id: "e", header: "Extensions", cell: (p) => Object.entries(p.extensionPolicies).map(([k, v]) => `${k}${v.pinnedVersion ? ` @${v.pinnedVersion}` : ""}`).join(", ") },
        { id: "s", header: "Selectors", cell: (p) => p.instanceSelectors.map((s) => Object.entries(s.labelSelector.inclusionLabels).map(([k, v]) => `${k}=${v}`).join(",")).join(" | ") },
        { id: "pr", header: "Priority", cell: (p) => p.priority },
        { id: "ro", header: "Rollout", cell: (p) => p.rolloutOperation?.rolloutInput?.predefinedRolloutPlan || "—" },
        { id: "c", header: "Created", cell: (p) => fmtDate(p.creationTimestamp) },
      ]} />
  );
}
