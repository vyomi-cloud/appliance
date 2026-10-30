/* Schemas — Pub/Sub's Avro / Protocol Buffer schema registry (schemas.create/list/delete). */
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

export default function Schemas() {
  const { data = [], loading, error, reload } = useAsync(() => api.listSchemas(), []);
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);

  const deleteSelected = async () => {
    let ok = 0, fail = 0;
    for (const name of sel) { try { await api.deleteSchema(api.shortId(name)); ok++; } catch { fail++; } }
    if (ok) notify.success(`Deleted ${ok} schema${ok === 1 ? "" : "s"}`);
    if (fail) notify.error(`${fail} schema${fail === 1 ? "" : "s"} failed to delete`);
    setSel([]); reload();
  };

  return (
    <>
      <PageHeader title="Schemas" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create schema</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </>} />
      <ResourceTable
        resourceName="schemas"
        items={data}
        rowKey={(s) => s.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        columns={[
          { id: "id", header: "Schema ID", cell: (s) => api.shortId(s.name) },
          { id: "type", header: "Schema type", cell: (s) => (s.type === "PROTOCOL_BUFFER" ? "Protocol Buffer" : s.type === "AVRO" ? "Avro" : s.type) },
          { id: "rev", header: "Latest revision", cell: (s) => s.revisionId },
          { id: "revCreated", header: "Revision created", cell: (s) => s.revisionCreateTime },
        ]}
        empty={
          <Stack spacing={1.5} alignItems="center">
            <Typography variant="body2" color="text.secondary">No schemas to display.</Typography>
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreate(true)}>Create schema</Button>
          </Stack>
        }
      />
      <DeleteDialog
        open={del}
        onClose={() => setDel(false)}
        title={sel.length === 1 ? "Delete schema?" : `Delete ${sel.length} schemas?`}
        confirmText={sel.length === 1 ? api.shortId(sel[0]) : "DELETE"}
        warning="This can't be undone."
        onConfirm={deleteSelected}
      >
        <Typography variant="body2">{sel.map(api.shortId).join(", ")} will be permanently deleted.</Typography>
      </DeleteDialog>
      <CreateSchemaDialog open={create} onClose={() => setCreate(false)} onCreated={() => { notify.success("Schema created"); reload(); }} />
    </>
  );
}

function CreateSchemaDialog({ open, onClose, onCreated }) {
  const [id, setId] = useState("");
  const [type, setType] = useState("AVRO");
  const [definition, setDefinition] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const go = async () => {
    setBusy(true); setError(null);
    try { await api.createSchema(id, type, definition); onCreated(); onClose(); setId(""); setDefinition(""); }
    catch (e) { setError(e); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="create-schema-title">
      <DialogTitle id="create-schema-title">Create a schema</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <ErrorAlert error={error} title="Failed to create schema" />
          <TextField label="Schema ID" autoFocus value={id} onChange={(e) => setId(e.target.value.trim())} />
          <FormControl>
            <InputLabel id="schema-type-l">Type</InputLabel>
            <Select labelId="schema-type-l" label="Type" value={type} onChange={(e) => setType(e.target.value)}>
              <MenuItem value="AVRO">Avro</MenuItem>
              <MenuItem value="PROTOCOL_BUFFER">Protocol Buffer</MenuItem>
            </Select>
          </FormControl>
          <TextField label="Definition" multiline minRows={5} value={definition} onChange={(e) => setDefinition(e.target.value)}
            placeholder='{"type":"record","name":"Message","fields":[]}' />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !id || !definition.trim()} onClick={go}>{busy ? "Creating…" : "Create"}</Button>
      </DialogActions>
    </Dialog>
  );
}
