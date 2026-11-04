/* Jobs — Cloud Run Jobs (run-to-completion containers), native Cloud Run Admin API v2. */
import { useState } from "react";
import { Button, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Jobs() {
  const notify = useNotify();
  const project = useProject();
  const region = api.getRegion();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data: jobs = [], loading, error, reload } = useAsync(() => api.listJobs(region), [project, region]);
  const rows = jobs.map((j) => ({ ...j, _id: j.name.split("/").pop() }));

  const runSelected = async () => {
    for (const id of sel) {
      try { await api.runJob(region, id); } catch (e) { notify.error(e); }
    }
    notify.success(sel.length === 1 ? `Started an execution of "${sel[0]}"` : `Started ${sel.length} executions`);
    reload();
  };

  return (
    <>
      <PageHeader title="Jobs" actions={<>
        <Button startIcon={<CloudUploadIcon />} href="#/run/create">Deploy container</Button>
        <Button startIcon={<AddIcon />} variant="contained" href="#/run/jobs/create">Create job</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<PlayArrowIcon />} disabled={!sel.length} onClick={runSelected}>Execute</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="jobs"
        items={rows}
        rowKey={(j) => j._id}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter jobs"
        columns={[
          { id: "name", header: "Name", sortField: "_id", cell: (j) => <Link href={hashHref("run", "jobs", "details", api.regionOf(j.name), j._id)}>{j._id}</Link> },
          { id: "status", header: "Status of last execution", cell: api.lastExecutionStatus },
          { id: "executed", header: "Last executed", cell: (j) => fmtDate(api.lastExecutedAt(j)) },
          { id: "region", header: "Region", cell: (j) => api.regionOf(j.name) },
          { id: "cost", header: "Cost", cell: () => "—" },
          { id: "by", header: "Created by", sortField: "creator", cell: (j) => j.creator },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center" sx={{ py: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>Execute jobs on a fully managed platform</Typography>
            <Typography variant="body2" color="text.secondary">Run a container to completion as a job.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/run/jobs/create">Create job</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete job?" : `Delete ${sel.length} jobs?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const id of sel) await api.deleteJob(region, id);
          notify.success(sel.length === 1 ? "Deleted job" : `Deleted ${sel.length} jobs`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
