/* Eventarc > Triggers: every trigger of the project across regions, with create / delete. */
import { useState } from "react";
import { Button, Chip, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Triggers() {
  const project = useProject();
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listTriggers(), [project]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const chosen = () => data.filter((t) => sel.includes(t.name));

  return (
    <>
      <PageHeader title="Eventarc triggers" actions={<>
        <Button startIcon={<AddIcon />} href="#/eventarc/triggers/new">Create trigger</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="triggers" items={data} rowKey={(t) => t.name} loading={loading} error={error} onRetry={reload}
        selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter triggers"
        columns={[
          { id: "name", header: "Name", sortValue: api.triggerId, cell: (t) => <Link href={hashHref("eventarc", "triggers", api.triggerRegion(t), api.triggerId(t))}>{api.triggerId(t)}</Link> },
          { id: "region", header: "Region", sortValue: api.triggerRegion, cell: api.triggerRegion },
          { id: "event", header: "Event type", sortValue: api.eventType, cell: (t) => <Chip size="small" variant="outlined" label={api.eventType(t).replace(/^google\.cloud\./, "")} /> },
          { id: "dest", header: "Destination", cell: (t) => { const d = api.destinationOf(t); return `${d.kind}: ${d.name}`; } },
          { id: "sa", header: "Service account", cell: (t) => t.serviceAccount || "—" },
        ]}
        empty={<Stack spacing={1.5} alignItems="center">
          <Typography variant="body2" color="text.secondary">There are no triggers in this project.</Typography>
          <Button variant="contained" startIcon={<AddIcon />} href="#/eventarc/triggers/new">Create trigger</Button>
        </Stack>}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={sel.length === 1 ? "Delete trigger?" : `Delete ${sel.length} triggers?`}
        confirmText={sel.length === 1 ? api.triggerId(chosen()[0] || { name: "" }) : "DELETE"} warning="This can't be undone."
        onConfirm={async () => {
          for (const t of chosen()) await api.deleteTrigger(api.triggerRegion(t), api.triggerId(t));
          notify.success(`Deleted ${sel.length} trigger${sel.length === 1 ? "" : "s"}`); setSel([]); reload();
        }}>
        <Typography variant="body2">{chosen().map(api.triggerId).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}
