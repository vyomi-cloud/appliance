/* Agent Platform pages that used to be "Coming soon": Sessions, Memory Bank, RAG Engine, Agent Retrieval, Search / App Builder, Evaluation,
 * Metadata, Monitoring, Agent Registry, ADK, Topology, and the declared "Not in scope" pages. Every list/create/delete here is a real call on the
 * native aiplatform / discoveryengine REST wire (core/gcp_agentplatform_core, gcp_agentengine_core, gcp_vertex_core); no data is made up. */
import { useState } from "react";
import { Alert, Box, Button, Checkbox, Chip, Dialog, FormControlLabel, DialogActions, DialogContent, DialogTitle, IconButton, MenuItem, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import DeleteIcon from "@mui/icons-material/esm/DeleteOutline.js";
import { restJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { useProject } from "../../project.js";
import { PageHeader, Section, ErrorAlert, NotSimulatedContainer } from "../../kit/common.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { Link } from "../../link.jsx";
import ResourceList, { StateChip, Tabbed } from "./ResourceList.jsx";
import Crumbs from "./Crumbs.jsx";
import * as api from "./api.js";

const AP = { text: "Agent Platform", href: "#/vertex-ai" };
const Page = ({ title, group = "Agents", groupHref = "#/vertex-ai/agent-garden", children, actions }) => (
  <Box>
    <Crumbs trail={[AP, { text: group, href: groupHref }, { text: title }]} />
    <PageHeader title={title} actions={actions} />
    {children}
  </Box>
);
const P = (loc = "us-central1") => `/v1/projects/${encodeURIComponent(api_project())}/locations/${loc}`;
let _proj = "";
const api_project = () => _proj;
const useP = () => { _proj = useProject(); return _proj; };
const json = (method, path, body, query) => restJson(method, path, { body, query });

/* ── a reasoning engine (agent deployment) picker shared by Sessions and Memory Bank ── */
function useEngines() {
  const project = useP();
  const [region, setRegion] = useState("us-central1");
  const [engine, setEngine] = useState("");
  const r = useAsync(async () => { const xs = await api.list("reasoningEngines", { loc: region }); if (xs.length && !xs.some((x) => x.name === engine)) setEngine(xs[0].name); if (!xs.length) setEngine(""); return xs; }, [project, region]);
  const picker = (
    <Stack direction="row" spacing={1} alignItems="center" useFlexGap sx={{ flexWrap: "wrap" }}>
      <TextField select size="small" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} sx={{ minWidth: 170 }}>{api.REGIONS.map((x) => <MenuItem key={x} value={x}>{x}</MenuItem>)}</TextField>
      <TextField select size="small" label="Agent deployment" value={engine} onChange={(e) => setEngine(e.target.value)} sx={{ minWidth: 280 }} disabled={!r.data?.length}>
        {(r.data || []).map((x) => <MenuItem key={x.name} value={x.name}>{x.displayName} ({api.shortId(x.name)})</MenuItem>)}</TextField>
    </Stack>);
  const none = !r.loading && !r.data?.length && <Alert severity="info">No agent deployments in this region. Create one under <Link href="#/vertex-ai/adk">ADK</Link> or via the reasoningEngines API.</Alert>;
  return { engine, picker, none, engines: r.data || [], loading: r.loading, error: r.error };
}

const bar = (children) => <Stack direction="row" spacing={1} alignItems="center" useFlexGap sx={{ flexWrap: "wrap", mb: 1.5 }}>{children}</Stack>;
const fmt = (t) => (t ? new Date(t).toLocaleString() : "—");

/* ── Sessions ── */
export function Sessions() {
  const notify = useNotify();
  const { engine, picker, none } = useEngines();
  const [creating, setCreating] = useState(false);
  const [del, setDel] = useState(null);
  const [open, setOpen] = useState(null);
  const s = useAsync(() => (engine ? api.list("sessions", { parent: engine }) : Promise.resolve([])), [engine]);
  const ev = useAsync(() => (open ? api.list("events", { parent: open.name }).catch(() => []) : Promise.resolve([])), [open?.name]);
  return (
    <Page title="Sessions" actions={null}>
      {bar(<>{picker}
        <Button variant="contained" startIcon={<AddIcon />} disabled={!engine} onClick={() => setCreating(true)}>Create session</Button>
        <Button startIcon={<RefreshIcon />} onClick={s.reload}>Refresh</Button></>)}
      {none}
      {engine && <ResourceTable resourceName="sessions" items={s.data || []} rowKey={(x) => x.name} loading={s.loading} error={s.error} onRetry={s.reload} filterPlaceholder="Filter"
        columns={[
          { id: "id", header: "Session ID", sortValue: (x) => x.name, cell: (x) => <Link href="#" onClick={(e) => { e.preventDefault(); setOpen(x); }}>{api.shortId(x.name)}</Link> },
          { id: "user", header: "User ID", cell: (x) => x.userId },
          { id: "created", header: "Created", cell: (x) => fmt(x.createTime) }, { id: "updated", header: "Last updated", cell: (x) => fmt(x.updateTime) },
          { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete session ${api.shortId(x.name)}`} onClick={() => setDel(x)}><DeleteIcon fontSize="small" /></IconButton> }]}
        empty={<Typography variant="body2" color="text.secondary">No sessions. Sessions are created by the agent runtime (create_session / :query with a session_id) or here.</Typography>} />}
      <FormDialog open={creating} title="Create session" fields={[{ key: "userId", label: "User ID", default: "user-1" }]} onClose={(ok) => { setCreating(false); if (ok) s.reload(); }}
        onSubmit={async (v) => { await json("POST", `/v1beta1/${engine}/sessions`, { userId: v.userId }); notify.success("Created session"); }} />
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete session?" confirmText={del ? api.shortId(del.name) : ""} warning="This can't be undone."
        onConfirm={async () => { await api.del(del.name); notify.success("Deleted session"); s.reload(); }}><Typography variant="body2">The session and its events will be deleted.</Typography></DeleteDialog>
      <Dialog open={!!open} onClose={() => setOpen(null)} fullWidth maxWidth="md" aria-label="Session events">
        <DialogTitle>Session {open && api.shortId(open.name)}</DialogTitle>
        <DialogContent>
          <ErrorAlert error={ev.error} />
          {!ev.loading && !(ev.data || []).length && <Typography variant="body2" color="text.secondary">No events yet.</Typography>}
          <Stack spacing={1}>{(ev.data || []).map((e) => (
            <Box key={e.name} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
              <Typography variant="caption" color="text.secondary">{e.author} · {fmt(e.timestamp)}</Typography>
              <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>{(e.content?.parts || []).map((p) => p.text || JSON.stringify(p.functionCall || p.functionResponse || p)).join("\n")}</Typography>
            </Box>))}</Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setOpen(null)}>Close</Button></DialogActions>
      </Dialog>
    </Page>
  );
}

/* ── Memory Bank ── */
export function MemoryBank() {
  const notify = useNotify();
  const { engine, picker, none } = useEngines();
  const [creating, setCreating] = useState(false);
  const [gen, setGen] = useState(false);
  const [del, setDel] = useState(null);
  const [q, setQ] = useState(""); const [uid, setUid] = useState("user-1"); const [hits, setHits] = useState(null); const [err, setErr] = useState(null);
  const m = useAsync(() => (engine ? api.list("memories", { parent: engine }) : Promise.resolve([])), [engine]);
  const search = async () => {
    setErr(null);
    try { const r = await json("POST", `/v1beta1/${engine}/memories:retrieve`, { scope: { user_id: uid }, similaritySearchParams: { searchQuery: q, topK: 5 } }); setHits(r.retrievedMemories || []); } catch (e) { setErr(e); }
  };
  return (
    <Page title="Memory Bank">
      {bar(<>{picker}
        <Button variant="contained" startIcon={<AddIcon />} disabled={!engine} onClick={() => setCreating(true)}>Create memory</Button>
        <Button disabled={!engine} onClick={() => setGen(true)}>Generate from conversation</Button>
        <Button startIcon={<RefreshIcon />} onClick={m.reload}>Refresh</Button></>)}
      {none}
      {engine && (
        <Stack spacing={2}>
          <ResourceTable resourceName="memories" items={m.data || []} rowKey={(x) => x.name} loading={m.loading} error={m.error} onRetry={m.reload} filterPlaceholder="Filter"
            columns={[{ id: "fact", header: "Memory", sortValue: (x) => x.fact, cell: (x) => x.fact }, { id: "scope", header: "Scope", cell: (x) => Object.entries(x.scope || {}).map(([k, v]) => `${k}=${v}`).join(", ") },
              { id: "created", header: "Created", cell: (x) => fmt(x.createTime) },
              { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete memory ${api.shortId(x.name)}`} onClick={() => setDel(x)}><DeleteIcon fontSize="small" /></IconButton> }]}
            empty={<Typography variant="body2" color="text.secondary">No memories for this agent deployment.</Typography>} />
          <Section title="Retrieve memories" description="Similarity search over the stored facts for one scope (memories:retrieve).">
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
              <TextField size="small" label="user_id" value={uid} onChange={(e) => setUid(e.target.value)} />
              <TextField size="small" label="Search query" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 280 }} />
              <Button variant="outlined" onClick={search} disabled={!q.trim()}>Search</Button>
            </Stack>
            <ErrorAlert error={err} />
            {hits && (hits.length ? hits.map((h) => <Typography key={h.memory.name} variant="body2" sx={{ mt: 1 }}>{h.memory.fact} <Chip size="small" label={`distance ${h.distance}`} /></Typography>) : <Typography variant="body2" sx={{ mt: 1 }} color="text.secondary">No memories in that scope.</Typography>)}
          </Section>
        </Stack>)}
      <FormDialog open={creating} title="Create memory" fields={[{ key: "fact", label: "Fact", multiline: true }, { key: "userId", label: "Scope user_id", default: "user-1" }]}
        onClose={(ok) => { setCreating(false); if (ok) m.reload(); }} onSubmit={async (v) => { await json("POST", `/v1beta1/${engine}/memories`, { fact: v.fact, scope: { user_id: v.userId } }); notify.success("Created memory"); }} />
      <FormDialog open={gen} title="Generate memories from a conversation" submitLabel="Generate" fields={[{ key: "userId", label: "Scope user_id", default: "user-1" },
        { key: "text", label: "Conversation (one turn per line, “user: …” or “model: …”)", multiline: true, helper: "The local chat model extracts the durable facts; with no model running this returns 503." }]}
        onClose={(ok) => { setGen(false); if (ok) m.reload(); }}
        onSubmit={async (v) => {
          const events = v.text.split("\n").filter((l) => l.trim()).map((l) => { const mm = l.match(/^(user|model):\s*(.*)$/i); return { content: { role: mm ? mm[1].toLowerCase() : "user", parts: [{ text: mm ? mm[2] : l }] } }; });
          const r = await json("POST", `/v1beta1/${engine}/memories:generate`, { scope: { user_id: v.userId }, directContentsSource: { events } });
          notify.success(`Generated ${r.response?.generatedMemories?.length || 0} memories`);
        }} />
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete memory?" confirmText="" warning="This can't be undone."
        onConfirm={async () => { await api.del(del.name); notify.success("Deleted memory"); m.reload(); }}><Typography variant="body2">{del?.fact}</Typography></DeleteDialog>
    </Page>
  );
}

/* ── RAG Engine ── */
function CorpusDetail({ corpus, onClose, onChanged }) {
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [mode, setMode] = useState("dense");
  const [q, setQ] = useState(""); const [res, setRes] = useState(null); const [err, setErr] = useState(null);
  const f = useAsync(() => api.list("ragFiles", { parent: corpus.name }), [corpus.name]);
  const changed = () => { f.reload(); onChanged?.(); };   // the corpus list shows file and chunk counts, so it is refreshed too
  const run = async () => {
    setErr(null);
    const ragRetrievalConfig = { topK: 4, ...(mode === "hybrid" ? { hybridSearch: { alpha: 0.5 } } : {}) };
    try { const r = await json("POST", `/v1/${corpus.name.split("/ragCorpora/")[0]}:retrieveContexts`, { query: { text: q, ragRetrievalConfig }, vertexRagStore: { ragResources: [{ ragCorpus: corpus.name }] } }); setRes(r.contexts?.contexts || []); } catch (e) { setErr(e); }
  };
  const upload = async (v) => {
    await json("POST", `/upload/v1/${corpus.name}/ragFiles:upload`, { ragFile: { displayName: v.name }, text: v.text });
    notify.success(`Uploaded ${v.name}`);
  };
  const importGcs = async (v) => {
    const uris = v.uris.split(/[\s,]+/).filter(Boolean);
    const op = await json("POST", `/v1/${corpus.name}/ragFiles:import`, { importRagFilesConfig: { gcsSource: { uris } } });
    const r = op.response || {};
    notify.success(`Imported ${r.importedRagFilesCount || 0}, skipped ${r.skippedRagFilesCount || 0}, failed ${r.failedRagFilesCount || 0}`);
  };
  return (
    <Section title={`Corpus: ${corpus.displayName}`} actions={<Button onClick={onClose}>Close</Button>} description={corpus.name}>
      <Stack spacing={2}>
        {bar(<><Button variant="contained" startIcon={<AddIcon />} onClick={() => setAdding(true)}>Upload text file</Button><Button variant="outlined" onClick={() => setImporting(true)}>Import from Cloud Storage</Button><Button startIcon={<RefreshIcon />} onClick={changed}>Refresh</Button></>)}
        <ResourceTable resourceName="files" items={f.data || []} rowKey={(x) => x.name} loading={f.loading} error={f.error} onRetry={f.reload}
          columns={[{ id: "n", header: "File", cell: (x) => x.displayName }, { id: "c", header: "Chunks", cell: (x) => x.vyomiChunks }, { id: "s", header: "Size (bytes)", cell: (x) => x.sizeBytes },
            { id: "st", header: "Status", cell: (x) => <StateChip s={x.fileStatus?.state} /> },
            { id: "src", header: "Source", cell: (x) => x.gcsSource?.uris?.[0] || "Direct upload" },
            { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete file ${x.displayName}`} onClick={async () => { await api.del(x.name); changed(); }}><DeleteIcon fontSize="small" /></IconButton> }]}
          empty={<Typography variant="body2" color="text.secondary">No files. Upload text or import objects from Cloud Storage to index them.</Typography>} />
        <Stack direction="row" spacing={1}><TextField select size="small" label="Search mode" value={mode} onChange={(e) => setMode(e.target.value)} sx={{ minWidth: 190 }} inputProps={{ "aria-label": "Search mode" }}><MenuItem value="dense">Dense (vector)</MenuItem><MenuItem value="hybrid">Hybrid (vector + BM25)</MenuItem></TextField><TextField size="small" label="Test retrieval" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 340 }} /><Button variant="outlined" disabled={!q.trim()} onClick={run}>Retrieve</Button></Stack>
        <ErrorAlert error={err} />
        {res && (res.length ? res.map((c, i) => (
          <Box key={i} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}><Typography variant="caption" color="text.secondary">{c.sourceDisplayName} · distance {c.distance} · score {c.score}</Typography><Typography variant="body2">{c.text}</Typography></Box>))
          : <Typography variant="body2" color="text.secondary">No chunk matched the query.</Typography>)}
      </Stack>
      <FormDialog open={adding} title="Upload text file" submitLabel="Upload" fields={[{ key: "name", label: "File name", default: "notes.txt" }, { key: "text", label: "Content", multiline: true }]}
        onClose={(ok) => { setAdding(false); if (ok) changed(); }} onSubmit={upload} />
      <FormDialog open={importing} title="Import from Cloud Storage" submitLabel="Import" fields={[{ key: "uris", label: "Cloud Storage URIs", default: "gs://", multiline: true, helper: "One gs://bucket/object or gs://bucket/prefix per line" }]}
        onClose={(ok) => { setImporting(false); if (ok) changed(); }} onSubmit={importGcs} />
    </Section>
  );
}

export function RagEngine() {
  const [sel, setSel] = useState(null);
  const [rev, setRev] = useState(0);
  return (
    <Page title="RAG Engine">
      <Stack spacing={2}>
        <ResourceList key={rev} coll="ragCorpora" title="RAG corpora" singular="RAG corpus" regionScoped hideId
          fields={[{ key: "displayName", label: "Corpus name" }, { key: "description", label: "Description" }]}
          build={(v) => ({ body: { displayName: v.displayName, description: v.description } })}
          nameOf={(i) => i.displayName} href={null}
          columns={[{ id: "files", header: "Files", cell: (i) => i.vyomiStats?.files }, { id: "chunks", header: "Chunks", cell: (i) => i.vyomiStats?.chunks },
            { id: "open", header: "Detail", cell: (i) => <Link href="#" onClick={(e) => { e.preventDefault(); setSel(i); }}>Manage files</Link> }]} />
        {sel && <CorpusDetail corpus={sel} onClose={() => setSel(null)} onChanged={() => setRev((n) => n + 1)} />}
      </Stack>
    </Page>
  );
}

/* ── Vertex AI Search (data stores + apps) ── */
const DE = (loc = "global") => `/v1/projects/${encodeURIComponent(api_project())}/locations/${loc}/collections/default_collection`;

function SearchBox({ servingPath }) {
  const [q, setQ] = useState(""); const [res, setRes] = useState(null); const [err, setErr] = useState(null);
  const [sum, setSum] = useState(false);
  const go = async () => { setErr(null); try { setRes(await json("POST", `${servingPath}/servingConfigs/default_search:search`, { query: q, pageSize: 10, ...(sum ? { contentSearchSpec: { summarySpec: { summaryResultCount: 3, includeCitations: true } } } : {}) })); } catch (e) { setErr(e); } };
  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1}><TextField size="small" label="Search" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 340 }} onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) go(); }} /><Button variant="outlined" disabled={!q.trim()} onClick={go}>Search</Button><FormControlLabel control={<Checkbox checked={sum} onChange={(e) => setSum(e.target.checked)} inputProps={{ "aria-label": "Generate summary" }} />} label="Generate summary" /></Stack>
      <ErrorAlert error={err} />
      {res && <Typography variant="body2" color="text.secondary">{res.totalSize || 0} results (hybrid: BM25 + embeddings)</Typography>}
      {res?.summary?.summaryText && <Alert severity="info" data-testid="search-summary">{res.summary.summaryText}<Typography variant="caption" display="block">{res.summary.vyomiModel}</Typography></Alert>}
      {res?.summary?.summarySkippedReasons && <Alert severity="warning">No summary: {res.summary.summarySkippedReasons.join(", ")}{res.summary.vyomiNote ? ` (${res.summary.vyomiNote})` : ""}</Alert>}
      {(res?.results || []).map((r) => (
        <Box key={r.id} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
          <Typography variant="subtitle2">{r.document?.structData?.title || r.id}</Typography><Typography variant="body2" color="text.secondary">{r.vyomiSnippet}</Typography></Box>))}
    </Stack>
  );
}

function StoreDetail({ ds, onClose }) {
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const base = `/v1/${ds.name}`;
  const d = useAsync(() => api.list("documents", { parent: `${ds.name}/branches/default_branch` }), [ds.name]);
  const [importing, setImporting] = useState(false);
  return (
    <Section title={`Data store: ${ds.displayName}`} description={ds.name} actions={<Button onClick={onClose}>Close</Button>}>
      <Stack spacing={2}>
        {bar(<><Button variant="contained" startIcon={<AddIcon />} onClick={() => setAdding(true)}>Add document</Button><Button variant="outlined" onClick={() => setImporting(true)}>Import from Cloud Storage</Button><Button startIcon={<RefreshIcon />} onClick={d.reload}>Refresh</Button></>)}
        <ResourceTable resourceName="documents" items={d.data || []} rowKey={(x) => x.name} loading={d.loading} error={d.error} onRetry={d.reload}
          columns={[{ id: "id", header: "Document ID", cell: (x) => x.id }, { id: "t", header: "Title", cell: (x) => x.structData?.title || "—" },
            { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete document ${x.id}`} onClick={async () => { await api.del(x.name); d.reload(); }}><DeleteIcon fontSize="small" /></IconButton> }]}
          empty={<Typography variant="body2" color="text.secondary">No documents yet.</Typography>} />
        <SearchBox servingPath={base} />
      </Stack>
      <FormDialog open={adding} title="Add document" fields={[{ key: "id", label: "Document ID" }, { key: "title", label: "Title" }, { key: "body", label: "Content", multiline: true }]}
        onClose={(ok) => { setAdding(false); if (ok) d.reload(); }}
        onSubmit={async (v) => { await json("POST", `${base}/branches/default_branch/documents`, { structData: { title: v.title, body: v.body } }, { documentId: v.id }); notify.success("Added document"); }} />
      <FormDialog open={importing} title="Import from Cloud Storage" submitLabel="Import"
        fields={[{ key: "uris", label: "Cloud Storage URIs", default: "gs://", multiline: true, helper: "One gs:// object or prefix per line" }, { key: "schema", label: "Data schema", options: ["content", "custom", "document"], default: "content", helper: "content = one document per file; custom / document = JSON lines" }]}
        onClose={(ok) => { setImporting(false); if (ok) d.reload(); }}
        onSubmit={async (v) => { const op = await json("POST", `${base}/branches/default_branch/documents:import`, { gcsSource: { inputUris: v.uris.split(/[\s,]+/).filter(Boolean), dataSchema: v.schema } }); notify.success(`Imported ${op.metadata?.successCount || 0} documents (${op.metadata?.failureCount || 0} failed)`); }} />
    </Section>
  );
}

export function SearchApps({ initial = "stores" }) {
  const project = useP();
  const notify = useNotify();
  const [sel, setSel] = useState(null);
  const [creating, setCreating] = useState(null);
  const [del, setDel] = useState(null);
  const [app, setApp] = useState(null);
  const stores = useAsync(() => api.list("dataStores", { parent: DE().slice(4) }), [project]);
  const apps = useAsync(() => api.list("engines", { parent: DE().slice(4) }), [project]);
  const tabs = [
    { id: "stores", label: "Data stores", render: () => (
      <Stack spacing={2}>
        {bar(<><Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating("store")}>Create data store</Button><Button startIcon={<RefreshIcon />} onClick={stores.reload}>Refresh</Button></>)}
        <ResourceTable resourceName="data stores" items={stores.data || []} rowKey={(x) => x.name} loading={stores.loading} error={stores.error} onRetry={stores.reload}
          columns={[{ id: "n", header: "Name", sortValue: (x) => x.displayName, cell: (x) => <Link href="#" onClick={(e) => { e.preventDefault(); setSel(x); }}>{x.displayName}</Link> }, { id: "id", header: "ID", cell: (x) => api.shortId(x.name) },
            { id: "d", header: "Documents", cell: (x) => x.vyomiStats?.documents }, { id: "c", header: "Created", cell: (x) => fmt(x.createTime) },
            { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete data store ${x.displayName}`} onClick={() => setDel(x)}><DeleteIcon fontSize="small" /></IconButton> }]}
          empty={<Typography variant="body2" color="text.secondary">No data stores in this project.</Typography>} />
        {sel && <StoreDetail ds={sel} onClose={() => setSel(null)} />}
      </Stack>) },
    { id: "apps", label: "Apps", render: () => (
      <Stack spacing={2}>
        {bar(<><Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating("app")} disabled={!stores.data?.length}>Create app</Button><Button startIcon={<RefreshIcon />} onClick={apps.reload}>Refresh</Button></>)}
        {!stores.loading && !stores.data?.length && <Alert severity="info">Create a data store first; an app searches the data stores linked to it.</Alert>}
        <ResourceTable resourceName="apps" items={apps.data || []} rowKey={(x) => x.name} loading={apps.loading} error={apps.error} onRetry={apps.reload}
          columns={[{ id: "n", header: "Name", sortValue: (x) => x.displayName, cell: (x) => <Link href="#" onClick={(e) => { e.preventDefault(); setApp(x); }}>{x.displayName}</Link> }, { id: "t", header: "Type", cell: (x) => String(x.solutionType || "").replace("SOLUTION_TYPE_", "") },
            { id: "s", header: "Data stores", cell: (x) => (x.dataStoreIds || []).join(", ") },
            { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete app ${x.displayName}`} onClick={() => setDel(x)}><DeleteIcon fontSize="small" /></IconButton> }]}
          empty={<Typography variant="body2" color="text.secondary">No apps in this project.</Typography>} />
        {app && <Section title={`Preview: ${app.displayName}`} actions={<Button onClick={() => setApp(null)}>Close</Button>}><SearchBox servingPath={`/v1/${app.name}`} /></Section>}
      </Stack>) },
  ];
  return (
    <Page title={initial === "apps" ? "App Builder" : "Search"}>
      <Tabbed key={initial} tabs={initial === "apps" ? [tabs[1], tabs[0]] : tabs} />
      <FormDialog open={creating === "store"} title="Create data store" fields={[{ key: "id", label: "Data store ID", helper: "Lowercase letters, digits, - and _" }, { key: "displayName", label: "Display name" }]}
        onClose={(ok) => { setCreating(null); if (ok) stores.reload(); }}
        onSubmit={async (v) => { await json("POST", `${DE()}/dataStores`, { displayName: v.displayName || v.id, industryVertical: "GENERIC", solutionTypes: ["SOLUTION_TYPE_SEARCH"], contentConfig: "CONTENT_REQUIRED" }, { dataStoreId: v.id }); notify.success("Created data store"); }} />
      {creating === "app" && <FormDialog open title="Create app" fields={[{ key: "id", label: "App ID" }, { key: "displayName", label: "Display name" },
        { key: "store", label: "Data store", options: (stores.data || []).map((s) => ({ value: api.shortId(s.name), label: s.displayName })), default: stores.data?.[0] ? api.shortId(stores.data[0].name) : "" }]}
        onClose={(ok) => { setCreating(null); if (ok) apps.reload(); }}
        onSubmit={async (v) => { await json("POST", `${DE()}/engines`, { displayName: v.displayName || v.id, solutionType: "SOLUTION_TYPE_SEARCH", dataStoreIds: [v.store], searchEngineConfig: { searchTier: "STANDARD_TIER" } }, { engineId: v.id }); notify.success("Created app"); }} />}
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete?" confirmText={del ? api.shortId(del.name) : ""} warning="This can't be undone."
        onConfirm={async () => { await api.del(del.name); notify.success("Deleted"); stores.reload(); apps.reload(); }}><Typography variant="body2">{del?.displayName}</Typography></DeleteDialog>
    </Page>
  );
}

/* ── Agent Retrieval: one query across RAG corpora and Search data stores ── */
export function AgentRetrieval() {
  const project = useP();
  const [region] = useState("us-central1");
  const corp = useAsync(() => api.list("ragCorpora", { loc: region }), [project]);
  const stores = useAsync(() => api.list("dataStores", { parent: DE().slice(4) }), [project]);
  const [q, setQ] = useState(""); const [out, setOut] = useState(null); const [err, setErr] = useState(null); const [busy, setBusy] = useState(false);
  const run = async () => {
    setErr(null); setBusy(true);
    try {
      const rows = [];
      if (corp.data?.length) {
        const r = await json("POST", `${P(region)}:retrieveContexts`, { query: { text: q, ragRetrievalConfig: { topK: 4 } }, vertexRagStore: { ragResources: corp.data.map((c) => ({ ragCorpus: c.name })) } });
        (r.contexts?.contexts || []).forEach((c) => rows.push({ src: `RAG corpus · ${c.sourceDisplayName}`, text: c.text, score: c.score }));
      }
      for (const s of stores.data || []) {
        const r = await json("POST", `/v1/${s.name}/servingConfigs/default_search:search`, { query: q, pageSize: 4 });
        (r.results || []).forEach((x) => rows.push({ src: `Search · ${s.displayName} · ${x.document?.structData?.title || x.id}`, text: x.vyomiSnippet, score: null }));
      }
      setOut(rows);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const n = (corp.data?.length || 0) + (stores.data?.length || 0);
  return (
    <Page title="Agent Retrieval">
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>One query over every knowledge source an agent can retrieve from: RAG Engine corpora and Search data stores in this project.</Typography>
      {!corp.loading && !stores.loading && !n && <Alert severity="info" sx={{ mb: 1.5 }}>No sources yet. Create a <Link href="#/vertex-ai/rag-engine">RAG corpus</Link> or a <Link href="#/vertex-ai/search">Search data store</Link>.</Alert>}
      <Stack direction="row" spacing={1} sx={{ mb: 1.5 }}><TextField size="small" label="Query" value={q} onChange={(e) => setQ(e.target.value)} sx={{ minWidth: 380 }} onKeyDown={(e) => { if (e.key === "Enter" && q.trim() && n) run(); }} />
        <Button variant="contained" disabled={!q.trim() || !n || busy} onClick={run}>Retrieve</Button>
        <Chip size="small" label={`${corp.data?.length || 0} corpora · ${stores.data?.length || 0} data stores`} sx={{ alignSelf: "center" }} /></Stack>
      <ErrorAlert error={err} />
      {out && (out.length ? <Stack spacing={1}>{out.map((r, i) => <Box key={i} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}><Typography variant="caption" color="text.secondary">{r.src}</Typography><Typography variant="body2">{r.text}</Typography></Box>)}</Stack>
        : <Typography variant="body2" color="text.secondary">Nothing matched the query.</Typography>)}
    </Page>
  );
}

/* ── Evaluation ── */
export function Evaluation() {
  const notify = useNotify();
  const project = useP();
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState(null);
  const [del, setDel] = useState(null);
  const r = useAsync(() => api.list("evaluationRuns", { loc: "us-central1" }), [project]);
  return (
    <Page title="Evaluation" group="Models" groupHref="#/vertex-ai/model-garden">
      <Alert severity="info" sx={{ mb: 1.5 }}>Runs generate with the local model (or use responses you supply) and score with exact match, BLEU and ROUGE. There is no Gemini autorater.</Alert>
      {bar(<><Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)}>Create evaluation</Button><Button startIcon={<RefreshIcon />} onClick={r.reload}>Refresh</Button></>)}
      <ResourceTable resourceName="evaluation runs" items={r.data || []} rowKey={(x) => x.name} loading={r.loading} error={r.error} onRetry={r.reload} filterPlaceholder="Filter"
        columns={[{ id: "n", header: "Name", sortValue: (x) => x.displayName, cell: (x) => <Link href="#" onClick={(e) => { e.preventDefault(); setOpen(x); }}>{x.displayName}</Link> },
          { id: "s", header: "State", cell: (x) => <StateChip s={x.state} /> }, { id: "m", header: "Model", cell: (x) => x.model },
          { id: "sc", header: "Scores", cell: (x) => Object.entries(x.summary || {}).map(([k, v]) => `${k} ${Number(v).toFixed(3)}`).join(" · ") },
          { id: "c", header: "Created", cell: (x) => fmt(x.createTime) },
          { id: "a", header: "Actions", cell: (x) => <IconButton size="small" aria-label={`Delete ${x.displayName}`} onClick={() => setDel(x)}><DeleteIcon fontSize="small" /></IconButton> }]}
        empty={<Typography variant="body2" color="text.secondary">No evaluation runs.</Typography>} />
      <FormDialog open={creating} title="Create evaluation" fields={[{ key: "displayName", label: "Name" },
        { key: "metric", label: "Metrics", options: [{ value: "rouge", label: "ROUGE-L" }, { value: "bleu", label: "BLEU" }, { value: "exact_match", label: "Exact match" }, { value: "all", label: "All three" }], default: "rouge" },
        { key: "rows", label: "Dataset (one row per line: prompt | reference | optional response)", multiline: true, helper: "Without a response the local model generates it; with no model running that fails with 503." }]}
        onClose={(ok) => { setCreating(false); if (ok) r.reload(); }}
        onSubmit={async (v) => {
          const rows = v.rows.split("\n").filter((l) => l.trim()).map((l) => { const [prompt, reference, response] = l.split("|").map((s) => s.trim()); return { prompt, reference, ...(response ? { response } : {}) }; });
          await json("POST", `${P()}/evaluationRuns`, { displayName: v.displayName, metrics: v.metric === "all" ? ["rouge", "bleu", "exact_match"] : [v.metric], dataset: { rows } });
          notify.success("Evaluation finished");
        }} />
      <Dialog open={!!open} onClose={() => setOpen(null)} fullWidth maxWidth="md" aria-label="Evaluation results">
        <DialogTitle>{open?.displayName}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{open?.vyomiNote}</Typography>
          <ResourceTable resourceName="rows" items={open?.rows || []} rowKey={(x) => x.prompt + x.reference} columns={[{ id: "p", header: "Prompt", cell: (x) => x.prompt }, { id: "r", header: "Reference", cell: (x) => x.reference },
            { id: "o", header: "Response", cell: (x) => x.response }, { id: "s", header: "Scores", cell: (x) => Object.entries(x.scores).map(([k, v]) => `${k} ${Number(v).toFixed(3)}`).join(" · ") }]} />
        </DialogContent>
        <DialogActions><Button onClick={() => setOpen(null)}>Close</Button></DialogActions>
      </Dialog>
      <DeleteDialog open={!!del} onClose={() => setDel(null)} title="Delete evaluation run?" confirmText="" warning="This can't be undone."
        onConfirm={async () => { await api.del(del.name); notify.success("Deleted"); r.reload(); }}><Typography variant="body2">{del?.displayName}</Typography></DeleteDialog>
    </Page>
  );
}

/* ── Metadata (ML Metadata store) ── */
export function Metadata({ query }) {
  const fp = (region, project) => `projects/${project}/locations/${region}/metadataStores/default`;
  const mk = (coll, singular, idKey, schema) => () => (
    <ResourceList coll={coll} title={singular + "s"} singular={singular} fixedParent={fp} noRegion={false} hideId
      fields={[{ key: "id", label: `${singular[0].toUpperCase()}${singular.slice(1)} ID` }, { key: "displayName", label: "Display name" }, { key: "schemaTitle", label: "Schema title", default: schema }]}
      build={(v) => ({ body: { displayName: v.displayName || v.id, schemaTitle: v.schemaTitle }, idKey, id: v.id })}
      columns={[{ id: "schema", header: "Schema", cell: (i) => i.schemaTitle }, { id: "state", header: "State", cell: (i) => i.state || "—" }]} />);
  return (
    <Page title="Metadata" group="Models" groupHref="#/vertex-ai/model-garden">
      <Tabbed query={query} tabs={[
        { id: "artifacts", label: "Artifacts", render: mk("artifacts", "artifact", "artifactId", "system.Artifact") },
        { id: "executions", label: "Executions", render: mk("executions", "execution", "executionId", "system.ContainerExecution") },
        { id: "contexts", label: "Contexts", render: mk("contexts", "context", "contextId", "system.Experiment") }]} />
    </Page>
  );
}

/* ── Monitoring (model deployment monitoring jobs) ── */
export function Monitoring() {
  const project = useP();
  const eps = useAsync(() => api.list("endpoints", { loc: "-" }), [project]);
  const opts = (eps.data || []).map((e) => ({ value: e.name, label: `${e.displayName || api.shortId(e.name)} (${api.pname(e.name).location})` }));
  return (
    <Page title="Monitoring" group="Models" groupHref="#/vertex-ai/model-garden">
      {!eps.loading && !eps.data?.length && <Alert severity="info" sx={{ mb: 1.5 }}>A monitoring job watches an endpoint. Create an <Link href="#/vertex-ai/endpoints">endpoint</Link> first.</Alert>}
      <ResourceList key={opts.length} coll="modelDeploymentMonitoringJobs" title="Monitoring jobs" singular="monitoring job" regionScoped hideId
        fields={eps.data?.length ? [{ key: "displayName", label: "Name" }, { key: "endpoint", label: "Endpoint", options: opts, default: opts[0]?.value }, { key: "interval", label: "Monitor interval (hours)", default: "1" }] : null}
        build={(v) => ({ body: { displayName: v.displayName, endpoint: v.endpoint, loggingSamplingStrategy: { randomSampleConfig: { sampleRate: 0.8 } },
          modelDeploymentMonitoringScheduleConfig: { monitorInterval: `${Number(v.interval || 1) * 3600}s` }, modelDeploymentMonitoringObjectiveConfigs: [] }, loc: api.pname(v.endpoint).location })}
        poll columns={[{ id: "ep", header: "Endpoint", cell: (i) => api.shortId(i.endpoint) }, { id: "st", header: "Status", cell: (i) => <StateChip s={i.state} /> }]}
        actions={[{ label: "Pause", when: (i) => i.state === "JOB_STATE_RUNNING", run: (i) => api.verb(i.name, "pause") }, { label: "Resume", when: (i) => i.state === "JOB_STATE_PAUSED", run: (i) => api.verb(i.name, "resume") }]} />
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>The job record, lifecycle and pause/resume are real; no drift or skew statistics are computed, so no anomaly results appear.</Typography>
    </Page>
  );
}

/* ── Agent Registry, ADK, Topology (over the Agent Engine deployments) ── */
const specOf = (e) => { const s = e.spec?.vyomiAgentSpec ?? (e.spec?.deploymentSpec?.env || []).find((x) => x.name === "VYOMI_AGENT_SPEC")?.value; try { return typeof s === "string" ? JSON.parse(s) : s || null; } catch { return null; } };

export function AgentRegistry() {
  const project = useP();
  const r = useAsync(async () => (await Promise.all(api.REGIONS.map((l) => api.list("reasoningEngines", { loc: l }).catch(() => [])))).flat(), [project]);
  return (
    <Page title="Agent Registry" group="Govern" groupHref="#/vertex-ai/agent-registry">
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Every agent deployed in this project, across regions, with the model and tools its spec declares. Manage them under <Link href="#/vertex-ai/deployments">Deployments</Link>.</Typography>
      <ResourceTable resourceName="agents" items={r.data || []} rowKey={(x) => x.name} loading={r.loading} error={r.error} onRetry={r.reload} filterPlaceholder="Filter"
        columns={[{ id: "n", header: "Agent", sortValue: (x) => x.displayName, cell: (x) => x.displayName }, { id: "id", header: "ID", cell: (x) => api.shortId(x.name) },
          { id: "l", header: "Region", cell: (x) => api.pname(x.name).location }, { id: "m", header: "Model", cell: (x) => specOf(x)?.model || "default local model" },
          { id: "t", header: "Tools", cell: (x) => (specOf(x)?.tools || []).map((t) => t.name).join(", ") || "—" }, { id: "c", header: "Created", cell: (x) => fmt(x.createTime) }]}
        empty={<Typography variant="body2" color="text.secondary">No agents registered. Deploy one from <Link href="#/vertex-ai/adk">ADK</Link>.</Typography>} />
    </Page>
  );
}

const ADK_SPEC = { instructions: "You answer facilities questions briefly.", max_steps: 4, tools: [{ name: "current_time", type: "builtin", builtin: "current_time" }] };
const ADK_SNIPPET = `import json, requests
# Deploy an agent: Agent Engine reasoningEngines (the Vyomi agent spec carries instructions + tools)
spec = ${JSON.stringify(ADK_SPEC)}
requests.post(f"{BASE}/v1/projects/{PROJECT}/locations/us-central1/reasoningEngines",
              json={"displayName": "facilities-agent", "spec": {"vyomiAgentSpec": spec}})`;

export function Adk() {
  const notify = useNotify();
  const [creating, setCreating] = useState(false);
  return (
    <Page title="Agent Development Kit">
      <Stack spacing={2}>
        <Section title="Build and deploy an agent" description="Agents here are declarative Vyomi agent specs (instructions, model, tools) run by the local model; the Google ADK Python framework and pickled classes are not executed.">
          <Stack spacing={1.5}>
            <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: "action.hover", borderRadius: 1, overflow: "auto", fontSize: 12 }}>{ADK_SNIPPET}</Box>
            <Stack direction="row" spacing={1}><Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreating(true)}>Deploy an agent</Button><Button href="#/vertex-ai/deployments">View deployments</Button></Stack>
          </Stack>
        </Section>
        <Section title="Your agents"><Deployments_ /></Section>
      </Stack>
      <FormDialog open={creating} title="Deploy an agent" submitLabel="Deploy" fields={[{ key: "displayName", label: "Agent name", default: "facilities-agent" },
        { key: "spec", label: "Agent spec (JSON)", multiline: true, default: JSON.stringify(ADK_SPEC, null, 2) }]}
        onClose={() => setCreating(false)}
        onSubmit={async (v) => { let spec; try { spec = JSON.parse(v.spec); } catch { throw new Error("The agent spec is not valid JSON."); }
          await json("POST", `${P()}/reasoningEngines`, { displayName: v.displayName, spec: { vyomiAgentSpec: spec } }); notify.success("Agent deployed"); }} />
    </Page>
  );
}
function Deployments_() {
  const project = useP();
  const r = useAsync(() => api.list("reasoningEngines", { loc: "us-central1" }), [project]);
  return <ResourceTable resourceName="agents" items={r.data || []} rowKey={(x) => x.name} loading={r.loading} error={r.error} onRetry={r.reload}
    columns={[{ id: "n", header: "Agent", cell: (x) => x.displayName }, { id: "id", header: "ID", cell: (x) => api.shortId(x.name) }, { id: "t", header: "Tools", cell: (x) => (specOf(x)?.tools || []).map((t) => t.name).join(", ") || "—" }]}
    empty={<Typography variant="body2" color="text.secondary">No agents deployed.</Typography>} />;
}

export function Topology() {
  const project = useP();
  const r = useAsync(async () => (await Promise.all(api.REGIONS.map((l) => api.list("reasoningEngines", { loc: l }).catch(() => [])))).flat(), [project]);
  const engines = r.data || [];
  const rowH = 70;
  const nodes = [];
  const edges = [];
  let y = 40;
  engines.forEach((e) => {
    const sp = specOf(e) || {}; const tools = sp.tools || [];
    const ay = y + (Math.max(tools.length, 1) - 1) * rowH / 2;
    nodes.push({ id: e.name, x: 320, y: ay, label: e.displayName, kind: "agent" });
    nodes.push({ id: e.name + "#m", x: 80, y: ay, label: sp.model || "local model", kind: "model" });
    edges.push([80 + 70, ay, 320 - 70, ay]);
    (tools.length ? tools : []).forEach((t, i) => { const ty = y + i * rowH; nodes.push({ id: e.name + t.name, x: 580, y: ty, label: t.name, kind: "tool" }); edges.push([320 + 70, ay, 580 - 70, ty]); });
    y += Math.max(tools.length, 1) * rowH + 20;
  });
  const color = { agent: "#1a73e8", model: "#188038", tool: "#b06000" };
  return (
    <Page title="Topology" group="Govern" groupHref="#/vertex-ai/agent-registry">
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>The agents deployed in this project, the model each runs on, and the tools its spec lets it call. Drawn from the live reasoning engines.</Typography>
      <ErrorAlert error={r.error} />
      {!r.loading && !engines.length && <Alert severity="info">No agents deployed yet. Deploy one from <Link href="#/vertex-ai/adk">ADK</Link>.</Alert>}
      {engines.length > 0 && (
        <svg role="img" aria-label="Agent topology" width="100%" viewBox={`0 0 700 ${Math.max(y, 120)}`} style={{ maxWidth: 760 }}>
          {edges.map((e, i) => <line key={i} x1={e[0]} y1={e[1]} x2={e[2]} y2={e[3]} stroke="#9aa0a6" strokeWidth="1.5" />)}
          {nodes.map((n) => (<g key={n.id}><rect x={n.x - 70} y={n.y - 20} width="140" height="40" rx="8" fill="none" stroke={color[n.kind]} strokeWidth="1.5" />
            <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize="12" fill="currentColor">{String(n.label).slice(0, 20)}</text></g>))}
        </svg>)}
    </Page>
  );
}

/* ── declared "Not in scope" pages: a reason and what to use instead, never a bare "Coming soon" ── */
const OOS = {
  "training-clusters": ["Training clusters", "Models", "#/vertex-ai/model-garden", "Training clusters are managed multi-node GPU/TPU Slurm or GKE capacity for large pretraining. A single-machine simulator has no accelerator fleet to schedule onto.", "Use Tuning (heads and chat LoRA run for real) or Training > custom jobs for the job lifecycle."],
  "provisioned-throughput": ["Provisioned Throughput", "Models", "#/vertex-ai/model-garden", "Provisioned Throughput is a billing commitment that reserves model serving capacity. A local model has no shared capacity, quota or commitment to reserve.", "Use Endpoints for deployment and Model Garden for the served models."],
  "ray": ["Ray on Agent Platform", "Models", "#/vertex-ai/model-garden", "Ray clusters (persistentResources) need multi-node compute and the Ray runtime, which the simulator does not host.", "Run Ray locally and submit work through Training custom jobs for the job lifecycle."],
  "mcp-servers": ["MCP Servers", "Agents", "#/vertex-ai/agent-garden", "The catalogue of managed Google MCP servers is a vendor-hosted service; the simulator does not run or proxy them.", "Declare your own tools in the agent spec under ADK (static, template, builtin, webhook), or register an MCP server on the AWS AgentCore Gateway."],
  "policies": ["Policies", "Govern", "#/vertex-ai/agent-registry", "Agent Platform policies enforce org-level agent guardrails in a vendor control plane with no public API to model.", "Use IAM for access control and the Bedrock/AgentCore Cedar policy engine for tool-call policy."],
  "gateways": ["Gateways", "Govern", "#/vertex-ai/agent-registry", "The Agent Gateway is a vendor-hosted traffic proxy for agent and MCP calls with no public API to model.", "Use API Gateway (Cloud API Gateway) in this console for fronting an agent's HTTP endpoint."],
  "security": ["Security", "Govern", "#/vertex-ai/agent-registry", "Agent Platform security posture (Model Armor, threat detection) is a vendor analysis service.", "Use Security Command Center in this console, and IAM for identity."],
};
export function NotInScope({ id }) {
  const [title, group, groupHref, why, instead] = OOS[id];
  return (
    <Page title={title} group={group} groupHref={groupHref}>
      <NotSimulatedContainer outOfScope feature={title} title={`${title}: not in scope for Vyomi`} description={why} note={instead} />
    </Page>
  );
}
export const OOS_IDS = Object.keys(OOS);
