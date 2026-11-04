/* Manage resources — the project/folder tree the native console shows under IAM & Admin's
 * "Manage Resources" link. Vyomi's GCP lens models no organizations or folders (every other
 * product is project-scoped — see core/capabilities/gcp/iam-admin.json), so the native tree
 * renders here as the flat list of projects on the Resource Manager v3 API. Create, rename
 * and delete are real; Move is an honest gap (there is no folder/org to move a project into). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import { setProject } from "../../project.js";
import * as api from "./api.js";

export default function ManageResources() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [menu, setMenu] = useState(null);
  const [del, setDel] = useState(null);      // project ID[] awaiting delete confirmation
  const [rename, setRename] = useState(null);
  const [move, setMove] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.searchProjects(""), []);

  const open = (p) => { setProject(p.projectId); location.hash = "/dashboard"; };
  const closeMenu = () => setMenu((m) => ({ ...m, open: false }));

  return (
    <>
      <PageHeader title="Manage resources" actions={<>
        <Button startIcon={<AddIcon />} href="#/resource-manager/create">Create Project</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(sel)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="resources"
        items={data}
        rowKey={(p) => p.projectId}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter resources by name or ID"
        columns={[
          { id: "name", header: "Name", sortField: "displayName", cell: (p) => <Link href="#" onClick={(e) => { e.preventDefault(); open(p); }}>{p.displayName || p.projectId}</Link> },
          { id: "id", header: "ID", sortField: "projectId", cell: (p) => p.projectId },
          { id: "actions", header: "Actions", cell: (p) => (
            <IconButton size="small" aria-label={`Actions for ${p.projectId}`} onClick={(e) => setMenu({ anchor: e.currentTarget, open: true, project: p })}><MoreVertIcon fontSize="small" /></IconButton>
          ) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No rows to display</Typography>
            <Button variant="contained" startIcon={<AddIcon />} href="#/resource-manager/create">Create Project</Button>
          </Stack>
        }
      />
      <Menu anchorEl={menu?.anchor} open={!!menu?.open} onClose={closeMenu}>
        <MenuItem onClick={() => { open(menu.project); closeMenu(); }}>Open</MenuItem>
        <MenuItem onClick={() => { setProject(menu.project.projectId); location.hash = "/iam-admin/settings"; closeMenu(); }}>Settings</MenuItem>
        <MenuItem onClick={() => { setRename(menu.project); closeMenu(); }}>Rename</MenuItem>
        <MenuItem onClick={() => { setMove(true); closeMenu(); }}>Move</MenuItem>
        <MenuItem onClick={() => { setDel([menu.project.projectId]); closeMenu(); }}>Delete</MenuItem>
      </Menu>

      {rename && <RenameDialog project={rename} onClose={() => setRename(null)} onDone={(msg) => { notify.success(msg); setRename(null); reload(); }} />}

      <Dialog open={move} onClose={() => setMove(false)} maxWidth="xs" fullWidth aria-labelledby="move-title">
        <DialogTitle id="move-title">Move project</DialogTitle>
        <DialogContent><NotSimulated compact feature="Moving a project to a different resource hierarchy" note="Vyomi's GCP lens is project-scoped; it models no organizations or folders to move a project into." /></DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}><Button onClick={() => setMove(false)}>Close</Button></DialogActions>
      </Dialog>

      <DeleteDialog
        open={!!del}
        onClose={() => setDel(null)}
        title={<Stack direction="row" spacing={1} alignItems="center"><span>{del && del.length === 1 ? "Delete project?" : `Delete ${del?.length || 0} projects?`}</span><CapabilityBadge id="gcp.resource-manager.delete-project" /></Stack>}
        confirmText={del && del.length === 1 ? del[0] : "DELETE"}
        warning="Every resource in this project will be deleted. This can't be undone."
        onConfirm={async () => {
          for (const id of del) await api.deleteProject(id);
          notify.success(del.length === 1 ? `Deleted project "${del[0]}"` : `Deleted ${del.length} projects`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{del?.join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function RenameDialog({ project, onClose, onDone }) {
  const [name, setName] = useState(project.displayName || project.projectId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const save = async () => {
    setBusy(true); setError(null);
    try { await api.renameProject(project.projectId, name); onDone(`Renamed project "${project.projectId}"`); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="rename-title">
      <DialogTitle id="rename-title">Rename project</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField autoFocus label="Project name" value={name} onChange={(e) => setName(e.target.value)} inputProps={{ "aria-label": "Project name" }} />
          <ErrorAlert error={error} title="Failed to rename project" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name.trim()} onClick={save}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
