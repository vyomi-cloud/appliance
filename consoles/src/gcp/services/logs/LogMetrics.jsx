/* Log-based Metrics list — user-defined metrics (real logMetrics CRUD) + a static
 * reference table of the system-defined metrics every Cloud Logging project ships. */
import { useState } from "react";
import { Button, Stack, Switch, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader, Section } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import * as api from "./api.js";

export default function LogMetrics() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const metrics = useAsync(() => api.listMetrics(), []);
  const entries = useAsync(() => api.listEntries({ pageSize: 1000 }), []);
  const now = Date.now();

  return (
    <>
      <PageHeader title="Log-based Metrics" actions={<>
        <Button startIcon={<AddIcon />} href="#/logs/metrics/edit">Create metric</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={metrics.reload}>Refresh</Button>
      </>} />
      <ResourceTable
        resourceName="user-defined metrics"
        items={metrics.data || []}
        rowKey={(m) => m.name}
        loading={metrics.loading}
        error={metrics.error}
        onRetry={metrics.reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter"
        columns={[
          { id: "enabled", header: "Enabled", cell: (m) => <Switch size="small" checked={!m.disabled} onChange={async () => { await api.updateMetric(m.name.split("/metrics/")[1], { ...m, disabled: !m.disabled }); metrics.reload(); }} inputProps={{ "aria-label": `Enable ${m.name}` }} /> },
          { id: "name", header: "Name", sortField: "name", cell: (m) => <Link href={`#/logs/metrics/edit?name=${encodeURIComponent(m.name.split("/metrics/")[1])}`}>{m.name.split("/metrics/")[1]}</Link> },
          { id: "type", header: "Type", cell: api.metricType },
          { id: "description", header: "Description", cell: (m) => m.description || "—" },
          { id: "prevUsage", header: "Previous month usage", cell: (m) => `${api.metricUsage(entries.data || [], m, now)[0]} entries` },
          { id: "mtdUsage", header: "Month-to-date usage (MTD)", cell: (m) => `${api.metricUsage(entries.data || [], m, now)[1]} entries` },
          { id: "created", header: "Created", sortField: "createTime", cell: (m) => fmtDate(m.createTime) },
          { id: "updated", header: "Last updated", sortField: "updateTime", cell: (m) => fmtDate(m.updateTime) },
          { id: "resource", header: "Resource", cell: () => "global" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No rows to display</Typography>}
      />
      <Section title="System-defined metrics" description="Built-in metrics Cloud Logging reports for every project.">
        <ResourceTable resourceName="system-defined metrics" items={api.SYSTEM_METRICS} rowKey={(m) => m[0]} dense
          columns={[
            { id: "name", header: "Name", cell: (m) => `logging.googleapis.com/${m[0]}` },
            { id: "description", header: "Description", cell: (m) => m[1] },
            { id: "resource", header: "Resource", cell: (m) => m[2] },
          ]} />
      </Section>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete metric?" : `Delete ${sel.length} metrics?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const name of sel) await api.deleteMetric(name.split("/metrics/")[1]);
          notify.success(`Deleted ${sel.length} metric${sel.length === 1 ? "" : "s"}`);
          setSel([]); metrics.reload();
        }}
      >
        <Typography variant="body2">{sel.map((n) => n.split("/metrics/")[1]).join(", ")}</Typography>
      </DeleteDialog>
    </>
  );
}
