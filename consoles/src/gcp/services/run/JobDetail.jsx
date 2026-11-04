/* Job details: summary strip + tabs (History, Observability, Triggers, YAML), native
 * Cloud Run Admin API v2. History lists executions, each a real run-to-completion job. */
import { useState } from "react";
import {
  Alert, Box, Breadcrumbs, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, Stack, Tab, Tabs, TextField, Tooltip, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { Link } from "../../link.jsx";
import * as api from "./api.js";

const TABS = [["history", "History"], ["observability", "Observability"], ["triggers", "Triggers"], ["yaml", "YAML"]];

export default function JobDetail({ params, query }) {
  const { region, name } = params;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "history";
  const notify = useNotify();
  const job = useAsync(() => api.getJob(region, name), [region, name]);
  const [del, setDel] = useState(false);
  const tabHref = (t) => `#/run/jobs/details/${region}/${name}` + (t === "history" ? "" : `?tab=${t}`);

  return (
    <>
      <PageHeader title="Job details" back={<IconButton aria-label="Back to jobs" href="#/run/jobs"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<PlayArrowIcon />} onClick={async () => { await api.runJob(region, name); notify.success("Execution started"); job.reload(); }}>Execute</Button>
          <Button startIcon={<EditIcon />} href="#/run/jobs/create">Edit</Button>
          <Button startIcon={<RefreshIcon />} onClick={job.reload}>Refresh</Button>
          <Button startIcon={<DeleteIcon />} color="error" onClick={() => setDel(true)}>Delete</Button>
        </>} />
      <Breadcrumbs sx={{ mb: 1 }} aria-label="Job path">
        <Typography variant="body2" color="text.secondary">Cloud Run</Typography>
        <Link href="#/run/jobs">Jobs</Link>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>{name}</Typography>
      </Breadcrumbs>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ fontSize: 22 }}>{name}</Typography>
        <Tooltip title="Copy job name"><IconButton size="small" aria-label="Copy job name" onClick={() => navigator.clipboard?.writeText(name).catch(() => {})}><ContentCopyIcon fontSize="inherit" /></IconButton></Tooltip>
      </Stack>
      {job.error ? <ErrorAlert error={job.error} title="Failed to load job" /> : job.data && (
        <Stack useFlexGap direction="row" spacing={4} sx={{ mb: 1, flexWrap: "wrap", rowGap: 1 }} aria-label="Job summary">
          <Box><Typography variant="caption" color="text.secondary">Region</Typography><Typography variant="body2">{region}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Created by</Typography><Typography variant="body2">{job.data.creator}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Labels</Typography><Typography variant="body2">{api.labelsText(job.data)}</Typography></Box>
        </Stack>
      )}
      <Tabs value={tab} onChange={(_, t) => { location.hash = tabHref(t).slice(1); }}
        variant="scrollable" scrollButtons="auto" sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Job tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {!job.data && !job.error && <Box sx={{ textAlign: "center", py: 4 }}><CircularProgress size={24} /></Box>}
      {job.data && tab === "history" && <History region={region} name={name} />}
      {job.data && tab === "observability" && <Observability region={region} name={name} />}
      {job.data && tab === "triggers" && <Triggers region={region} name={name} />}
      {job.data && tab === "yaml" && <Yaml job={job.data} />}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete job?" confirmText={name}
        onConfirm={async () => { await api.deleteJob(region, name); notify.success(`Deleted job "${name}"`); location.hash = "/run/jobs"; }}>
        <Typography variant="body2">Job <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

// ── Triggers ─────────────────────────────────────────────────────────────────────────────
// A trigger is a Cloud Scheduler job whose httpTarget names this job's own :run endpoint;
// firing it really starts an execution (see api.jobRunUri / core/aws_wire_router.py).
function Triggers({ region, name }) {
  const notify = useNotify();
  const list = useAsync(() => api.listJobTriggers(region, name), [region, name]);
  const [add, setAdd] = useState(false);
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2" sx={{ flex: 1 }}>Triggers</Typography>
        <Button startIcon={<AddIcon />} onClick={() => setAdd(true)}>Add trigger</Button>
      </Stack>
      <ResourceTable
        resourceName="triggers"
        items={list.data || []}
        rowKey={(j) => j.name}
        loading={list.loading}
        error={list.error}
        onRetry={list.reload}
        filterPlaceholder="Filter triggers"
        empty={<Typography variant="body2" color="text.secondary">No Cloud Scheduler triggers call this job yet.</Typography>}
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (j) => api.triggerId(j) },
          { id: "schedule", header: "Schedule", cell: (j) => j.schedule },
          { id: "last-run", header: "Last run", cell: (j) => j.lastAttemptTime ? fmtDate(j.lastAttemptTime) : "Has not run yet" },
          { id: "status", header: "Status", cell: (j) => j.status?.message ? "Failed" : j.lastAttemptTime ? "Succeeded" : "—" },
          { id: "actions", header: "Actions", cell: (j) => (
            <Stack direction="row" spacing={1}>
              <Button size="small" onClick={async () => { await api.runJobTriggerNow(region, api.triggerId(j)); notify.success("Trigger fired"); setTimeout(list.reload, 300); }}>Run now</Button>
              <Button size="small" color="error" onClick={async () => { await api.deleteJobTrigger(region, api.triggerId(j)); notify.success("Trigger deleted"); list.reload(); }}>Delete</Button>
            </Stack>
          ) },
        ]}
      />
      <NotSimulated compact feature="Event triggers (Eventarc)"
        note="Vyomi has no Eventarc backend; only Cloud Scheduler triggers are modelled here, and firing one really starts an execution." />
      {add && <AddTriggerDialog region={region} name={name} onClose={() => setAdd(false)} onAdded={() => { notify.success("Trigger added"); list.reload(); }} />}
    </Stack>
  );
}

function AddTriggerDialog({ region, name, onClose, onAdded }) {
  const [id, setId] = useState(`${name}-trigger`);
  const [schedule, setSchedule] = useState("0 * * * *");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const idErr = api.validName(id, "Trigger");
  const save = async () => {
    setBusy(true); setError(null);
    try { await api.createJobTrigger(region, name, id, schedule); onAdded(); onClose(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Add trigger">
      <DialogTitle>Add trigger</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">Creates a Cloud Scheduler job that calls this job's run endpoint on the schedule below.</Typography>
          <TextField label="Trigger name" required value={id} onChange={(e) => setId(e.target.value.trim())} error={!!idErr} helperText={idErr || " "} />
          <TextField label="Frequency (unix-cron)" required value={schedule} onChange={(e) => setSchedule(e.target.value)} helperText="e.g. 0 * * * * — every hour" />
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !!idErr || !schedule.trim()} onClick={save}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

// ── Observability (real counts from real executions, + real Cloud Logging entries for
// every execution start — see api.js listJobLogs) ─────────────────────────────────────────
function Observability({ region, name }) {
  const execs = useAsync(() => api.listExecutions(region, name), [region, name]);
  const logs = useAsync(() => api.listJobLogs(name), [name]);
  const list = execs.data || [];
  const succeeded = list.filter((e) => api.executionStatus(e) === "Succeeded").length;
  const failed = list.filter((e) => api.executionStatus(e) === "Failed").length;
  const tasks = list.reduce((n, e) => n + (e.taskCount || 0), 0);
  return (
    <Stack spacing={2}>
      <CapabilityContainer id="gcp.run.jobs.observability" title="Metrics">
        <Stack useFlexGap direction="row" spacing={4} sx={{ flexWrap: "wrap", rowGap: 1 }}>
          <Box><Typography variant="caption" color="text.secondary">Executions</Typography><Typography variant="h3" sx={{ fontSize: 20 }}>{list.length}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Succeeded</Typography><Typography variant="h3" sx={{ fontSize: 20 }}>{succeeded}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Failed</Typography><Typography variant="h3" sx={{ fontSize: 20 }}>{failed}</Typography></Box>
          <Box><Typography variant="caption" color="text.secondary">Tasks run</Typography><Typography variant="h3" sx={{ fontSize: 20 }}>{tasks}</Typography></Box>
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          Real counts from this job's own execution history (see the History tab) — Vyomi runs
          each task to completion synchronously, so per-task CPU/memory metrics aren't produced.
        </Typography>
      </CapabilityContainer>
      <CapabilityContainer id="gcp.run.jobs.observability" title="Logs">
        <ResourceTable
          resourceName="log entries"
          items={logs.data || []}
          rowKey={(e) => e.insertId}
          loading={logs.loading}
          error={logs.error}
          onRetry={logs.reload}
          filterPlaceholder="Filter log entries"
          empty={<Typography variant="body2" color="text.secondary">No log entries yet — execute the job to see activity here.</Typography>}
          columns={[
            { id: "time", header: "Time", sortField: "timestamp", cell: (e) => fmtDate(e.timestamp) },
            { id: "severity", header: "Severity", cell: (e) => e.severity },
            { id: "message", header: "Message", cell: (e) => e.textPayload },
          ]}
        />
      </CapabilityContainer>
    </Stack>
  );
}

// ── History ──────────────────────────────────────────────────────────────────────────────
function History({ region, name }) {
  const execs = useAsync(() => api.listExecutions(region, name), [region, name]);
  return (
    <Stack spacing={2}>
      <Typography variant="h3" component="h2">Executions</Typography>
      <ResourceTable
        resourceName="executions"
        items={execs.data || []}
        rowKey={(e) => e.name}
        loading={execs.loading}
        error={execs.error}
        onRetry={execs.reload}
        filterPlaceholder="Filter executions"
        columns={[
          { id: "execution", header: "Execution", sortField: "name", cell: (e) => e.name.split("/").pop() },
          { id: "status", header: "Status", sortValue: api.executionStatus, cell: api.executionStatus },
          { id: "created", header: "Creation time", sortField: "createTime", cell: (e) => fmtDate(e.createTime) },
          { id: "tasks", header: "Tasks", cell: (e) => e.taskCount },
          { id: "completed", header: "Completed", cell: (e) => fmtDate(e.completionTime) },
        ]}
      />
    </Stack>
  );
}

// ── YAML ─────────────────────────────────────────────────────────────────────────────────
function Yaml({ job }) {
  const yamlText = toYaml(job);
  return (
    <CapabilityContainer id="gcp.run.jobs.yaml" title="YAML">
      <TextField label="Job YAML" value={yamlText} multiline minRows={14} fullWidth
        InputProps={{ readOnly: true, sx: { fontFamily: "monospace", fontSize: 12.5 } }} />
    </CapabilityContainer>
  );
}

function toYaml(o, indent = 0) {
  const pad = "  ".repeat(indent);
  if (Array.isArray(o)) return o.map((v) => `${pad}- ${typeof v === "object" && v ? "\n" + toYaml(v, indent + 1) : v}`).join("\n");
  if (o && typeof o === "object") {
    return Object.entries(o).filter(([k]) => !k.startsWith("_")).map(([k, v]) => {
      if (v && typeof v === "object") return `${pad}${k}:\n${toYaml(v, indent + 1)}`;
      return `${pad}${k}: ${v}`;
    }).join("\n");
  }
  return `${pad}${o}`;
}
