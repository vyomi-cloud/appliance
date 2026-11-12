/* Batch Operations — bulk Delete / SetStorageClass jobs over a bucket+prefix, real and
 * synchronous against core/gcp_storage_core.py's batchOperations sub-resource. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel, MenuItem, Radio, RadioGroup, FormControlLabel, Select, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function BatchOperations() {
  const notify = useNotify();
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(null);
  const { data = [], loading, error, reload } = useAsync(api.listBatchJobs, []);

  return (
    <>
      <PageHeader title={<Stack direction="row" spacing={1} alignItems="center"><span>Batch operations</span><CapabilityBadge id="gcp.storage.batch-operations" /></Stack>}
        actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create job</Button>
          <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        </>} />
      <ResourceTable
        resourceName="jobs"
        items={data}
        rowKey={(j) => j.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter jobs"
        columns={[
          { id: "name", header: "Job", cell: (j) => j.name.split("/").pop() },
          { id: "bucket", header: "Bucket", sortField: "bucket", cell: (j) => j.bucket },
          { id: "prefix", header: "Prefix", sortField: "prefix", cell: (j) => j.prefix || "—" },
          { id: "action", header: "Action", cell: (j) => j.action.type === "Delete" ? "Delete" : `Set class to ${j.action.storageClass}` },
          { id: "state", header: "State", cell: (j) => j.state },
          { id: "counts", header: "Objects", cell: (j) => `${j.counts.succeeded} succeeded / ${j.counts.failed} failed / ${j.counts.matched} matched` },
          { id: "created", header: "Created", sortField: "createTime", cell: (j) => fmtDate(j.createTime) },
          { id: "del", header: "", cell: (j) => <Button size="small" startIcon={<DeleteIcon />} onClick={() => setDel(j)}>Delete</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No batch jobs yet. Create one to bulk-edit objects under a bucket and prefix.</Typography>}
      />
      {create && <CreateJobDialog onClose={() => setCreate(false)} onSave={async (body) => {
        try { await api.createBatchJob(body); notify.success("Batch job created"); reload(); } catch (e) { notify.error(e); }
      }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete job record?" actionLabel="Delete"
        onConfirm={async () => { await api.deleteBatchJob(del.name.split("/").pop()); notify.success("Job record deleted"); setDel(null); reload(); }}>
        <Typography variant="body2">This only removes the job's record — it already ran.</Typography>
      </DeleteDialog>
    </>
  );
}

function CreateJobDialog({ onClose, onSave }) {
  const [bucket, setBucket] = useState("");
  const [prefix, setPrefix] = useState("");
  const [action, setAction] = useState("Delete");
  const [storageClass, setStorageClass] = useState("NEARLINE");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = bucket.trim().length > 0;
  const save = async () => {
    setBusy(true); setError(null);
    try {
      await onSave({ bucket: bucket.trim(), prefix, action: action === "Delete" ? { type: "Delete" } : { type: "SetStorageClass", storageClass } });
      onClose();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Create batch job">
      <DialogTitle>Create job</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Bucket" value={bucket} onChange={(e) => setBucket(e.target.value)} helperText="Objects under this bucket (and prefix) will be edited immediately." />
          <TextField label="Prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} helperText="Only objects whose name starts with this prefix are matched." />
          <RadioGroup value={action} onChange={(e) => setAction(e.target.value)} aria-label="Batch action">
            <FormControlLabel value="Delete" control={<Radio size="small" />} label="Delete matching objects" />
            <FormControlLabel value="SetStorageClass" control={<Radio size="small" />} label="Set storage class" />
          </RadioGroup>
          {action === "SetStorageClass" && (
            <FormControl><InputLabel id="bj-class">Storage class</InputLabel>
              <Select labelId="bj-class" label="Storage class" value={storageClass} onChange={(e) => setStorageClass(e.target.value)}>
                {["NEARLINE", "COLDLINE", "ARCHIVE", "STANDARD"].map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
              </Select>
            </FormControl>
          )}
          {error && <Typography color="error" variant="body2">{error.message}</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !ok} onClick={save}>Create</Button>
      </DialogActions>
    </Dialog>
  );
}
