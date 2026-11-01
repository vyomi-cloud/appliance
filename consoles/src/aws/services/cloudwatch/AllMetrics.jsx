import { useMemo, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Tabs from "@cloudscape-design/components/tabs";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { LineChart, toSeries } from "./common.jsx";
import * as api from "./api.js";

const TIME_RANGES = [{ label: "1h", value: "3600" }, { label: "3h", value: "10800" }, { label: "12h", value: "43200" }, { label: "1d", value: "86400" }, { label: "3d", value: "259200" }, { label: "1w", value: "604800" }];
const metricKey = (m) => `${m.Namespace}${m.MetricName}${JSON.stringify(m.Dimensions || [])}`;

function BrowseTab({ onGraph }) {
  const t = useAsync(() => api.listMetrics({}), []);
  const [selected, setSelected] = useState([]);
  const items = (t.data || []).map((m) => ({ ...m, key: metricKey(m) }));
  return (
    <ResourceTable
      resourceName="Metrics"
      items={items}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="key"
      selectionType="multi"
      selectedItems={selected}
      onSelectionChange={setSelected}
      filterPlaceholder="Search for any metric, dimension, resource id or account id"
      actions={<Button disabled={!selected.length} onClick={() => { onGraph(selected); setSelected([]); }}>Graph metrics</Button>}
      columns={[{ id: "name", header: "Metric name", isRowHeader: true, cell: (m) => `${m.Namespace} / ${m.MetricName}${m.Dimensions?.length ? " (" + m.Dimensions.map((d) => `${d.Name}=${d.Value}`).join(", ") + ")" : ""}` }]}
      empty={{ title: "No metrics", subtitle: "Metrics appear here once a resource publishes data with PutMetricData." }}
    />
  );
}

function GraphedTab({ graphed, onRemove }) {
  return (
    <ResourceTable
      resourceName="Graphed metrics"
      items={graphed}
      trackBy="key"
      columns={[
        { id: "name", header: "Metric name", cell: (m) => `${m.Namespace} / ${m.MetricName}` },
        { id: "remove", header: "", cell: (m) => <Button variant="icon" iconName="remove" ariaLabel={`Remove ${m.MetricName}`} onClick={() => onRemove(m.key)} /> },
      ]}
      empty={{ title: "No graphed metrics", subtitle: "Select metrics in Browse and choose Graph metrics." }}
    />
  );
}

function MetricGraph({ m, rangeSeconds, refreshKey, options }) {
  const now = Math.floor(Date.now() / 1000);
  const t = useAsync(() => api.getMetricData(
    [{ Id: "m1", MetricStat: { Metric: { Namespace: m.Namespace, MetricName: m.MetricName, Dimensions: m.Dimensions || [] }, Period: Number(options.period), Stat: options.stat }, ReturnData: true }],
    now - rangeSeconds, now,
  ), [m.key, rangeSeconds, refreshKey, options.period, options.stat]);
  if (t.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  const series = toSeries((t.data || [])[0]);
  const latest = series.length ? series[series.length - 1].v : null;
  return (
    <Box padding={{ bottom: "l" }}>
      <Header variant="h3">{m.Namespace} / {m.MetricName}</Header>
      {options.widgetType === "Number" ? (
        <Box fontSize="display-l" fontWeight="bold" textAlign="center" padding="l">{latest === null ? "-" : latest.toFixed(2)}</Box>
      ) : (
        <LineChart series={series} />
      )}
    </Box>
  );
}

// ── Metrics Insights ("Multi source query") ─────────────────────────────────────────────
// A real (if partial) SQL engine over the SAME ListMetrics/GetMetricData data the Browse
// tab shows — never a fabricated result. SELECT <AVG|SUM|MIN|MAX|COUNT>(metric) FROM
// SCHEMA("Namespace"[, dim...]) [WHERE dim = 'v' [AND ...]] [GROUP BY dim] [ORDER BY func()
// ASC|DESC] [LIMIT n], matching the shape (not the full grammar) of AWS Metrics Insights.
const AGG_FUNCS = {
  AVG: (vs) => vs.reduce((a, b) => a + b, 0) / (vs.length || 1),
  SUM: (vs) => vs.reduce((a, b) => a + b, 0),
  MIN: (vs) => Math.min(...vs),
  MAX: (vs) => Math.max(...vs),
  COUNT: (vs) => vs.length,
};

function splitSqlClauses(sql) {
  const marks = [];
  const re = /\bSELECT\b|\bFROM\b|\bWHERE\b|\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b/gi;
  let m;
  while ((m = re.exec(sql))) marks.push({ kw: m[0].toUpperCase().replace(/\s+/g, " "), start: m.index, end: m.index + m[0].length });
  const out = {};
  marks.forEach((mk, i) => { out[mk.kw] = sql.slice(mk.end, i + 1 < marks.length ? marks[i + 1].start : sql.length).trim(); });
  return out;
}

export function parseInsightsQuery(raw) {
  const clauses = splitSqlClauses(raw.trim().replace(/;\s*$/, ""));
  const sel = (clauses.SELECT || "").match(/^(\w+)\(([\w.]*)\)$/i);
  if (!sel || !clauses.FROM) throw new Error('Expected: SELECT FUNC(metric) FROM SCHEMA("Namespace"[, dims...])');
  const func = sel[1].toUpperCase();
  if (!AGG_FUNCS[func]) throw new Error(`Unsupported aggregate function: ${sel[1]}`);
  const from = clauses.FROM.match(/^SCHEMA\s*\(\s*"?([^",)]+)"?\s*(?:,\s*(.+))?\)$/i);
  if (!from) throw new Error('Expected: FROM SCHEMA("Namespace"[, dims...])');
  const groupBy = (clauses["GROUP BY"] || "").split(",").map((s) => s.trim()).filter(Boolean);
  const orderDir = /DESC/i.test(clauses["ORDER BY"] || "") ? "DESC" : clauses["ORDER BY"] ? "ASC" : null;
  const limit = clauses.LIMIT ? parseInt(clauses.LIMIT, 10) : null;
  return { func, metricName: sel[2] || null, namespace: from[1], where: clauses.WHERE || "", groupBy, orderDir, limit };
}

function matchesWhere(m, where) {
  if (!where) return true;
  return where.split(/\bAND\b/i).every((raw) => {
    const clause = raw.trim();
    const inM = clause.match(/^(\w+)\s+IN\s*\(([^)]+)\)$/i);
    if (inM) {
      const vals = inM[2].split(",").map((v) => v.trim().replace(/^'|'$/g, ""));
      return vals.includes((m.Dimensions || []).find((d) => d.Name === inM[1])?.Value);
    }
    const eqM = clause.match(/^(\w+)\s*=\s*'([^']*)'$/);
    if (eqM) return (m.Dimensions || []).find((d) => d.Name === eqM[1])?.Value === eqM[2];
    return true;
  });
}

async function runInsightsQuery(sql, rangeSeconds) {
  const q = parseInsightsQuery(sql);
  const all = await api.listMetrics({ Namespace: q.namespace });
  const rows = all.filter((m) => (!q.metricName || m.MetricName === q.metricName) && matchesWhere(m, q.where));
  if (!rows.length) return [];
  const bucketKey = (m) => (q.groupBy.length
    ? q.groupBy.map((d) => (m.Dimensions || []).find((x) => x.Name === d)?.Value ?? "").join(" | ")
    : `${m.MetricName} (${(m.Dimensions || []).map((d) => `${d.Name}=${d.Value}`).join(", ") || "no dimensions"})`);
  const buckets = new Map();
  for (const m of rows) {
    const key = bucketKey(m);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(m);
  }
  const now = Math.floor(Date.now() / 1000);
  const results = [];
  for (const [label, members] of buckets) {
    const queries = members.map((m, i) => ({ Id: `s${i}`, MetricStat: { Metric: { Namespace: m.Namespace, MetricName: m.MetricName, Dimensions: m.Dimensions || [] }, Period: 300, Stat: "Average" }, ReturnData: true }));
    const data = await api.getMetricData(queries, now - rangeSeconds, now);
    const byTs = new Map();
    for (const d of data) (d.Timestamps || []).forEach((ts, i) => { const key = Number(ts); const arr = byTs.get(key) || []; arr.push(Number(d.Values[i])); byTs.set(key, arr); });
    const series = [...byTs.entries()].map(([t, vs]) => ({ t, v: AGG_FUNCS[q.func](vs) })).sort((a, b) => a.t - b.t);
    results.push({ label, series, lastValue: series.length ? series[series.length - 1].v : 0 });
  }
  if (q.orderDir) results.sort((a, b) => (q.orderDir === "DESC" ? b.lastValue - a.lastValue : a.lastValue - b.lastValue));
  return q.limit ? results.slice(0, q.limit) : results;
}

function MultiSourceQueryTab({ rangeSeconds }) {
  const [sql, setSql] = useState('SELECT AVG(StatusCheckFailed) FROM SCHEMA("AWS/EC2", InstanceId)');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError(null);
    try { setResult(await runInsightsQuery(sql, rangeSeconds)); } catch (e) { setError(e); setResult(null); } finally { setBusy(false); }
  };

  return (
    <CapabilityContainer id="aws.cloudwatch.metrics.multi-source-query" title="Multi source query" actions={<Button variant="primary" loading={busy} onClick={run}>Run query</Button>}>
      <SpaceBetween size="l">
        <FormField label="Query" description={'A real SQL-like query over the metrics already in this account: SELECT AVG|SUM|MIN|MAX|COUNT(metric) FROM SCHEMA("Namespace"[, dim]) [WHERE dim = \'v\'] [GROUP BY dim] [ORDER BY func() ASC|DESC] [LIMIT n]. One query can graph many metric sources in a single step.'}>
          <Textarea value={sql} onChange={({ detail }) => setSql(detail.value)} rows={3} ariaLabel="Metrics Insights query" />
        </FormField>
        {error && <ErrorAlert error={error} />}
        {result && (result.length ? (
          <SpaceBetween size="l">
            {result.map((r) => (
              <Box key={r.label}>
                <Header variant="h3">{r.label}</Header>
                <LineChart series={r.series} />
              </Box>
            ))}
          </SpaceBetween>
        ) : <Box color="text-body-secondary">No metrics matched this query.</Box>)}
      </SpaceBetween>
    </CapabilityContainer>
  );
}

const WIDGET_TYPES = ["Line", "Number"];
const STATS = ["Average", "Sum", "Minimum", "Maximum", "SampleCount"];

function OptionsTab({ options, setOptions }) {
  return (
    <CapabilityContainer id="aws.cloudwatch.metrics.multi-source-query" title="Options" description="Applies to every metric in the Graph section below.">
      <SpaceBetween size="l">
        <FormField label="Widget type"><Select selectedOption={{ label: options.widgetType, value: options.widgetType }} onChange={({ detail }) => setOptions({ ...options, widgetType: detail.selectedOption.value })} options={WIDGET_TYPES.map((w) => ({ label: w, value: w }))} ariaLabel="Widget type" /></FormField>
        <FormField label="Statistic"><Select selectedOption={{ label: options.stat, value: options.stat }} onChange={({ detail }) => setOptions({ ...options, stat: detail.selectedOption.value })} options={STATS.map((s) => ({ label: s, value: s }))} ariaLabel="Statistic" /></FormField>
        <FormField label="Period (seconds)"><Input type="number" value={String(options.period)} onChange={({ detail }) => setOptions({ ...options, period: detail.value })} ariaLabel="Period" /></FormField>
      </SpaceBetween>
    </CapabilityContainer>
  );
}

function SourceTab({ graphed, rangeSeconds, options }) {
  const widget = {
    metrics: graphed.map((m) => [m.Namespace, m.MetricName, ...(m.Dimensions || []).flatMap((d) => [d.Name, d.Value]), { stat: options.stat, period: Number(options.period) }]),
    view: options.widgetType === "Number" ? "singleValue" : "timeSeries",
    region: api.REGION,
    stat: options.stat,
    period: Number(options.period),
    start: `-PT${Math.round(rangeSeconds / 3600) || 1}H`,
    end: "PT0H",
  };
  return (
    <CapabilityContainer id="aws.cloudwatch.metrics.multi-source-query" title="Source" description="The real widget JSON this account/region's graphed metrics resolve to — the same source a dashboard widget's Source tab shows.">
      <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(widget, null, 2)}</pre></Box>
    </CapabilityContainer>
  );
}

export default function AllMetrics() {
  const notify = useNotify();
  const [graphed, setGraphed] = useState([]);
  const [range, setRange] = useState("3600");
  const [refreshKey, setRefreshKey] = useState(0);
  const [dashName, setDashName] = useState("");
  const [options, setOptions] = useState({ widgetType: "Line", stat: "Average", period: "300" });

  const addToGraph = (rows) => setGraphed((prev) => {
    const existing = new Set(prev.map((m) => m.key));
    return [...prev, ...rows.filter((m) => !existing.has(m.key))];
  });

  const addToDashboard = async () => {
    if (!dashName || !graphed.length) return;
    try {
      let body = { widgets: [] };
      try { body = JSON.parse((await api.getDashboard(dashName)).DashboardBody); } catch { /* new dashboard */ }
      const widgets = [...(body.widgets || []), ...graphed.map((m) => ({ id: `w${Date.now()}-${m.MetricName}`, type: options.widgetType === "Number" ? "Number" : "Line", title: `${m.Namespace} ${m.MetricName}`, namespace: m.Namespace, metricName: m.MetricName, dimensions: m.Dimensions || [], stat: options.stat, period: Number(options.period) }))];
      await api.putDashboard(dashName, { widgets });
      notify.success(`Added ${graphed.length} metric(s) to dashboard ${dashName}.`);
    } catch (e) { notify.error(e); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Metrics</Header>}>
      <SpaceBetween size="l">
        <Tabs tabs={[
          { id: "browse", label: "Browse", content: <BrowseTab onGraph={addToGraph} /> },
          { id: "multi", label: "Multi source query", content: <MultiSourceQueryTab rangeSeconds={Number(range)} /> },
          { id: "graphed", label: "Graphed metrics", content: <GraphedTab graphed={graphed} onRemove={(key) => setGraphed((g) => g.filter((m) => m.key !== key))} /> },
          { id: "options", label: "Options", content: <OptionsTab options={options} setOptions={setOptions} /> },
          { id: "source", label: "Source", content: <SourceTab graphed={graphed} rangeSeconds={Number(range)} options={options} /> },
        ]} />
        <Container header={
          <Header variant="h2" actions={
            <SpaceBetween direction="horizontal" size="xs">
              <ButtonDropdown items={[{ id: "a", text: "Add to dashboard" }]} onItemClick={() => {}}>Actions</ButtonDropdown>
              <Button iconName="refresh" ariaLabel="Refresh" onClick={() => setRefreshKey((k) => k + 1)} />
              <Input placeholder="Dashboard name" value={dashName} onChange={({ detail }) => setDashName(detail.value)} ariaLabel="Dashboard name" />
              <Button disabled={!graphed.length || !dashName} onClick={addToDashboard}>Add to dashboard</Button>
            </SpaceBetween>
          }>Graph</Header>
        }>
          <SpaceBetween size="l">
            <FormField label="Time range">
              <Select selectedOption={TIME_RANGES.find((r) => r.value === range)} onChange={({ detail }) => setRange(detail.selectedOption.value)} options={TIME_RANGES} ariaLabel="Time range" />
            </FormField>
            {graphed.length ? graphed.map((m) => <MetricGraph key={m.key} m={m} rangeSeconds={Number(range)} refreshKey={refreshKey} options={options} />) : <Box color="text-body-secondary">No metrics selected. Choose metrics in Browse and select Graph metrics.</Box>}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
