/* Snapshots — a subscription's captured backlog, replayable later via subscriptions.seek. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, InputLabel,
  MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Snapshots() {
  const { data = [], loading, error, reload } = useAsync(() => api.listSnapshots(), []);
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);

  const deleteSelected = async () => {
    let ok = 0, fail = 0;
    for (const name of sel) { try { await api.deleteSnapshot(api.shortId(name)); ok++; } catch { fail++; } }
    if (ok) notify.success(`Deleted ${ok} snapshot${ok === 1 ? "" : "s"}`);
    if (fail) notify.error(`${fail} snapshot${fail === 1 ? "" : "s"} failed to delete`);
    setSel([]); reload();
  };

  return (
    <>
      <PageHeader title="Snapshots" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create snapshot</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="snapshots"
        items={data}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        columns={[
          { id: "id", header: "Snapshot ID", cell: (s) => api.shortId(s.name) },
          { id: "topic", header: "Topic name", cell: (s) => s.topic },
          { id: "sub", header: "Subscription", cell: (s) => api.shortId(s.subscription) },
          { id: "expiration", header: "Expiration", cell: (s) => s.expireTime },
          { id: "labels", header: "Labels", cell: (s) => api.labelsText(s.labels) },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No snapshots to display.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create snapshot</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete snapshot?" : `Delete ${sel.length} snapshots?`}
        confirmText={sel.length === 1 ? api.shortId(sel[0]) : "DELETE"}
        warning="This can't be undone."
        onConfirm={deleteSelected}
      >
        <Typography variant="body2">{sel.map(api.shortId).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      <CreateSnapshotDialog open={create} onClose={() => setCreate(false)} onCreated={() => { notify.success("Snapshot created"); reload(); }} />
    </>
  );
}

function CreateSnapshotDialog({ open, onClose, onCreated }) {
  const subs = useAsync(() => (open ? api.listSubscriptions() : Promise.resolve([])), [open]);
  const [id, setId] = useState("");
  const [sub, setSub] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await api.createSnapshot(id, sub); onCreated(); onClose(); setId(""); setSub(""); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="create-snap3-title">
      <DialogTitle id="create-snap3-title">Create a snapshot</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create snapshot" />
          <TextField label="Snapshot ID" autoFocus value={id} onChange={(e) => setId(e.target.value.trim())} />
          <FormControl>
            <InputLabel id="snap-sub3-l">Subscription</InputLabel>
            <Select labelId="snap-sub3-l" label="Subscription" value={sub} onChange={(e) => setSub(e.target.value)}>
              {(subs.data || []).map((s) => <MenuItem key={s.name} value={s.name}>{api.shortId(s.name)}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !id || !sub} onClick={go}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
