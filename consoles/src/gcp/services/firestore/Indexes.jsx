/* Indexes — Composite (real CRUD), Single field (exemption overrides, stored not enforced)
 * and Vector (not simulated) tabs, as in the console's Indexes page. */
import { useState } from "react";
import { Box, Button, Chip, FormControl, InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [["composite", "Composite"], ["single-field", "Single field"], ["vector", "Vector"]];

export default function Indexes({ params, query }) {
  const db = params.name;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "composite";
  return (
    <>
      <PageHeader title="Indexes" />
      <Tabs value={tab} onChange={(_, t) => { location.hash = `#/firestore/databases/${encodeURIComponent(db)}/indexes${t === "composite" ? "" : "?tab=" + t}`; }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Indexes tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "composite" && <Composite db={db} />}
      {tab === "single-field" && <SingleField db={db} />}
      {tab === "vector" && <CapabilityContainer id="gcp.firestore.vector-indexes" title="Vector indexes" />}
    </>
  );
}

function Composite({ db }) {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.listIndexes(db, "-"), [db]);

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}>
        <Button variant="contained" startIcon={<AddIcon />} href={`#/firestore/databases/${encodeURIComponent(db)}/create-index`}>Create index</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
      </Stack>
      <ResourceTable
        resourceName="indexes"
        items={data}
        rowKey={(i) => i.name}
        loading={loading}
        error={error}
        onRetry={reload}
        selectable
        selected={sel}
        onSelectedChange={setSel}
        filterPlaceholder="Filter indexes"
        columns={[
          { id: "collection", header: "Collection ID", sortField: "collectionGroup", cell: (i) => i.collectionGroup },
          { id: "fields", header: "Fields indexed", wrap: true, cell: (i) => i.fields.map((f) => `${f.fieldPath} (${f.arrayConfig ? "Array" : f.order === "DESCENDING" ? "Decreasing" : "Increasing"})`).join(", ") },
          { id: "scope", header: "Query scope", cell: (i) => i.queryScope === "COLLECTION_GROUP" ? "Collection group" : "Collection" },
          { id: "id", header: "Index ID", cell: (i) => i.name.split("/").pop() },
          { id: "status", header: "Status", cell: () => <Chip size="small" color="success" label="Enabled" /> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No composite indexes yet.</Typography>}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} title={`Delete ${sel.length} index${sel.length === 1 ? "" : "es"}?`} confirmText="DELETE"
        onConfirm={async () => {
          for (const name of sel) { const [, , , , , , cid, , iid] = name.split("/"); await api.deleteIndex(db, cid, iid); }
          notify.success(`Deleted ${sel.length} index${sel.length === 1 ? "" : "es"}`);
          setSel([]); reload();
        }}>
        <Typography variant="body2">{sel.map((n) => n.split("/").pop()).join(", ")}</Typography>
      </DeleteDialog>
    </Box>
  );
}

function SingleField({ db }) {
  const notify = useNotify();
  const { data = [], loading, error, reload } = useAsync(() => api.listFieldExemptions(db), [db]);
  const [open, setOpen] = useState(false);
  const [group, setGroup] = useState("");
  const [path, setPath] = useState("");
  const [mode, setMode] = useState("disabled");

  return (
    <CapabilityContainer id="gcp.firestore.single-field-exemptions" title="Single field exemptions"
      actions={<Button size="small" startIcon={<AddIcon />} onClick={() => setOpen(true)}>Add exemption</Button>}>
      <ResourceTable
        resourceName="exemptions"
        items={data}
        rowKey={(f) => f.name}
        loading={loading}
        error={error}
        onRetry={reload}
        filterPlaceholder="Filter fields"
        columns={[
          { id: "collection", header: "Collection ID", cell: (f) => api.ttlGroupOf(f) },
          { id: "field", header: "Field path", cell: (f) => api.ttlFieldOf(f) },
          { id: "config", header: "Index config", cell: (f) => f.indexConfig.indexes.length ? "Indexing enabled" : "Indexing disabled" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No single-field exemptions. Every field is indexed by default.</Typography>}
      />
      {open && (
        <ExemptionDialog group={group} path={path} mode={mode} onGroup={setGroup} onPath={setPath} onMode={setMode}
          onClose={() => setOpen(false)} onSave={async () => {
            await api.setFieldExemption(db, group, path, mode === "disabled" ? [] : [{ order: "ASCENDING" }, { order: "DESCENDING" }]);
            notify.success(`Saved exemption for "${path}"`);
            setGroup(""); setPath(""); reload();
          }} />
      )}
    </CapabilityContainer>
  );
}

function ExemptionDialog({ group, path, mode, onGroup, onPath, onMode, onClose, onSave }) {
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); try { await onSave(); onClose(); } finally { setBusy(false); } };
  return (
    <Box sx={{ mt: 2, p: 2, border: 1, borderColor: "divider", borderRadius: 2 }}>
      <Stack spacing={2} sx={{ maxWidth: 420 }}>
        <TextField label="Collection ID" value={group} onChange={(e) => onGroup(e.target.value.trim())} />
        <TextField label="Field path" value={path} onChange={(e) => onPath(e.target.value.trim())} />
        <FormControl><InputLabel id="exemption-mode">Index config</InputLabel>
          <Select labelId="exemption-mode" label="Index config" value={mode} onChange={(e) => onMode(e.target.value)}>
            <MenuItem value="disabled">Indexing disabled</MenuItem>
            <MenuItem value="enabled">Indexing enabled</MenuItem>
          </Select>
        </FormControl>
        <Stack direction="row" spacing={1}>
          <Button variant="contained" disabled={busy || !group || !path} onClick={go}>{busy ? "Saving…" : "Save"}</Button>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
