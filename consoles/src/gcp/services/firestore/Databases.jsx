/* All databases — list, columns and delete flow as in the console's "All databases" page. */
import { useState } from "react";
import { Box, Button, Chip, IconButton, Menu, MenuItem, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { Link, hashHref } from "../../link.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const dbId = (d) => d.name.split("/").pop();

export default function Databases() {
  const notify = useNotify();
  const project = useProject();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [menu, setMenu] = useState(null); // {anchor, id}
  const { data = [], loading, error, reload } = useAsync(() => api.listDatabases(), [project]);

  return (
    <>
      <PageHeader title="All databases" actions={<>
        <Button startIcon={<AddIcon />} href="#/firestore/create-database">Create a Firestore database</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="databases"
        items={data}
        rowKey={dbId}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Enter property name or value"
        columns={[
          { id: "status", header: "Status", cell: () => <Chip size="small" color="success" label="Active" /> },
          { id: "id", header: "Database ID", sortValue: dbId, cell: (d) => <Link href={hashHref("firestore", "databases", dbId(d), "studio")}>{dbId(d)}</Link> },
          { id: "edition", header: "Edition", sortField: "databaseEdition", cell: (d) => d.databaseEdition === "ENTERPRISE" ? "Enterprise Edition" : "Standard Edition" },
          { id: "modes", header: "Modes", cell: (d) => d.type === "DATASTORE_MODE" ? "Datastore mode" : "Native mode" },
          { id: "location", header: "Location", sortField: "locationId", cell: (d) => d.locationId },
          { id: "created", header: "Creation time", sortField: "createTime", cell: (d) => fmtDate(d.createTime) },
          { id: "backups", header: "Scheduled backups", cell: (d) => d.pointInTimeRecoveryEnablement === "POINT_IN_TIME_RECOVERY_ENABLED" ? "On" : "Off" },
          { id: "enctype", header: "Encryption type", cell: () => "Google-managed" },
          { id: "enckey", header: "Encryption key", cell: () => "—" },
          { id: "actions", header: "Actions", cell: (d) => (
            <IconButton size="small" aria-label={`Actions for ${dbId(d)}`} onClick={(ev) => setMenu({ anchor: ev.currentTarget, id: dbId(d) })}>
              <MoreVertIcon fontSize="small" />
            </IconButton>
          ) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">You don't have any databases in this project yet.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/firestore/create-database">Create a Firestore Database</Button>
          </Stack>
        }
      />
      <Menu anchorEl={menu?.anchor} open={!!menu} onClose={() => setMenu(null)}>
        <MenuItem component="a" href={menu ? hashHref("firestore", "databases", menu.id, "studio") : undefined} onClick={() => setMenu(null)}>View database</MenuItem>
        <MenuItem onClick={() => { setSel([menu.id]); setMenu(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete database?" : `Delete ${sel.length} databases?`}
        confirmText={sel.length === 1 ? sel[0] : "DELETE"}
        warning="All collections and documents in the database are deleted as well. This can't be undone."
        onConfirm={async () => {
          for (const id of sel) await api.deleteDatabase(id);
          notify.success(sel.length === 1 ? `Deleted database "${sel[0]}"` : `Deleted ${sel.length} databases`);
          setSel([]);
          reload();
        }}
      >
        <Box><Typography variant="body2">{sel.length === 1 ? <>Database <b>{sel[0]}</b> will be permanently deleted.</> : <>{sel.join(", ")} will be permanently deleted.</>}</Typography></Box>
      </DeleteDialog>
    </>
  );
}
