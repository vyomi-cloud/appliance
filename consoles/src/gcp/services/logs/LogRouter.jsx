/* Log Router — sinks list (real CRUD) plus volume rollups computed live from each
 * enabled sink's matched-entry counters (core/gcp_logging_core.py's _route_to_sinks). */
import { useState } from "react";
import { Button, Stack, Switch, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtBytes, fmtDate, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { Link } from "../../link.jsx";
import * as api from "./api.js";

const sinkId = (name) => name.split("/sinks/")[1];

export default function LogRouter() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listSinks(), []);

  const totalCount = data.reduce((n, s) => n + (s.matchedCount || 0), 0);
  const totalBytes = data.reduce((n, s) => n + (s.matchedBytes || 0), 0);
  const byKind = {};
  for (const s of data) byKind[api.destinationKind(s.destination)] = (byKind[api.destinationKind(s.destination)] || 0) + (s.matchedCount || 0);

  return (
    <>
      <PageHeader title="Log Router" actions={<>
        <Button startIcon={<AddIcon />} href="#/logs/router/sink">Create sink</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Stack spacing={2}>
        <Section title="Log Router Volume">
          <KeyValue items={[["Entries routed", totalCount], ["Volume", fmtBytes(totalBytes)]]} />
        </Section>
        <Section title="Volume by destination type">
          {Object.keys(byKind).length
            ? <KeyValue items={Object.entries(byKind).map(([k, v]) => [k, `${v} entries`])} />
            : <Typography variant="body2" color="text.secondary">No entries have matched a sink yet.</Typography>}
        </Section>
        <ResourceTable
          resourceName="Log Router sinks"
          items={data}
          rowKey={(s) => s.name}
          loading={loading}
          error={error}
          onRetry={reload}
          selectable
          selected={sel}
          onSelectedChange={setSel}
          filterPlaceholder="Filter"
          columns={[
            { id: "enabled", header: "Enabled", cell: (s) => <Switch size="small" checked={!s.disabled} onChange={async () => { await api.patchSink(sinkId(s.name), { disabled: !s.disabled }, "disabled"); reload(); }} inputProps={{ "aria-label": `Enable ${sinkId(s.name)}` }} /> },
            { id: "type", header: "Type", cell: (s) => api.destinationKind(s.destination) },
            { id: "name", header: "Name", sortField: "name", cell: (s) => <Link href={`#/logs/router/sink?edit=${encodeURIComponent(sinkId(s.name))}`}>{sinkId(s.name)}</Link> },
            { id: "description", header: "Description", cell: (s) => s.description || "—" },
            { id: "destination", header: "Destination", cell: (s) => s.destination },
            { id: "volume", header: "Volume", cell: (s) => `${s.matchedCount || 0} entries (${fmtBytes(s.matchedBytes || 0)})` },
            { id: "created", header: "Created", sortField: "createTime", cell: (s) => fmtDate(s.createTime) },
            { id: "updated", header: "Last updated", sortField: "updateTime", cell: (s) => fmtDate(s.updateTime) },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No rows to display</Typography>}
        />
      </Stack>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete sink?" : `Delete ${sel.length} sinks?`}
        confirmText="DELETE"
        onConfirm={async () => {
          for (const name of sel) await api.deleteSink(sinkId(name));
          notify.success(`Deleted ${sel.length} sink${sel.length === 1 ? "" : "s"}`);
          setSel([]); reload();
        }}
      >
        <Typography variant="body2">{sel.map(sinkId).join(", ")}</Typography>
      </DeleteDialog>
    </>
  );
}
