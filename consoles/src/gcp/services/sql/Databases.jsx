/* Databases — instance-scoped schemas (create / delete). */
import { useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function Databases({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listDatabases(name), [name]);

  return (
    <>
      <InstanceNav name={name} active="databases" />
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ flex: 1, fontSize: 20 }}>Databases</Typography>
        <Button startIcon={<AddIcon />} href={`#/sql/instances/${encodeURIComponent(name)}/databases/create`}>Create database</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </Stack>
      <ResourceTable
        resourceName="databases"
        items={data}
        rowKey={(d) => d.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter databases"
        columns={[
          { id: "name", header: "Name", sortField: "name", cell: (d) => d.name },
          { id: "collation", header: "Collation", cell: (d) => d.collation },
          { id: "charset", header: "Character set", cell: (d) => d.charset },
          { id: "type", header: "Type", cell: () => "Database" },
          { id: "actions", header: "Actions", cell: (d) => <Button size="small" onClick={() => { setSel([d.name]); setDel(true); }}>Delete</Button> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No databases on this instance.</Typography>}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={sel.length === 1 ? "Delete database?" : `Delete ${sel.length} databases?`} confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        onConfirm={async () => { for (const d of sel) await api.deleteDatabase(name, d); notify.success(`Deleted ${sel.length} database${sel.length === 1 ? "" : "s"}`); setSel([]); reload(); }}>
        <Box><Typography variant="body2">{sel.join(", ")} will be permanently deleted.</Typography></Box>
      </DeleteDialog>
    </>
  );
}
