/* Logs Storage — log buckets list (real buckets CRUD). The storage-usage figures are a
 * live tally of ingested entry bytes this/last calendar month, not a GCP billing export. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

const PROTECTED = new Set(["_Default", "_Required"]);

function usageStats(entries) {
  const now = new Date();
  const curStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const prevStart = new Date(now.getFullYear(), now.getMonth() - 1, 1).getTime();
  let cur = 0, prev = 0;
  for (const en of entries) {
    const t = new Date(en.timestamp).getTime();
    const bytes = JSON.stringify(en).length;
    if (t >= curStart) cur += bytes; else if (t >= prevStart) prev += bytes;
  }
  const dayOfMonth = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const projected = dayOfMonth ? (cur / dayOfMonth) * daysInMonth : 0;
  return { cur, prev, projected };
}

export default function LogsStorage() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [alertOpen, setAlertOpen] = useState(false);
  const buckets = useAsync(() => api.listBuckets(), []);
  const entries = useAsync(() => api.listEntries({ pageSize: 1000 }), []);
  const { cur, prev, projected } = usageStats(entries.data || []);
  const billable = (buckets.data || []).filter((b) => (b.retentionDays || 30) > 30).length;

  return (
    <>
      <PageHeader title="Logs Storage" actions={<>
        <Button startIcon={<AddIcon />} href="#/logs/storage/bucket">Create log bucket</Button>
        <Button onClick={() => setAlertOpen(true)}>Create usage alert</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={buckets.reload}>Refresh</Button>
      </>} />
      <Stack spacing={2}>
        <Section title="Storage">
          <KeyValue items={[
            ["Current month storage", fmtBytes(cur)],
            ["Previous month storage", fmtBytes(prev)],
            ["Projected storage by EOM", fmtBytes(projected)],
            ["Current month billable retention", `${billable} bucket${billable === 1 ? "" : "s"} over 30 days`],
          ]} />
        </Section>
        <ResourceTable
          resourceName="log buckets"
          items={buckets.data || []}
          rowKey={(b) => b.name}
          loading={buckets.loading}
          error={buckets.error}
          onRetry={buckets.reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Name", sortField: "name", cell: (b) => <Link href={hashHref("logs", "storage", "bucket", api.bucketId(b.name)) + `?loc=${api.bucketLocation(b.name)}`}>{api.bucketId(b.name)}</Link> },
            { id: "description", header: "Description", cell: (b) => b.description || "—" },
            { id: "analytics", header: "Observability Analytics available", cell: (b) => (b.analyticsEnabled ? "Yes" : "No") },
            { id: "bq", header: "BigQuery linked dataset", cell: (b) => b.bigQueryDataset || "—" },
            { id: "retention", header: "Retention period", sortField: "retentionDays", cell: (b) => `${b.retentionDays} days` },
            { id: "region", header: "Region", cell: (b) => api.bucketLocation(b.name) },
            { id: "status", header: "Status", cell: (b) => (b.lifecycleState === "ACTIVE" ? "Active" : "Delete requested") },
            { id: "tags", header: "Tags", cell: () => "—" },
            { id: "created", header: "Created", sortField: "createTime", cell: (b) => fmtDate(b.createTime) },
            { id: "updated", header: "Last updated", sortField: "updateTime", cell: (b) => fmtDate(b.updateTime) },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No rows to display</Typography>}
        />
      </Stack>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete log bucket?" : `Delete ${sel.length} log buckets?`}
        confirmText="DELETE"
        warning={sel.some((n) => PROTECTED.has(api.bucketId(n))) ? "_Default and _Required buckets can't be deleted." : undefined}
        onConfirm={async () => {
          for (const n of sel) await api.deleteBucket(api.bucketId(n), api.bucketLocation(n));
          notify.success(`Deleted ${sel.length} bucket${sel.length === 1 ? "" : "s"}`);
          setSel([]); buckets.reload();
        }}
      >
        <Typography variant="body2">{sel.map(api.bucketId).join(", ")}</Typography>
      </DeleteDialog>
      {alertOpen && (
        <CreateUsageAlertDialog onClose={() => setAlertOpen(false)} onCreated={(name) => notify.success(`Created usage alert "${name}"`)} />
      )}
    </>
  );
}

function CreateUsageAlertDialog({ onClose, onCreated }) {
  const [name, setName] = useState("Log storage usage alert");
  const [thresholdGb, setThresholdGb] = useState("10");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create usage alert</DialogTitle>
      <DialogContent>
        <CapabilityContainer id="gcp.logs.storage.usage_alerts" title="Usage alert">
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2" color="text.secondary">
              Hands off to Cloud Monitoring: creates a real alert policy on this project's live
              month-to-date log bytes (logging.googleapis.com/byte_count).
            </Typography>
            <TextField label="Alert name" required value={name} onChange={(e) => setName(e.target.value)} />
            <TextField label="Threshold" type="number" required value={thresholdGb}
              onChange={(e) => setThresholdGb(e.target.value)} helperText="GB of logs ingested this month" />
            <ErrorAlert error={error} />
          </Stack>
        </CapabilityContainer>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name.trim() || !thresholdGb}
          onClick={async () => {
            setBusy(true); setError(null);
            try {
              await api.createUsageAlert(name.trim(), Number(thresholdGb) * 1e9);
              onCreated(name.trim()); onClose();
            } catch (e) { setError(e); } finally { setBusy(false); }
          }}>Create</Button>
      </DialogActions>
    </Dialog>
  );
}
