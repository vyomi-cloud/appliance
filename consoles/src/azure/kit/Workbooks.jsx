/* Workbooks for a resource: Microsoft.Insights/workbooks CRUD (core/azure_monitor_core.py) + the renderer
 * (core/azure_workbooks_core.py, POST .../workbooks/{name}/render). In real Azure the portal renders serializedData
 * client-side; Vyomi renders it server-side so the KQL query items actually run against the Log Analytics subset and
 * come back as tables. Items the renderer cannot run (metrics, Resource Graph, ...) are shown as such, never blanked. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Spinner, Textarea, ToolbarButton, Link,
} from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { getSubscription, parseId } from "./arm.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";

const V = "2022-04-01";
const base = (rg) => `/subscriptions/${getSubscription()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Insights/workbooks`;
const same = (a, b) => String(a || "").toLowerCase() === String(b || "").toLowerCase();

const template = (wsId) => JSON.stringify({
  version: "Notebook/1.0",
  items: [
    { type: 1, name: "intro", content: { json: "## Workspace summary" } },
    { type: 9, name: "parameters", content: { parameters: [{ name: "TimeRange", type: 4, label: "Time range", value: { durationMs: 86400000 } }] } },
    { type: 3, name: "tables", content: { queryType: 0, visualization: "table", title: "Rows per table", crossComponentResources: [wsId],
      query: "AzureActivity | where {TimeRange} | summarize operations = count() by OperationName | order by operations desc | take 10" } },
  ],
}, null, 2);

export default function WorkbooksPanel({ workspace, capId = "azure.loganalytics.workspace.monitoring" }) {
  const notify = useNotify();
  const rg = parseId(workspace.id).resourceGroup;
  const list = useAsync(async () => {
    const rows = (await restJson("GET", base(rg), { query: { "api-version": V, category: "workbook" } })).value || [];
    return rows.filter((w) => same(w.properties?.sourceId, workspace.id));
  }, [workspace.id]);
  const [add, setAdd] = useState(false);
  const [open, setOpen] = useState(null);
  return (
    <CapabilityContainer id={capId} title={`${workspace.name} | Workbooks`}>
      <BrowseGrid
        resourceName="workbook" rowKey={(r) => r.id} filterPlaceholder="Search workbooks"
        items={list.data || []} loading={list.loading} error={list.error} onRefresh={list.reload} csvName="workbooks.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>New</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await restJson("DELETE", `${base(rg)}/${encodeURIComponent(r.name)}`, { query: { "api-version": V } }); notify.success(`Deleted ${sel.length} workbook(s).`, "Delete succeeded"); list.reload(); }}
        columns={[
          { key: "name", label: "Name", value: (r) => r.properties?.displayName || r.name, render: (r) => <Link onClick={() => setOpen(r)}>{r.properties?.displayName || r.name}</Link> },
          { key: "category", label: "Category", value: (r) => r.properties?.category },
          { key: "kind", label: "Type", value: (r) => r.kind },
          { key: "modified", label: "Last modified", value: (r) => r.properties?.timeModified || "" },
        ]}
      />
      {add && <NewWorkbook workspace={workspace} rg={rg} onClose={() => setAdd(false)} onDone={list.reload} />}
      {open && <Viewer wb={open} rg={rg} workspace={workspace} onClose={() => setOpen(null)} />}
    </CapabilityContainer>
  );
}

function NewWorkbook({ workspace, rg, onClose, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [json, setJson] = useState(() => template(workspace.id));
  const [busy, setBusy] = useState(false);
  let valid = true;
  try { JSON.parse(json); } catch { valid = false; }
  const go = async () => {
    setBusy(true);
    try {
      const id = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-0000-4000-8000-000000000000`);
      await restJson("PUT", `${base(rg)}/${id}`, { query: { "api-version": V }, body: { location: workspace.location, kind: "shared",
        properties: { displayName: name.trim(), category: "workbook", serializedData: json, sourceId: workspace.id } } });
      notify.success(`Workbook '${name}' was saved.`, "Workbook saved");
      onDone(); onClose();
    } catch (e) { notify.error(e, "Failed to save the workbook"); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="New workbook" style={{ maxWidth: 760 }}>
        <DialogBody>
          <DialogTitle>New workbook</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Field label="Title" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Workbook title" /></Field>
              <Field label="Content (Notebook/1.0 JSON: text 1, parameters 9, KQL query 3, group 12)" validationMessage={valid ? "" : "Not valid JSON"}>
                <Textarea value={json} onChange={(_, d) => setJson(d.value)} rows={16} style={{ fontFamily: "monospace", width: "100%" }} aria-label="Workbook content" />
              </Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !name.trim() || !valid} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function Viewer({ wb, rg, workspace, onClose }) {
  const notify = useNotify();
  const [overrides, setOverrides] = useState({});
  const [tick, setTick] = useState(0);
  const run = useAsync(() => restJson("POST", `${base(rg)}/${encodeURIComponent(wb.name)}/render`, { query: { "api-version": V }, body: { parameters: overrides, workspaceId: workspace.id } }), [wb.id, tick]);
  const r = run.data;
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={wb.properties?.displayName || wb.name} style={{ maxWidth: 980, width: "90vw" }}>
        <DialogBody>
          <DialogTitle>{wb.properties?.displayName || wb.name}</DialogTitle>
          <DialogContent>
            {run.loading && <Spinner size="tiny" label="Running the workbook's queries..." />}
            {run.error && <p role="alert">Render failed: {String(run.error.message || run.error)}</p>}
            {r && <>
              <p className="vy-muted" style={{ fontSize: 12 }}>{r.summary.queries} queries: {r.summary.ok} ok, {r.summary.errors} failed, {r.summary.unsupported} item(s) not rendered.</p>
              <Items items={r.items} params={r.parameters} onParam={(k, v) => setOverrides({ ...overrides, [k]: v })} onRun={() => { setTick(tick + 1); notify.info?.("Re-running the workbook"); }} />
            </>}
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function Items({ items, params, onParam, onRun }) {
  return <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>{items.map((it, i) => <Item key={i} it={it} params={params} onParam={onParam} onRun={onRun} />)}</div>;
}

function Item({ it, params, onParam, onRun }) {
  if (it.type === "hidden") return null;
  if (it.type === "text") return <div style={{ whiteSpace: "pre-wrap" }}>{it.markdown.replace(/^#+\s*/gm, "")}</div>;
  if (it.type === "parameters") {
    return (
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        {it.parameters.map((p) => (
          <Field key={p.name} label={p.label}>
            {typeof p.value === "object" && p.value ? <Input disabled value={`${Math.round((p.value.durationMs || 0) / 3600000)}h`} aria-label={p.label} />
              : <Input value={String(params[p.name] ?? "")} onChange={(_, d) => onParam(p.name, d.value)} aria-label={p.label} />}
          </Field>
        ))}
        <Button size="small" onClick={onRun}>Run</Button>
      </div>
    );
  }
  if (it.type === "group") return <section className="vy-section"><b>{it.title}</b><Items items={it.items} params={params} onParam={onParam} onRun={onRun} /></section>;
  if (it.type === "links") return <div>{it.links.map((l, i) => <span key={i} style={{ marginRight: 12 }}>{l.label}</span>)}</div>;
  if (it.type === "query") {
    return (
      <section className="vy-section">
        {it.title && <b>{it.title}</b>}
        {it.status === "ok" ? <ResultTable it={it} /> : <p role="alert" style={{ margin: "6px 0" }}>{it.status === "unsupported" ? "Not rendered: " : "Query failed: "}{it.reason || it.error}</p>}
      </section>
    );
  }
  return <p className="vy-muted">Not rendered: {it.reason}</p>;
}

function ResultTable({ it }) {
  const max = it.visualization === "barchart" || it.visualization === "piechart" ? Math.max(1, ...it.rows.map((r) => Number(r[r.length - 1]) || 0)) : 0;
  return (
    <table className="vy-grid" style={{ marginTop: 6 }}>
      <thead><tr>{it.columns.map((c) => <th key={c.name}>{c.name}</th>)}{max > 0 && <th />}</tr></thead>
      <tbody>
        {it.rows.length ? it.rows.map((r, i) => (
          <tr key={i}>
            {r.map((v, j) => <td key={j}>{v === null || v === undefined ? "" : String(v)}</td>)}
            {max > 0 && <td style={{ width: 160 }}><div style={{ background: "var(--colorBrandBackground, #0f6cbd)", height: 10, width: `${Math.round(((Number(r[r.length - 1]) || 0) / max) * 100)}%` }} /></td>}
          </tr>
        )) : <tr><td colSpan={it.columns.length} className="vy-muted">No results</td></tr>}
      </tbody>
    </table>
  );
}
