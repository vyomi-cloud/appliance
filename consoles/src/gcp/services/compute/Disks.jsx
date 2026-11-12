/* Disks — list across all zones, bulk delete. */
import { useState } from "react";
import { Button, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Disks() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listDisksAllZones(), [project]);

  const byKey = (k) => data.find((d) => `${d._zoneScope}/${d.name}` === k);

  return (
    <>
      <PageHeader title="Disks" actions={<>
        <Button startIcon={<AddIcon />} href="#/compute/disks/create">Create disk</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="disks"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        rowKey={(d) => `${d._zoneScope}/${d.name}`}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "status", header: "Status", sortField: "status", cell: (d) => d.status },
          { id: "name", header: "Name", sortField: "name", cell: (d) => d.name },
          { id: "type", header: "Type", cell: (d) => api.diskTypeLabel(api.last(d.type)) },
          { id: "size", header: "Size", sortField: "sizeGb", cell: (d) => `${d.sizeGb} GB` },
          { id: "arch", header: "Architecture", sortField: "architecture", cell: (d) => d.architecture || "—" },
          { id: "zone", header: "Zone", sortField: "_zoneScope", cell: (d) => d._zoneScope },
          { id: "inuse", header: "In use by", cell: (d) => d._display?.inUseBy || "—" },
          { id: "schedule", header: "Snapshot schedule", cell: () => "None" },
          { id: "encryption", header: "Encryption", cell: () => "Google-managed" },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">There are no disks in this project.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/compute/disks/create">Create disk</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete disk?" : `Delete ${sel.length} disks?`}
        confirmText={sel.length === 1 ? byKey(sel[0])?.name : "DELETE"}
        warning="Deleted disks can't be recovered. This can't be undone."
        onConfirm={async () => {
          for (const k of sel) {
            const d = byKey(k);
            if (d) await api.deleteDisk(d._zoneScope, d.name);
          }
          notify.success(sel.length === 1 ? `Deleted disk "${byKey(sel[0])?.name}"` : `Deleted ${sel.length} disks`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{sel.length === 1 ? <>Disk <b>{byKey(sel[0])?.name}</b> will be permanently deleted.</> : <>{sel.length} disks will be permanently deleted.</>}</Typography>
      </DeleteDialog>
    </>
  );
}
