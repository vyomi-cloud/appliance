/* Jobs — the console's Cloud Scheduler landing page: tabs (Scheduler jobs / Cron jobs),
 * the jobs table (every region merged into one list, as the real console shows it) and
 * the bulk/row lifecycle actions. */
import { useState } from "react";
import { Button, Chip, IconButton, Menu, MenuItem, Stack, Tab, Tabs, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import PauseIcon from "@mui/icons-material/esm/Pause.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const STATE_COLOR = { ENABLED: "success", PAUSED: "default", DISABLED: "default", UPDATE_FAILED: "error" };

export default function Jobs({ query }) {
  const tab = query.tab === "cron" ? "cron" : "jobs";
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.listAllJobs(), [project]);

  return (
    <>
      <PageHeader title="Cloud Scheduler" actions={<>
        <Button startIcon={<AddIcon />} href="#/cloudscheduler/jobs/new">Create job</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = hashHref("cloudscheduler", "jobs") + (t === "cron" ? "?tab=cron" : ""); }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Cloud Scheduler tabs">
        <Tab value="jobs" label="Scheduler jobs" />
        <Tab value="cron" label="Cron jobs" />
      </Tabs>
      {tab === "jobs"
        ? <JobsTable data={data} loading={loading} error={error} reload={reload} />
        : <CronJobsTab />}
    </>
  );
}

/** The "Cron jobs" tab: legacy App Engine cron.yaml jobs. Real console affordance is
 * read-only (jobs arrive via `gcloud app deploy cron.yaml`, not a console form) plus
 * "Run now" — no create/pause/delete here, matching the real UI. */
function CronJobsTab() {
  const project = useProject();
  const { data = [], loading, error, reload } = useAsync(() => api.listLegacyCronJobs(), [project]);
  const notify = useNotify();

  const run = async (j) => {
    try { await api.runJob(api.jobRegion(j), api.jobId(j)); notify.success(`Ran ${api.jobId(j)}`); }
    catch { notify.error(`${api.jobId(j)} failed to run`); }
    reload();
  };

  return (
    <CapabilityContainer id="gcp.cloudscheduler.cron-jobs" title="Cron jobs">
      <ResourceTable
        resourceName="cron jobs"
        items={data}
        rowKey={(j) => j.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter cron jobs"
        columns={[
          { id: "description", header: "Description", sortValue: (j) => j.description || "", cell: (j) => j.description || "No description" },
          { id: "target", header: "Target", cell: api.targetText },
          { id: "schedule", header: "Schedule", cell: (j) => j.schedule },
          { id: "timezone", header: "Time zone", cell: (j) => j.timeZone || "Etc/UTC" },
          { id: "lastRun", header: "Last run", sortValue: api.lastRunText, cell: api.lastRunText },
          { id: "lastResult", header: "Last run result", cell: api.lastResultText },
          { id: "nextRun", header: "Next scheduled run", cell: api.nextRunText },
          { id: "actions", header: "Actions", cell: (j) => <Button size="small" startIcon={<PlayArrowIcon />} onClick={() => run(j)}>Run now</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">There are no cron.yaml jobs deployed for this App Engine app.</Typography>}
      />
    </CapabilityContainer>
  );
}

function JobsTable({ data, loading, error, reload }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [menu, setMenu] = useState(null);   // {anchor, job}

  const run = async (jobs, fn, verb) => {
    let ok = 0, fail = 0;
    for (const job of jobs) { try { await fn(job); ok++; } catch { fail++; } }
    if (ok) notify.success(`${verb} ${ok} job${ok === 1 ? "" : "s"}`);
    if (fail) notify.error(`${fail} job${fail === 1 ? "" : "s"} failed to ${verb.toLowerCase()}`);
    setSel([]); reload();
  };
  const selectedJobs = () => data.filter((j) => sel.includes(j.name));

  return (
    <>
      <Stack useFlexGap direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: "wrap" }}>
        <Button startIcon={<PlayArrowIcon />} disabled={!sel.length} onClick={() => run(selectedJobs(), (j) => api.runJob(api.jobRegion(j), api.jobId(j)), "Ran")}>Force run</Button>
        <Button startIcon={<PauseIcon />} disabled={!sel.length} onClick={() => run(selectedJobs(), (j) => api.pauseJob(api.jobRegion(j), api.jobId(j)), "Paused")}>Pause</Button>
        <Button startIcon={<PlayArrowIcon />} disabled={!sel.length} onClick={() => run(selectedJobs(), (j) => api.resumeJob(api.jobRegion(j), api.jobId(j)), "Resumed")}>Resume</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </Stack>
      <ResourceTable
        resourceName="jobs"
        items={data}
        rowKey={(j) => j.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter jobs"
        columns={[
          { id: "name", header: "Name", sortValue: api.jobId, cell: (j) => <Link href={hashHref("cloudscheduler", "jobs", api.jobRegion(j), api.jobId(j))}>{api.jobId(j)}</Link> },
          { id: "region", header: "Region", sortValue: api.jobRegion, cell: api.jobRegion },
          { id: "state", header: "State", sortValue: api.stateLabel, cell: (j) => <Chip size="small" label={api.stateLabel(j)} color={STATE_COLOR[j.state] || "default"} variant={j.state === "ENABLED" ? "filled" : "outlined"} /> },
          { id: "description", header: "Description", cell: (j) => j.description || "No description" },
          { id: "frequency", header: "Frequency", cell: (j) => j.schedule },
          { id: "target", header: "Target", cell: api.targetText },
          { id: "lastRun", header: "Last run", sortValue: api.lastRunText, cell: api.lastRunText },
          { id: "lastResult", header: "Last run result", cell: api.lastResultText },
          { id: "nextRun", header: "Next run", cell: api.nextRunText },
          { id: "actions", header: "Actions", cell: (j) => <IconButton size="small" aria-label={`Actions for ${api.jobId(j)}`} onClick={(e) => setMenu({ anchor: e.currentTarget, job: j })}><MoreVertIcon fontSize="small" /></IconButton> },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no scheduler jobs in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/cloudscheduler/jobs/new">Create job</Button>
          </Stack>
        }
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        {menu && [
          <MenuItem key="edit" component="a" href={`#/cloudscheduler/jobs/${api.jobRegion(menu.job)}/${api.jobId(menu.job)}/edit`} onClick={() => setMenu(null)}>Edit</MenuItem>,
          <MenuItem key="run" disabled={menu.job.state === "PAUSED"} onClick={() => { const j = menu.job; setMenu(null); run([j], (x) => api.runJob(api.jobRegion(x), api.jobId(x)), "Ran"); }}>Force run</MenuItem>,
          <MenuItem key="pr" onClick={() => { const j = menu.job; setMenu(null); run([j], (x) => x.state === "PAUSED" ? api.resumeJob(api.jobRegion(x), api.jobId(x)) : api.pauseJob(api.jobRegion(x), api.jobId(x)), j.state === "PAUSED" ? "Resumed" : "Paused"); }}>
            {menu.job.state === "PAUSED" ? "Resume" : "Pause"}
          </MenuItem>,
          <MenuItem key="del" onClick={() => { setSel([menu.job.name]); setMenu(null); setDel(true); }}>Delete</MenuItem>,
        ]}
      </Menu>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete job?" : `Delete ${sel.length} jobs?`}
        confirmText={sel.length === 1 ? api.jobId(selectedJobs()[0]) : "DELETE"}
        warning="This can't be undone."
        onConfirm={() => run(selectedJobs(), (j) => api.deleteJob(api.jobRegion(j), api.jobId(j)), "Deleted")}
      >
        <Typography variant="body2">{selectedJobs().map(api.jobId).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
