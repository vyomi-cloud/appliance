/* Foundry Agents: the built-in tools. Code interpreter (REAL sandboxed Python, core/code_sandbox_core.py) and File search (REAL retrieval over vector stores:
 * chunk + embed + cosine, cited as file_citation annotations) of core/azure_openai_agents_core.py, through the Assistants wire (/openai/assistants,
 * /openai/vector_stores, /openai/files). Pieces used by AgentsPage: tool toggles for the New agent dialog, the Vector stores tab, and the message
 * renderer that shows citations, code and output files. */
import { useEffect, useState } from "react";
import { Badge, Button, Checkbox, Field, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { restJson, WIRE_BASE } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, InfoBar } from "../../kit/common.jsx";

const AV = "2024-05-01-preview", H = { "api-key": "console" }, e = encodeURIComponent;
const q = (extra = {}) => ({ "api-version": AV, ...extra });
export const toolsApi = {
  stores: () => restJson("GET", "/openai/vector_stores", { query: q({ limit: 100 }), headers: H }).then((r) => r.data || []),
  createStore: (name, file_ids) => restJson("POST", "/openai/vector_stores", { query: q(), headers: H, body: { name, ...(file_ids?.length ? { file_ids } : {}) } }),
  deleteStore: (id) => restJson("DELETE", `/openai/vector_stores/${e(id)}`, { query: q(), headers: H }),
  storeFiles: (id) => restJson("GET", `/openai/vector_stores/${e(id)}/files`, { query: q({ limit: 100 }), headers: H }).then((r) => r.data || []),
  addFile: (id, file_id) => restJson("POST", `/openai/vector_stores/${e(id)}/files`, { query: q(), headers: H, body: { file_id } }),
  removeFile: (id, fid) => restJson("DELETE", `/openai/vector_stores/${e(id)}/files/${e(fid)}`, { query: q(), headers: H }),
  file: (id) => restJson("GET", `/openai/files/${e(id)}`, { query: q(), headers: H }),
  steps: (t, r) => restJson("GET", `/openai/threads/${e(t)}/runs/${e(r)}/steps`, { query: q({ order: "asc" }), headers: H }).then((x) => x.data || []),
  /** Multipart upload exactly like the SDK: file + purpose=assistants. */
  async upload(file) {
    const fd = new FormData(); fd.append("purpose", "assistants"); fd.append("file", file, file.name);
    const res = await fetch(`${WIRE_BASE}/openai/files?api-version=${AV}`, { method: "POST", headers: H, body: fd });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(j.error?.message || `HTTP ${res.status}`), { code: j.error?.code });
    return j;
  },
  content: async (id) => (await fetch(`${WIRE_BASE}/openai/files/${e(id)}/content?api-version=${AV}`, { headers: H })).text(),
};

const toolsOf = (a) => (a.tools || []).map((t) => t.type);
export const ToolBadges = ({ agent }) => <span data-testid="agent-tools">{toolsOf(agent).filter((t) => t !== "function").map((t) => <Badge key={t} appearance="tint" color="brand" style={{ marginRight: 4 }}>{t === "code_interpreter" ? "Code interpreter" : t === "file_search" ? "File search" : t}</Badge>)}{!toolsOf(agent).filter((t) => t !== "function").length && "-"}</span>;

/** Tool toggles inside the New agent dialog. value = {ci, fs, ciFiles:[File], vs:"", newVs:"", fsFiles:[File]}; onChange(next). */
export function ToolToggles({ value, onChange, stores }) {
  const set = (p) => onChange({ ...value, ...p });
  return (
    <div style={{ display: "grid", gap: 8, border: "1px solid var(--colorNeutralStroke2, #ddd)", padding: 10 }} data-testid="tool-toggles">
      <b>Tools</b>
      <Checkbox checked={!!value.ci} onChange={(_, d) => set({ ci: !!d.checked })} label="Code interpreter" />
      {value.ci && <Field hint="Optional input files the agent's Python can read (the sandbox is real Python; output files are returned as downloads)."><input type="file" multiple aria-label="Code interpreter files" onChange={(ev) => set({ ciFiles: [...ev.target.files] })} /></Field>}
      <Checkbox checked={!!value.fs} onChange={(_, d) => set({ fs: !!d.checked })} label="File search" />
      {value.fs && (
        <div style={{ display: "grid", gap: 8 }}>
          <Field label="Vector store"><Select value={value.vs} onChange={(_, d) => set({ vs: d.value })} aria-label="Vector store">
            <option value="">Create a new vector store from files</option>{stores.map((s) => <option key={s.id} value={s.id}>{s.name || s.id} ({s.file_counts?.completed ?? 0} files)</option>)}</Select></Field>
          {!value.vs && <>
            <Field label="New vector store name"><Input value={value.newVs} onChange={(_, d) => set({ newVs: d.value })} aria-label="New vector store name" /></Field>
            <Field label="Files" hint="Text, Markdown, JSON, CSV, PDF and Office documents are parsed, chunked and embedded."><input type="file" multiple aria-label="File search files" onChange={(ev) => set({ fsFiles: [...ev.target.files] })} /></Field></>}
        </div>)}
    </div>
  );
}

/** Create the vector store / upload files the toggles ask for, then return the {tools, tool_resources} for the assistant. */
export async function buildToolsPayload(v) {
  const tools = [], tool_resources = {};
  if (v.ci) {
    tools.push({ type: "code_interpreter" });
    if (v.ciFiles?.length) tool_resources.code_interpreter = { file_ids: await Promise.all(v.ciFiles.map(async (f) => (await toolsApi.upload(f)).id)) };
  }
  if (v.fs) {
    tools.push({ type: "file_search" });
    let id = v.vs;
    if (!id) {
      const ids = await Promise.all((v.fsFiles || []).map(async (f) => (await toolsApi.upload(f)).id));
      id = (await toolsApi.createStore(v.newVs || "agent-store", ids)).id;
    }
    tool_resources.file_search = { vector_store_ids: [id] };
  }
  return { tools, ...(Object.keys(tool_resources).length ? { tool_resources } : {}) };
}

const stat = (s) => <Badge appearance="tint" color={s === "completed" ? "success" : s === "failed" ? "danger" : "informative"}>{s}</Badge>;

/** The "Vector stores" tab: create, add files (upload + attach), per-file status (chunking/embedding failures are modeled), delete. */
export function VectorStoresPanel() {
  const notify = useNotify();
  const list = useAsync(() => toolsApi.stores(), []);
  const [open, setOpen] = useState(null), [name, setName] = useState(""), [files, setFiles] = useState([]), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const sf = useAsync(() => (open ? toolsApi.storeFiles(open) : Promise.resolve([])), [open]);
  const names = useAsync(async () => Object.fromEntries(await Promise.all((sf.data || []).map(async (f) => [f.id, (await toolsApi.file(f.id).catch(() => ({}))).filename || f.id]))), [sf.data]);
  const wrap = async (fn, ok) => { setBusy(true); setErr(null); try { await fn(); if (ok) notify.success(ok); } catch (x) { setErr(x); } finally { setBusy(false); } };
  const create = () => wrap(async () => { const ids = await Promise.all(files.map(async (f) => (await toolsApi.upload(f)).id)); const v = await toolsApi.createStore(name, ids); setName(""); setFiles([]); setOpen(v.id); list.reload(); }, "Vector store created.");
  const add = (fl) => wrap(async () => { for (const f of fl) await toolsApi.addFile(open, (await toolsApi.upload(f)).id); sf.reload(); list.reload(); }, "Files added.");
  return (
    <div className="vy-page" data-testid="foundry-vector-stores" style={{ display: "grid", gap: 12 }}>
      <InfoBar>Vector stores hold the files File search retrieves from. Each file is parsed, split into chunks and embedded with the local embedding model; answers cite the file they used. Retrieval is exact cosine search, not Azure AI Search.</InfoBar>
      <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <Field label="New vector store name"><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Vector store name" /></Field>
        <input type="file" multiple aria-label="Vector store files" onChange={(ev) => setFiles([...ev.target.files])} />
        <Button appearance="primary" icon={<Add20Regular />} disabled={!name || busy} onClick={create}>Create vector store</Button>
        <Button appearance="subtle" icon={<ArrowClockwise20Regular />} onClick={list.reload}>Refresh</Button>
      </div>
      <ErrorBar error={err || list.error} title="Vector store request failed" />
      <Table size="small" aria-label="Vector stores"><TableHeader><TableRow>{["Name", "ID", "Files", "Usage", "Status", ""].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
        <TableBody>{(list.data || []).map((s) => (
          <TableRow key={s.id}><TableCell><a href="#/foundry/agents" onClick={(ev) => { ev.preventDefault(); setOpen(open === s.id ? null : s.id); }}>{s.name || "(unnamed)"}</a></TableCell><TableCell>{s.id}</TableCell>
            <TableCell>{s.file_counts?.completed ?? 0} done{s.file_counts?.failed ? `, ${s.file_counts.failed} failed` : ""}</TableCell><TableCell>{((s.usage_bytes || 0) / 1024).toFixed(1)} KB</TableCell><TableCell>{stat(s.status)}</TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${s.name}`} onClick={() => wrap(async () => { await toolsApi.deleteStore(s.id); if (open === s.id) setOpen(null); list.reload(); }, "Vector store deleted.")} /></TableCell></TableRow>))}
          {!list.loading && !(list.data || []).length && <TableRow><TableCell colSpan={6}>No vector stores yet. Create one with a few files, then turn on File search for an agent.</TableCell></TableRow>}</TableBody></Table>
      {open && (
        <section style={{ border: "1px solid var(--colorNeutralStroke2, #ddd)", padding: 12, display: "grid", gap: 8 }} data-testid="vector-store-files">
          <b>Files in {open}</b>
          <Table size="small" aria-label="Vector store files"><TableHeader><TableRow>{["File", "ID", "Status", "Size", ""].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
            <TableBody>{(sf.data || []).map((f) => (
              <TableRow key={f.id}><TableCell>{names.data?.[f.id] || f.id}</TableCell><TableCell>{f.id}</TableCell><TableCell>{stat(f.status)}{f.last_error ? ` ${f.last_error.message}` : ""}</TableCell><TableCell>{((f.usage_bytes || 0) / 1024).toFixed(1)} KB</TableCell>
                <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Remove ${f.id}`} onClick={() => wrap(async () => { await toolsApi.removeFile(open, f.id); sf.reload(); list.reload(); }, "File removed.")} /></TableCell></TableRow>))}
              {!(sf.data || []).length && <TableRow><TableCell colSpan={5}>No files in this store.</TableCell></TableRow>}</TableBody></Table>
          <div><input type="file" multiple aria-label="Add files to the store" onChange={(ev) => ev.target.files.length && add([...ev.target.files])} /></div>
        </section>)}
    </div>
  );
}

/** One assistant message with its annotations: [n] markers for file_citation, a Sources list, and download links for file_path outputs. */
export function RichMessage({ m }) {
  const parts = (m.content || []).map((c) => c.text || { value: "", annotations: [] });
  const value = parts.map((p) => p.value || "").join(""), ann = parts.flatMap((p) => p.annotations || []);
  const cites = ann.filter((a) => a.type === "file_citation"), outs = ann.filter((a) => a.type === "file_path");
  const [names, setNames] = useState({}), [shown, setShown] = useState(null);
  useEffect(() => { [...cites, ...outs].forEach((a) => { const id = (a.file_citation || a.file_path).file_id; toolsApi.file(id).then((f) => setNames((n) => ({ ...n, [id]: f.filename || id }))).catch(() => {}); }); }, [m.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  let text = value; cites.forEach((a, i) => { text = text.split(a.text).join(`[${i + 1}]`); });
  return (
    <div data-testid="rich-message">
      <div style={{ whiteSpace: "pre-wrap" }} data-testid="rich-text">{text}</div>
      {!!cites.length && <div data-testid="citations" style={{ marginTop: 6, fontSize: 12 }}><b>Sources</b>{cites.map((a, i) => <div key={i}>[{i + 1}] {names[a.file_citation.file_id] || a.file_citation.file_id} <span style={{ opacity: 0.6 }}>({a.file_citation.file_id})</span></div>)}</div>}
      {!!outs.length && <div data-testid="output-files" style={{ marginTop: 6, fontSize: 12 }}><b>Files</b>{outs.map((a, i) => { const id = a.file_path.file_id; return (
        <div key={i}>{names[id] || a.text} <Button size="small" appearance="subtle" onClick={async () => setShown({ id, text: await toolsApi.content(id) })}>View</Button></div>); })}
        {shown && <pre data-testid="output-file-content" style={{ background: "var(--colorNeutralBackground3, #f5f5f5)", padding: 8, maxHeight: 160, overflow: "auto" }}>{shown.text}</pre>}</div>}
    </div>
  );
}

/** Run steps for the last run: tool calls (code interpreter input + logs, file search) in order. */
export function RunSteps({ steps }) {
  const calls = steps.filter((s) => s.type === "tool_calls").flatMap((s) => s.step_details.tool_calls || []);
  if (!calls.length) return null;
  return (
    <details data-testid="run-steps" style={{ marginTop: 6 }} open>
      <summary>Run steps: {calls.length} tool call{calls.length === 1 ? "" : "s"}</summary>
      {calls.map((c, i) => (
        <div key={i} style={{ margin: "6px 0" }}>
          <Badge appearance="outline">{c.type}</Badge>
          {c.type === "code_interpreter" && <>
            <pre data-testid="ci-code" style={{ background: "var(--colorNeutralBackground3, #f5f5f5)", padding: 8, overflow: "auto" }}>{c.code_interpreter.input}</pre>
            {(c.code_interpreter.outputs || []).map((o, j) => <pre key={j} data-testid="ci-logs" style={{ borderLeft: "3px solid var(--colorBrandStroke1, #0f6cbd)", padding: "4px 8px", margin: 0 }}>{o.logs}</pre>)}</>}
          {c.type === "file_search" && <span style={{ marginLeft: 6 }}>retrieved from the vector store</span>}
        </div>))}
    </details>
  );
}
