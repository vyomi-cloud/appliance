/* Manage resources — the organization > folder > project tree from the native console, over the
 * Resource Manager v3 API (folders, projects:search, :move). Click a folder to drill in (breadcrumb
 * shows the path); create / rename / move / delete folders, create / rename / move / delete projects. */
import { useState } from "react";
import { Breadcrumbs, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Menu, MenuItem, Stack, TextField, Typography } from "@mui/material";
import FolderOutlinedIcon from "@mui/icons-material/esm/FolderOutlined.js";
import CreateNewFolderOutlinedIcon from "@mui/icons-material/esm/CreateNewFolderOutlined.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import { setProject } from "../../project.js";
import * as api from "./api.js";
import LocationPicker from "./LocationPicker.jsx";

export default function ManageResources() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [menu, setMenu] = useState(null);
  const [del, setDel] = useState(null);      // project ID[] awaiting delete confirmation
  const [rename, setRename] = useState(null);
  const [move, setMove] = useState(null);       // row being moved
  const [newFolder, setNewFolder] = useState(false);
  const [cwd, setCwd] = useState(null);          // current parent name (organizations/N | folders/N); null = organization
  const { data: tree, loading, error, reload } = useAsync(async () => {
    const [org, folders, projects] = await Promise.all([api.getOrg(), api.allFolders(), api.searchProjects("")]);
    return { org, folders, projects };
  }, []);
  const org = tree?.org;
  const here = cwd || org?.name;
  const crumbs = [];
  for (let n = here; n && tree; ) {
    const f = tree.folders.find((x) => x.name === n);
    crumbs.unshift({ name: n, label: f ? f.displayName : org?.displayName });
    n = f ? f.parent : null;
  }
  const data = !tree ? [] : [
    ...tree.folders.filter((f) => f.parent === here).map((f) => ({ ...f, kind: "folder", id: f.name })),
    ...tree.projects.filter((p) => api.parentName(p.parent) === here).map((p) => ({ ...p, kind: "project", id: p.projectId })),
  ];
  const isFolder = (r) => r.kind === "folder";

  const open = (p) => { setProject(p.projectId); location.hash = "/dashboard"; };
  const closeMenu = () => setMenu((m) => ({ ...m, open: false }));

  return (
    <>
      <PageHeader title="Manage resources" actions={<>
        <Button startIcon={<AddIcon />} href="#/resource-manager/create">Create Project</Button>
        <Button startIcon={<CreateNewFolderOutlinedIcon />} onClick={() => setNewFolder(true)}>Create Folder</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(sel)}>Delete</Button>
      </>} />
      <Breadcrumbs aria-label="Resource path" sx={{ mb: 1.5 }}>
        {crumbs.map((c, i) => i === crumbs.length - 1
          ? <Typography key={c.name} variant="body2" color="text.primary">{c.label}</Typography>
          : <Link key={c.name} href="#" onClick={(e) => { e.preventDefault(); setCwd(c.name); setSel([]); }}>{c.label}</Link>)}
      </Breadcrumbs>
      <ResourceTable
        resourceName="resources"
        items={data}
        rowKey={(p) => p.id}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter resources by name or ID"
        columns={[
          { id: "name", header: "Name", sortField: "displayName", cell: (p) => isFolder(p)
            ? <Stack direction="row" spacing={0.75} alignItems="center"><FolderOutlinedIcon fontSize="small" /><Link href="#" onClick={(e) => { e.preventDefault(); setCwd(p.name); setSel([]); }}>{p.displayName}</Link></Stack>
            : <Link href="#" onClick={(e) => { e.preventDefault(); open(p); }}>{p.displayName || p.projectId}</Link> },
          { id: "type", header: "Type", cell: (p) => isFolder(p) ? "Folder" : "Project" },
          { id: "id", header: "ID", sortField: "projectId", cell: (p) => isFolder(p) ? p.name.split("/")[1] : p.projectId },
          { id: "actions", header: "Actions", cell: (p) => (
            <IconButton size="small" aria-label={`Actions for ${p.id}`} onClick={(e) => setMenu({ anchor: e.currentTarget, open: true, project: p })}><MoreVertIcon fontSize="small" /></IconButton>
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
        {menu?.project && !isFolder(menu.project) && <MenuItem onClick={() => { open(menu.project); closeMenu(); }}>Open</MenuItem>}
        {menu?.project && !isFolder(menu.project) && <MenuItem onClick={() => { setProject(menu.project.projectId); location.hash = "/iam-admin/settings"; closeMenu(); }}>Settings</MenuItem>}
        <MenuItem onClick={() => { setRename(menu.project); closeMenu(); }}>Rename</MenuItem>
        <MenuItem onClick={() => { setMove(menu.project); closeMenu(); }}>Move</MenuItem>
        <MenuItem onClick={() => { setDel([menu.project.id]); closeMenu(); }}>Delete</MenuItem>
      </Menu>

      {rename && (isFolder(rename)
        ? <FolderNameDialog title="Rename folder" folder={rename} onClose={() => setRename(null)} onDone={(msg) => { notify.success(msg); setRename(null); reload(); }} />
        : <RenameDialog project={rename} onClose={() => setRename(null)} onDone={(msg) => { notify.success(msg); setRename(null); reload(); }} />)}

      {move && <MoveDialog row={move} onClose={() => setMove(null)} onDone={(msg) => { notify.success(msg); setMove(null); reload(); }} />}
      {newFolder && <FolderNameDialog title="Create folder" parent={here} onClose={() => setNewFolder(false)} onDone={(msg) => { notify.success(msg); setNewFolder(false); reload(); }} />}

      <DeleteDialog
        open={!!del}
        onClose={() => setDel(null)}
        title={<Stack direction="row" spacing={1} alignItems="center"><span>{del && del.length === 1 ? (del[0].startsWith("folders/") ? "Delete folder?" : "Delete project?") : `Delete ${del?.length || 0} resources?`}</span><CapabilityBadge id="gcp.resource-manager.delete-project" /></Stack>}
        confirmText={del && del.length === 1 ? (del[0].startsWith("folders/") ? (tree?.folders.find((f) => f.name === del[0])?.displayName || del[0]) : del[0]) : "DELETE"}
        warning="Every resource in a deleted project is deleted too. A folder can only be deleted when it is empty."
        onConfirm={async () => {
          for (const id of del) await (id.startsWith("folders/") ? api.deleteFolder(id) : api.deleteProject(id));
          notify.success(del.length === 1 ? `Deleted "${del[0]}"` : `Deleted ${del.length} resources`);
          setSel([]);
          reload();
        }}
      >
        <Typography variant="body2">{del?.join(", ")} will be deleted.</Typography>
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

function FolderNameDialog({ title, parent, folder, onClose, onDone }) {
  const [name, setName] = useState(folder?.displayName || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const err = name ? api.validFolderName(name) : null;
  const save = async () => {
    setBusy(true); setError(null);
    try {
      if (folder) { await api.renameFolder(folder.name, name); onDone(`Renamed folder to "${name}"`); }
      else { await api.createFolder(parent, name); onDone(`Created folder "${name}"`); }
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="folder-title">
      <DialogTitle id="folder-title">{title}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField autoFocus label="Folder name" value={name} onChange={(e) => setName(e.target.value)} error={!!err} helperText={err} inputProps={{ "aria-label": "Folder name" }} />
          <ErrorAlert error={error} title="Failed to save folder" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name || !!err} onClick={save}>{busy ? "Saving…" : folder ? "Save" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function MoveDialog({ row, onClose, onDone }) {
  const [dest, setDest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try {
      if (row.kind === "folder") await api.moveFolder(row.name, dest); else await api.moveProject(row.projectId, dest);
      onDone(`Moved "${row.displayName || row.id}"`);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="move-title">
      <DialogTitle id="move-title">{row.kind === "folder" ? "Move folder" : "Move project"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <LocationPicker value={dest} onChange={setDest} exclude={row.kind === "folder" ? row.name : undefined} />
          <ErrorAlert error={error} title="Failed to move" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !dest} onClick={go}>{busy ? "Moving…" : "Move"}</Button>
      </DialogActions>
    </Dialog>
  );
}
