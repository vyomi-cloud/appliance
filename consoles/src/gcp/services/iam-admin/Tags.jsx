/* Tags (tag keys) — native Resource Manager v3 tagKeys CRUD; "Manage access" grants an
 * IAM role on the tag key resource over the same generic :setIamPolicy verb the IAM page uses. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Tags() {
  const notify = useNotify();
  const list = useAsync(() => api.listTagKeys(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  const [access, setAccess] = useState(null);

  return (
    <>
      <PageHeader title="Tags" actions={
        <Stack direction="row" spacing={1}>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create</Button>
          <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button disabled={sel.length !== 1} onClick={() => setAccess(sel[0])}>Manage access</Button>
        </Stack>} />
      <ErrorAlert error={list.error} title="Failed to load tag keys" />
      <ResourceTable resourceName="tag keys" items={list.data || []} rowKey={(t) => t.name} loading={list.loading} onRetry={list.reload}
        selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter" empty="No tag keys to display"
        columns={[
          { id: "key", header: "Tag key", sortField: "shortName", cell: (t) => t.shortName },
          { id: "id", header: "Tag key ID", cell: (t) => t.name },
          { id: "desc", header: "Description", cell: (t) => t.description || "—" },
          { id: "actions", header: "Actions", cell: (t) => <Button size="small" color="error" onClick={() => setDel(t.name)}>Delete</Button> },
        ]} />
      {create && <CreateTagKeyDialog onClose={() => setCreate(false)} onCreated={() => { notify.success("Created tag key"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(false)} title="Delete tag key(s)?" confirmText="DELETE"
        onConfirm={async () => {
          const names = del === true ? sel : [del];
          for (const n of names) await api.deleteTagKey(n);
          notify.success(`Deleted ${names.length} tag key${names.length === 1 ? "" : "s"}`);
          setSel([]); list.reload();
        }} />
      {access && <ManageAccessDialog tagKey={access} onClose={() => setAccess(null)} onSaved={() => notify.success("Access updated")} />}
    </>
  );
}

function CreateTagKeyDialog({ onClose, onCreated }) {
  const [shortName, setShortName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[a-zA-Z0-9_-]{1,63}$/.test(shortName);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create tag key</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Tag key" value={shortName} onChange={(e) => setShortName(e.target.value.trim())} error={!!shortName && !ok} />
          <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createTagKey(shortName, description); onCreated(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function ManageAccessDialog({ tagKey, onClose, onSaved }) {
  const [member, setMember] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^(user|serviceAccount|group|domain):.+/.test(member);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Manage access — {tagKey.name}</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Grants Tag User on this tag key.</Typography>
        <TextField fullWidth label="New principal" value={member} onChange={(e) => setMember(e.target.value.trim())} helperText="e.g. user:dev@example.com" />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try {
            const cur = await api.getIamPolicy(tagKey.name).catch(() => ({ bindings: [] }));
            const bs = (cur.bindings || []).map((b) => ({ ...b, members: [...b.members] }));
            const role = "roles/resourcemanager.tagUser";
            const hit = bs.find((b) => b.role === role);
            if (hit) { if (!hit.members.includes(member)) hit.members.push(member); } else bs.push({ role, members: [member] });
            await api.setIamPolicy({ ...cur, bindings: bs }, tagKey.name);
            onSaved(); onClose();
          } catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}
