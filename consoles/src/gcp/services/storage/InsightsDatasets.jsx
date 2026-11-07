/* Insights datasets — Storage Intelligence dataset configs. Creating one really exports the matching buckets/objects into a
 * linked BigQuery dataset (core/gcp_bigquery_core.py) that you can query with SQL below; Refresh re-runs the export. */
import { useState } from "react";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
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

export default function InsightsDatasets() {
  const notify = useNotify();
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(null);
  const { data = [], loading, error, reload } = useAsync(api.listInsightsDatasets, []);

  return (
    <>
      <PageHeader title={<Stack direction="row" spacing={1} alignItems="center"><span>Insights datasets</span><CapabilityBadge id="gcp.storage.insights-datasets" /></Stack>}
        actions={<>
          <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create dataset config</Button>
          <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        </>} />
      <ResourceTable
        resourceName="dataset configs"
        items={data}
        rowKey={(d) => d.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter dataset configs"
        columns={[
          { id: "name", header: "Display name", sortField: "displayName", cell: (d) => d.displayName },
          { id: "prefix", header: "Source bucket prefix", cell: (d) => d.sourceBucketPrefix || "—" },
          { id: "state", header: "State", cell: (d) => d.state },
          { id: "bq", header: "BigQuery dataset", cell: (d) => d.link?.dataset?.split("/").pop() },
          { id: "rows", header: "Exported objects", cell: (d) => d.tableRowCounts?.object_attributes_view ?? 0 },
          { id: "refreshed", header: "Last refresh", cell: (d) => fmtDate(d.lastRefreshTime) },
          { id: "ref", header: "", cell: (d) => <Button size="small" onClick={async () => { try { await api.refreshInsightsDataset(d.name.split("/").pop()); notify.success("Export refreshed"); reload(); } catch (e) { notify.error(e); } }}>Refresh export</Button> },
          { id: "created", header: "Created", sortField: "createTime", cell: (d) => fmtDate(d.createTime) },
          { id: "del", header: "", cell: (d) => <Button size="small" startIcon={<DeleteIcon />} onClick={() => setDel(d)}>Delete</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No dataset configs yet.</Typography>}
      />
      <QueryPanel datasets={data} />
      {create && <CreateDatasetDialog onClose={() => setCreate(false)} onSave={async (body) => {
        try { await api.createInsightsDataset(body); notify.success("Dataset config created"); reload(); } catch (e) { notify.error(e); }
      }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete dataset config?" actionLabel="Delete"
        onConfirm={async () => { await api.deleteInsightsDataset(del.name.split("/").pop()); notify.success("Dataset config deleted"); setDel(null); reload(); }}>
        <Typography variant="body2"><b>{del?.displayName}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function CreateDatasetDialog({ onClose, onSave }) {
  const [displayName, setDisplayName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = displayName.trim().length > 0;
  const save = async () => {
    setBusy(true); setError(null);
    try { await onSave({ displayName: displayName.trim(), sourceBucketPrefix: prefix }); onClose(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-label="Create dataset config">
      <DialogTitle>Create dataset config</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <TextField label="Source bucket prefix" value={prefix} onChange={(e) => setPrefix(e.target.value)} helperText="Buckets whose name starts with this prefix feed the dataset." />
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

function QueryPanel({ datasets }) {
  const first = datasets[0]?.link?.dataset?.split("/").pop();
  const [sql, setSql] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const q = sql || (first ? `SELECT bucket, COUNT(*) AS objects, SUM(size) AS bytes FROM \`${first}.object_attributes_view\` GROUP BY bucket` : "");
  if (!first) return null;
  return (
    <Stack spacing={1} sx={{ mt: 3 }}>
      <Typography variant="h3" component="h2">Query the exported inventory (BigQuery)</Typography>
      <TextField multiline minRows={2} value={q} onChange={(e) => setSql(e.target.value)} inputProps={{ "aria-label": "SQL" }} />
      <Stack direction="row" spacing={1}><Button variant="contained" onClick={async () => { setErr(null); try { setRes(await api.bqQuery(q)); } catch (e) { setErr(e); } }}>Run query</Button></Stack>
      {err && <Alert severity="error">{err.message}</Alert>}
      {res && (
        <ResourceTable resourceName="rows" items={(res.rows || []).map((r, i) => ({ i, c: r.f.map((x) => x.v) }))} rowKey={(r) => r.i}
          columns={res.schema.fields.map((f, k) => ({ id: f.name, header: f.name, cell: (r) => String(r.c[k] ?? "") }))} />
      )}
      <Typography variant="caption" color="text.secondary">Queries run on SQLite over the exported tables (bucket_attributes_view, object_attributes_view, project_attributes_view), not GoogleSQL.</Typography>
    </Stack>
  );
}
