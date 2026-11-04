/* Bucket "Inventory reports" tab — Storage Insights report configs for this bucket + the reports they generated. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const dstr = (d) => d ? `${d.year}-${String(d.month).padStart(2, "0")}-${String(d.day).padStart(2, "0")}` : "";

export default function InventoryReports({ bucket, bucketMeta }) {
  const notify = useNotify();
  const loc = (bucketMeta?.location || "US").toLowerCase();
  const { data, loading, error, reload } = useAsync(() => api.listReportConfigs(loc, bucket), [bucket, loc]);
  const [create, setCreate] = useState(false);
  const [open, setOpen] = useState(null);       // config whose reports are shown
  const run = async (c) => { try { await api.runReportConfig(c.name); notify.success("Report generated"); setOpen(c); reload(); } catch (e) { notify.error(e); } };
  const del = async (c) => { try { await api.deleteReportConfig(c.name); notify.success(`Deleted ${c.name.split("/").pop()}`); if (open?.name === c.name) setOpen(null); reload(); } catch (e) { notify.error(e); } };
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2">Inventory report configurations</Typography>
        <CapabilityBadge id="gcp.storage.inventory-reports" />
        <span style={{ flex: 1 }} />
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create configuration</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <ErrorAlert error={error} title="Failed to list report configurations" />
      <ResourceTable resourceName="report configurations" items={data || []} rowKey={(c) => c.name} loading={loading} dense
        filterPlaceholder="Filter configurations"
        columns={[
          { id: "name", header: "Name", cell: (c) => c.name.split("/").pop() },
          { id: "display", header: "Display name", cell: (c) => c.displayName },
          { id: "freq", header: "Frequency", cell: (c) => c.frequencyOptions.frequency },
          { id: "range", header: "Active", cell: (c) => `${dstr(c.frequencyOptions.startDate)} to ${dstr(c.frequencyOptions.endDate)}` },
          { id: "dest", header: "Destination", cell: (c) => `gs://${c.objectMetadataReportOptions.storageDestinationOptions.bucket}/${c.objectMetadataReportOptions.storageDestinationOptions.destinationPath || ""}` },
          { id: "actions", header: "Actions", cell: (c) => (
            <Stack direction="row" spacing={0.5}>
              <Button size="small" onClick={() => setOpen(c)}>View reports</Button>
              <Button size="small" onClick={() => run(c)}>Generate now</Button>
              <Button size="small" color="error" onClick={() => del(c)}>Delete</Button>
            </Stack>) },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No inventory report configurations for this bucket.</Typography>} />
      {open && <Reports cfg={open} key={open.name} />}
      {create && <CreateDialog bucket={bucket} loc={loc} onClose={() => setCreate(false)} onDone={(c) => { setCreate(false); notify.success("Created report configuration"); setOpen(c); reload(); }} />}
    </Stack>
  );
}

function Reports({ cfg }) {
  const { data, loading, error, reload } = useAsync(() => api.listReportDetails(cfg.name), [cfg.name]);
  return (
    <Stack spacing={1}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h3" component="h2">Reports from {cfg.name.split("/").pop()}</Typography>
        <span style={{ flex: 1 }} />
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <ErrorAlert error={error} title="Failed to list reports" />
      <ResourceTable resourceName="reports" items={data || []} rowKey={(d) => d.name} loading={loading} dense
        columns={[
          { id: "t", header: "Snapshot time", sortValue: (d) => d.snapshotTime, cell: (d) => fmtDate(d.snapshotTime) },
          { id: "s", header: "Status", cell: (d) => d.status?.code ? `Error: ${d.status.message}` : "Succeeded" },
          { id: "r", header: "Rows", cell: (d) => d.rowCount },
          { id: "p", header: "Report path", cell: (d) => d.reportPathPrefix },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No reports yet.</Typography>} />
    </Stack>
  );
}

function CreateDialog({ bucket, loc, onClose, onDone }) {
  const buckets = useAsync(() => api.listBuckets(), []);
  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);
  const [id, setId] = useState("inventory-" + String(Date.now()).slice(-5));
  const [freq, setFreq] = useState("DAILY");
  const [start, setStart] = useState(iso(today));
  const [end, setEnd] = useState(iso(new Date(today.getTime() + 90 * 864e5)));
  const [dest, setDest] = useState("");
  const [path, setPath] = useState("inventory");
  const [fields, setFields] = useState(["project", "bucket", "name", "size", "storageClass", "updated"]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const parts = (s) => { const [y, m, d] = s.split("-").map(Number); return { year: y, month: m, day: d }; };
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const c = await api.createReportConfig(loc, id, {
        displayName: id, frequencyOptions: { frequency: freq, startDate: parts(start), endDate: parts(end) },
        csvOptions: { recordSeparator: "\n", delimiter: ",", headerRequired: true },
        objectMetadataReportOptions: { metadataFields: fields, storageFilters: { bucket }, storageDestinationOptions: { bucket: dest, destinationPath: path } },
      });
      onDone(c);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="inv-title">
      <DialogTitle id="inv-title">Create inventory report configuration</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Configuration name" value={id} onChange={(e) => setId(e.target.value)} inputProps={{ "aria-label": "Configuration name" }} />
          <Select size="small" value={freq} onChange={(e) => setFreq(e.target.value)} inputProps={{ "aria-label": "Frequency" }}>
            <MenuItem value="DAILY">Daily</MenuItem><MenuItem value="WEEKLY">Weekly</MenuItem>
          </Select>
          <Stack direction="row" spacing={1}>
            <TextField type="date" label="Start date" value={start} onChange={(e) => setStart(e.target.value)} InputLabelProps={{ shrink: true }} />
            <TextField type="date" label="End date" value={end} onChange={(e) => setEnd(e.target.value)} InputLabelProps={{ shrink: true }} />
          </Stack>
          <Select size="small" displayEmpty value={dest} onChange={(e) => setDest(e.target.value)} inputProps={{ "aria-label": "Destination bucket" }} renderValue={(v) => v || "Select destination bucket"}>
            {(buckets.data || []).map((b) => <MenuItem key={b.name} value={b.name}>{b.name}</MenuItem>)}
          </Select>
          <TextField label="Destination path" value={path} onChange={(e) => setPath(e.target.value)} inputProps={{ "aria-label": "Destination path" }} />
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Metadata fields</Typography>
          <Stack direction="row" flexWrap="wrap">
            {api.REPORT_FIELDS.map((f) => (
              <FormControlLabel key={f} sx={{ width: "33%" }} label={f} control={<Checkbox size="small" checked={fields.includes(f)} disabled={["project", "bucket", "name"].includes(f)}
                onChange={(e) => setFields(e.target.checked ? [...fields, f] : fields.filter((x) => x !== f))} />} />
            ))}
          </Stack>
          <ErrorAlert error={err} title="Failed to create configuration" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !dest || !id} onClick={save}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
