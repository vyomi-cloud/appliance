/* Data Explorer: a NOSQL API resource tree (databases → containers → Items) over the native
 * Cosmos DB REST (SQL/Core API) data plane, the "New Container" create form the real portal
 * shows by default when nothing is selected yet, and an Items browser with a real SQL query
 * box. Settings / Stored Procedures / User Defined Functions / Triggers under a container are
 * an honest gap — the core only models databases, containers, documents and SELECT queries. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Radio, RadioGroup, Select,
  Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ChevronDown16Regular, ChevronRight16Regular, Delete20Regular, Play20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { FormRow } from "../../kit/CreateWizard.jsx";
import { ErrorBar, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

const NEW_ITEM_TEMPLATE = '{\n  "id": "replace-with-new-document-id"\n}';

export default function DataExplorer() {
  const notify = useNotify();
  const dbs = useAsync(() => api.listDatabases(), []);
  const [containersByDb, setContainersByDb] = useState({});
  const [expanded, setExpanded] = useState({});
  const [view, setView] = useState({ type: "new-container" });
  const [search, setSearch] = useState("");

  const loadContainers = async (dbId) => {
    const cs = await api.listContainers(dbId).catch(() => []);
    setContainersByDb((m) => ({ ...m, [dbId]: cs }));
  };
  const toggle = async (dbId) => {
    const open = !expanded[dbId];
    setExpanded((e) => ({ ...e, [dbId]: open }));
    if (open && !containersByDb[dbId]) await loadContainers(dbId);
  };
  const reloadTree = async () => { await dbs.reload(); for (const id of Object.keys(expanded)) if (expanded[id]) await loadContainers(id); };

  const q = search.trim().toLowerCase();
  const databases = (dbs.data || []).filter((d) => !q || d.id.toLowerCase().includes(q) || (containersByDb[d.id] || []).some((c) => c.id.toLowerCase().includes(q)));

  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Data Explorer commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setView({ type: "new-container" })}>New Container</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reloadTree}>Refresh</ToolbarButton>
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 8 }}>
        <nav style={{ width: 260, flex: "none" }}>
          <div className="vy-muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>NOSQL API</div>
          <Input size="small" style={{ width: "100%" }} placeholder="Search resources" aria-label="Search resources" value={search} onChange={(_, d) => setSearch(d.value)} />
          <div style={{ marginTop: 8 }}>
            {dbs.loading ? <Spinner size="tiny" /> : databases.length ? databases.map((d) => (
              <div key={d.id}>
                <button style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 4px", font: "inherit", color: "inherit", background: "none", border: 0, width: "100%", textAlign: "left", cursor: "pointer" }}
                  aria-expanded={!!expanded[d.id]} onClick={() => toggle(d.id)}>
                  {expanded[d.id] ? <ChevronDown16Regular /> : <ChevronRight16Regular />} {d.id}
                </button>
                {expanded[d.id] && (
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    {(containersByDb[d.id] || []).map((c) => (
                      <a key={c.id} href="#" style={{ paddingLeft: 28, fontWeight: view.type === "items" && view.db === d.id && view.coll === c.id ? 600 : 400 }}
                        onClick={(e) => { e.preventDefault(); setView({ type: "items", db: d.id, coll: c.id }); }}>
                        {c.id}
                      </a>
                    ))}
                    {!containersByDb[d.id]?.length && <div className="vy-muted" style={{ fontSize: 12, padding: "2px 28px" }}>No containers</div>}
                  </div>
                )}
              </div>
            )) : <div className="vy-muted" style={{ fontSize: 12 }}>No databases yet — use New Container to create one.</div>}
          </div>
        </nav>
        <div style={{ flex: 1, minWidth: 0 }}>
          {view.type === "new-container"
            ? <NewContainer databases={dbs.data || []} onCreated={async (db, coll) => { await reloadTree(); setExpanded((e) => ({ ...e, [db]: true })); await loadContainers(db); setView({ type: "items", db, coll }); }} notify={notify} />
            : <Items db={view.db} coll={view.coll} />}
        </div>
      </div>
    </>
  );
}

// ── New Container (the default Data Explorer body when nothing is selected) ────────────
function NewContainer({ databases, onCreated, notify }) {
  const [dbMode, setDbMode] = useState(databases.length ? "existing" : "new");
  const [newDbId, setNewDbId] = useState("");
  const [existingDbId, setExistingDbId] = useState(databases[0]?.id || "");
  const [shareThroughput, setShareThroughput] = useState(false);
  const [dbThroughputMode, setDbThroughputMode] = useState("Autoscale");
  const [dbMaxRu, setDbMaxRu] = useState(1000);
  const [containerId, setContainerId] = useState("");
  const [indexing, setIndexing] = useState("Automatic");
  const [partitionKey, setPartitionKey] = useState("");
  const [hpkGap, setHpkGap] = useState(false);
  const [uniqueKeys, setUniqueKeys] = useState([]);
  const [analyticalStore, setAnalyticalStore] = useState("Off");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => { if (!existingDbId && databases.length) setExistingDbId(databases[0].id); }, [databases]);

  const valid = (dbMode === "new" ? newDbId.trim() : existingDbId) && containerId.trim() && partitionKey.trim();
  const ok = async () => {
    setErr(null); setBusy(true);
    try {
      const dbId = dbMode === "new" ? newDbId.trim() : existingDbId;
      if (dbMode === "new") await api.createDatabase(dbId);
      await api.createContainer(dbId, containerId.trim(), partitionKey.trim(), { indexingOff: indexing === "Off", uniqueKeys: uniqueKeys.filter(Boolean), analyticalStore });
      notify.success(`Container '${containerId.trim()}' was created in database '${dbId}'.`, "Container created");
      onCreated(dbId, containerId.trim());
    } catch (e) { setErr(e); notify.error(e, "Creating container failed"); }
    finally { setBusy(false); }
  };

  return (
    <section className="vy-section">
      <h3>New Container</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 480 }}>
        <FormRow label="Database id">
          <RadioGroup value={dbMode} onChange={(_, d) => setDbMode(d.value)} aria-label="Database id mode">
            <Radio value="new" label="Create new" /><Radio value="existing" label="Use existing" />
          </RadioGroup>
          {dbMode === "new" ? (
            <>
              <Input value={newDbId} onChange={(_, d) => setNewDbId(d.value)} placeholder="Enter new database id" aria-label="Database id" style={{ width: "100%", marginTop: 4 }} />
              <Checkbox label="Share throughput across containers" checked={shareThroughput} onChange={(_, d) => setShareThroughput(!!d.checked)} />
            </>
          ) : (
            <Select value={existingDbId} onChange={(_, d) => setExistingDbId(d.value)} aria-label="Existing database id" style={{ width: "100%", marginTop: 4 }}>
              {databases.map((d) => <option key={d.id} value={d.id}>{d.id}</option>)}
            </Select>
          )}
        </FormRow>
        <FormRow label="Database throughput">
          <RadioGroup disabled={!(dbMode === "new" && shareThroughput)} value={dbThroughputMode} onChange={(_, d) => setDbThroughputMode(d.value)} aria-label="Database throughput">
            <Radio value="Autoscale" label="Autoscale" /><Radio value="Manual" label="Manual" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Database Max RU/s">
          <Input type="number" disabled={!(dbMode === "new" && shareThroughput)} value={String(dbMaxRu)} onChange={(_, d) => setDbMaxRu(d.value)} aria-label="Database Max RU/s" />
        </FormRow>
        <FormRow label="Container id" required>
          <Input value={containerId} onChange={(_, d) => setContainerId(d.value)} aria-label="Container id" />
        </FormRow>
        <FormRow label="Indexing">
          <RadioGroup value={indexing} onChange={(_, d) => setIndexing(d.value)} aria-label="Indexing">
            <Radio value="Automatic" label="Automatic" /><Radio value="Off" label="Off" />
          </RadioGroup>
        </FormRow>
        <FormRow label="Partition key" required>
          <Input value={partitionKey} onChange={(_, d) => setPartitionKey(d.value)} placeholder="/pk" aria-label="Partition key" />
        </FormRow>
        <div>
          <Button size="small" onClick={() => setHpkGap(true)}>Add hierarchical partition key</Button>
          {hpkGap && <div style={{ marginTop: 6 }}><NotSimulated feature="Hierarchical (multi-level) partition keys" note="Containers in Vyomi always use a single partition key path." /></div>}
        </div>
        <FormRow label="Unique keys">
          <div>
            <Table size="small" aria-label="Unique keys">
              <TableHeader><TableRow><TableHeaderCell>Unique key</TableHeaderCell><TableHeaderCell style={{ width: 40 }} /></TableRow></TableHeader>
              <TableBody>
                {uniqueKeys.map((k, i) => (
                  <TableRow key={i}>
                    <TableCell><Input size="small" value={k} placeholder="/path" onChange={(_, d) => setUniqueKeys((xs) => xs.map((x, j) => (j === i ? d.value : x)))} aria-label={`Unique key ${i + 1}`} /></TableCell>
                    <TableCell><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Remove unique key" onClick={() => setUniqueKeys((xs) => xs.filter((_, j) => j !== i))} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Button size="small" style={{ marginTop: 4 }} onClick={() => setUniqueKeys((xs) => [...xs, ""])}>Add unique key</Button>
          </div>
        </FormRow>
        <FormRow label="Analytical store">
          <RadioGroup value={analyticalStore} onChange={(_, d) => setAnalyticalStore(d.value)} aria-label="Analytical store">
            <Radio value="On" label="On" /><Radio value="Off" label="Off" />
          </RadioGroup>
        </FormRow>
        <ErrorBar error={err} />
        <div><Button appearance="primary" disabled={!valid || busy} onClick={ok}>OK</Button></div>
      </div>
    </section>
  );
}

// ── Items (a container's documents, over the native /docs wire + a real SQL query) ─────
function Items({ db, coll }) {
  const notify = useNotify();
  const docs = useAsync(() => api.listDocuments(db, coll), [db, coll]);
  const [query, setQuery] = useState("SELECT * FROM c");
  const [results, setResults] = useState(null);
  const [queryError, setQueryError] = useState(null);
  const [running, setRunning] = useState(false);
  const [newItem, setNewItem] = useState(null); // text of the new-item dialog, or null
  const [edit, setEdit] = useState(null); // {id, text}

  useEffect(() => { setResults(null); setQuery("SELECT * FROM c"); }, [db, coll]);

  const run = async () => {
    setRunning(true); setQueryError(null);
    try { setResults(await api.runQuery(db, coll, query)); }
    catch (e) { setQueryError(e); setResults(null); }
    finally { setRunning(false); }
  };
  const rows = results ?? docs.data ?? [];

  const createItem = async (text) => {
    try {
      const doc = JSON.parse(text);
      await api.putDocument(db, coll, doc);
      notify.success(`Item '${doc.id}' was saved.`, "Item saved");
      setNewItem(null); setEdit(null);
      setResults(null); docs.reload();
    } catch (e) { notify.error(e, "Saving item failed"); }
  };

  return (
    <section className="vy-section">
      <h3>{db} / {coll} — Items</h3>
      <div className="vy-cmdbar" role="toolbar" aria-label="Items commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setNewItem(NEW_ITEM_TEMPLATE)}>New Item</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { setResults(null); docs.reload(); }}>Refresh</ToolbarButton>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <Input style={{ flex: 1, fontFamily: "monospace" }} value={query} onChange={(_, d) => setQuery(d.value)} aria-label="SQL query" />
        <Button icon={<Play20Regular />} disabled={running} onClick={run}>Execute</Button>
      </div>
      <ErrorBar error={queryError} title="Query failed" />
      <Table size="small" aria-label="Items" style={{ marginTop: 8 }}>
        <TableHeader><TableRow><TableHeaderCell>id</TableHeaderCell><TableHeaderCell>Document</TableHeaderCell><TableHeaderCell style={{ width: 90 }} /></TableRow></TableHeader>
        <TableBody>
          {docs.loading ? <TableRow><TableCell colSpan={3}><Spinner size="tiny" /></TableCell></TableRow> : rows.length ? rows.map((d) => (
            <TableRow key={d.id}>
              <TableCell>{d.id}</TableCell>
              <TableCell style={{ fontFamily: "monospace", fontSize: 12, maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{JSON.stringify(d)}</TableCell>
              <TableCell>
                <Button appearance="subtle" size="small" onClick={() => setEdit({ id: d.id, text: JSON.stringify(d, null, 2) })}>Edit</Button>
                <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete ${d.id}`}
                  onClick={async () => { await api.deleteDocument(db, coll, d.id); notify.success(`Item '${d.id}' was deleted.`, "Delete succeeded"); setResults(null); docs.reload(); }} />
              </TableCell>
            </TableRow>
          )) : <TableRow><TableCell colSpan={3} className="vy-muted">No items to display</TableCell></TableRow>}
        </TableBody>
      </Table>

      <Dialog open={!!newItem} onOpenChange={(_, d) => !d.open && setNewItem(null)}>
        <DialogSurface aria-label="New Item">
          <DialogBody>
            <DialogTitle>New Item</DialogTitle>
            <DialogContent><Textarea value={newItem || ""} onChange={(_, d) => setNewItem(d.value)} style={{ width: "100%", minHeight: 220, fontFamily: "monospace" }} aria-label="New item JSON" /></DialogContent>
            <DialogActions><Button appearance="primary" onClick={() => createItem(newItem)}>Save</Button><Button onClick={() => setNewItem(null)}>Discard</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog open={!!edit} onOpenChange={(_, d) => !d.open && setEdit(null)}>
        <DialogSurface aria-label="Edit Item">
          <DialogBody>
            <DialogTitle>Edit Item</DialogTitle>
            <DialogContent><Textarea value={edit?.text || ""} onChange={(_, d) => setEdit((x) => ({ ...x, text: d.value }))} style={{ width: "100%", minHeight: 220, fontFamily: "monospace" }} aria-label="Edit item JSON" /></DialogContent>
            <DialogActions><Button appearance="primary" onClick={() => createItem(edit.text)}>Update</Button><Button onClick={() => setEdit(null)}>Discard</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </section>
  );
}
