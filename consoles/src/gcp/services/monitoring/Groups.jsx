/* Groups — real Groups API (create/list/delete, parent/child nesting). Membership is an
 * honest gap: Vyomi stores the filter string but never evaluates it against resources
 * (there are no live resource inventories to group); see gcp.monitoring.groups. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function CreateGroupDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [filter, setFilter] = useState('resource.type = "gce_instance"');
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Create Group</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField autoFocus label="Group name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!name.trim() || busy} onClick={async () => {
          setBusy(true);
          await api.createGroup({ displayName: name, filter });
          notify.success(`Created group "${name}"`);
          setBusy(false); onCreated();
        }}>Create</Button>
      </DialogActions>
    </Dialog>
  );
}

function RowMenu({ group, onDeleted }) {
  const notify = useNotify();
  const [anchor, setAnchor] = useState(null);
  const [del, setDel] = useState(false);
  const id = group.name.split("/").pop();
  return (
    <>
      <IconButton size="small" aria-label={`Actions for ${group.displayName}`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
      <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
        <MenuItem onClick={() => { setAnchor(null); setDel(true); }}>Delete</MenuItem>
      </Menu>
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete group?" confirmText={group.displayName}
        onConfirm={async () => { await api.deleteGroup(id); notify.success(`Deleted group "${group.displayName}"`); onDeleted(); }}>
        <Typography variant="body2">Group <b>{group.displayName}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

export default function Groups() {
  const project = useProject();
  const [createOpen, setCreateOpen] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listGroups(), [project]);

  return (
    <>
      <PageHeader title="Groups" actions={<Button startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>Create Group</Button>} />
      <ResourceTable
        resourceName="groups"
        items={data}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(g) => g.name}
        filterPlaceholder="Filter"
        columns={[
          { id: "name", header: "Name", sortField: "displayName", cell: (g) => g.displayName },
          { id: "instances", header: <>Instances<CapabilityBadge id="gcp.monitoring.groups" /></>, cell: () => "—" },
          { id: "resources", header: "Resources", cell: () => "—" },
          { id: "actions", header: "", cell: (g) => <RowMenu group={g} onDeleted={reload} /> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No groups to display</Typography>}
      />
      <CreateGroupDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={() => { setCreateOpen(false); reload(); }} />
    </>
  );
}
