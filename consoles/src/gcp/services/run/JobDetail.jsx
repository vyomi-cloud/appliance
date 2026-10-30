/* Job details: summary strip + tabs (History, Observability, Triggers, YAML), native
 * Cloud Run Admin API v2. History lists executions, each a real run-to-completion job. */
import { useState } from "react";
import { Box, Breadcrumbs, Button, CircularProgress, IconButton, Stack, Tab, Tabs, TextField, Tooltip, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, fmtDate, PageHeader } from "../../kit/common.jsx";
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
        <Stack direction="row" spacing={4} sx={{ mb: 1, flexWrap: "wrap", rowGap: 1 }} aria-label="Job summary">
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
      {job.data && tab === "observability" && <CapabilityContainer id="gcp.run.jobs.observability" title="Observability" />}
      {job.data && tab === "triggers" && <CapabilityContainer id="gcp.run.jobs.triggers" title="Triggers" />}
      {job.data && tab === "yaml" && <Yaml job={job.data} />}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete job?" confirmText={name}
        onConfirm={async () => { await api.deleteJob(region, name); notify.success(`Deleted job "${name}"`); location.hash = "/run/jobs"; }}>
        <Typography variant="body2">Job <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
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
