/* Azure Managed Grafana: the Prometheus data source Vyomi serves (/_obs/prom, core/observability_core.py) and a built-in dashboard
 * whose panels are PromQL range queries against it - exactly what a Grafana Prometheus data source sends. Series are the requests
 * Vyomi measured (vyomi_requests_total, vyomi_request_duration_ms_*) plus anything posted to /_obs/v1/metrics (OTLP).
 * No traffic -> empty panels. There is no Grafana server; point a real Grafana at the URL below to use its UI. */
import { useEffect, useMemo, useState } from "react";
import { Button, Input } from "@fluentui/react-components";
import { WIRE_BASE } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";

const PROM = `${WIRE_BASE}/_obs/prom`;
const COLORS = ["#0078d4", "#d13438", "#107c10", "#8764b8", "#ca5010", "#038387"];
export const dataSourceUrl = () => `${location.origin}${WIRE_BASE.replace(/\/_wire$/, "")}/_obs/prom`;

async function prom(path, params) {
  const r = await fetch(`${PROM}/api/v1/${path}?${new URLSearchParams(params)}`);
  const j = await r.json();
  if (j.status !== "success") throw new Error(j.error || `HTTP ${r.status}`);
  return j.data;
}
export const PANELS = [
  { id: "rate", title: "Request rate by service (req/s)", q: "sum by (service) (rate(vyomi_requests_total[1m]))" },
  { id: "err", title: "5xx error rate (req/s)", q: 'sum(rate(vyomi_requests_total{code="5xx"}[1m]))' },
  { id: "p95", title: "p95 request latency (ms)", q: "histogram_quantile(0.95, sum by (le) (rate(vyomi_request_duration_ms_bucket[1m])))" },
  { id: "total", title: "Total requests by service", q: "sum by (service) (vyomi_requests_total)" },
];

function Chart({ series, id }) {
  const w = 460, h = 150, pad = 28;
  const pts = series.flatMap((s) => s.values.map(([t, v]) => [t, Number(v)])).filter(([, v]) => Number.isFinite(v));
  if (!pts.length) return <p className="vy-muted" data-testid={`graf-${id}-empty`}>No data</p>;
  const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0]), t0 + 1), mx = Math.max(1e-9, ...pts.map((p) => p[1]));
  const x = (t) => pad + ((t - t0) / (t1 - t0)) * (w - pad - 6), y = (v) => h - pad - (v / mx) * (h - pad - 8);
  return (
    <svg width={w} height={h} role="img" aria-label={`${id} chart`} data-testid={`graf-${id}-chart`} style={{ maxWidth: "100%" }}>
      <line x1={pad} y1={h - pad} x2={w - 4} y2={h - pad} stroke="#ccc" /><text x={2} y={12} fontSize="10" fill="#666">{Math.round(mx * 1000) / 1000}</text>
      {series.map((s, i) => {
        const v = s.values.map(([t, val]) => [t, Number(val)]).filter(([, val]) => Number.isFinite(val));
        const d = v.map(([t, val], k) => `${k ? "L" : "M"} ${x(t)} ${y(val)}`).join(" ");
        return v.length === 1 ? <circle key={i} cx={x(v[0][0])} cy={y(v[0][1])} r={3} fill={COLORS[i % 6]} /> : <path key={i} d={d} fill="none" stroke={COLORS[i % 6]} strokeWidth="2" />;
      })}
    </svg>
  );
}

function Panel({ p, tick }) {
  const r = useAsync(() => { const end = Math.floor(Date.now() / 1000); return prom("query_range", { query: p.q, start: end - 900, end, step: 15 }); }, [p.q, tick]);
  const series = r.data?.result || [];
  return (
    <section className="vy-section" data-testid={`graf-${p.id}`}>
      <h3>{p.title}</h3>
      {r.error ? <p className="vy-muted">Query failed: {String(r.error.message || r.error)}</p> : r.loading && !r.data ? <p>Loading...</p> : <Chart series={series} id={p.id} />}
      <div style={{ fontSize: 11, opacity: 0.7 }}>{series.map((s, i) => <span key={i} style={{ color: COLORS[i % 6], marginRight: 8 }}>{Object.values(s.metric).join("/") || p.id}</span>)}</div>
      <code style={{ fontSize: 11 }}>{p.q}</code>
    </section>
  );
}

export default function GrafanaPanel({ workspace }) {
  const [tick, setTick] = useState(0);
  const [status, setStatus] = useState("");
  const [expr, setExpr] = useState("vyomi_requests_total");
  const [res, setRes] = useState(null);
  useEffect(() => { const id = setInterval(() => setTick((n) => n + 1), 10000); return () => clearInterval(id); }, []);
  const test = async () => { try { const d = await prom("status/buildinfo", {}); setStatus(`Data source is working (Prometheus-compatible, version ${d.version}).`); } catch (e) { setStatus(`Data source test failed: ${e.message}`); } };
  const run = async () => { try { setRes(await prom("query", { query: expr })); } catch (e) { setRes({ error: e.message }); } };
  const url = useMemo(dataSourceUrl, []);
  return (
    <section className="vy-form-section" aria-label="Grafana workspace dashboard" data-testid="grafana-panel">
      <h3>{workspace ? `${workspace.name} - ` : ""}Prometheus data source and built-in dashboard</h3>
      <table className="vy-grid" aria-label="Data source">
        <tbody>
          <tr><td>Type</td><td>Prometheus</td></tr>
          <tr><td>URL</td><td><code data-testid="graf-url">{url}</code></td></tr>
          <tr><td>Access</td><td>Server (default); no authentication</td></tr>
        </tbody>
      </table>
      <div className="vy-cmdbar"><Button onClick={test}>Save &amp; test</Button><Button onClick={() => setTick((n) => n + 1)}>Refresh</Button></div>
      {status && <p data-testid="graf-status">{status}</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(440px, 1fr))", gap: 12 }}>{PANELS.map((p) => <Panel key={p.id} p={p} tick={tick} />)}</div>
      <h4>Explore</h4>
      <div className="vy-cmdbar"><Input value={expr} onChange={(_, d) => setExpr(d.value)} aria-label="PromQL expression" style={{ minWidth: 420 }} /><Button appearance="primary" onClick={run}>Run query</Button></div>
      {res && (res.error ? <p data-testid="graf-explore-error">{res.error}</p> : (
        <table className="vy-grid" aria-label="Query result" data-testid="graf-explore">
          <thead><tr><th>Series</th><th>Value</th></tr></thead>
          <tbody>{(res.result || []).length ? res.result.map((s, i) => <tr key={i}><td><code>{JSON.stringify(s.metric)}</code></td><td>{s.value?.[1]}</td></tr>) : <tr><td colSpan={2} className="vy-muted">Empty result</td></tr>}</tbody>
        </table>
      ))}
    </section>
  );
}
