/* Essential Contacts — native Essential Contacts v1 CRUD. */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, FormGroup, Stack, TextField, ToggleButton, ToggleButtonGroup } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";

import * as api from "./api.js";

const CATEGORIES = ["ALL", "SECURITY", "BILLING", "TECHNICAL", "LEGAL"];

export default function EssentialContacts() {
  const notify = useNotify();
  const list = useAsync(() => api.listContacts(), []);
  const [filterBy, setFilterBy] = useState("category");
  const [add, setAdd] = useState(false);
  const [del, setDel] = useState(false);

  return (
    <>
      <PageHeader title="Essential Contacts" actions={
        <Stack direction="row" spacing={1}>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setAdd(true)}>Add Contact</Button>
          <Button href="https://cloud.google.com/resource-manager/docs/managing-notification-contacts" target="_blank" rel="noreferrer">Learn</Button>
        </Stack>} />
      <ToggleButtonGroup exclusive size="small" value={filterBy} onChange={(_, v) => v && setFilterBy(v)} sx={{ mb: 1.5 }} aria-label="Filter">
        <ToggleButton value="category">Category</ToggleButton>
        <ToggleButton value="contact">Contact</ToggleButton>
      </ToggleButtonGroup>
      <ErrorAlert error={list.error} title="Failed to load contacts" />
      <ResourceTable resourceName="contacts" items={list.data || []} rowKey={(c) => c.name} loading={list.loading} onRetry={list.reload}
        filterPlaceholder="Filter" empty="No results to display"
        columns={[
          { id: "contacts", header: "Contacts", sortField: "email", cell: (c) => c.email },
          { id: "inheritance", header: "Inheritance", cell: () => "Direct" },
          { id: "actions", header: "Actions", cell: (c) => <Button size="small" color="error" onClick={() => setDel(c.name)}>Remove</Button> },
        ]} />
      {add && <AddContactDialog onClose={() => setAdd(false)} onAdded={() => { notify.success("Added contact"); list.reload(); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(false)} title="Remove this contact?" actionLabel="Remove"
        onConfirm={async () => { await api.deleteContact(del); notify.success("Removed contact"); list.reload(); }} />
    </>
  );
}

function AddContactDialog({ onClose, onAdded }) {
  const [email, setEmail] = useState("");
  const [cats, setCats] = useState(["ALL"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const ok = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add Contact</DialogTitle>
      <DialogContent>
        <ErrorAlert error={error} />
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Email" value={email} onChange={(e) => setEmail(e.target.value.trim())} error={!!email && !ok} />
          <FormGroup row>
            {CATEGORIES.map((c) => (
              <FormControlLabel key={c} control={<Checkbox size="small" checked={cats.includes(c)}
                onChange={(e) => setCats(e.target.checked ? [...cats, c] : cats.filter((x) => x !== c))} />} label={c} />
            ))}
          </FormGroup>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createContact({ email, notificationCategorySubscriptions: cats.map((c) => ({ notificationCategory: c, includeInEmails: true })) }); onAdded(); onClose(); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>{busy ? "Adding…" : "Add"}</Button>
      </DialogActions>
    </Dialog>
  );
}
