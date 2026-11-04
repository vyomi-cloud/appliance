/* Datastore (Firestore in Datastore mode): entities browser (kind / namespace / GQL), create-edit-delete entity,
 * and composite indexes — all over the native Cloud Datastore API v1 (:runQuery, :commit, /indexes). */
import { useState } from "react";
import { Box, Button, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

function Dialog({ title, onClose, onSave, saveLabel = "Save", children }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Box role="dialog" aria-label={title} sx={{ position: "fixed", inset: 0, bgcolor: "rgba(0,0,0,.4)", display: "grid", placeItems: "center", zIndex: 1300 }} onClick={onClose}>
      <Box sx={{ bgcolor: "background.paper", borderRadius: 2, p: 3, minWidth: 440, maxWidth: 640 }} onClick={(e) => e.stopPropagation()}>
        <Typography variant="h3" component="h2" sx={{ mb: 2 }}>{title}</Typography>
        <Stack spacing={2}>{children}{error && <ErrorAlert error={error} />}</Stack>
        <Stack direction="row" spacing={1} sx={{ mt: 3, justifyContent: "flex-end" }}>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="contained" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { await onSave(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); } }}>{saveLabel}</Button>
        </Stack>
      </Box>
    </Box>
  );
}

export default function DatastoreStudio() {
  const project = useProject();
  const notify = useNotify();
  const dbs = useAsync(() => api.listDatabases().then((ds) => ds.filter((d) => d.type === "DATASTORE_MODE")), [project]);
  const [tab, setTab] = useState("entities");
  const db = (dbs.data || [])[0]?.name.split("/").pop();

  const createDb = async () => {
    try { await api.createDatabase("(default)", { type: "DATASTORE_MODE", locationId: "us-central1" }); notify.success("Created Datastore mode database (default)"); dbs.reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Datastore" actions={<Button startIcon={<RefreshIcon />} onClick={dbs.reload}>Refresh</Button>} />
      <ErrorAlert error={dbs.error} title="Failed to load databases" />
      {dbs.data && !db && (
        <Stack spacing={1.5} alignItems="flex-start" data-testid="ds-empty">
          <Typography variant="body1">There is no Firestore database in Datastore mode in this project.</Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={createDb}>Create a Datastore mode database</Button>
        </Stack>
      )}
      {db && (
        <>
          <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }} aria-label="Datastore tabs">
            <Tab value="entities" label="Entities" />
            <Tab value="indexes" label="Indexes" />
          </Tabs>
          {tab === "entities" ? <Entities db={db} /> : <Indexes db={db} />}
        </>
      )}
    </>
  );
}

function Entities({ db }) {
  const notify = useNotify();
  const [kind, setKind] = useState("");
  const [ns, setNs] = useState("");
  const [gql, setGql] = useState("");
  const [run, setRun] = useState(0);
  const [dlg, setDlg] = useState(null);
  const kinds = useAsync(() => api.dsCall("runQuery", { query: { kind: [{ name: "__kind__" }] }, partitionId: ns ? { namespaceId: ns } : undefined })
    .then((r) => (r.batch.entityResults || []).map((x) => x.entity.key.path[0].name)), [run, ns]);
  const q = gql.trim() || (kind ? `SELECT * FROM ${kind}` : "");
  const ents = useAsync(() => (q ? api.dsCall("runQuery", { partitionId: ns ? { namespaceId: ns } : undefined, gqlQuery: { queryString: q, allowLiterals: true } }).then((r) => (r.batch.entityResults || []).map((x) => x.entity)) : Promise.resolve([])), [q, run, ns]);
  const reload = () => setRun((n) => n + 1);

  const upsert = async (e, kindName, name, json) => {
    const props = Object.fromEntries(Object.entries(JSON.parse(json || "{}")).map(([k, v]) => [k, api.toDsValue(v)]));
    const key = e ? e.key : { partitionId: ns ? { namespaceId: ns } : undefined, path: [{ kind: kindName, ...(name ? (/^\d+$/.test(name) ? { id: name } : { name }) : {}) }] };
    await api.dsCall("commit", { mode: "NON_TRANSACTIONAL", mutations: [{ [e ? "update" : "upsert"]: { key, properties: props } }] });
    notify.success(e ? "Entity updated" : "Entity created");
    if (!kind) setKind(kindName);
    reload();
  };
  const del = async (e) => { try { await api.dsCall("commit", { mode: "NON_TRANSACTIONAL", mutations: [{ delete: e.key }] }); notify.success("Entity deleted"); reload(); } catch (x) { notify.error(x); } };

  return (
    <CapabilityContainer id="gcp.datastore.entities" title="Entities" actions={<Button startIcon={<AddIcon />} onClick={() => setDlg({ create: true })}>Create entity</Button>}>
      <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center">
        <FormControl sx={{ minWidth: 200 }}>
          <InputLabel id="ds-kind">Kind</InputLabel>
          <Select labelId="ds-kind" label="Kind" value={kind} onChange={(e) => { setKind(e.target.value); setGql(""); }} inputProps={{ "aria-label": "Kind" }}>
            {(kinds.data || []).map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Namespace" size="small" value={ns} onChange={(e) => setNs(e.target.value.trim())} />
        <TextField label="GQL query" size="small" fullWidth value={gql} placeholder={kind ? `SELECT * FROM ${kind} WHERE ... ORDER BY ... LIMIT 50` : "SELECT * FROM Kind"} onChange={(e) => setGql(e.target.value)} onKeyDown={(e) => e.key === "Enter" && reload()} />
        <Button variant="outlined" onClick={reload}>Run</Button>
      </Stack>
      <ErrorAlert error={ents.error} title="Query failed" />
      <ResourceTable
        resourceName="entities"
        items={ents.data || []}
        rowKey={(e) => JSON.stringify(e.key)}
        loading={ents.loading}
        onRetry={reload}
        filterPlaceholder="Filter"
        columns={[
          { id: "key", header: "Key", cell: (e) => api.dsKeyLabel(e.key) },
          { id: "props", header: "Properties", cell: (e) => <code style={{ fontSize: 12 }}>{JSON.stringify(api.fromDsValue({ entityValue: { properties: e.properties || {} } }))}</code> },
          { id: "act", header: "", cell: (e) => <>
            <IconButton size="small" aria-label="Edit entity" onClick={() => setDlg({ e })}><EditIcon fontSize="small" /></IconButton>
            <IconButton size="small" aria-label="Delete entity" onClick={() => del(e)}><DeleteIcon fontSize="small" /></IconButton></> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">{q ? "No entities match this query." : "Pick a kind or run a GQL query."}</Typography>}
      />
      {dlg && <EntityDialog dlg={dlg} onClose={() => setDlg(null)} onSave={upsert} />}
    </CapabilityContainer>
  );
}

function EntityDialog({ dlg, onClose, onSave }) {
  const e = dlg.e;
  const [kind, setKind] = useState(e ? e.key.path.at(-1).kind : "");
  const [name, setName] = useState("");
  const [json, setJson] = useState(e ? JSON.stringify(api.fromDsValue({ entityValue: { properties: e.properties || {} } }), null, 2) : '{\n  "title": "hello"\n}');
  return (
    <Dialog title={e ? "Edit entity" : "Create entity"} onClose={onClose} onSave={() => onSave(e, kind, name, json)}>
      {e ? <Typography variant="body2">{api.dsKeyLabel(e.key)}</Typography> : <>
        <TextField label="Kind" value={kind} onChange={(x) => setKind(x.target.value.trim())} />
        <TextField label="Key name or numeric id (blank = auto-allocated id)" value={name} onChange={(x) => setName(x.target.value.trim())} />
      </>}
      <TextField label="Properties (JSON)" multiline minRows={5} value={json} onChange={(x) => setJson(x.target.value)} inputProps={{ style: { fontFamily: "monospace", fontSize: 13 } }} />
    </Dialog>
  );
}

function Indexes({ db }) {
  const notify = useNotify();
  const idx = useAsync(() => api.dsListIndexes(db), [db]);
  const [dlg, setDlg] = useState(false);
  const [kind, setKind] = useState("");
  const [props, setProps] = useState("");
  const create = async () => {
    const properties = props.split(",").map((s) => s.trim()).filter(Boolean).map((s) => (s.startsWith("-") ? { name: s.slice(1), direction: "DESCENDING" } : { name: s, direction: "ASCENDING" }));
    await api.dsCreateIndex({ kind, properties });
    notify.success("Index created"); idx.reload();
  };
  return (
    <CapabilityContainer id="gcp.datastore.indexes" title="Composite indexes" actions={<Button startIcon={<AddIcon />} onClick={() => setDlg(true)}>Create index</Button>}>
      <ResourceTable
        resourceName="indexes"
        items={idx.data || []}
        rowKey={(i) => i.indexId}
        loading={idx.loading}
        error={idx.error}
        onRetry={idx.reload}
        columns={[
          { id: "kind", header: "Kind", cell: (i) => i.kind },
          { id: "props", header: "Properties", cell: (i) => i.properties.map((p) => `${p.name} ${p.direction === "DESCENDING" ? "↓" : "↑"}`).join(", ") },
          { id: "state", header: "Status", cell: (i) => i.state },
          { id: "act", header: "", cell: (i) => <IconButton size="small" aria-label="Delete index" onClick={async () => { await api.dsDeleteIndex(i.indexId); idx.reload(); }}><DeleteIcon fontSize="small" /></IconButton> },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No composite indexes. Queries that need one fail with the recommended definition.</Typography>}
      />
      {dlg && (
        <Dialog title="Create composite index" onClose={() => setDlg(false)} onSave={create} saveLabel="Create">
          <TextField label="Kind" value={kind} onChange={(e) => setKind(e.target.value.trim())} />
          <TextField label="Properties (comma separated, prefix - for descending)" value={props} onChange={(e) => setProps(e.target.value)} />
        </Dialog>
      )}
    </CapabilityContainer>
  );
}
