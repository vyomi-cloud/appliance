/* Log bucket details — bucket summary + its Log views (real buckets/views CRUD). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function BucketDetail({ params, query }) {
  const name = params.name;
  const location_ = query.loc || "global";
  const [editOpen, setEditOpen] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const [viewOpen, setViewOpen] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const notify = useNotify();
  const b = useAsync(() => api.getBucket(name, location_), [name, location_]);
  const views = useAsync(() => api.listViews(name, location_), [name, location_]);

  return (
    <>
      <PageHeader title={name} back={<IconButton aria-label="Back to Logs Storage" href="#/logs/storage"><ArrowBackIcon /></IconButton>} actions={<>
        <Button onClick={() => setEditOpen(true)}>Edit bucket</Button>
        <Button startIcon={<DeleteIcon />} onClick={() => setDelOpen(true)}>Delete bucket</Button>
        <Button href={`#/logs/query`}>View logs</Button>
        <Button onClick={() => setUsageOpen(true)}>View usage data</Button>
        <Button startIcon={<RefreshIcon />} onClick={() => { b.reload(); views.reload(); }}>Refresh</Button>
      </>} />
      <ErrorAlert error={b.error} title="Failed to load bucket" />
      {b.data && (
        <Stack spacing={2}>
          <Section title="Bucket details">
            <KeyValue items={[
              ["Name", api.bucketId(b.data.name)],
              ["Description", b.data.description || "—"],
              ["Retention period", `${b.data.retentionDays} days`],
              ["Region", api.bucketLocation(b.data.name)],
              ["Observability Analytics", b.data.analyticsEnabled ? "Enabled" : "Disabled"],
              ["BigQuery analysis", b.data.bigQueryDataset || "Not linked"],
              ["Tags", "—"],
            ]} />
          </Section>
          <Section title="Log views" actions={<Button startIcon={<AddIcon />} onClick={() => setViewOpen(true)}>Create log view</Button>}>
            <ErrorAlert error={views.error} title="Failed to load log views" />
            <ResourceTable resourceName="log views" items={views.data || []} rowKey={(v) => v.name} loading={views.loading} dense
              filterPlaceholder="Filter"
              columns={[
                { id: "name", header: "Name", cell: (v) => v.name.split("/views/")[1] },
                { id: "description", header: "Description", cell: (v) => v.description || "—" },
                { id: "updated", header: "Last updated", cell: (v) => fmtDate(v.updateTime) },
                { id: "actions", header: "", cell: (v) => (
                  <IconButton size="small" aria-label={`Delete view ${v.name.split("/views/")[1]}`}
                    onClick={async () => { await api.deleteView(name, v.name.split("/views/")[1], location_); views.reload(); }}>
                    <DeleteIcon fontSize="inherit" />
                  </IconButton>
                ) },
              ]}
              empty={<Typography variant="body2" color="text.secondary">No rows to display</Typography>} />
          </Section>
        </Stack>
      )}
      {editOpen && (
        <EditDialog bucket={b.data} onClose={() => setEditOpen(false)} onSave={async (body) => {
          await api.patchBucket(name, body, undefined, location_);
          notify.success("Bucket updated"); b.reload();
        }} />
      )}
      {viewOpen && (
        <ViewDialog onClose={() => setViewOpen(false)} onSave={async (viewId, body) => {
          await api.createView(name, viewId, body, location_);
          notify.success(`Created log view "${viewId}"`); views.reload();
        }} />
      )}
      <DeleteDialog open={delOpen} onClose={() => setDelOpen(false)} title="Delete log bucket?" confirmText={name}
        onConfirm={async () => { await api.deleteBucket(name, location_); notify.success(`Deleted bucket "${name}"`); location.hash = "#/logs/storage"; }}>
        <Typography variant="body2">Bucket <b>{name}</b> and every log view on it will be permanently deleted.</Typography>
      </DeleteDialog>
      {usageOpen && <ViewUsageDataDialog onClose={() => setUsageOpen(false)} />}
    </>
  );
}

function ViewUsageDataDialog({ onClose }) {
  const points = useAsync(() => api.usageTimeSeries(30), []);
  const rows = (points.data || []).slice().reverse();
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>View usage data</DialogTitle>
      <DialogContent>
        <CapabilityContainer id="gcp.logs.storage.usage_alerts" title="Usage data">
          <ErrorAlert error={points.error} title="Failed to load usage data" />
          <ResourceTable
            resourceName="usage samples"
            items={rows}
            rowKey={(p) => p.interval.endTime}
            loading={points.loading}
            dense
            columns={[
              { id: "time", header: "Time", cell: (p) => fmtDate(p.interval.endTime) },
              { id: "bytes", header: "Project log bytes (month-to-date)", cell: (p) => fmtBytes(Number(p.value.int64Value)) },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No usage data yet — write some log entries first.</Typography>}
          />
        </CapabilityContainer>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

function EditDialog({ bucket, onClose, onSave }) {
  const [description, setDescription] = useState(bucket?.description || "");
  const [retention, setRetention] = useState(bucket?.retentionDays || 30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit bucket</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
          <TextField label="Retention period" type="number" helperText="days" value={retention} onChange={(e) => setRetention(e.target.value)} />
          <ErrorAlert error={error} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await onSave({ description, retentionDays: Number(retention) || 30 }); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}

function ViewDialog({ onClose, onSave }) {
  const [id, setId] = useState("");
  const [description, setDescription] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create log view</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="View ID" required value={id} onChange={(e) => setId(e.target.value.trim())} />
          <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
          <TextField label="Filter" multiline minRows={2} value={filter} onChange={(e) => setFilter(e.target.value)} />
          <ErrorAlert error={error} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !id.trim()} onClick={async () => {
          setBusy(true); setError(null);
          try { await onSave(id.trim(), { description, filter }); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>Create</Button>
      </DialogActions>
    </Dialog>
  );
}
