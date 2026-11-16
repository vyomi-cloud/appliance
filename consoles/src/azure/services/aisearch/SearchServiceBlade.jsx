/* Azure AI Search service blade: Overview, Keys, Indexes (+ search explorer and document upload), Indexers, Data sources, Activity log.
 * Every action is a real ARM call into core/azure_search_core.py (the same engine the Search SDKs use). Not built here: semantic ranker
 * configuration, skillsets editor, vector profiles, scaling and networking panels (the engine declares them not modelled). */
import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular, Play20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, InfoBar, Loading } from "../../kit/common.jsx";
import SharedActivityLog from "../../kit/ActivityLog.jsx";
import { remember, forget, setInactive, isNotFound } from "../../kit/recent.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { group: "Search management", items: [{ id: "indexes", label: "Indexes" }, { id: "indexers", label: "Indexers" }, { id: "datasources", label: "Data sources" }] },
  { group: "Settings", items: [{ id: "keys", label: "Keys" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const SAMPLE_INDEX = { fields: [{ name: "id", type: "Edm.String", key: true }, { name: "title", type: "Edm.String", searchable: true }, { name: "category", type: "Edm.String", filterable: true, facetable: true }] };
const json = (v) => JSON.stringify(v, null, 2);
const Pre = ({ children, ...p }) => <pre {...p} style={{ background: "var(--colorNeutralBackground3, #f5f5f5)", padding: 12, fontSize: 12, overflow: "auto", maxHeight: 360, margin: 0 }}>{children}</pre>;

export default function SearchServiceBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const svc = useAsync(() => api.getService(rg, name), [rg, name]);
  const self = `#/aisearch/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (svc.data) { remember({ name, type: "AI Search", href: self }); setInactive(self, false); } }, [!!svc.data, self]);
  const gone = !!svc.error && isNotFound(svc.error);
  useEffect(() => { if (gone) setInactive(self, true); }, [gone, self]);
  let body;
  if (svc.loading && !svc.data) body = <Loading />;
  else if (gone) body = <><InfoBar>{name} is inactive. It was created in an earlier session and no longer exists in this one.</InfoBar><Link href="#/aisearch">Back to AI Search</Link></>;
  else if (svc.error) body = <><ErrorBar error={svc.error} title="Failed to load the search service" /><Link href="#/aisearch">Back to AI Search</Link></>;
  else {
    const a = svc.data;
    body = {
      overview: () => <Overview a={a} reload={svc.reload} self={self} />,
      activitylog: () => <SharedActivityLog scope={a.id} name={a.name} />,
      indexes: () => <Indexes a={a} />,
      indexers: () => <Indexers a={a} />,
      datasources: () => <DataSources a={a} />,
      keys: () => <Keys a={a} />,
    }[panel]?.() || <InfoBar>Unknown panel.</InfoBar>;
  }
  return (
    <ResourceBlade title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Search service" glyph={<Glyph id="cognitiveservices" />} closeHref="#/aisearch"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>
      {body}
    </ResourceBlade>
  );
}

function Overview({ a, reload, self }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const st = useAsync(() => api.stats(a.resourceGroup, a.name), [a.id]);
  const p = a.properties || {}, c = st.data?.counters || {};
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); st.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>], ["Location", locationLabel(a.location)], ["Subscription", "Vyomi simulator (default directory)"], ["Url", p.endpoint], ["Status", p.status]]}
        right={[["Pricing tier", a.sku?.name], ["Replicas", p.replicaCount], ["Partitions", p.partitionCount], ["Semantic ranker", p.semanticSearch], ["Public network access", p.publicNetworkAccess]]}
      />
      <h3 style={{ marginTop: 16 }}>Usage</h3>
      <Table size="small" aria-label="Usage" style={{ maxWidth: 520 }}>
        <TableHeader><TableRow><TableHeaderCell>Counter</TableHeaderCell><TableHeaderCell>Used</TableHeaderCell><TableHeaderCell>Quota</TableHeaderCell></TableRow></TableHeader>
        <TableBody>{[["Indexes", "indexesCount"], ["Indexers", "indexersCount"], ["Data sources", "dataSourcesCount"], ["Documents", "documentCount"]].map(([l, k]) => (
          <TableRow key={k}><TableCell>{l}</TableCell><TableCell>{c[k]?.usage ?? "-"}</TableCell><TableCell>{c[k]?.quota ?? "Unlimited"}</TableCell></TableRow>))}</TableBody>
      </Table>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="search service" names={[a.name]}
        onConfirm={async () => { await api.deleteService(a.resourceGroup, a.name); forget(self); notify.success(`Search service '${a.name}' was deleted.`, "Delete succeeded"); navigate("aisearch"); }} />
    </>
  );
}

function Keys({ a }) {
  const notify = useNotify();
  const admin = useAsync(() => api.adminKeys(a.resourceGroup, a.name), [a.id]);
  const q = useAsync(() => api.queryKeys(a.resourceGroup, a.name), [a.id]);
  const [nm, setNm] = useState("");
  const act = async (fn, msg) => { try { await fn(); notify.success(msg, "Succeeded"); } catch (e) { notify.error(e, "Failed"); } admin.reload(); q.reload(); };
  return (
    <div style={{ maxWidth: 760 }}>
      <div className="vy-panel-title">Keys</div>
      <h3>Manage admin keys</h3>
      {admin.error && <ErrorBar error={admin.error} />}
      {[["primary", "Primary admin key"], ["secondary", "Secondary admin key"]].map(([w, l]) => (
        <Field key={w} label={l} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", gap: 8 }}><Input readOnly style={{ flex: 1 }} value={admin.data?.[`${w}Key`] || ""} aria-label={l} />
            <Button onClick={() => act(() => api.regenKey(a.resourceGroup, a.name, w), `Regenerated the ${w} admin key.`)}>Regenerate</Button></div>
        </Field>))}
      <h3 style={{ marginTop: 20 }}>Manage query keys</h3>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <Input placeholder="Query key name" value={nm} onChange={(_, d) => setNm(d.value)} aria-label="Query key name" />
        <Button appearance="primary" disabled={!nm} icon={<Add20Regular />} onClick={() => act(async () => { await api.createQueryKey(a.resourceGroup, a.name, nm); setNm(""); }, `Created query key '${nm}'.`)}>Add</Button>
      </div>
      <Table size="small" aria-label="Query keys"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Key</TableHeaderCell><TableHeaderCell style={{ width: 60 }} /></TableRow></TableHeader>
        <TableBody>{(q.data || []).map((k) => (
          <TableRow key={k.key}><TableCell>{k.name}</TableCell><TableCell><code>{k.key}</code></TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${k.name}`} onClick={() => act(() => api.deleteQueryKey(a.resourceGroup, a.name, k.key), "Deleted the query key.")} /></TableCell></TableRow>))}
          {!(q.data || []).length && <TableRow><TableCell colSpan={3}>No query keys.</TableCell></TableRow>}</TableBody></Table>
    </div>
  );
}

function JsonDialog({ open, title, init, onClose, onSave, nameLabel = "Name", withName = true, saveLabel = "Save" }) {
  const [name, setName] = useState("");
  const [text, setText] = useState(init);
  const [err, setErr] = useState(null);
  useEffect(() => { if (open) { setName(""); setText(init); setErr(null); } }, [open]);
  const go = async () => { try { await onSave(name, JSON.parse(text)); onClose(); } catch (e) { setErr(e instanceof SyntaxError ? { message: `The JSON is not valid: ${e.message}` } : e); } };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title} style={{ maxWidth: 640 }}><DialogBody><DialogTitle>{title}</DialogTitle>
        <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {withName && <Field label={nameLabel} required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label={nameLabel} /></Field>}
          <Field label="JSON definition"><Textarea rows={12} value={text} onChange={(_, d) => setText(d.value)} aria-label="JSON definition" style={{ fontFamily: "monospace" }} /></Field>
          <ErrorBar error={err} title="Request failed" /></div></DialogContent>
        <DialogActions><Button appearance="primary" disabled={withName && !name} onClick={go}>{saveLabel}</Button><Button onClick={onClose}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
  );
}

function Indexes({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.indexes.list(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [open, setOpen] = useState(null);
  const del = async (n) => { try { await api.indexes.remove(a.resourceGroup, a.name, n); notify.success(`Deleted index '${n}'.`, "Delete succeeded"); if (open === n) setOpen(null); } catch (e) { notify.error(e, "Delete failed"); } reload(); };
  return (
    <>
      <div className="vy-panel-title">Indexes</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Index commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add index</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      {loading && !data ? <Loading /> : <ErrorBar error={error} />}
      <Table size="small" aria-label="Indexes"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Fields</TableHeaderCell><TableHeaderCell>Key</TableHeaderCell><TableHeaderCell style={{ width: 60 }} /></TableRow></TableHeader>
        <TableBody>{(data || []).map((ix) => (
          <TableRow key={ix.name}><TableCell><Link as="button" onClick={() => setOpen(ix.name)}>{ix.name}</Link></TableCell><TableCell>{(ix.fields || []).length}</TableCell>
            <TableCell>{(ix.fields || []).find((f) => f.key)?.name}</TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${ix.name}`} onClick={() => del(ix.name)} /></TableCell></TableRow>))}
          {!loading && !(data || []).length && <TableRow><TableCell colSpan={4}>No indexes yet. Add one, or use Import data from a storage account.</TableCell></TableRow>}</TableBody></Table>
      {open && <Explorer a={a} index={open} onChange={reload} />}
      <JsonDialog open={add} title="Add index" nameLabel="Index name" init={json(SAMPLE_INDEX)} saveLabel="Create"
        onClose={() => setAdd(false)} onSave={async (n, body) => { await api.indexes.put(a.resourceGroup, a.name, n, { ...body, name: n }); notify.success(`Created index '${n}'.`, "Create succeeded"); reload(); }} />
    </>
  );
}

function Explorer({ a, index, onChange }) {
  const notify = useNotify();
  const [q, setQ] = useState("*");
  const [filter, setFilter] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [docs, setDocs] = useState('[{ "@search.action": "mergeOrUpload", "id": "1", "title": "Hello Vyomi", "category": "demo" }]');
  const count = useAsync(() => api.indexCount(a.resourceGroup, a.name, index), [index]);
  const run = async () => { setErr(null); try { setRes(await api.searchDocs(a.resourceGroup, a.name, index, { search: q || "*", filter: filter || undefined, top: 20, count: true })); } catch (e) { setErr(e); } };
  useEffect(() => { setRes(null); setErr(null); }, [index]);
  const upload = async () => {
    setErr(null);
    try { const r = await api.indexDocs(a.resourceGroup, a.name, index, JSON.parse(docs)); notify.success(`Uploaded ${(r.value || []).length} document(s).`, "Documents indexed"); count.reload(); onChange?.(); }
    catch (e) { setErr(e instanceof SyntaxError ? { message: `The JSON is not valid: ${e.message}` } : e); }
  };
  return (
    <section style={{ marginTop: 20, border: "1px solid var(--colorNeutralStroke2, #ddd)", padding: 16 }} data-testid="search-explorer">
      <h3 style={{ marginTop: 0 }}>Search explorer: {index} <span style={{ fontWeight: 400, fontSize: 13 }}>({count.data ?? "-"} documents)</span></h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <Input style={{ minWidth: 260 }} value={q} onChange={(_, d) => setQ(d.value)} aria-label="Query string" placeholder="Query string" />
        <Input value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Filter" placeholder="$filter, for example category eq 'demo'" style={{ minWidth: 260 }} />
        <Button appearance="primary" icon={<Play20Regular />} onClick={run}>Search</Button>
      </div>
      <ErrorBar error={err} title="Request failed" />
      {res && <Pre data-testid="search-results">{json(res)}</Pre>}
      <h4>Upload documents</h4>
      <Textarea rows={5} value={docs} onChange={(_, d) => setDocs(d.value)} aria-label="Documents JSON" style={{ width: "100%", fontFamily: "monospace" }} />
      <Button style={{ marginTop: 8 }} onClick={upload}>Upload</Button>
    </section>
  );
}

function DataSources({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.datasources.list(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const init = json({ type: "azureblob", credentials: { connectionString: "DefaultEndpointsProtocol=https;AccountName=<account>;AccountKey=<key>;" }, container: { name: "<container>" } });
  return (
    <>
      <div className="vy-panel-title">Data sources</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Data source commands"><ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add data source</ToolbarButton><ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton></div>
      {loading && !data ? <Loading /> : <ErrorBar error={error} />}
      <Table size="small" aria-label="Data sources"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Container</TableHeaderCell><TableHeaderCell style={{ width: 60 }} /></TableRow></TableHeader>
        <TableBody>{(data || []).map((d) => (
          <TableRow key={d.name}><TableCell>{d.name}</TableCell><TableCell>{d.type}</TableCell><TableCell>{d.container?.name}</TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${d.name}`} onClick={async () => { try { await api.datasources.remove(a.resourceGroup, a.name, d.name); notify.success(`Deleted '${d.name}'.`, "Delete succeeded"); } catch (e) { notify.error(e, "Delete failed"); } reload(); }} /></TableCell></TableRow>))}
          {!loading && !(data || []).length && <TableRow><TableCell colSpan={4}>No data sources.</TableCell></TableRow>}</TableBody></Table>
      <InfoBar>Vyomi indexers read Azure Blob Storage data sources. Cosmos DB and SQL data sources are stored, and their indexers report the failure.</InfoBar>
      <JsonDialog open={add} title="Add data source" nameLabel="Data source name" init={init} saveLabel="Create"
        onClose={() => setAdd(false)} onSave={async (n, body) => { await api.datasources.put(a.resourceGroup, a.name, n, { ...body, name: n }); notify.success(`Created data source '${n}'.`, "Create succeeded"); reload(); }} />
    </>
  );
}

function Indexers({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.indexers.list(a.resourceGroup, a.name), [a.id]);
  const [add, setAdd] = useState(false);
  const [status, setStatus] = useState(null);
  const init = json({ dataSourceName: "<data source>", targetIndexName: "<index>", parameters: { configuration: { parsingMode: "default" } } });
  const run = async (n) => { try { await api.runIndexer(a.resourceGroup, a.name, n); setStatus({ name: n, ...(await api.indexerStatus(a.resourceGroup, a.name, n)) }); notify.success(`Ran indexer '${n}'.`, "Indexer run"); } catch (e) { notify.error(e, "Run failed"); } };
  return (
    <>
      <div className="vy-panel-title">Indexers</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Indexer commands"><ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add indexer</ToolbarButton><ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton></div>
      {loading && !data ? <Loading /> : <ErrorBar error={error} />}
      <Table size="small" aria-label="Indexers"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Data source</TableHeaderCell><TableHeaderCell>Target index</TableHeaderCell><TableHeaderCell style={{ width: 130 }} /></TableRow></TableHeader>
        <TableBody>{(data || []).map((d) => (
          <TableRow key={d.name}><TableCell>{d.name}</TableCell><TableCell>{d.dataSourceName}</TableCell><TableCell>{d.targetIndexName}</TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Play20Regular />} aria-label={`Run ${d.name}`} onClick={() => run(d.name)} />
              <Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${d.name}`} onClick={async () => { try { await api.indexers.remove(a.resourceGroup, a.name, d.name); notify.success(`Deleted '${d.name}'.`, "Delete succeeded"); } catch (e) { notify.error(e, "Delete failed"); } reload(); }} /></TableCell></TableRow>))}
          {!loading && !(data || []).length && <TableRow><TableCell colSpan={4}>No indexers.</TableCell></TableRow>}</TableBody></Table>
      {status && <section style={{ marginTop: 16 }} data-testid="indexer-status"><h3>Execution status: {status.name}</h3><Pre>{json({ status: status.status, lastResult: status.lastResult })}</Pre></section>}
      <JsonDialog open={add} title="Add indexer" nameLabel="Indexer name" init={init} saveLabel="Create"
        onClose={() => setAdd(false)} onSave={async (n, body) => { await api.indexers.put(a.resourceGroup, a.name, n, { ...body, name: n }); notify.success(`Created indexer '${n}'.`, "Create succeeded"); reload(); }} />
    </>
  );
}
