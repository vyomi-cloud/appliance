/* Backups — on-demand backupRuns for one instance (create / delete / restore). Restoring
 * replays the backup's databases/users snapshot via instances.restoreBackup — see
 * core/capabilities/gcp/sql.json (gcp.sql.backups, "full"). */
import { useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";
import * as api from "./api.js";

export default function InstanceBackups({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [del, setDel] = useState(null);
  const [restore, setRestore] = useState(null);
  const [creating, setCreating] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listBackups(name), [name]);

  const create = async () => {
    setCreating(true);
    try { await api.insertBackup(name, { description: "On-demand backup" }); notify.success("Backup created"); reload(); }
    catch (e) { notify.error(e); } finally { setCreating(false); }
  };

  return (
    <>
      <InstanceNav name={name} active="backups" />
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h2" component="h2" sx={{ flex: 1, fontSize: 20 }}>Backups</Typography>
        <Button startIcon={<AddIcon />} disabled={creating} onClick={create}>{creating ? "Creating…" : "Create backup"}</Button>
      </Stack>
      <CapabilityContainer id="gcp.sql.backups" title="Backup runs">
        <ResourceTable
          resourceName="backups"
          items={data}
          rowKey={(b) => b.id}
          loading={loading}
          error={error}
          onRetry={reload}
          filterPlaceholder="Filter backups"
          columns={[
            { id: "created", header: "Created", cell: (b) => b.enqueuedTime ? fmtDate(b.enqueuedTime) : "Just now" },
            { id: "type", header: "Type", cell: (b) => b.type === "ON_DEMAND" ? "On-demand" : "Automated" },
            { id: "description", header: "Description", cell: (b) => b.description || "—" },
            { id: "location", header: "Location", cell: (b) => b.location },
            { id: "status", header: "Status", cell: (b) => b.status },
            {
              id: "actions", header: "Actions", cell: (b) => (
                <Stack direction="row" spacing={1}>
                  <Button size="small" onClick={() => setRestore(b)}>Restore</Button>
                  <Button size="small" onClick={() => setDel(b)}>Delete</Button>
                </Stack>
              ),
            },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No backups for this instance yet.</Typography>}
        />
      </CapabilityContainer>
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete backup?" confirmText="DELETE"
        onConfirm={async () => { await api.deleteBackup(name, del.id); notify.success("Backup deleted"); reload(); }}>
        <Box><Typography variant="body2">This backup will be permanently deleted.</Typography></Box>
      </DeleteDialog>
      <DeleteDialog open={!!restore} onClose={() => setRestore(null)} title="Restore backup?" actionLabel="Restore"
        warning="Restoring replaces this instance's current databases and users with the backup's state. This can't be undone."
        onConfirm={async () => { await api.restoreBackup(name, restore.id); notify.success("Instance restored from backup"); reload(); }}>
        <Box><Typography variant="body2">Instance <b>{name}</b> will be restored to the state captured by this backup.</Typography></Box>
      </DeleteDialog>
    </>
  );
}
