/* Job details: the console's "Job details" card plus the header's lifecycle actions,
 * all on the native jobs.get/patch/delete/:pause/:resume/:run calls. */
import { useState } from "react";
import { Box, Button, CircularProgress, IconButton, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import PauseIcon from "@mui/icons-material/esm/Pause.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function JobDetail({ params }) {
  const { region, name } = params;
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState(false);
  const j = useAsync(() => api.getJob(region, name), [region, name]);

  const act = async (fn, msg) => {
    setBusy(true);
    try { await fn(); notify.success(msg); j.reload(); }
    catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };

  if (j.loading) return <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  if (j.error) return <ErrorAlert error={j.error} title="Failed to load job" />;
  const job = j.data;
  const paused = job.state === "PAUSED";

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back to jobs" href="#/cloudscheduler"><ArrowBackIcon /></IconButton>}
        actions={<>
          <Button startIcon={<EditIcon />} href={`#/cloudscheduler/jobs/${region}/${name}/edit`}>Edit</Button>
          <Button startIcon={<PlayArrowIcon />} disabled={busy || paused} onClick={() => act(() => api.runJob(region, name), "Job run")}>Force run</Button>
          <Button startIcon={paused ? <PlayArrowIcon /> : <PauseIcon />} disabled={busy}
            onClick={() => act(() => (paused ? api.resumeJob(region, name) : api.pauseJob(region, name)), paused ? "Job resumed" : "Job paused")}>
            {paused ? "Resume" : "Pause"}
          </Button>
          <Button startIcon={<RefreshIcon />} onClick={j.reload}>Refresh</Button>
          <Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>
        </>} />
      <Section title="Job details">
        <KeyValue items={[
          ["Name", name],
          ["Region", region],
          ["Frequency", job.schedule],
          ["Timezone", job.timeZone || "Etc/UTC"],
          ["Target", `${api.targetKind(job)} — ${api.targetText(job)}`, <CapabilityBadge key="tgt" id="gcp.cloudscheduler.jobs.targets" />],
          ["State", api.stateLabel(job)],
          ["Last run", api.lastRunText(job)],
          ["Next run", api.nextRunText(job)],
        ]} />
      </Section>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete job?" confirmText={name}
        warning="This can't be undone."
        onConfirm={async () => { await api.deleteJob(region, name); notify.success(`Deleted job "${name}"`); location.hash = "/cloudscheduler"; }}>
        <Typography variant="body2">Job <b>{name}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
