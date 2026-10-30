/* Create a custom IAM role — native projects.roles.create. */
import { useState } from "react";
import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

const STAGES = ["Alpha", "Beta", "General Availability", "Disabled"];

export default function CreateRole() {
  const notify = useNotify();
  const [title, setTitle] = useState("Custom Role");
  const [description, setDescription] = useState(`Created on: ${new Date().toISOString().slice(0, 10)}`);
  const [id, setId] = useState("CustomRole");
  const [stage, setStage] = useState("Alpha");
  const [permissions, setPermissions] = useState([]);
  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-zA-Z0-9_.]{3,64}$/.test(id) && title.trim();

  const submit = async (ev) => {
    ev.preventDefault();
    if (!ok) return;
    setBusy(true); setError(null);
    try {
      const role = await api.createRole(id, { title, description, stage: stage === "General Availability" ? "GA" : stage.toUpperCase(), includedPermissions: permissions });
      notify.success(`Created role "${role.title}"`);
      location.hash = hashHref("iam-admin", "roles", "details", api.roleSlug(role.name)).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create role" back={<IconButton aria-label="Back" href="#/iam-admin/roles"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create role" />
      <Section title="Role">
        <Stack spacing={2}>
          <TextField required label="Title" value={title} onChange={(e) => setTitle(e.target.value.slice(0, 100))} helperText="100 characters max" />
          <TextField label="Description" multiline minRows={2} value={description} onChange={(e) => setDescription(e.target.value.slice(0, 256))} helperText="256 characters max" />
          <TextField required label="ID" value={id} onChange={(e) => setId(e.target.value.trim())} error={!/^[a-zA-Z0-9_.]{3,64}$/.test(id)} />
          <FormControl sx={{ maxWidth: 320 }}>
            <InputLabel id="stage-l">Role launch stage</InputLabel>
            <Select labelId="stage-l" label="Role launch stage" value={stage} onChange={(e) => setStage(e.target.value)}>
              {STAGES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </Section>
      <Box sx={{ height: 16 }} />
      <Section title="Assigned permissions" actions={<Button onClick={() => setAddOpen(true)}>Add permissions</Button>}>
        <ResourceTable resourceName="permissions" items={permissions.map((p) => ({ p }))} rowKey={(r) => r.p} filterPlaceholder="Filter"
          empty="No rows to display"
          columns={[
            { id: "permission", header: "Permission", sortField: "p", cell: (r) => r.p },
            { id: "status", header: "Status", cell: () => "Added" },
            { id: "remove", header: "", cell: (r) => <IconButton size="small" aria-label={`Remove ${r.p}`} onClick={() => setPermissions(permissions.filter((x) => x !== r.p))}><DeleteIcon fontSize="small" /></IconButton> },
          ]} />
      </Section>
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={!ok || busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/iam-admin/roles">Cancel</Button>
      </Stack>
      <AddPermissionsDialog open={addOpen} onClose={() => setAddOpen(false)} onAdd={(ps) => setPermissions([...new Set([...permissions, ...ps])])} />
    </Box>
  );
}

function AddPermissionsDialog({ open, onClose, onAdd }) {
  const [value, setValue] = useState("");
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add permissions</DialogTitle>
      <DialogContent>
        <TextField autoFocus fullWidth multiline minRows={3} sx={{ mt: 1 }} label="Permissions" value={value} onChange={(e) => setValue(e.target.value)}
          helperText="Comma or newline-separated, e.g. storage.objects.get, storage.objects.list" />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => { onAdd(value.split(/[,\n]/).map((s) => s.trim()).filter(Boolean)); setValue(""); onClose(); }}>Add</Button>
      </DialogActions>
    </Dialog>
  );
}
