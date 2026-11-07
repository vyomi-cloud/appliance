/* Activity log blade body shared by every Azure resource blade: the real
 * Microsoft.Insights/eventtypes/management/values feed (core/azure_monitor_core.py) filtered
 * server-side by resourceUri / timespan / level / status / caller, with the portal's command
 * bar: Edit columns (persisted), Activity (event detail), Insights (live summary), Download as
 * CSV, Export Activity Logs (JSON), Pin current filters, Reset filters. */
import { useMemo, useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, ArrowDownload20Regular } from "@fluentui/react-icons";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { getSubscription } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { downloadCsv, ErrorBar, fmtDate, NotSimulated, Loading } from "./common.jsx";

const COLUMNS = [
  { key: "op", label: "Operation name", get: (e) => e.operationName?.localizedValue || e.operationName?.value, on: true },
  { key: "status", label: "Status", get: (e) => e.status?.localizedValue || e.status?.value, on: true },
  { key: "time", label: "Time", get: (e) => fmtDate(e.eventTimestamp), on: true },
  { key: "stamp", label: "Time stamp", get: (e) => e.eventTimestamp, on: true },
  { key: "sub", label: "Subscription", get: (e) => e.subscriptionId, on: true },
  { key: "by", label: "Event initiated by", get: (e) => e.caller, on: true },
  { key: "level", label: "Severity", get: (e) => e.level },
  { key: "rg", label: "Resource group", get: (e) => e.resourceGroupName },
  { key: "res", label: "Resource", get: (e) => (e.resourceId || "").split("/").pop() },
  { key: "type", label: "Resource type", get: (e) => e.resourceProviderName?.value },
  { key: "event", label: "Event name", get: (e) => e.eventName?.localizedValue || e.eventName?.value },
  { key: "sub2", label: "Sub-status", get: (e) => e.subStatus?.localizedValue || e.subStatus?.value },
];
const SPANS = [["30m", "Last 30 minutes", 30 * 60e3], ["1h", "Last hour", 3600e3], ["6h", "Last 6 hours", 6 * 3600e3], ["24h", "Last 24 hours", 24 * 3600e3], ["7d", "Last 7 days", 7 * 86400e3], ["30d", "Last 30 days", 30 * 86400e3]];
const DEF = { span: "30d", level: "", status: "", caller: "", q: "" };

const store = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || "null"); localStorage.setItem(k, JSON.stringify(v)); } catch { return null; } };

function save(name, text, mime) {
  const el = document.createElement("a");
  el.href = URL.createObjectURL(new Blob([text], { type: mime }));
  el.download = name; document.body.appendChild(el); el.click(); el.remove();
  setTimeout(() => URL.revokeObjectURL(el.href), 1000);
}

const ARM = (path) => `/subscriptions/${getSubscription()}/providers/${path}`;
const DIAG = "Microsoft.Insights/diagnosticSettings";
const DV = { query: { "api-version": "2021-05-01-preview" } };
const CATS = ["Administrative", "Security", "ServiceHealth", "Alert", "Recommendation", "Policy", "Autoscale", "ResourceHealth"];

/** "Export Activity Logs": download the filtered events, or manage the SUBSCRIPTION's continuous export = a real
 *  Microsoft.Insights/diagnosticSettings at subscription scope (Administrative events are delivered to the chosen
 *  Log Analytics workspace / storage account by core/azure_diag_pipeline.py). */
function ExportDialog({ rows, name, onClose }) {
  const settings = useAsync(() => restJson("GET", ARM(DIAG), DV).then((r) => (r.data || r).value || []), []);
  const dests = useAsync(async () => {
    const list = (p, v) => restJson("GET", ARM(p), { query: { "api-version": v } }).then((r) => (r.data || r).value || []).catch(() => []);
    return { w: await list("Microsoft.OperationalInsights/workspaces", "2022-10-01"), s: await list("Microsoft.Storage/storageAccounts", "2023-01-01") };
  }, []);
  const [nm, setNm] = useState("activity-log-export");
  const [cats, setCats] = useState(["Administrative"]);
  const [ws, setWs] = useState("");
  const [st, setSt] = useState("");
  const [err, setErr] = useState("");
  const create = async () => {
    setErr("");
    try {
      await restJson("PUT", `${ARM(DIAG)}/${encodeURIComponent(nm)}`, { ...DV, body: { properties: { ...(ws ? { workspaceId: ws } : {}), ...(st ? { storageAccountId: st } : {}), logs: cats.map((category) => ({ category, enabled: true })) } } });
      settings.reload();
    } catch (e) { setErr(e?.message || String(e)); }
  };
  const del = async (n) => { await restJson("DELETE", `${ARM(DIAG)}/${encodeURIComponent(n)}`, DV); settings.reload(); };
  return <>
    <DialogTitle>Export Activity Logs</DialogTitle>
    <DialogContent>
      <p style={{ fontSize: 13 }}>Continuous export is a diagnostic setting on the subscription. New Administrative events are delivered to the destinations below as they happen.</p>
      <table className="vy-grid" aria-label="Export settings"><thead><tr><th>Name</th><th>Categories</th><th>Destinations</th><th /></tr></thead><tbody>
        {(settings.data || []).length ? settings.data.map((s) => (
          <tr key={s.name}><td>{s.name}</td><td>{(s.properties.logs || []).filter((l) => l.enabled).map((l) => l.category).join(", ")}</td>
            <td>{[s.properties.workspaceId && "Log Analytics", s.properties.storageAccountId && "Storage account"].filter(Boolean).join(", ")}</td>
            <td><Button size="small" onClick={() => del(s.name)} aria-label={`Delete ${s.name}`}>Delete</Button></td></tr>
        )) : <tr><td colSpan={4} className="vy-muted">No export settings</td></tr>}
      </tbody></table>
      <h4>Add export</h4>
      <Input size="small" value={nm} onChange={(_, d) => setNm(d.value)} aria-label="Setting name" />
      <div>{CATS.map((c) => <Checkbox key={c} label={c} checked={cats.includes(c)} onChange={(_, d) => setCats(d.checked ? [...cats, c] : cats.filter((x) => x !== c))} />)}</div>
      <Select size="small" value={ws} onChange={(_, d) => setWs(d.value)} aria-label="Log Analytics workspace"><option value="">Send to Log Analytics workspace: none</option>{(dests.data?.w || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>
      <Select size="small" value={st} onChange={(_, d) => setSt(d.value)} aria-label="Storage account"><option value="">Archive to a storage account: none</option>{(dests.data?.s || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>
      {err && <p role="alert" style={{ color: "#b10e1c" }}>{err}</p>}
    </DialogContent>
    <DialogActions>
      <Button onClick={() => save(`${name || "subscription"}-activity-log.json`, JSON.stringify(rows, null, 2), "application/json")}>Download JSON</Button>
      <Button appearance="primary" onClick={create}>Save export</Button>
      <Button onClick={onClose}>Close</Button>
    </DialogActions>
  </>;
}

/** scope: resource / resource-group id ("" = whole subscription). */
export default function ActivityLog({ scope, name, capId, title }) {
  const [f, setF] = useState(() => store("vyomi.az.activity.pinned") || DEF);
  const [cols, setCols] = useState(() => store("vyomi.az.activity.cols") || COLUMNS.filter((c) => c.on).map((c) => c.key));
  const [dlg, setDlg] = useState(null);       // "columns" | "feedback" | "insights" | event
  const [pinned, setPinned] = useState(() => !!store("vyomi.az.activity.pinned"));
  const span = SPANS.find((s) => s[0] === f.span) || SPANS[5];
  const { data, loading, error, reload } = useAsync(() => {
    const parts = [];
    if (scope) parts.push(`resourceUri eq '${scope}'`);
    parts.push(`eventTimestamp ge '${new Date(Date.now() - span[2]).toISOString()}'`);
    if (f.level) parts.push(`level eq '${f.level}'`);
    if (f.status) parts.push(`status eq '${f.status}'`);
    if (f.caller.trim()) parts.push(`caller eq '${f.caller.trim().replace(/'/g, "")}'`);
    return restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query: { "api-version": "2015-04-01", "$filter": parts.join(" and ") } }).then((r) => r.value || []);
  }, [scope, f.span, f.level, f.status, f.caller]);
  const q = f.q.trim().toLowerCase();
  const rows = useMemo(() => (data || []).filter((e) => !q || COLUMNS.some((c) => String(c.get(e) ?? "").toLowerCase().includes(q))), [data, q]);
  const shown = COLUMNS.filter((c) => cols.includes(c.key));
  const set = (patch) => setF((x) => ({ ...x, ...patch }));
  const count = (get) => rows.reduce((m, e) => { const k = get(e) || "-"; m[k] = (m[k] || 0) + 1; return m; }, {});
  return (
    <CapabilityContainer id={capId || "azure.common.activity_log"} title={title || `${name} | Activity log`}>
      <div className="vy-cmdbar" role="toolbar" aria-label="Activity log commands">
        <ToolbarButton onClick={() => setDlg(rows[0] || "none")}>Activity</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("export")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!rows.length} onClick={() => downloadCsv(`${name || "subscription"}-activity-log.csv`, shown.map((c) => ({ label: c.label, csv: c.get })), rows)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("insights")}>Insights</ToolbarButton>
        <ToolbarButton onClick={() => setDlg("feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => { store("vyomi.az.activity.pinned", pinned ? null : f); setPinned(!pinned); }}>{pinned ? "Unpin current filters" : "Pin current filters"}</ToolbarButton>
        <ToolbarButton onClick={() => setF(DEF)}>Reset filters</ToolbarButton>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
        <Input size="small" style={{ width: 220 }} placeholder="Search" value={f.q} onChange={(_, d) => set({ q: d.value })} aria-label="Search activity log" />
        <Select size="small" value={f.span} onChange={(_, d) => set({ span: d.value })} aria-label="Timespan">{SPANS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
        <Select size="small" value={f.level} onChange={(_, d) => set({ level: d.value })} aria-label="Event severity">
          <option value="">Severity: All</option>{["Critical", "Error", "Warning", "Informational", "Verbose"].map((l) => <option key={l}>{l}</option>)}
        </Select>
        <Select size="small" value={f.status} onChange={(_, d) => set({ status: d.value })} aria-label="Status">
          <option value="">Status: All</option>{["Succeeded", "Failed", "Started", "Accepted"].map((l) => <option key={l}>{l}</option>)}
        </Select>
        <Input size="small" style={{ width: 200 }} placeholder="Event initiated by" value={f.caller} onChange={(_, d) => set({ caller: d.value })} aria-label="Event initiated by" />
      </div>
      <ErrorBar error={error} title="Failed to load the activity log" />
      {loading ? <Loading /> : (
        <table className="vy-grid" aria-label="Activity log">
          <thead><tr>{shown.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.length ? rows.map((e) => (
              <tr key={e.id} onClick={() => setDlg(e)} style={{ cursor: "pointer" }}>{shown.map((c) => <td key={c.key}>{c.get(e)}</td>)}</tr>
            )) : <tr><td colSpan={shown.length || 1} className="vy-muted">No events to display</td></tr>}
          </tbody>
        </table>
      )}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Activity log dialog">
          <DialogBody>
            {dlg === "columns" && <>
              <DialogTitle>Edit columns</DialogTitle>
              <DialogContent>
                {COLUMNS.map((c) => <div key={c.key}><Checkbox label={c.label} checked={cols.includes(c.key)}
                  onChange={(_, d) => { const n = d.checked ? COLUMNS.filter((x) => cols.includes(x.key) || x.key === c.key).map((x) => x.key) : cols.filter((k) => k !== c.key); setCols(n); store("vyomi.az.activity.cols", n); }} /></div>)}
              </DialogContent>
              <DialogActions><Button onClick={() => { const n = COLUMNS.filter((c) => c.on).map((c) => c.key); setCols(n); store("vyomi.az.activity.cols", n); }}>Reset</Button><Button appearance="primary" onClick={() => setDlg(null)}>OK</Button></DialogActions>
            </>}
            {dlg === "insights" && <>
              <DialogTitle>Activity log insights</DialogTitle>
              <DialogContent>
                <p>{rows.length} event{rows.length === 1 ? "" : "s"} in the selected timespan.</p>
                {[["By status", (e) => e.status?.value], ["By severity", (e) => e.level], ["By initiator", (e) => e.caller]].map(([h, g]) => (
                  <div key={h}><strong>{h}</strong><ul>{Object.entries(count(g)).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul></div>
                ))}
              </DialogContent>
              <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
            </>}
            {dlg === "export" && <ExportDialog rows={rows} name={name} onClose={() => setDlg(null)} />}
            {dlg === "feedback" && <>
              <DialogTitle>Feedback</DialogTitle>
              <DialogContent><NotSimulated feature="Sending product feedback" /></DialogContent>
              <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
            </>}
            {dlg && typeof dlg === "object" && <>
              <DialogTitle>{dlg.operationName?.localizedValue || "Activity"}</DialogTitle>
              <DialogContent><pre className="vy-mono" style={{ maxHeight: 360, overflow: "auto", fontSize: 12 }}>{JSON.stringify(dlg, null, 2)}</pre></DialogContent>
              <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
            </>}
            {dlg === "none" && <>
              <DialogTitle>Activity</DialogTitle>
              <DialogContent><p>No events to display.</p></DialogContent>
              <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
            </>}
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}
