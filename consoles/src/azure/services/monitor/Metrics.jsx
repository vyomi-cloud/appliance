import { useEffect, useState } from "react";
import { Button, Select, Tab, TabList } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listAllResources, listMetricDefinitions, getMetrics, LOCATIONS_OF, RESOURCE_TYPES } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading, NotSimulatedContainer } from "../../kit/common.jsx";

const COLORS = ["#0078d4", "#d13438", "#107c10", "#8764b8"];

function newRow(scope) {
  return { id: Math.random().toString(36).slice(2), scope, namespace: "Platform", metric: "", aggregation: "Total", defs: null, series: null };
}

/** A dependency-free inline chart (line or bar — real axis/points over real data, never a
 *  static image). The "Line chart" header button toggles between the two render modes. */
function MetricChart({ rows, chartType }) {
  const w = 640, h = 180, pad = 28;
  const allPoints = rows.flatMap((r) => (r.series || []));
  const max = Math.max(1, ...allPoints.map((p) => p.value));
  return (
    <svg width={w} height={h} role="img" aria-label={`Metric ${chartType} chart`}>
      <line x1={pad} y1={h - pad} x2={w - 4} y2={h - pad} stroke="#ccc" />
      <line x1={pad} y1={4} x2={pad} y2={h - pad} stroke="#ccc" />
      <text x={2} y={10} fontSize="10" fill="#666">{max}</text>
      <text x={2} y={h - pad} fontSize="10" fill="#666">0</text>
      {rows.map((row, ri) => {
        const pts = row.series || [];
        if (pts.length < 2) return null;
        const stepX = (w - pad - 8) / (pts.length - 1);
        const yFor = (p) => h - pad - (p.value / max) * (h - pad - 8);
        if (chartType === "bar") {
          const barW = Math.max(2, stepX / rows.length - 2);
          return pts.map((p, i) => (
            <rect key={`${row.id}-${i}`} x={pad + i * stepX + ri * barW} y={yFor(p)} width={barW} height={h - pad - yFor(p)} fill={COLORS[ri % COLORS.length]} />
          ));
        }
        const d = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${pad + i * stepX} ${yFor(p)}`).join(" ");
        return <path key={row.id} d={d} fill="none" stroke={COLORS[ri % COLORS.length]} strokeWidth="2" />;
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
    getMetrics(row.scope, { metricnames: row.metric, aggregation: row.aggregation, interval: "PT1H" }).then((r) => {
      const ts = r.value?.[0]?.timeseries?.[0]?.data || [];
      const key = row.aggregation.toLowerCase();
      onChange({ ...row, series: ts.map((p) => ({ t: p.timeStamp, value: p[key] ?? 0 })) });
    }).catch(() => onChange({ ...row, series: [] }));
  }, [row.scope, row.metric, row.aggregation]);

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
      {removable && <Button appearance="subtle" onClick={onRemove}>Remove metric</Button>}
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
                <NotSimulatedContainer title="Not simulated in Vyomi" note="Add filter, Apply splitting, Save to dashboard — Vyomi has no metric dimensions and no custom-dashboard resource to save a chart into." />
              </>
            )}
          </CapabilityContainer>
        </>
      )}
    </MonitorShell>
  );
}
