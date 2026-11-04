/* Compute Engine pages backed by core/gcp_compute_ext_core over the native Compute v1 / Recommender v1
 * REST wire: Compute Advisor, Reservations, Sole-tenant nodes, Storage Pools, Async Replication,
 * Consistency Groups, Network endpoint groups — plus the reusable tabs (Instance schedules, Snapshot
 * schedules, Instant snapshots, Recommendations) other pages embed. */
import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Select,
  Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { getProject, useProject } from "../../project.js";
import * as api from "./api.js";

const last = (v) => String(v || "").split("/").pop();
const scopeName = (s) => String(s || "").replace(/^(zones|regions)\//, "");

/* ── generic create form ─────────────────────────────────────────────────────────────── */
export function FormDialog({ open, title, fields, onClose, onSubmit, submitLabel = "Create", children }) {
  const init = () => Object.fromEntries(fields.map((f) => [f.key, f.default ?? ""]));
  const [v, setV] = useState(init);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { if (open) { setV(init()); setError(null); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = async () => {
    setBusy(true); setError(null);
    try { await onSubmit(v); onClose(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title={`Failed: ${title}`} />
          {fields.filter((f) => !f.show || f.show(v)).map((f) => f.options ? (
            <FormControl key={f.key} fullWidth>
              <InputLabel id={`f-${f.key}`}>{f.label}</InputLabel>
              <Select labelId={`f-${f.key}`} label={f.label} value={v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.value })}>
                {f.options.map(([val, label]) => <MenuItem key={val} value={val}>{label}</MenuItem>)}
              </Select>
            </FormControl>
          ) : (
            <TextField key={f.key} label={f.label} type={f.type || "text"} required={f.required} value={v[f.key]} helperText={f.helper}
              multiline={f.multiline} onChange={(e) => setV({ ...v, [f.key]: f.trim === false ? e.target.value : e.target.value.trim() })}
              inputProps={{ "aria-label": f.label }} />
          ))}
          {children && children(v, setV)}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={go}>{busy ? "Working…" : submitLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}

export const ZONE_OPTS = Object.values(api.ZONES_BY_REGION).flat().map((z) => [z, z]);
const REGION_OPTS = api.REGIONS.map(([v, l]) => [v, l]);
const MT_OPTS = ["e2-micro", "e2-small", "e2-medium", "n2-standard-2", "n2-standard-4", "c2-standard-4"].map((m) => [m, m]);

export function ListPage({ title, capId, resourceName, load, columns, rowKey, create, extraActions, tabs, deleteFn, deleteTitle, emptyText, children, sectionTitle }) {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [open, setOpen] = useState(false);
  const { data = [], loading, error, reload } = useAsync(load, [project]);
  return (
    <>
      <PageHeader title={title} actions={<>
        {create && <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>{create.label}</Button>}
        {extraActions?.({ sel, reload, data })}
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        {deleteFn && <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>}
      </>} />
      {tabs}
      <CapabilityContainer id={capId} title={sectionTitle || title}>
        <ResourceTable resourceName={resourceName} items={data} loading={loading} error={error} onRetry={reload} selectable={!!deleteFn}
          selected={sel} onSelectedChange={setSel} rowKey={rowKey} columns={columns}
          empty={<Typography variant="body2" color="text.secondary">{emptyText || `There are no ${resourceName} in this project.`}</Typography>} />
      </CapabilityContainer>
      {children?.({ reload, data })}
      {create && <FormDialog open={open} title={create.title || create.label} fields={create.fields} onClose={() => setOpen(false)}
        onSubmit={async (v) => { await create.submit(v); notify.success(create.done(v)); reload(); }}>{create.extra}</FormDialog>}
      {deleteFn && <DeleteDialog open={del} onClose={() => setDel(false)} title={deleteTitle(sel)} confirmText={sel.length === 1 ? last(sel[0]) : "DELETE"}
        warning="This can't be undone." onConfirm={async () => {
          for (const k of sel) { const it = data.find((d) => rowKey(d) === k); await deleteFn(it); }
          notify.success(`Deleted ${sel.length} item(s)`); setSel([]); reload();
        }} />}
    </>
  );
}

/* ── Recommendations (Compute Advisor, dashboard, instance tab) ──────────────────────── */
const fmtSavings = (r) => {
  const c = r.primaryImpact?.costProjection?.cost;
  if (!c) return r.primaryImpact?.category === "MANAGEABILITY" ? "Manageability" : "—";
  const m = -(Number(c.units) + c.nanos / 1e9);
  return `$${m.toFixed(2)}/mo`;
};

export function RecommendationsTable({ filter, onLoaded }) {
  const notify = useNotify();
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(async () => { const r = await api.listRecommendations(); onLoaded?.(r); return r; }, [project]);
  const rows = filter ? data.filter(filter) : data;
  const act = async (r, verb, msg) => { try { await api.markRecommendation(r, verb); notify.success(msg); reload(); } catch (e) { notify.error?.(e.message); } };
  return (
    <ResourceTable resourceName="recommendations" items={rows} loading={loading} error={error} onRetry={reload} rowKey={(r) => r.name}
      filterPlaceholder="Filter recommendations"
      empty={<Typography variant="body2" color="text.secondary">No recommendations — Compute resources in this project look healthy.</Typography>}
      columns={[
        { id: "desc", header: "Recommendation", cell: (r) => r.description },
        { id: "type", header: "Type", cell: (r) => api.RECOMMENDERS[r._recommender] || r._recommender },
        { id: "res", header: "Resource", sortValue: (r) => last(r.targetResources?.[0]), cell: (r) => last(r.targetResources?.[0]) },
        { id: "zone", header: "Location", cell: (r) => r._zone },
        { id: "impact", header: "Estimated savings", cell: fmtSavings },
        { id: "state", header: "State", sortValue: (r) => r.stateInfo.state, cell: (r) => <Chip size="small" label={r.stateInfo.state} color={r.stateInfo.state === "ACTIVE" ? "warning" : "default"} /> },
        { id: "act", header: "Actions", cell: (r) => (
          <Stack direction="row" spacing={0.5}>
            {r.stateInfo.state === "ACTIVE" && <Button size="small" onClick={() => act(r, "markClaimed", "Marked claimed")}>Claim</Button>}
            {["ACTIVE", "CLAIMED"].includes(r.stateInfo.state) && <Button size="small" onClick={() => act(r, "markSucceeded", "Marked applied")}>Mark applied</Button>}
            {["ACTIVE", "CLAIMED"].includes(r.stateInfo.state) && <Button size="small" onClick={() => act(r, "markDismissed", "Dismissed")}>Dismiss</Button>}
          </Stack>
        ) },
      ]} />
  );
}

export function ComputeAdvisor() {
  return (
    <>
      <PageHeader title="Compute Advisor" />
      <CapabilityContainer id="gcp.compute.recommender" title="Recommendations">
        <RecommendationsTable />
      </CapabilityContainer>
    </>
  );
}

/* ── Instance schedules ─────────────────────────────────────────────────────────────── */
export function InstanceSchedules({ instances }) {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [attach, setAttach] = useState(null);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(async () => (await api.listPolicies()).filter((p) => p.instanceSchedulePolicy), [project]);
  const key = (p) => `${scopeName(p._scope)}/${p.name}`;
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create schedule</Button>
        <Button disabled={sel.length !== 1} onClick={() => setAttach(data.find((p) => key(p) === sel[0]))}>Attach to VMs</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <CapabilityContainer id="gcp.compute.instance_schedules" title="Instance schedules">
        <ResourceTable resourceName="instance schedules" items={data} loading={loading} error={error} onRetry={reload} selectable selected={sel}
          onSelectedChange={setSel} rowKey={key} filterPlaceholder="Filter instance schedules"
          empty={<Typography variant="body2" color="text.secondary">No instance schedules. Create one to start and stop VMs automatically.</Typography>}
          columns={[
            { id: "name", header: "Name", sortField: "name", cell: (p) => p.name },
            { id: "region", header: "Region", cell: (p) => scopeName(p._scope) },
            { id: "start", header: "Start schedule", cell: (p) => p.instanceSchedulePolicy.vmStartSchedule?.schedule || "—" },
            { id: "stop", header: "Stop schedule", cell: (p) => p.instanceSchedulePolicy.vmStopSchedule?.schedule || "—" },
            { id: "tz", header: "Time zone", cell: (p) => p.instanceSchedulePolicy.timeZone },
            { id: "vms", header: "Attached VMs", cell: (p) => (p._display.attachedInstances.join(", ") || "—") },
            { id: "next", header: "Next run", cell: (p) => (p.resourceStatus?.instanceSchedulePolicy?.nextRunStartTime ? fmtDate(p.resourceStatus.instanceSchedulePolicy.nextRunStartTime) : "—") },
          ]} />
      </CapabilityContainer>
      <FormDialog open={open} title="Create instance schedule" onClose={() => setOpen(false)}
        fields={[
          { key: "name", label: "Name", required: true },
          { key: "region", label: "Region", options: REGION_OPTS, default: api.DEFAULT_REGION },
          { key: "start", label: "Start time (unix-cron)", default: "0 8 * * 1-5", helper: "Minute Hour DayOfMonth Month DayOfWeek" },
          { key: "stop", label: "Stop time (unix-cron)", default: "0 18 * * 1-5" },
          { key: "tz", label: "Time zone", default: "UTC" },
        ]}
        onSubmit={async (v) => {
          await api.insertPolicy(v.region, { name: v.name, instanceSchedulePolicy: {
            ...(v.start ? { vmStartSchedule: { schedule: v.start } } : {}), ...(v.stop ? { vmStopSchedule: { schedule: v.stop } } : {}), timeZone: v.tz || "UTC" } });
          notify.success(`Created schedule "${v.name}"`); reload();
        }} />
      <AttachDialog policy={attach} coll="instances" targets={instances} onClose={() => setAttach(null)} onDone={() => { notify.success("Schedule attached"); reload(); }} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete instance schedule(s)?" confirmText={sel.length === 1 ? last(sel[0]) : "DELETE"}
        warning="A schedule attached to VMs can't be deleted; detach it first." onConfirm={async () => {
          for (const k of sel) { const [region, name] = k.split("/"); await api.deletePolicy(region, name); }
          notify.success("Deleted"); setSel([]); reload();
        }} />
    </>
  );
}

function AttachDialog({ policy, coll, targets = [], onClose, onDone }) {
  const [pick, setPick] = useState("");
  const [error, setError] = useState(null);
  const region = policy && scopeName(policy._scope);
  const cands = targets.filter((t) => (api.ZONES_BY_REGION[region] || []).includes(t._zoneScope));
  const attachedKey = (policy?._display.attachedInstances || []).concat(policy?._display.attachedDisks || []);
  return (
    <Dialog open={!!policy} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Attach "{policy?.name}"</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to attach" />
          <FormControl fullWidth>
            <InputLabel id="att-l">{coll === "instances" ? "VM instance" : "Disk"} in {region}</InputLabel>
            <Select labelId="att-l" label={`${coll === "instances" ? "VM instance" : "Disk"} in ${region}`} value={pick} onChange={(e) => setPick(e.target.value)}>
              {cands.filter((t) => !attachedKey.includes(t.name)).map((t) => <MenuItem key={`${t._zoneScope}/${t.name}`} value={`${t._zoneScope}/${t.name}`}>{t._zoneScope}/{t.name}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!pick} onClick={async () => {
          try { const [zone, name] = pick.split("/"); await api.attachPolicy(coll, zone, name, region, policy.name); setPick(""); onClose(); onDone(); } catch (e) { setError(e); }
        }}>Attach</Button>
      </DialogActions>
    </Dialog>
  );
}

/* ── Snapshot schedules ─────────────────────────────────────────────────────────────── */
const SNAP_FIELDS = [
  { key: "name", label: "Name", required: true },
  { key: "region", label: "Region", options: REGION_OPTS, default: api.DEFAULT_REGION },
  { key: "cadence", label: "Schedule frequency", options: [["hourly", "Hourly"], ["daily", "Daily"], ["weekly", "Weekly"]], default: "daily" },
  { key: "hours", label: "Repeat every (hours: 1,2,3,4,6,8,12)", type: "number", default: 4, show: (v) => v.cadence === "hourly" },
  { key: "days", label: "Repeat every (days)", type: "number", default: 1, show: (v) => v.cadence === "daily" },
  { key: "dow", label: "Day of week", default: "MONDAY", options: ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"].map((d) => [d, d]), show: (v) => v.cadence === "weekly" },
  { key: "start", label: "Start time (UTC, HH:MM)", default: "00:00" },
  { key: "retention", label: "Keep snapshots (days)", type: "number", default: 14 },
  { key: "onDelete", label: "When source disk is deleted", options: [["KEEP_AUTO_SNAPSHOTS", "Keep snapshots"], ["APPLY_RETENTION_POLICY", "Apply retention policy"]], default: "KEEP_AUTO_SNAPSHOTS" },
];
export const snapshotPolicyBody = (v) => ({
  name: v.name,
  snapshotSchedulePolicy: {
    schedule: v.cadence === "hourly" ? { hourlySchedule: { hoursInCycle: Number(v.hours), startTime: v.start } }
      : v.cadence === "daily" ? { dailySchedule: { daysInCycle: Number(v.days), startTime: v.start } }
        : { weeklySchedule: { dayOfWeekSchedules: [{ day: v.dow, startTime: v.start }] } },
    retentionPolicy: { maxRetentionDays: Number(v.retention), onSourceDiskDelete: v.onDelete },
  },
});
const describeSchedule = (s) => s.hourlySchedule ? `Every ${s.hourlySchedule.hoursInCycle}h from ${s.hourlySchedule.startTime} UTC`
  : s.dailySchedule ? `Every ${s.dailySchedule.daysInCycle} day(s) at ${s.dailySchedule.startTime} UTC`
    : `Weekly: ${(s.weeklySchedule?.dayOfWeekSchedules || []).map((d) => `${d.day} ${d.startTime}`).join(", ")} UTC`;

export function SnapshotSchedules({ disks }) {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [attach, setAttach] = useState(null);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(async () => (await api.listPolicies()).filter((p) => p.snapshotSchedulePolicy), [project]);
  const key = (p) => `${scopeName(p._scope)}/${p.name}`;
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create snapshot schedule</Button>
        <Button disabled={sel.length !== 1} onClick={() => setAttach(data.find((p) => key(p) === sel[0]))}>Attach to disk</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <CapabilityContainer id="gcp.compute.snapshot_schedules" title="Snapshot schedules">
        <ResourceTable resourceName="snapshot schedules" items={data} loading={loading} error={error} onRetry={reload} selectable selected={sel}
          onSelectedChange={setSel} rowKey={key} filterPlaceholder="Filter snapshot schedules"
          empty={<Typography variant="body2" color="text.secondary">No snapshot schedules.</Typography>}
          columns={[
            { id: "name", header: "Name", sortField: "name", cell: (p) => p.name },
            { id: "region", header: "Region", cell: (p) => scopeName(p._scope) },
            { id: "sched", header: "Schedule", cell: (p) => describeSchedule(p.snapshotSchedulePolicy.schedule) },
            { id: "ret", header: "Retention", cell: (p) => `${p.snapshotSchedulePolicy.retentionPolicy.maxRetentionDays} days` },
            { id: "disks", header: "Attached disks", cell: (p) => p._display.attachedDisks.join(", ") || "—" },
          ]} />
      </CapabilityContainer>
      <FormDialog open={open} title="Create snapshot schedule" fields={SNAP_FIELDS} onClose={() => setOpen(false)}
        onSubmit={async (v) => { await api.insertPolicy(v.region, snapshotPolicyBody(v)); notify.success(`Created snapshot schedule "${v.name}"`); reload(); }} />
      <AttachDialog policy={attach} coll="disks" targets={disks} onClose={() => setAttach(null)} onDone={() => { notify.success("Schedule attached"); reload(); }} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete snapshot schedule(s)?" confirmText={sel.length === 1 ? last(sel[0]) : "DELETE"}
        warning="A schedule attached to a disk can't be deleted; detach it first." onConfirm={async () => {
          for (const k of sel) { const [region, name] = k.split("/"); await api.deletePolicy(region, name); }
          notify.success("Deleted"); setSel([]); reload();
        }} />
    </>
  );
}
export { SNAP_FIELDS };

/* ── Instant snapshots ──────────────────────────────────────────────────────────────── */
export function InstantSnapshots({ disks }) {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [open, setOpen] = useState(false);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listInstantSnapshots(), [project]);
  const key = (s) => `${scopeName(s._scope)}/${s.name}`;
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create instant snapshot</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <CapabilityContainer id="gcp.compute.instant_snapshots" title="Instant snapshots">
        <ResourceTable resourceName="instant snapshots" items={data} loading={loading} error={error} onRetry={reload} selectable selected={sel}
          onSelectedChange={setSel} rowKey={key} filterPlaceholder="Filter instant snapshots"
          empty={<Typography variant="body2" color="text.secondary">No instant snapshots.</Typography>}
          columns={[
            { id: "status", header: "Status", cell: (s) => s.status },
            { id: "name", header: "Name", sortField: "name", cell: (s) => s.name },
            { id: "zone", header: "Location", cell: (s) => scopeName(s._scope) },
            { id: "src", header: "Source disk", cell: (s) => last(s.sourceDisk) },
            { id: "size", header: "Disk size", cell: (s) => `${s.diskSizeGb} GB` },
            { id: "created", header: "Creation time", cell: (s) => fmtDate(s.creationTimestamp) },
          ]} />
      </CapabilityContainer>
      <FormDialog open={open} title="Create instant snapshot" onClose={() => setOpen(false)}
        fields={[{ key: "name", label: "Name", required: true },
          { key: "disk", label: "Source disk", options: disks.map((d) => [`${d._zoneScope}/${d.name}`, `${d._zoneScope}/${d.name}`]) }]}
        onSubmit={async (v) => { const [zone, disk] = v.disk.split("/"); await api.insertInstantSnapshot(zone, { name: v.name, sourceDisk: `zones/${zone}/disks/${disk}` }); notify.success(`Created instant snapshot "${v.name}"`); reload(); }} />
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete instant snapshot(s)?" confirmText={sel.length === 1 ? last(sel[0]) : "DELETE"}
        onConfirm={async () => { for (const k of sel) { const [zone, name] = k.split("/"); await api.deleteInstantSnapshot(zone, name); } notify.success("Deleted"); setSel([]); reload(); }} />
    </>
  );
}

/* ── Reservations ───────────────────────────────────────────────────────────────────── */
export function Reservations() {
  const notify = useNotify();
  return (
    <ListPage title="Reservations" capId="gcp.compute.reservations" resourceName="reservations" load={api.listReservations}
      rowKey={(r) => `${scopeName(r._scope)}/${r.name}`} deleteTitle={(s) => (s.length === 1 ? "Delete reservation?" : `Delete ${s.length} reservations?`)}
      deleteFn={(r) => api.deleteReservation(scopeName(r._scope), r.name)}
      extraActions={({ sel, reload, data }) => <Button disabled={sel.length !== 1} onClick={async () => {
        const r = data.find((x) => `${scopeName(x._scope)}/${x.name}` === sel[0]);
        const n = window.prompt("New number of reserved VMs", r.specificReservation.count);
        if (n) { try { await api.resizeReservation(scopeName(r._scope), r.name, n); notify.success("Reservation resized"); reload(); } catch (e) { notify.error?.(e.message); } }
      }}>Resize</Button>}
      create={{ label: "Create reservation", fields: [
        { key: "name", label: "Name", required: true },
        { key: "zone", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE },
        { key: "mt", label: "Machine type", options: MT_OPTS, default: "e2-medium" },
        { key: "count", label: "Number of VM instances", type: "number", default: 1 },
        { key: "required", label: "Use reservation", options: [["false", "Automatically (any matching VM)"], ["true", "Select specific reservation only"]], default: "false" },
      ], submit: (v) => api.insertReservation(v.zone, { name: v.name, specificReservation: { count: String(v.count), instanceProperties: { machineType: v.mt } }, specificReservationRequired: v.required === "true" }),
      done: (v) => `Created reservation "${v.name}"` }}
      columns={[
        { id: "name", header: "Name", sortField: "name", cell: (r) => r.name },
        { id: "status", header: "Status", cell: (r) => r.status },
        { id: "zone", header: "Zone", cell: (r) => scopeName(r._scope) },
        { id: "mt", header: "Machine type", cell: (r) => r._display.machineType },
        { id: "res", header: "Reserved", cell: (r) => r.specificReservation.count },
        { id: "use", header: "In use", cell: (r) => `${r.specificReservation.inUseCount}${r._display.consumers.length ? ` (${r._display.consumers.join(", ")})` : ""}` },
        { id: "mode", header: "Use reservation", cell: (r) => (r.specificReservationRequired ? "Specific only" : "Automatic") },
        { id: "created", header: "Created", cell: (r) => fmtDate(r.creationTimestamp) },
      ]} />
  );
}

/* ── Sole-tenant nodes ──────────────────────────────────────────────────────────────── */
export function SoleTenantNodes() {
  const notify = useNotify();
  const project = useProject();
  const [tab, setTab] = useState("groups");
  const [view, setView] = useState(null);
  const [tplOpen, setTplOpen] = useState(false);
  const [tplSel, setTplSel] = useState([]);
  const [tplDel, setTplDel] = useState(false);
  const tpls = useAsync(api.listNodeTemplates, [project]);
  const tabs = (
    <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
      <Tab label="Node groups" value="groups" /><Tab label="Node templates" value="templates" />
    </Tabs>
  );
  const tplOpts = (tpls.data || []).map((t) => [`${scopeName(t._scope)}/${t.name}`, `${t.name} (${scopeName(t._scope)}, ${t.nodeType})`]);
  if (tab === "templates") {
    return (
      <>
        <PageHeader title="Sole-tenant nodes" actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setTplOpen(true)}>Create node template</Button>
          <Button startIcon={<RefreshIcon />} onClick={tpls.reload}>Refresh</Button>
          <Button startIcon={<DeleteIcon />} disabled={!tplSel.length} onClick={() => setTplDel(true)}>Delete</Button>
        </>} />
        {tabs}
        <CapabilityContainer id="gcp.compute.sole_tenant" title="Node templates">
          <ResourceTable resourceName="node templates" items={tpls.data || []} loading={tpls.loading} error={tpls.error} onRetry={tpls.reload} selectable
            selected={tplSel} onSelectedChange={setTplSel} rowKey={(t) => `${scopeName(t._scope)}/${t.name}`}
            empty={<Typography variant="body2" color="text.secondary">No node templates.</Typography>}
            columns={[
              { id: "name", header: "Name", sortField: "name", cell: (t) => t.name },
              { id: "region", header: "Region", cell: (t) => scopeName(t._scope) },
              { id: "type", header: "Node type", cell: (t) => t.nodeType },
              { id: "groups", header: "Used by", cell: (t) => t._display.groups.join(", ") || "—" },
            ]} />
        </CapabilityContainer>
        <FormDialog open={tplOpen} title="Create node template" onClose={() => setTplOpen(false)}
          fields={[{ key: "name", label: "Name", required: true }, { key: "region", label: "Region", options: REGION_OPTS, default: api.DEFAULT_REGION },
            { key: "type", label: "Node type", options: ["n1-node-96-624", "n2-node-80-640", "n2d-node-224-896", "c2-node-60-240", "m1-node-96-1433"].map((n) => [n, n]), default: "n2-node-80-640" }]}
          onSubmit={async (v) => { await api.insertNodeTemplate(v.region, { name: v.name, nodeType: v.type }); notify.success(`Created node template "${v.name}"`); tpls.reload(); }} />
        <DeleteDialog open={tplDel} onClose={() => setTplDel(false)} title="Delete node template(s)?" confirmText={tplSel.length === 1 ? last(tplSel[0]) : "DELETE"}
          onConfirm={async () => { for (const k of tplSel) { const [r, n] = k.split("/"); await api.deleteNodeTemplate(r, n); } notify.success("Deleted"); setTplSel([]); tpls.reload(); }} />
      </>
    );
  }
  return (
    <ListPage title="Sole-tenant nodes" capId="gcp.compute.sole_tenant" sectionTitle="Node groups" resourceName="node groups" load={api.listNodeGroups} tabs={tabs}
      rowKey={(g) => `${scopeName(g._scope)}/${g.name}`} deleteTitle={(s) => (s.length === 1 ? "Delete node group?" : `Delete ${s.length} node groups?`)}
      deleteFn={(g) => api.deleteNodeGroup(scopeName(g._scope), g.name)}
      extraActions={({ sel, reload, data }) => <>
        <Button disabled={sel.length !== 1} onClick={() => setView(data.find((x) => `${scopeName(x._scope)}/${x.name}` === sel[0]))}>View nodes</Button>
        <Button disabled={sel.length !== 1} onClick={async () => {
          const g = data.find((x) => `${scopeName(x._scope)}/${x.name}` === sel[0]);
          try { await api.nodeGroupAction(scopeName(g._scope), g.name, "addNodes", { additionalNodeCount: 1 }); notify.success("Added 1 node"); reload(); } catch (e) { notify.error?.(e.message); }
        }}>Add node</Button></>}
      create={{ label: "Create node group", fields: [
        { key: "name", label: "Name", required: true }, { key: "zone", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE },
        { key: "tpl", label: "Node template", options: tplOpts }, { key: "n", label: "Number of nodes", type: "number", default: 1 },
      ], submit: (v) => { const [r, t] = v.tpl.split("/"); return api.insertNodeGroup(v.zone, { name: v.name, nodeTemplate: `regions/${r}/nodeTemplates/${t}` }, v.n); },
      done: (v) => `Created node group "${v.name}"` }}
      columns={[
        { id: "name", header: "Name", sortField: "name", cell: (g) => g.name },
        { id: "status", header: "Status", cell: (g) => g.status },
        { id: "zone", header: "Zone", cell: (g) => scopeName(g._scope) },
        { id: "type", header: "Node type", cell: (g) => g._display.nodeType },
        { id: "tpl", header: "Template", cell: (g) => g._display.template },
        { id: "size", header: "Nodes", cell: (g) => g.size },
        { id: "vms", header: "VM instances", cell: (g) => g._display.instanceCount },
      ]}>
      {() => (
        <Dialog open={!!view} onClose={() => setView(null)} maxWidth="md" fullWidth>
          <DialogTitle>Nodes in {view?.name}</DialogTitle>
          <DialogContent>
            <ResourceTable resourceName="nodes" items={view?._display.nodes || []} rowKey={(n) => n.name}
              empty={<Typography variant="body2">This group has no nodes.</Typography>}
              columns={[{ id: "n", header: "Node", cell: (n) => n.name }, { id: "s", header: "Status", cell: (n) => n.status },
                { id: "t", header: "Node type", cell: (n) => n.nodeType }, { id: "c", header: "vCPUs used", cell: (n) => n.cpuUsed },
                { id: "m", header: "Memory used (MB)", cell: (n) => n.memoryMbUsed }, { id: "i", header: "VM instances", cell: (n) => n.instances.join(", ") || "—" }]} />
          </DialogContent>
          <DialogActions><Button onClick={() => setView(null)}>Close</Button></DialogActions>
        </Dialog>
      )}
    </ListPage>
  );
}

/* ── Storage pools ──────────────────────────────────────────────────────────────────── */
export function StoragePools() {
  return (
    <ListPage title="Storage Pools" capId="gcp.compute.storage_pools" resourceName="storage pools" load={api.listStoragePools}
      rowKey={(p) => `${scopeName(p._scope)}/${p.name}`} deleteTitle={(s) => (s.length === 1 ? "Delete storage pool?" : `Delete ${s.length} storage pools?`)}
      deleteFn={(p) => api.deleteStoragePool(scopeName(p._scope), p.name)}
      create={{ label: "Create storage pool", fields: [
        { key: "name", label: "Name", required: true }, { key: "zone", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE },
        { key: "type", label: "Pool type", options: [["hyperdisk-balanced", "Hyperdisk Balanced"], ["hyperdisk-throughput", "Hyperdisk Throughput"]], default: "hyperdisk-balanced" },
        { key: "cap", label: "Provisioned capacity (GB, min 10240)", type: "number", default: 10240 },
        { key: "iops", label: "Provisioned IOPS (balanced only)", type: "number", default: 10000, show: (v) => v.type === "hyperdisk-balanced" },
        { key: "tput", label: "Provisioned throughput (MB/s)", type: "number", default: 1024, show: (v) => v.type === "hyperdisk-balanced" },
        { key: "tputT", label: "Provisioned throughput (MB/s)", type: "number", default: 10240, show: (v) => v.type === "hyperdisk-throughput" },
        { key: "prov", label: "Capacity provisioning", options: [["STANDARD", "Standard"], ["ADVANCED", "Advanced (thin, 5x)"]], default: "STANDARD" },
      ], submit: (v) => api.insertStoragePool(v.zone, { name: v.name, storagePoolType: v.type, poolProvisionedCapacityGb: String(v.cap),
        ...(v.type === "hyperdisk-balanced" ? { poolProvisionedIops: String(v.iops), poolProvisionedThroughput: String(v.tput) } : { poolProvisionedThroughput: String(v.tputT) }),
        capacityProvisioningType: v.prov }),
      done: (v) => `Created storage pool "${v.name}"` }}
      columns={[
        { id: "name", header: "Name", sortField: "name", cell: (p) => p.name },
        { id: "state", header: "State", cell: (p) => p.state },
        { id: "zone", header: "Zone", cell: (p) => scopeName(p._scope) },
        { id: "type", header: "Type", cell: (p) => p._display.type },
        { id: "cap", header: "Provisioned capacity", cell: (p) => `${p.poolProvisionedCapacityGb} GB` },
        { id: "used", header: "Disk capacity used", cell: (p) => `${p._display.usedGb} / ${p._display.limitGb} GB` },
        { id: "disks", header: "Disks", cell: (p) => p._display.disks.join(", ") || "—" },
        { id: "iops", header: "IOPS / throughput", cell: (p) => `${p.poolProvisionedIops} / ${p.poolProvisionedThroughput} MB/s` },
      ]} />
  );
}

/* ── Async replication ──────────────────────────────────────────────────────────────── */
export function AsyncReplication() {
  const notify = useNotify();
  const [disks, setDisks] = useState([]);
  useEffect(() => { api.listDisksAllZones().then(setDisks).catch(() => setDisks([])); }, []);
  const opts = disks.map((d) => [`${d._zoneScope}/${d.name}`, `${d._zoneScope}/${d.name}`]);
  return (
    <ListPage title="Async Replication" capId="gcp.compute.async_replication" resourceName="replications"
      load={async () => (await api.listDisksAllZones()).filter((d) => d.asyncSecondaryDisks).flatMap((d) => Object.keys(d.asyncSecondaryDisks).map((s) => ({ primary: d, secondary: s })))}
      rowKey={(r) => `${r.primary._zoneScope}/${r.primary.name}`} deleteTitle={() => "Stop replication?"} deleteFn={(r) => api.stopReplication(r.primary._zoneScope, r.primary.name)}
      create={{ label: "Start replication", fields: [{ key: "p", label: "Primary disk", options: opts }, { key: "s", label: "Secondary disk (other region, unattached)", options: opts }],
        submit: (v) => { const [pz, pn] = v.p.split("/"); const [sz, sn] = v.s.split("/"); return api.startReplication(pz, pn, `projects/${getProject()}/zones/${sz}/disks/${sn}`); },
        done: () => "Replication started" }}
      columns={[
        { id: "p", header: "Primary disk", cell: (r) => r.primary.name },
        { id: "pz", header: "Primary zone", cell: (r) => r.primary._zoneScope },
        { id: "s", header: "Secondary disk", cell: (r) => r.secondary },
        { id: "st", header: "Replication state", cell: (r) => r.primary.resourceStatus?.asyncSecondaryDisks?.[r.secondary]?.state || "ACTIVE" },
        { id: "sz", header: "Disk size", cell: (r) => `${r.primary.sizeGb} GB` },
      ]} />
  );
}

/* ── Consistency groups ─────────────────────────────────────────────────────────────── */
export function ConsistencyGroups() {
  const notify = useNotify();
  const [disks, setDisks] = useState([]);
  const [attach, setAttach] = useState(null);
  useEffect(() => { api.listDisksAllZones().then(setDisks).catch(() => setDisks([])); }, []);
  return (
    <ListPage title="Consistency Groups" capId="gcp.compute.consistency_groups" resourceName="consistency groups"
      load={async () => (await api.listPolicies()).filter((p) => p.diskConsistencyGroupPolicy)} rowKey={(p) => `${scopeName(p._scope)}/${p.name}`}
      deleteTitle={(s) => (s.length === 1 ? "Delete consistency group?" : `Delete ${s.length} groups?`)} deleteFn={(p) => api.deletePolicy(scopeName(p._scope), p.name)}
      extraActions={({ sel, data }) => <Button disabled={sel.length !== 1} onClick={() => setAttach(data.find((p) => `${scopeName(p._scope)}/${p.name}` === sel[0]))}>Add disk</Button>}
      create={{ label: "Create consistency group", fields: [{ key: "name", label: "Name", required: true }, { key: "region", label: "Region", options: REGION_OPTS, default: api.DEFAULT_REGION }],
        submit: (v) => api.insertPolicy(v.region, { name: v.name, diskConsistencyGroupPolicy: {} }), done: (v) => `Created consistency group "${v.name}"` }}
      columns={[
        { id: "name", header: "Name", sortField: "name", cell: (p) => p.name },
        { id: "region", header: "Region", cell: (p) => scopeName(p._scope) },
        { id: "disks", header: "Disks", cell: (p) => p._display.attachedDisks.join(", ") || "—" },
        { id: "created", header: "Created", cell: (p) => fmtDate(p.creationTimestamp) },
      ]}>
      {({ reload }) => <AttachDialog policy={attach} coll="disks" targets={disks} onClose={() => setAttach(null)} onDone={() => { notify.success("Disk added to group"); reload(); }} />}
    </ListPage>
  );
}

/* ── Network endpoint groups ────────────────────────────────────────────────────────── */
export function NetworkEndpointGroups() {
  const notify = useNotify();
  const [view, setView] = useState(null);
  const [eps, setEps] = useState([]);
  const [epOpen, setEpOpen] = useState(false);
  const loadEps = async (g) => { try { setEps(await api.listNegEndpoints(g._display.scopeKind, g._display.scope, g.name)); } catch { setEps([]); } };
  return (
    <ListPage title="Network endpoint groups" capId="gcp.compute.network_endpoint_groups" resourceName="network endpoint groups" load={api.listNegs}
      rowKey={(g) => `${g._display.scopeKind}/${g._display.scope}/${g.name}`} deleteTitle={(s) => (s.length === 1 ? "Delete network endpoint group?" : `Delete ${s.length} NEGs?`)}
      deleteFn={(g) => api.deleteNeg(g._display.scopeKind, g._display.scope, g.name)}
      extraActions={({ sel, data }) => <Button disabled={sel.length !== 1} onClick={() => { const g = data.find((x) => `${x._display.scopeKind}/${x._display.scope}/${x.name}` === sel[0]); setView(g); loadEps(g); }}>Manage endpoints</Button>}
      create={{ label: "Create network endpoint group", fields: [
        { key: "name", label: "Name", required: true },
        { key: "type", label: "Type", options: [["GCE_VM_IP_PORT", "Zonal: VM IP:port"], ["GCE_VM_IP", "Zonal: VM IP"], ["NON_GCP_PRIVATE_IP_PORT", "Hybrid connectivity (zonal)"],
          ["INTERNET_IP_PORT", "Internet IP:port (global)"], ["INTERNET_FQDN_PORT", "Internet FQDN:port (global)"], ["SERVERLESS", "Serverless (Cloud Run, regional)"]], default: "GCE_VM_IP_PORT" },
        { key: "zone", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE, show: (v) => ["GCE_VM_IP_PORT", "GCE_VM_IP", "NON_GCP_PRIVATE_IP_PORT"].includes(v.type) },
        { key: "region", label: "Region", options: REGION_OPTS, default: api.DEFAULT_REGION, show: (v) => v.type === "SERVERLESS" },
        { key: "network", label: "Network", default: "default", show: (v) => ["GCE_VM_IP_PORT", "GCE_VM_IP", "NON_GCP_PRIVATE_IP_PORT"].includes(v.type) },
        { key: "subnet", label: "Subnetwork", default: "default", show: (v) => ["GCE_VM_IP_PORT", "GCE_VM_IP", "NON_GCP_PRIVATE_IP_PORT"].includes(v.type) },
        { key: "port", label: "Default port", type: "number", default: 80, show: (v) => v.type !== "GCE_VM_IP" && v.type !== "SERVERLESS" },
        { key: "service", label: "Cloud Run service", show: (v) => v.type === "SERVERLESS" },
      ], submit: (v) => {
        const zonal = ["GCE_VM_IP_PORT", "GCE_VM_IP", "NON_GCP_PRIVATE_IP_PORT"].includes(v.type);
        const body = { name: v.name, networkEndpointType: v.type, ...(zonal ? { network: v.network, subnetwork: v.subnet } : {}),
          ...(v.type !== "GCE_VM_IP" && v.type !== "SERVERLESS" && v.port ? { defaultPort: Number(v.port) } : {}), ...(v.type === "SERVERLESS" ? { cloudRun: { service: v.service } } : {}) };
        return api.insertNeg(zonal ? "zones" : v.type === "SERVERLESS" ? "regions" : "global", zonal ? v.zone : v.type === "SERVERLESS" ? v.region : null, body);
      }, done: (v) => `Created network endpoint group "${v.name}"` }}
      columns={[
        { id: "name", header: "Name", sortField: "name", cell: (g) => g.name },
        { id: "type", header: "Type", cell: (g) => g.networkEndpointType },
        { id: "loc", header: "Scope", cell: (g) => g._display.scopeKind === "global" ? "Global" : g._display.scope },
        { id: "net", header: "Network", cell: (g) => (g.network ? last(g.network) : "—") },
        { id: "port", header: "Default port", cell: (g) => g.defaultPort || "—" },
        { id: "size", header: "Endpoints", cell: (g) => g.size },
      ]}>
      {({ reload }) => (
        <>
          <Dialog open={!!view} onClose={() => { setView(null); reload(); }} maxWidth="md" fullWidth>
            <DialogTitle>Endpoints in {view?.name}</DialogTitle>
            <DialogContent>
              <Stack direction="row" spacing={1} sx={{ mb: 1 }}><Button startIcon={<AddIcon />} onClick={() => setEpOpen(true)}>Add network endpoint</Button></Stack>
              <ResourceTable resourceName="endpoints" items={eps} rowKey={(x) => JSON.stringify(x.networkEndpoint)}
                empty={<Typography variant="body2">No endpoints.</Typography>}
                columns={[{ id: "i", header: "Instance / FQDN", cell: (x) => last(x.networkEndpoint.instance) || x.networkEndpoint.fqdn || "—" },
                  { id: "ip", header: "IP address", cell: (x) => x.networkEndpoint.ipAddress || "—" }, { id: "p", header: "Port", cell: (x) => x.networkEndpoint.port || "—" },
                  { id: "a", header: "", cell: (x) => <Button size="small" onClick={async () => {
                    try { await api.negAction(view._display.scopeKind, view._display.scope, view.name, "detachNetworkEndpoints", { networkEndpoints: [x.networkEndpoint] }); notify.success("Endpoint removed"); loadEps(view); } catch (e) { notify.error?.(e.message); }
                  }}>Remove</Button> }]} />
            </DialogContent>
            <DialogActions><Button onClick={() => { setView(null); reload(); }}>Close</Button></DialogActions>
          </Dialog>
          <FormDialog open={epOpen} title="Add network endpoint" onClose={() => setEpOpen(false)} fields={[
            { key: "instance", label: "VM instance name", show: () => view?.networkEndpointType?.startsWith("GCE_VM") },
            { key: "ip", label: "IP address", show: () => view && !view.networkEndpointType.startsWith("GCE_VM") && view.networkEndpointType !== "INTERNET_FQDN_PORT" },
            { key: "fqdn", label: "FQDN", show: () => view?.networkEndpointType === "INTERNET_FQDN_PORT" },
            { key: "port", label: "Port", type: "number", default: view?.defaultPort || "" },
          ]} onSubmit={async (v) => {
            const e = { ...(v.instance ? { instance: v.instance } : {}), ...(v.ip ? { ipAddress: v.ip } : {}), ...(v.fqdn ? { fqdn: v.fqdn } : {}), ...(v.port ? { port: Number(v.port) } : {}) };
            await api.negAction(view._display.scopeKind, view._display.scope, view.name, "attachNetworkEndpoints", { networkEndpoints: [e] });
            notify.success("Endpoint added"); loadEps(view);
          }} />
        </>
      )}
    </ListPage>
  );
}

export const EXT_PAGE_IDS = {
  "compute-advisor": ComputeAdvisor, reservations: Reservations, "sole-tenant-nodes": SoleTenantNodes, "storage-pools": StoragePools,
  "async-replication": AsyncReplication, "consistency-groups": ConsistencyGroups, "network-endpoint-groups": NetworkEndpointGroups,
};
// VM Manager pages live in VmManager.jsx (it imports ListPage from here), so index.jsx merges them in.
