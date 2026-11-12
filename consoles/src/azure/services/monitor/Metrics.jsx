import { useEffect, useState } from "react";
import { Button, Checkbox, Input, Select, Tab, TabList } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listAllResources, listMetricDefinitions, getMetrics, metricFilter, listDashboards, getDashboard, putDashboard, deleteDashboard, LOCATIONS_OF, RESOURCE_TYPES } from "./api.js";
import { listResourceGroups } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading, ErrorBar } from "../../kit/common.jsx";

const COLORS = ["#0078d4", "#d13438", "#107c10", "#8764b8"];

function newRow(scope) {
  return { id: Math.random().toString(36).slice(2), scope, namespace: "Platform", metric: "", aggregation: "Total", defs: null, series: null, filters: [], splitBy: "", editor: "" };
}

/** A dependency-free inline chart (line or bar — real axis/points over real data, never a
 *  static image). The "Line chart" header button toggles between the two render modes. */
function MetricChart({ rows, chartType }) {
  const w = 640, h = 180, pad = 28;
  const lines = rows.flatMap((r) => (r.series || []).map((s) => ({ ...s, key: `${r.id}-${s.label}` })));
  const allPoints = lines.flatMap((l) => l.points);
  const max = Math.max(1, ...allPoints.map((p) => p.value));
  return (
    <svg width={w} height={h} role="img" aria-label={`Metric ${chartType} chart`}>
      <line x1={pad} y1={h - pad} x2={w - 4} y2={h - pad} stroke="#ccc" />
      <line x1={pad} y1={4} x2={pad} y2={h - pad} stroke="#ccc" />
      <text x={2} y={10} fontSize="10" fill="#666">{max}</text>
      <text x={2} y={h - pad} fontSize="10" fill="#666">0</text>
      {lines.map((row, ri) => {
        const pts = row.points;
        if (pts.length < 2) return null;
        const stepX = (w - pad - 8) / (pts.length - 1);
        const yFor = (p) => h - pad - (p.value / max) * (h - pad - 8);
        if (chartType === "bar") {
          const barW = Math.max(2, stepX / lines.length - 2);
          return pts.map((p, i) => (
            <rect key={`${row.key}-${i}`} x={pad + i * stepX + ri * barW} y={yFor(p)} width={barW} height={h - pad - yFor(p)} fill={COLORS[ri % COLORS.length]} />
          ));
        }
        const d = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${pad + i * stepX} ${yFor(p)}`).join(" ");
        return <path key={row.key} d={d} fill="none" stroke={COLORS[ri % COLORS.length]} strokeWidth="2" />;
      })}
    </svg>
  );
}

function MetricRow({ row, resources, onChange, onRemove, removable }) {
  useEffect(() => {
    if (!row.scope) return;
    listMetricDefinitions(row.scope).then((defs) => {
      onChange({ ...row, defs, metric: row.metric || defs[0]?.name.value || "", aggregation: defs[0]?.primaryAggregationType || "Total" });
    }).catch(() => onChange({ ...row, defs: [] }));
  }, [row.scope]);

  useEffect(() => {
    if (!row.scope || !row.metric) return;
    const flt = row.metric === "ActivityOperations" ? metricFilter(row.filters, row.splitBy) : "";
    getMetrics(row.scope, { metricnames: row.metric, aggregation: row.aggregation, interval: "PT1H", filter: flt }).then((r) => {
      const key = row.aggregation.toLowerCase();
      const series = (r.value?.[0]?.timeseries || []).map((t) => ({
        label: (t.metadatavalues || []).map((m) => m.value).join(" / ") || row.metric,
        points: (t.data || []).map((p) => ({ t: p.timeStamp, value: p[key] ?? 0 })),
      }));
      onChange({ ...row, series, error: "" });
    }).catch((e) => onChange({ ...row, series: [], error: String(e.message || e) }));
  }, [row.scope, row.metric, row.aggregation, JSON.stringify(row.filters), row.splitBy]);

  const resource = resources.find((r) => r.id === row.scope);
  return (
    <div className="vy-form-row-group" style={{ borderTop: "1px solid #eee", paddingTop: 8, marginTop: 8 }}>
      <FormRow label="Scope">
        <Select value={row.scope} onChange={(_, d) => onChange({ ...row, scope: d.value, defs: null, metric: "" })} aria-label="Scope">
          {resources.length === 0 ? <option value="">Select a scope</option> : null}
          {resources.map((r) => <option key={r.id} value={r.id}>{r.name} — {r.typeLabel}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Metric Namespace">
        <Select value="Platform" disabled aria-label="Metric Namespace"><option>Platform</option></Select>
      </FormRow>
      <FormRow label="Metric">
        <Select value={row.metric} onChange={(_, d) => onChange({ ...row, metric: d.value })} aria-label="Metric" disabled={!row.defs?.length}>
          {(row.defs || []).map((d) => <option key={d.name.value} value={d.name.value}>{d.name.localizedValue}</option>)}
        </Select>
      </FormRow>
      <FormRow label="Aggregation">
        <Select value={row.aggregation} onChange={(_, d) => onChange({ ...row, aggregation: d.value })} aria-label="Aggregation" disabled={!row.defs?.length}>
          {(row.defs?.[0]?.supportedAggregationTypes || ["Total"]).map((a) => <option key={a} value={a}>{a}</option>)}
        </Select>
      </FormRow>
      {resource && <p style={{ fontSize: 12, margin: "4px 0 0" }}>
        Showing the real count of {resource.name}'s own Activity log operations, bucketed hourly.</p>}
      {row.error && <ErrorBar error={row.error} title="Metric query failed" />}
      {row.metric === "ActivityOperations" && <CapabilityContainer id="azure.monitor.metric_dimensions" title="Filters and splitting"><FilterSplit row={row} onChange={onChange} /></CapabilityContainer>}
      {removable && <Button appearance="subtle" onClick={onRemove}>Remove metric</Button>}
    </div>
  );
}

const DIMENSIONS = ["OperationName", "Status"];

/** Add filter / Apply splitting for a metric's real dimensions (the Activity log columns being counted). The filter editor's
 *  value list is whatever values the scope really has - discovered by splitting the metric by that dimension. */
function FilterSplit({ row, onChange }) {
  const [draft, setDraft] = useState({ dimension: "OperationName", operator: "eq", values: [] });
  const [avail, setAvail] = useState([]);
  useEffect(() => {
    if (row.editor !== "filter") return;
    getMetrics(row.scope, { metricnames: row.metric, aggregation: row.aggregation, filter: `${draft.dimension} eq '*'` })
      .then((r) => setAvail([...new Set((r.value?.[0]?.timeseries || []).map((t) => t.metadatavalues?.[0]?.value).filter(Boolean))].sort()))
      .catch(() => setAvail([]));
  }, [row.editor, row.scope, draft.dimension]);
  const toggle = (v) => setDraft({ ...draft, values: draft.values.includes(v) ? draft.values.filter((x) => x !== v) : [...draft.values, v] });
  return (
    <div data-testid="metric-filter-split" style={{ marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Button appearance="subtle" onClick={() => onChange({ ...row, editor: row.editor === "filter" ? "" : "filter" })}>Add filter</Button>
        <Button appearance="subtle" onClick={() => onChange({ ...row, editor: row.editor === "split" ? "" : "split" })}>Apply splitting</Button>
        {row.filters.map((f, i) => (
          <span key={i} className="vy-pill vy-pill-static" data-testid="metric-filter-pill">
            {f.dimension} {f.operator === "ne" ? "!=" : "="} {f.values.join(", ")}{" "}
            <a href="#/monitor/metrics" aria-label={`Remove filter ${f.dimension}`} onClick={(e) => { e.preventDefault(); onChange({ ...row, filters: row.filters.filter((_, j) => j !== i) }); }}>x</a>
          </span>
        ))}
        {row.splitBy && <span className="vy-pill vy-pill-static" data-testid="metric-split-pill">Split by {row.splitBy}</span>}
      </div>
      {row.editor === "filter" && (
        <div className="vy-form-row-group" style={{ border: "1px solid #ddd", padding: 8, marginTop: 6 }}>
          <FormRow label="Property">
            <Select value={draft.dimension} onChange={(_, d) => setDraft({ dimension: d.value, operator: draft.operator, values: [] })} aria-label="Filter property">
              {DIMENSIONS.map((d) => <option key={d}>{d}</option>)}
            </Select>
          </FormRow>
          <FormRow label="Operator">
            <Select value={draft.operator} onChange={(_, d) => setDraft({ ...draft, operator: d.value })} aria-label="Filter operator">
              <option value="eq">=</option><option value="ne">!=</option>
            </Select>
          </FormRow>
          <FormRow label="Values">
            {avail.length === 0 ? <span className="vy-muted">No values yet - this scope has no recorded operations.</span>
              : avail.map((v) => <div key={v}><Checkbox label={v} checked={draft.values.includes(v)} onChange={() => toggle(v)} /></div>)}
          </FormRow>
          <Button appearance="primary" disabled={!draft.values.length}
            onClick={() => { onChange({ ...row, editor: "", filters: [...row.filters.filter((f) => f.dimension !== draft.dimension), draft] }); setDraft({ ...draft, values: [] }); }}>Apply filter</Button>
        </div>
      )}
      {row.editor === "split" && (
        <div className="vy-form-row-group" style={{ border: "1px solid #ddd", padding: 8, marginTop: 6 }}>
          <FormRow label="Values">
            <Select value={row.splitBy} onChange={(_, d) => onChange({ ...row, splitBy: d.value, editor: "" })} aria-label="Split by">
              <option value="">(none)</option>
              {DIMENSIONS.map((d) => <option key={d}>{d}</option>)}
            </Select>
          </FormRow>
        </div>
      )}
    </div>
  );
}

/** Save to dashboard: writes (or updates) a real Microsoft.Portal/dashboards resource carrying this chart as a metrics part;
 *  the pinned charts it holds are listed (and removable) underneath. */
function SaveToDashboard({ rows }) {
  const [open, setOpen] = useState(false);
  const [rgs, setRgs] = useState([]);
  const [rg, setRg] = useState("");
  const [name, setName] = useState("metrics-dashboard");
  const [msg, setMsg] = useState("");
  const [dashboards, setDashboards] = useState([]);
  const refresh = () => listDashboards().then(setDashboards).catch(() => setDashboards([]));
  useEffect(() => { listResourceGroups().then((r) => { setRgs(r); if (r[0]) setRg((v) => v || r[0].name); }).catch(() => {}); refresh(); }, []);
  const save = async () => {
    setMsg("");
    try {
      let cur = { properties: { lenses: [], metadata: {} } };
      try { cur = await getDashboard(rg, name); } catch { /* new dashboard */ }
      const lenses = JSON.parse(JSON.stringify(cur.properties?.lenses?.length ? cur.properties.lenses : [{ order: 0, parts: [] }]));
      const first = lenses[0];
      first.parts = first.parts || [];
      for (const r of rows) {
        first.parts.push({ position: { x: (first.parts.length % 3) * 4, y: Math.floor(first.parts.length / 3) * 4, colSpan: 4, rowSpan: 3 },
          metadata: { type: "Extension/HubsExtension/PartType/MonitorChartPart",
            inputs: [{ name: "options", value: { chart: { title: `${r.metric} (${r.aggregation})`, metrics: [{ resourceMetadata: { id: r.scope }, name: r.metric, aggregationType: r.aggregation,
              filterCollection: r.filters, splitBy: r.splitBy }] } } }] } });
      }
      await putDashboard(rg, name, { location: cur.location || "global", tags: cur.tags, properties: { lenses, metadata: cur.properties?.metadata || {} } });
      setMsg(`Saved ${rows.length} chart${rows.length === 1 ? "" : "s"} to dashboard ${name}.`);
      refresh();
    } catch (e) { setMsg(`Save failed: ${e.message || e}`); }
  };
  return (
    <div data-testid="metric-dashboards" style={{ marginTop: 12 }}>
      <Button appearance="subtle" onClick={() => setOpen(!open)}>Save to dashboard</Button>
      {open && (
        <div className="vy-form-row-group" style={{ border: "1px solid #ddd", padding: 8, marginTop: 6 }}>
          <FormRow label="Resource group">
            <Select value={rg} onChange={(_, d) => setRg(d.value)} aria-label="Dashboard resource group">{rgs.map((g) => <option key={g.name}>{g.name}</option>)}</Select>
          </FormRow>
          <FormRow label="Dashboard name"><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Dashboard name" /></FormRow>
          <Button appearance="primary" disabled={!rg || !name} onClick={save}>Pin to dashboard</Button>
        </div>
      )}
      {msg && <p role="status" data-testid="metric-dashboard-msg">{msg}</p>}
      {dashboards.length > 0 && (
        <ul data-testid="metric-dashboard-list" style={{ marginTop: 8 }}>
          {dashboards.map((d) => (
            <li key={d.id}>{d.name} ({d.resourceGroup}) - {(d.properties?.lenses || []).reduce((n, l) => n + (l.parts || []).length, 0)} pinned chart(s){" "}
              <Button size="small" appearance="subtle" onClick={() => deleteDashboard(d.resourceGroup, d.name).then(refresh)}>Delete</Button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FormRow({ label, children }) {
  return <div className="vy-form-row"><label>{label}</label><div>{children}</div></div>;
}

export default function Metrics() {
  const [tab, setTab] = useState("browse");
  const [resources, setResources] = useState(null);
  const [resourceType, setResourceType] = useState("All resource types");
  const [locationFilter, setLocationFilter] = useState("All locations");
  const [applied, setApplied] = useState({ resourceType: "All resource types", locationFilter: "All locations" });
  const [rows, setRows] = useState([]);
  const [chartType, setChartType] = useState("line");

  useEffect(() => { listAllResources().then((r) => { setResources(r); if (r[0]) setRows([newRow(r[0].id)]); }).catch(() => setResources([])); }, []);

  const locations = resources ? LOCATIONS_OF(resources) : [];
  const filtered = (resources || []).filter((r) =>
    (applied.resourceType === "All resource types" || `${r.resourceType}` === applied.resourceType) &&
    (applied.locationFilter === "All locations" || r.location === applied.locationFilter));

  const updateRow = (i, next) => setRows(rows.map((r, j) => (j === i ? next : r)));

  return (
    <MonitorShell active="metrics">
      <div className="vy-cmdbar" role="toolbar" aria-label="Command bar" style={{ marginBottom: 8 }}>
        <Button appearance="subtle" disabled>New chart</Button>
        <Button appearance="subtle" disabled>Share</Button>
        <span className="vy-pill vy-pill-static">Local Time: Last 24 hours (Automatic)</span>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Metrics">
        <Tab value="browse">Browse</Tab>
        <Tab value="recent">Recent</Tab>
      </TabList>
      {tab === "recent" ? (
        <p style={{ marginTop: 12 }}>No recently viewed charts yet.</p>
      ) : (
        <>
          <CapabilityContainer id="azure.monitor.metrics_scope" title="Select a scope">
            <FormRow label="Resource types">
              <Select value={resourceType} onChange={(_, d) => setResourceType(d.value)} aria-label="Resource types">
                <option>All resource types</option>
                {RESOURCE_TYPES.map((rt) => <option key={rt.type} value={`${rt.provider}/${rt.type}`}>{rt.label}</option>)}
              </Select>
            </FormRow>
            <FormRow label="Locations">
              <Select value={locationFilter} onChange={(_, d) => setLocationFilter(d.value)} aria-label="Locations">
                <option>All locations</option>
                {locations.map((l) => <option key={l} value={l}>{l}</option>)}
              </Select>
            </FormRow>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <Button appearance="primary" onClick={() => setApplied({ resourceType, locationFilter })}>Apply</Button>
              <Button onClick={() => { setResourceType("All resource types"); setLocationFilter("All locations"); setApplied({ resourceType: "All resource types", locationFilter: "All locations" }); }}>Cancel</Button>
            </div>
            {resources === null ? <Loading /> : (
              <p style={{ marginTop: 8 }}>{filtered.length} resource{filtered.length === 1 ? "" : "s"} in scope: {filtered.map((r) => r.name).join(", ") || "none"}.</p>
            )}
          </CapabilityContainer>

          <CapabilityContainer id="azure.monitor.metrics_charts" title="Chart Title" actions={
            <div className="vy-cmdbar" role="toolbar" aria-label="Chart actions">
              <Button appearance="subtle" as="a" href="#/monitor/logs">Drill into Logs</Button>
              <Button appearance="subtle" as="a" href="#/monitor/createalertrule">New alert rule</Button>
            </div>
          }>
            {resources === null ? <Loading /> : resources.length === 0 ? (
              <p>No resources yet — create one, then come back to chart its real activity.</p>
            ) : (
              <>
                {rows.map((row, i) => (
                  <MetricRow key={row.id} row={row} resources={filtered.length ? filtered : resources}
                    onChange={(next) => updateRow(i, next)} onRemove={() => setRows(rows.filter((_, j) => j !== i))} removable={rows.length > 1} />
                ))}
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <Button onClick={() => setRows([...rows, newRow((filtered[0] || resources[0]).id)])}>Add metric</Button>
                  <Button onClick={() => setChartType(chartType === "line" ? "bar" : "line")}>{chartType === "line" ? "Line chart" : "Bar chart"}</Button>
                </div>
                <div style={{ marginTop: 12 }}><MetricChart rows={rows} chartType={chartType} /></div>
                <CapabilityContainer id="azure.monitor.metrics_dashboards" title="Dashboards"><SaveToDashboard rows={rows} /></CapabilityContainer>
              </>
            )}
          </CapabilityContainer>
        </>
      )}
    </MonitorShell>
  );
}
