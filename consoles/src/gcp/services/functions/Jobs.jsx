/* Jobs — Cloud Run Jobs (run-to-completion containers), native Cloud Run Admin API v2. */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem,
  Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Jobs() {
  const notify = useNotify();
  const project = useProject();
  const region = api.getRegion();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data: jobs = [], loading, error, reload } = useAsync(() => api.listJobs(region), [project, region]);
  const rows = jobs.map((j) => ({ ...j, _id: j.name.split("/").pop() }));

  return (
    <>
      <PageHeader title="Jobs" actions={<>
        <Button startIcon={<AddIcon />} variant="contained" onClick={() => setCreate(true)}>Create job</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="jobs"
        items={rows}
        rowKey={(j) => j.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter jobs"
        columns={[
          { id: "name", header: "Name", sortField: "_id", cell: (j) => j._id },
          { id: "executions", header: "Executions", sortField: "executionCount", cell: (j) => j.executionCount },
          { id: "created", header: "Created", sortField: "createTime", cell: (j) => fmtDate(j.createTime) },
          { id: "actions", header: "Actions", cell: (j) => (
            <Button size="small" startIcon={<PlayArrowIcon fontSize="small" />} onClick={async () => {
              try { await api.runJob(region, j._id); notify.success(`Started an execution of "${j._id}"`); reload(); }
              catch (e) { notify.error(e); }
            }}>Execute</Button>
          ) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center" sx={{ py: 2 }}>
            <Typography variant="body2" color="text.secondary">Run a container to completion as a job.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create job</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete job?" : `Delete ${sel.length} jobs?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const n of sel) await api.deleteJob(region, rows.find((r) => r.name === n)._id);
          notify.success(sel.length === 1 ? "Deleted job" : `Deleted ${sel.length} jobs`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.map((n) => rows.find((r) => r.name === n)?._id).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      {create && <CreateJobDialog region={region} onClose={() => setCreate(false)} onCreated={() => { notify.success("Job created"); reload(); }} />}
    </>
  );
}

function CreateJobDialog({ region, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [image, setImage] = useState(api.DEFAULT_IMAGE);
  const [taskCount, setTaskCount] = useState("1");
  const [memory, setMemory] = useState("512Mi");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = api.validServiceName(name);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createJob(region, name, {
        template: { taskCount: Number(taskCount) || 1, template: { containers: [{ image, resources: { limits: { memory } } }] } },
      });
      onCreated(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Create job">
      <DialogTitle>Create job</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Job name" required value={name} onChange={(e) => setName(e.target.value.trim())} error={!!name && !!nameErr} helperText={name ? nameErr : " "} />
          <TextField label="Container image URL" required value={image} onChange={(e) => setImage(e.target.value)} />
          <Stack direction="row" spacing={2}>
            <TextField label="Task count" type="number" value={taskCount} onChange={(e) => setTaskCount(e.target.value)} sx={{ width: 180 }} />
            <FormControl sx={{ width: 180 }}><InputLabel id="jm-l">Memory</InputLabel>
              <Select labelId="jm-l" label="Memory" value={memory} onChange={(e) => setMemory(e.target.value)}>
                {api.MEMORIES.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
              </Select>
            </FormControl>
          </Stack>
          {error && <Alert severity="error">{error.message}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name || !!nameErr} onClick={submit}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
