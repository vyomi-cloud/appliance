/* Worker pools — Cloud Run worker pools (background containers with no ingress), native
 * Cloud Run Admin API v2. */
import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function WorkerPools() {
  const notify = useNotify();
  const project = useProject();
  const region = api.getRegion();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const { data: rows = [], loading, error, reload } = useAsync(async () => {
    const wps = await api.listWorkerPools(region);
    return wps.map((w) => ({ ...w, _id: api.idOf(w.name) }));
  }, [project, region]);

  return (
    <>
      <PageHeader title="Worker pools" actions={<>
        <Button startIcon={<CloudUploadIcon />} href="#/run/create">Deploy container</Button>
        <Button startIcon={<AddIcon />} variant="contained" onClick={() => setCreate(true)}>Create worker pool</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="worker pools"
        items={rows}
        rowKey={(w) => w._id}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "_id", cell: (w) => w._id },
          { id: "type", header: "Deployment type", cell: () => "Container" },
          { id: "region", header: "Region", cell: (w) => api.regionOf(w.name) },
          { id: "cost", header: "Cost", cell: () => "—" },
          { id: "updated", header: "Last updated", sortField: "updateTime", cell: (w) => fmtDate(w.updateTime) },
          { id: "instances", header: "Instances", cell: api.workerPoolInstances },
          { id: "by", header: "Modified by", sortField: "lastModifier", cell: (w) => w.lastModifier },
          { id: "labels", header: "Labels", wrap: true, cell: api.labelsText },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center" sx={{ py: 2 }}>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>Run your non-request workload on a fully managed platform</Typography>
            <Typography variant="body2" color="text.secondary">Run containers that don't serve HTTP traffic, like queue consumers.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create worker pool</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete worker pool?" : `Delete ${sel.length} worker pools?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const id of sel) await api.deleteWorkerPool(region, id);
          notify.success(sel.length === 1 ? "Deleted worker pool" : `Deleted ${sel.length} worker pools`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      {create && <CreateWorkerPoolDialog region={region} onClose={() => setCreate(false)} onCreated={() => { notify.success("Worker pool created"); reload(); }} />}
    </>
  );
}

function CreateWorkerPoolDialog({ region, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [image, setImage] = useState(api.DEFAULT_IMAGE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = api.validName(name, "Worker pool");
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createWorkerPool(region, name, { template: { containers: [{ image }] } });
      onCreated(); onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Create worker pool">
      <DialogTitle>Create worker pool</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Worker pool name" required value={name} onChange={(e) => setName(e.target.value.trim())} error={!!name && !!nameErr} helperText={name ? nameErr : " "} />
          <TextField label="Container image URL" required value={image} onChange={(e) => setImage(e.target.value)} />
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
