/* Firestore Studio — the console's data viewer (Panel view: collection > document > fields
 * columns) and its Query builder alternative, both on the native Firestore REST API. */
import { useState } from "react";
import {
  Box, Breadcrumbs, Button, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  FormControl, IconButton, InputLabel, List, ListItemButton, ListItemText, MenuItem, Paper, Select,
  Stack, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const OPS = ["EQUAL", "NOT_EQUAL", "LESS_THAN", "LESS_THAN_OR_EQUAL", "GREATER_THAN", "GREATER_THAN_OR_EQUAL", "ARRAY_CONTAINS", "ARRAY_CONTAINS_ANY", "IN", "NOT_IN"];

export default function FirestoreStudio({ params }) {
  const db = params.name;
  const notify = useNotify();
  const [mode, setMode] = useState("panel");
  const [parent, setParent] = useState("");         // "" (root) or a document path
  const [coll, setColl] = useState(null);           // selected collection id under `parent`
  const [docId, setDocId] = useState(null);         // selected document id under coll
  const [docDialog, setDocDialog] = useState(null); // null | "start" | "add"
  const [addFieldOpen, setAddFieldOpen] = useState(false);
  const [delOpen, setDelOpen] = useState(false);

  const colls = useAsync(() => api.listCollectionIds(db, parent), [db, parent]);
  const fullColl = coll ? (parent ? `${parent}/${coll}` : coll) : null;
  const docs = useAsync(() => (fullColl ? api.listDocuments(db, fullColl) : Promise.resolve([])), [db, fullColl]);
  const fullDoc = fullColl && docId ? `${fullColl}/${docId}` : null;
  const doc = docs.data?.find((d) => api.docId(d) === docId);
  const subcolls = useAsync(() => (fullDoc ? api.listCollectionIds(db, fullDoc) : Promise.resolve([])), [db, fullDoc]);

  const selectColl = (id) => { setColl(id); setDocId(null); };
  const drillInto = (id) => { setParent(fullDoc); setColl(id); setDocId(null); };
  const crumbTo = (depth) => {
    const segs = parent.split("/").filter(Boolean);
    setParent(segs.slice(0, depth).join("/"));
    setColl(null); setDocId(null);
  };

  const reload = () => { colls.reload(); docs.reload(); subcolls.reload(); };

  return (
    <>
      <PageHeader title="Firestore Studio" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setDocDialog("start")}>Start collection</Button>
        <Button startIcon={<AddIcon />} disabled={!fullColl} onClick={() => setDocDialog("add")}>Add document</Button>
        <Button disabled={!fullDoc} onClick={() => setAddFieldOpen(true)}>Add field</Button>
        <Button startIcon={<DeleteIcon />} disabled={!fullDoc} onClick={() => setDelOpen(true)}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <ToggleButtonGroup size="small" exclusive value={mode} onChange={(_, v) => v && setMode(v)} sx={{ mb: 2 }} aria-label="View mode">
        <ToggleButton value="panel">Panel view</ToggleButton>
        <ToggleButton value="query">Query builder</ToggleButton>
      </ToggleButtonGroup>

      {mode === "panel" ? (
        <PanelView
          db={db} parent={parent} colls={colls} coll={coll} docs={docs} docId={docId} doc={doc} subcolls={subcolls}
          onSelectColl={selectColl} onSelectDoc={setDocId} onDrillInto={drillInto} onCrumb={crumbTo}
          onFieldsSaved={() => { docs.reload(); }}
        />
      ) : (
        <QueryBuilder db={db} defaultCollection={fullColl || ""} />
      )}

      <StartCollectionDialog open={!!docDialog} onClose={() => setDocDialog(null)} db={db} parentPath={parent}
        fixedCollection={docDialog === "add" ? fullColl : null} onCreated={(newColl, newDoc) => {
          if (!fullColl || newColl !== fullColl) selectColl(newColl.split("/").pop());
          setDocId(newDoc);
          colls.reload(); docs.reload();
        }} />
      <AddFieldDialog open={addFieldOpen} onClose={() => setAddFieldOpen(false)} onSave={async (name, type, value) => {
        await api.setDocument(db, fullDoc, { [name]: api.encodeValue(type, value) });
        notify.success(`Added field "${name}"`);
        docs.reload();
      }} />
      <DeleteDialog open={delOpen} onClose={() => setDelOpen(false)} title="Delete document?" confirmText="DELETE"
        warning="Deleting a document does not delete its subcollections." onConfirm={async () => {
          await api.deleteDocument(db, fullDoc);
          notify.success(`Deleted document "${docId}"`);
          setDocId(null); docs.reload();
        }}>
        <Typography variant="body2"><b>{fullDoc}</b> will be permanently deleted.</Typography>
      </DeleteDialog>
    </>
  );
}

function Pane({ title, children }) {
  return (
    <Paper variant="outlined" sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", borderRadius: 2, overflow: "hidden" }}>
      <Typography variant="subtitle2" sx={{ px: 1.5, py: 1, borderBottom: 1, borderColor: "divider", fontWeight: 600 }}>{title}</Typography>
      <Box sx={{ flex: 1, overflow: "auto", minHeight: 320, maxHeight: 520 }}>{children}</Box>
    </Paper>
  );
}

function PanelView({ db, parent, colls, coll, docs, docId, doc, subcolls, onSelectColl, onSelectDoc, onDrillInto, onCrumb, onFieldsSaved }) {
  const segs = parent.split("/").filter(Boolean);
  return (
    <Stack spacing={1.5}>
      <Breadcrumbs aria-label="Parent path">
        <Typography variant="body2" component={segs.length ? "a" : "span"} href="#" onClick={(e) => { e.preventDefault(); onCrumb(0); }} sx={{ cursor: segs.length ? "pointer" : "default" }}>root</Typography>
        {segs.map((s, i) => (
          <Typography key={i} variant="body2" component={i < segs.length - 1 ? "a" : "span"} href="#"
            onClick={(e) => { e.preventDefault(); onCrumb(i + 1); }} sx={{ cursor: i < segs.length - 1 ? "pointer" : "default" }}>{s}</Typography>
        ))}
      </Breadcrumbs>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start" }}>
        <Pane title="Collections">
          <ErrorAlert error={colls.error} />
          <List dense disablePadding>
            {(colls.data || []).map((id) => (
              <ListItemButton key={id} selected={id === coll} onClick={() => onSelectColl(id)}><ListItemText primary={id} /></ListItemButton>
            ))}
            {!colls.loading && !(colls.data || []).length && <Typography variant="body2" color="text.secondary" sx={{ p: 1.5 }}>No collections here yet. Use "Start collection".</Typography>}
          </List>
        </Pane>
        <Pane title="Documents">
          {coll ? (
            <List dense disablePadding>
              {(docs.data || []).map((d) => {
                const id = api.docId(d);
                return <ListItemButton key={id} selected={id === docId} onClick={() => onSelectDoc(id)}><ListItemText primary={id} /></ListItemButton>;
              })}
              {!docs.loading && !(docs.data || []).length && <Typography variant="body2" color="text.secondary" sx={{ p: 1.5 }}>No documents in this collection.</Typography>}
            </List>
          ) : <Typography variant="body2" color="text.secondary" sx={{ p: 1.5 }}>Select a collection.</Typography>}
        </Pane>
        <Pane title="Fields">
          {doc ? (
            <FieldsView db={db} doc={doc} subcolls={subcolls.data || []} onDrillInto={onDrillInto} onSaved={onFieldsSaved} />
          ) : <Typography variant="body2" color="text.secondary" sx={{ p: 1.5 }}>Select a document.</Typography>}
        </Pane>
      </Stack>
    </Stack>
  );
}

function FieldsView({ db, doc, subcolls, onDrillInto, onSaved }) {
  const notify = useNotify();
  const entries = Object.entries(doc.fields || {});
  return (
    <Box sx={{ p: 1.5 }}>
      <Stack spacing={0.5} sx={{ mb: subcolls.length ? 2 : 0 }}>
        {entries.map(([name, v]) => (
          <Stack key={name} direction="row" spacing={1} justifyContent="space-between">
            <Typography variant="body2" sx={{ fontWeight: 500 }}>{name}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ fontFamily: "monospace", textAlign: "right", wordBreak: "break-all" }}>
              ({api.valueType(v)}) {api.displayValue(v)}
            </Typography>
          </Stack>
        ))}
        {!entries.length && <Typography variant="body2" color="text.secondary">No fields.</Typography>}
      </Stack>
      {subcolls.length > 0 && (
        <>
          <Divider sx={{ mb: 1 }} />
          <Typography variant="caption" color="text.secondary">Subcollections</Typography>
          <List dense disablePadding>
            {subcolls.map((id) => <ListItemButton key={id} onClick={() => onDrillInto(id)}><ListItemText primary={id} /></ListItemButton>)}
          </List>
        </>
      )}
    </Box>
  );
}

function StartCollectionDialog({ open, onClose, db, parentPath, fixedCollection, onCreated }) {
  const [collectionId, setCollectionId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [rows, setRows] = useState([{ name: "", type: "string", value: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const coll = fixedCollection || (parentPath ? `${parentPath}/${collectionId}` : collectionId);
  const canSave = fixedCollection || collectionId.trim();

  const save = async () => {
    setBusy(true); setError(null);
    try {
      const fields = api.fieldsFromRows(rows.filter((r) => r.name.trim()));
      const d = await api.createDocument(db, coll, fields, documentId.trim() || undefined);
      onCreated(coll, api.docId(d));
      onClose();
      setCollectionId(""); setDocumentId(""); setRows([{ name: "", type: "string", value: "" }]);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth aria-labelledby="sc-title">
      <DialogTitle id="sc-title">{fixedCollection ? "Add document" : "Start a collection"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <ErrorAlert error={error} title="Failed to save" />}
          <TextField label="Parent path" value={parentPath || "/"} disabled inputProps={{ "aria-label": "Parent path" }} />
          {!fixedCollection && (
            <TextField label="Collection ID" required value={collectionId} onChange={(e) => setCollectionId(e.target.value.trim())} inputProps={{ "aria-label": "Collection ID" }} />
          )}
          <Stack direction="row" spacing={1}>
            <TextField label="Document ID" value={documentId} onChange={(e) => setDocumentId(e.target.value.trim())} fullWidth inputProps={{ "aria-label": "Document ID" }} />
            <Button onClick={() => setDocumentId(Math.random().toString(36).slice(2, 10))}>Auto-ID</Button>
          </Stack>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>Fields</Typography>
          {rows.map((r, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label="Field name" value={r.name} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
              <FormControl sx={{ width: 150 }}>
                <InputLabel id={`type-${i}`}>Field type</InputLabel>
                <Select labelId={`type-${i}`} label="Field type" value={r.type} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, type: e.target.value } : x))}>
                  {api.FIELD_TYPES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
                </Select>
              </FormControl>
              <TextField label="Field value" value={r.value} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} disabled={["map", "array", "null"].includes(r.type)} />
              <IconButton aria-label={`Delete field ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <Box><Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { name: "", type: "string", value: "" }])}>Add field</Button></Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !canSave} onClick={save}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function AddFieldDialog({ open, onClose, onSave }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("string");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); try { await onSave(name, type, value); onClose(); setName(""); setValue(""); } finally { setBusy(false); } };
  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth aria-labelledby="af-title">
      <DialogTitle id="af-title">Add field</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Field name" autoFocus value={name} onChange={(e) => setName(e.target.value)} inputProps={{ "aria-label": "Field name" }} />
          <FormControl><InputLabel id="af-type">Field type</InputLabel>
            <Select labelId="af-type" label="Field type" value={type} onChange={(e) => setType(e.target.value)}>
              {api.FIELD_TYPES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Field value" value={value} onChange={(e) => setValue(e.target.value)} disabled={["map", "array", "null"].includes(type)} />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={busy || !name.trim()} onClick={go}>{busy ? "Saving…" : "Save"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function QueryBuilder({ db, defaultCollection }) {
  const [collectionId, setCollectionId] = useState(defaultCollection);
  const [filters, setFilters] = useState([{ field: "", op: "EQUAL", value: "" }]);
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      const active = filters.filter((f) => f.field.trim());
      const where = active.length === 0 ? undefined : active.length === 1
        ? { fieldFilter: { field: { fieldPath: active[0].field }, op: active[0].op, value: { stringValue: active[0].value } } }
        : { compositeFilter: { op: "AND", filters: active.map((f) => ({ fieldFilter: { field: { fieldPath: f.field }, op: f.op, value: { stringValue: f.value } } })) } };
      const sq = { from: [{ collectionId: collectionId.split("/").pop() }], ...(where ? { where } : {}) };
      const parent = collectionId.includes("/") ? collectionId.split("/").slice(0, -1).join("/") : "";
      const docs = await api.runQuery(db, parent, sq);
      setResults(docs);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Stack spacing={2}>
      <ErrorAlert error={error} title="Query failed" />
      <TextField label="Collection" value={collectionId} onChange={(e) => setCollectionId(e.target.value)} helperText="Collection ID, or a path like parentDoc/subcollection" sx={{ maxWidth: 420 }} inputProps={{ "aria-label": "Collection" }} />
      <Typography variant="body2" sx={{ fontWeight: 500 }}>Filters</Typography>
      {filters.map((f, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="center">
          <TextField label="Field" value={f.field} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, field: e.target.value } : x))} />
          <FormControl sx={{ width: 200 }}>
            <InputLabel id={`op-${i}`}>Operator</InputLabel>
            <Select labelId={`op-${i}`} label="Operator" value={f.op} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, op: e.target.value } : x))}>
              {OPS.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
            </Select>
          </FormControl>
          <TextField label="Value" value={f.value} onChange={(e) => setFilters(filters.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
          <IconButton aria-label={`Remove filter ${i + 1}`} onClick={() => setFilters(filters.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
        </Stack>
      ))}
      <Stack direction="row" spacing={1}>
        <Button startIcon={<AddIcon />} onClick={() => setFilters([...filters, { field: "", op: "EQUAL", value: "" }])}>Add filter</Button>
        <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={busy || !collectionId.trim()} onClick={run}>{busy ? "Running…" : "Run query"}</Button>
      </Stack>
      {results && (
        <Paper variant="outlined" sx={{ borderRadius: 2 }}>
          <Typography variant="subtitle2" sx={{ px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}>{results.length} result{results.length === 1 ? "" : "s"}</Typography>
          <List dense disablePadding>
            {results.map((d) => (
              <ListItemButton key={d.name} disableRipple sx={{ display: "block", "&:hover": { bgcolor: "transparent" } }}>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{api.docId(d)}</Typography>
                {Object.entries(d.fields || {}).map(([k, v]) => (
                  <Typography key={k} variant="caption" color="text.secondary" sx={{ display: "block", fontFamily: "monospace" }}>{k}: {api.displayValue(v)}</Typography>
                ))}
              </ListItemButton>
            ))}
            {!results.length && <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>No documents matched this query.</Typography>}
          </List>
        </Paper>
      )}
    </Stack>
  );
}
