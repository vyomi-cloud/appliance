/* Role details — custom roles over the native projects.roles.{get,patch,delete};
 * predefined roles read from the static GET /v1/roles catalog (read-only, as in the
 * real console — predefined roles can't be edited or deleted). */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";
import { AddPermissionsDialog } from "./pickers.jsx";
import { usePickerData } from "./usePickerData.js";

export default function RoleDetail({ params }) {
  const name = api.roleFromSlug(params["resource-name"]);
  const isCustom = name.startsWith("projects/");
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(false);
  const role = useAsync(async () => {
    if (isCustom) return api.getRole(name);
    const all = await api.listPredefinedRoles();
    return all.find((r) => r.name === name) || null;
  }, [name]);

  const data = role.data;
  const permissions = (data?.includedPermissions || []).map((p) => ({ p }));

  return (
    <>
      <PageHeader title={data?.title || name} back={<IconButton aria-label="Back to roles" href="#/iam-admin/roles"><ArrowBackIcon /></IconButton>}
        actions={
          <Stack direction="row" spacing={1}>
            <Button disabled={!isCustom} onClick={() => setEdit(true)}>Edit role</Button>
            <Button href="#/iam-admin/roles/create">Create role from this role</Button>
            <Button disabled={!isCustom} color="error" onClick={() => setDel(true)}>Delete</Button>
          </Stack>} />
      <ErrorAlert error={role.error} title="Failed to load role" />
      {data && (
        <Section title="Role">
          <KeyValue items={[
            ["ID", data.name],
            ["Role launch stage", data.stage],
            ["Description", data.description || "—"],
          ]} />
          <Box sx={{ mt: 2 }}>
            <ResourceTable resourceName="assigned permissions" items={permissions} rowKey={(r) => r.p} filterPlaceholder="Filter"
              empty="No rows to display" columns={[{ id: "permission", header: "Permission", sortField: "p", cell: (r) => r.p }]} />
          </Box>
        </Section>
      )}
      <DeleteDialog open={del} onClose={() => setDel(false)} title={`Delete role "${data?.title}"?`} confirmText="DELETE"
        onConfirm={async () => { await api.deleteRole(name); notify.success("Deleted role"); location.hash = hashHref("iam-admin", "roles").slice(1); }} />
      {edit && data && <EditRoleDialog role={data} onClose={() => setEdit(false)} onSaved={() => { notify.success("Saved role"); role.reload(); }} />}
    </>
  );
}

function EditRoleDialog({ role, onClose, onSaved }) {
  const [title, setTitle] = useState(role.title);
  const [description, setDescription] = useState(role.description || "");
  const [perms, setPerms] = useState(role.includedPermissions || []);
  const [addOpen, setAddOpen] = useState(false);
  const data = usePickerData();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>Edit role</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <TextField label="Description" multiline minRows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          <Stack direction="row" alignItems="center" justifyContent="space-between"><Typography variant="h3" component="h3">Assigned permissions ({perms.length})</Typography><Button onClick={() => setAddOpen(true)}>Add permissions</Button></Stack>
          <ResourceTable resourceName="permissions" items={perms.map((p) => ({ p }))} rowKey={(x) => x.p} filterPlaceholder="Filter" empty="No rows to display"
            columns={[{ id: "permission", header: "Permission", sortField: "p", cell: (x) => x.p },
              { id: "remove", header: "", cell: (x) => <IconButton size="small" aria-label={`Remove ${x.p}`} onClick={() => setPerms(perms.filter((y) => y !== x.p))}><DeleteIcon fontSize="small" /></IconButton> }]} />
        </Stack>
        <AddPermissionsDialog open={addOpen} catalog={data} existing={perms} onClose={() => setAddOpen(false)} onAdd={(ps) => setPerms([...new Set([...perms, ...ps])])} />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.patchRole(role.name, { title, description, includedPermissions: perms }); onSaved(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
