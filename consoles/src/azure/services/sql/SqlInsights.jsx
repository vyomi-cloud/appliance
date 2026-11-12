/* SQL database Intelligent Performance + Auditing: Query Performance Insight, Performance overview and Auditing.
 * All three read /azure-sql/.../queryinsights (core/azure_sql_core.query_insights) - the MEASURED wall-clock timing
 * of every statement run through the data plane. No statements run yet = empty views, never invented numbers. */
import { useEffect, useState } from "react";
import { Select, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading, fmtBytes } from "../../kit/common.jsx";
import * as api from "./api.js";

const WINDOWS = [["3600", "Last hour"], ["86400", "Last 24 hours"], ["604800", "Last 7 days"]];

function useInsights(a) {
  const [win, setWin] = useState("86400");
  const r = useAsync(() => api.queryInsights(a.server, a.name, win), [a.server, a.name, win]);
  useEffect(() => { const id = setInterval(r.reload, 5000); return () => clearInterval(id); }, [r.reload]);
  return { ...r, win, setWin };
}

const Toolbar = ({ win, setWin, reload }) => (
  <div className="vy-cmdbar" role="toolbar" aria-label="Insights commands" style={{ display: "flex", gap: 8, alignItems: "center" }}>
    <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
    <Select value={win} onChange={(_, d) => setWin(d.value)} aria-label="Time window">{WINDOWS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
  </div>
);

function Bars({ points, label, field = "count" }) {
  const w = 640, h = 140, max = Math.max(1, ...points.map((p) => p[field]));
  const bw = points.length ? Math.min(36, (w - 40) / points.length) : 0;
  return (
    <svg width={w} height={h} role="img" aria-label={label} style={{ maxWidth: "100%" }}>
      <line x1={30} y1={h - 20} x2={w - 4} y2={h - 20} stroke="#ccc" />
      <text x={2} y={12} fontSize="10" fill="#666">{max}</text>
      {points.map((p, i) => <rect key={p.ts} x={34 + i * bw} y={h - 20 - (p[field] / max) * (h - 36)} width={Math.max(2, bw - 3)} height={(p[field] / max) * (h - 36)} fill="#0078d4"><title>{new Date(p.ts * 1000).toLocaleTimeString()}: {p[field]}</title></rect>)}
    </svg>
  );
}

export function QueryPerformanceInsight({ a }) {
  const { data, loading, error, reload, win, setWin } = useInsights(a);
  const top = data?.topQueries || [];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Query Performance Insight</div>
      <CapabilityContainer id="azure.sql.query_performance" title="Query Performance Insight" actions={<Toolbar win={win} setWin={setWin} reload={reload} />}>
        <ErrorBar error={error} />
        {loading && !data ? <Loading /> : (
          <>
            <p style={{ fontSize: 12 }} data-testid="qpi-note">Top queries by total measured duration. Literals are normalised so repeated statements group together (like Query Store).</p>
            <table className="vy-grid" aria-label="Top queries">
              <thead><tr><th>Query ID</th><th>Query</th><th>Executions</th><th>Total (ms)</th><th>Avg (ms)</th><th>p95 (ms)</th><th>Max (ms)</th><th>Failed</th></tr></thead>
              <tbody>
                {top.length ? top.map((q) => (
                  <tr key={q.queryId} data-testid="qpi-row"><td>{q.queryId}</td><td style={{ fontFamily: "monospace", maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis" }}>{q.queryText}</td>
                    <td>{q.executions}</td><td>{q.totalMs}</td><td>{q.avgMs}</td><td>{q.p95Ms}</td><td>{q.maxMs}</td><td>{q.failures}</td></tr>
                )) : <tr><td colSpan={8} className="vy-muted" data-testid="qpi-empty">No statements have run in this window. Run SQL from the Query editor.</td></tr>}
              </tbody>
            </table>
          </>
        )}
      </CapabilityContainer>
    </>
  );
}

export function PerformanceOverview({ a }) {
  const { data, loading, error, reload, win, setWin } = useInsights(a);
  const o = data?.overview;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Performance overview</div>
      <CapabilityContainer id="azure.sql.perf_overview" title="Performance overview" actions={<Toolbar win={win} setWin={setWin} reload={reload} />}>
        <ErrorBar error={error} />
        {loading && !data ? <Loading /> : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, margin: "8px 0" }}>
              {[["Statements", o.statements, "po-statements"], ["Failed", o.failed], ["p50 (ms)", o.p50Ms], ["p95 (ms)", o.p95Ms], ["Max (ms)", o.maxMs], ["Database size", fmtBytes(o.sizeBytes)]].map(([t, v, id]) => (
                <div className="vy-section" key={t}><h3>{t}</h3><div style={{ fontSize: 24, fontWeight: 600 }} data-testid={id}>{v}</div></div>
              ))}
            </div>
            <h4>Statements over time</h4>
            <Bars points={data.timeline} label="Statements per bucket" />
            {!data.timeline.length && <p className="vy-muted" data-testid="po-empty">No statements measured in this window - nothing to chart.</p>}
            <p style={{ fontSize: 12 }}>DTU / CPU percentage is not offered: the SQL engine behind this database has no resource governor to measure it.</p>
          </>
        )}
      </CapabilityContainer>
    </>
  );
}

export function SqlAuditing({ a }) {
  const { data, loading, error, reload, win, setWin } = useInsights(a);
  const rows = data?.audit || [];
  return (
    <>
      <div className="vy-panel-title">{a.name} | Auditing</div>
      <CapabilityContainer id="azure.sql.auditing" title="Auditing" actions={<Toolbar win={win} setWin={setWin} reload={reload} />}>
        <ErrorBar error={error} />
        <p style={{ fontSize: 12 }}>Audit records of every statement executed through the SQL data plane (newest first, last 200). Storage / Log Analytics / Event Hub destinations are not offered.</p>
        {loading && !data ? <Loading /> : (
          <table className="vy-grid" aria-label="Audit records">
            <thead><tr><th>Event time</th><th>Action</th><th>Succeeded</th><th>Statement</th><th>Duration (ms)</th><th>Rows</th><th>Data sensitivity</th></tr></thead>
            <tbody>
              {rows.length ? rows.map((r, i) => (
                <tr key={i} data-testid="audit-row"><td>{new Date(r.eventTime * 1000).toLocaleString()}</td><td>{r.actionName}</td><td>{r.succeeded ? "Yes" : "No"}</td>
                  <td style={{ fontFamily: "monospace" }}>{r.statement}{r.errorMessage ? ` -- ${r.errorMessage}` : ""}</td><td>{r.durationMs}</td><td>{r.rowCount}</td>
                  <td>{(r.dataSensitivityInformation || []).map((d) => `${d.tableName}.${d.columnName} [${d.label || d.informationType}, ${d.rank}]`).join("; ") || "--"}{r.maskedColumns?.length ? ` (masked for ${r.serverPrincipalName}: ${r.maskedColumns.join(", ")})` : ""}</td></tr>
              )) : <tr><td colSpan={7} className="vy-muted" data-testid="audit-empty">No audit records yet.</td></tr>}
            </tbody>
          </table>
        )}
      </CapabilityContainer>
    </>
  );
}
