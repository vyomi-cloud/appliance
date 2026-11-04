/* The Monitoring-group panels every Azure resource blade shows (Alerts, Metrics, Logs, Insights,
 * Workbooks), scoped to ONE resource id. Everything here is real ARM:
 *   - metrics: Microsoft.Insights/metricDefinitions + metrics on the resource (core/azure_monitor_core.py) -
 *     "ActivityOperations" (the count of this resource's own Activity-log rows) and, for storage accounts,
 *     the real blob-store metrics. There is no CPU/latency/request telemetry pipeline, so those never appear.
 *   - alerts: Microsoft.Insights/metricAlerts whose scopes include this resource. Rules are stored and
 *     validated like the real resource; "Evaluate now" computes the rule against the real metric on demand.
 *     Nothing evaluates on a schedule and no action group is ever fired.
 *   - logs: a Log Analytics query (AzureActivity, filtered to this resource) - the only table with data.
 *   - workbooks: Microsoft.Insights/workbooks whose sourceId is this resource.
 *   - insights: the above rolled into one page (metric chart, alert rules, diagnostic settings, recent activity). */
import { useEffect, useMemo, useState } from "react";
import { Button, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import {
  deleteMetricAlert, deleteWorkbook, getMetrics, listActionGroups, listActivityLog, listDiagnosticSettings,
  listMetricAlerts, listMetricDefinitions, listWorkbooks, listWorkspaces, putMetricAlert, putWorkbook, runLogQuery,
  conditionSummary, SEVERITY_LABEL,
} from "../services/monitor/api.js";
import { parseId } from "./arm.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar, Loading, fmtDate } from "./common.jsx";

const CAP = "azure.common.resource_monitoring";
const COLORS = ["#0078d4", "#d13438", "#107c10", "#8764b8"];
const WIN_MIN = { PT1M: 1, PT5M: 5, PT15M: 15, PT30M: 30, PT1H: 60, PT6H: 360, PT12H: 720, P1D: 1440 };
const OPS = { GreaterThan: ">", GreaterThanOrEqual: ">=", LessThan: "<", LessThanOrEqual: "<=", Equals: "=" };
const same = (a, b) => String(a || "").toLowerCase() === String(b || "").toLowerCase();
const pointsOf = (res, agg) => (res?.value?.[0]?.timeseries?.[0]?.data || []).map((p) => ({ t: p.timeStamp, value: p[agg.toLowerCase()] ?? 0 }));

function LineChart({ points, label }) {
  const w = 640, h = 180, pad = 32;
  const max = Math.max(1, ...points.map((p) => p.value));
  const stepX = points.length > 1 ? (w - pad - 8) / (points.length - 1) : 0;
  const y = (v) => h - pad - (v / max) * (h - pad - 10);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${pad + i * stepX} ${y(p.value)}`).join(" ");
  return (
    <svg width={w} height={h} role="img" aria-label={label} style={{ maxWidth: "100%" }}>
      <line x1={pad} y1={h - pad} x2={w - 4} y2={h - pad} stroke="#ccc" />
      <line x1={pad} y1={4} x2={pad} y2={h - pad} stroke="#ccc" />
      <text x={2} y={12} fontSize="10" fill="#666">{max}</text>
      <text x={2} y={h - pad} fontSize="10" fill="#666">0</text>
      {points.length > 0 && <text x={pad} y={h - 8} fontSize="10" fill="#666">{fmtDate(points[0].t)}</text>}
      {points.length > 1 && <text x={w - 4} y={h - 8} fontSize="10" fill="#666" textAnchor="end">{fmtDate(points[points.length - 1].t)}</text>}
      {points.length === 1
        ? <circle cx={pad + 6} cy={y(points[0].value)} r={4} fill={COLORS[0]} />
        : <path d={d} fill="none" stroke={COLORS[0]} strokeWidth="2" />}
    </svg>
  );
}

const Row = ({ label, children }) => <div className="vy-form-row"><label>{label}</label><div>{children}</div></div>;

/** Metrics chart for one resource. */
export function ResourceMetrics({ id, name, title }) {
  const defs = useAsync(() => listMetricDefinitions(id), [id]);
  const [metric, setMetric] = useState("");
  const [agg, setAgg] = useState("Total");
  const [interval, setInterval_] = useState("PT1H");
  useEffect(() => { if (defs.data?.length && !metric) { setMetric(defs.data[0].name.value); setAgg(defs.data[0].primaryAggregationType || "Total"); } }, [defs.data]);
  const series = useAsync(() => (metric ? getMetrics(id, { metricnames: metric, aggregation: agg, interval }) : Promise.resolve(null)), [id, metric, agg, interval]);
  const def = defs.data?.find((d) => d.name.value === metric);
  const points = useMemo(() => pointsOf(series.data, agg), [series.data, agg]);
  const total = points.reduce((s, p) => s + p.value, 0);
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Metrics`}</div>
      <CapabilityContainer id={CAP} title="Metrics">
        <ErrorBar error={defs.error || series.error} title="Metrics query failed" />
        {defs.loading ? <Loading /> : (
          <>
            <Row label="Scope"><span>{name}</span></Row>
            <Row label="Metric Namespace"><Select value="Platform" disabled aria-label="Metric Namespace"><option>Platform</option></Select></Row>
            <Row label="Metric">
              <Select value={metric} onChange={(_, d) => setMetric(d.value)} aria-label="Metric">
                {(defs.data || []).map((m) => <option key={m.name.value} value={m.name.value}>{m.name.localizedValue}</option>)}
              </Select>
            </Row>
            <Row label="Aggregation">
              <Select value={agg} onChange={(_, d) => setAgg(d.value)} aria-label="Aggregation">
                {(def?.supportedAggregationTypes || ["Total"]).map((a) => <option key={a}>{a}</option>)}
              </Select>
            </Row>
            <Row label="Time granularity">
              <Select value={interval} onChange={(_, d) => setInterval_(d.value)} aria-label="Time granularity">
                {["PT1M", "PT5M", "PT15M", "PT1H"].map((a) => <option key={a}>{a}</option>)}
              </Select>
            </Row>
            {series.loading ? <Loading /> : <LineChart points={points} label={`${metric} ${agg} over the last 24 hours`} />}
            <p style={{ fontSize: 12 }} data-testid="metric-summary">{points.length} data points, sum {total}, last 24 hours.</p>
            <InfoBar>
              {metric === "ActivityOperations"
                ? `Real count of ${name}'s own Activity log operations. Vyomi has no CPU, request or latency telemetry for this resource type, so no other metrics are offered.`
                : "Real current value from this resource's own data (single point, no history)."}
            </InfoBar>
          </>
        )}
      </CapabilityContainer>
    </>
  );
}

/** Evaluate a stored metric alert rule against the real metric, on demand. */
export async function evaluateRule(id, rule) {
  const c = (rule.properties.criteria?.allOf || [])[0];
  if (!c) throw new Error("This rule has no metric criterion.");
  const win = WIN_MIN[rule.properties.windowSize] || 5;
  const end = new Date(Math.ceil(Date.now() / 1000) * 1000 + 1000), start = new Date(end.getTime() - win * 60000);
  const interval = win <= 60 ? "PT1M" : "PT5M";
  const res = await getMetrics(id, { metricnames: c.metricName, aggregation: c.timeAggregation, interval, timespan: `${start.toISOString().slice(0, 19)}Z/${end.toISOString().slice(0, 19)}Z` });
  const vals = pointsOf(res, c.timeAggregation === "Count" ? "Total" : c.timeAggregation).map((p) => p.value);
  const agg = { Total: (v) => v.reduce((a, b) => a + b, 0), Count: (v) => v.reduce((a, b) => a + b, 0), Maximum: (v) => Math.max(0, ...v),
    Minimum: (v) => (v.length ? Math.min(...v) : 0), Average: (v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0) }[c.timeAggregation](vals);
  const t = Number(c.threshold);
  const fires = { GreaterThan: agg > t, GreaterThanOrEqual: agg >= t, LessThan: agg < t, LessThanOrEqual: agg <= t, Equals: agg === t }[c.operator] ?? false;
  return { value: agg, fires, window: rule.properties.windowSize };
}

/** Alert rules scoped to this resource: list, create, delete, evaluate now. */
export function ResourceAlerts({ id, name, title }) {
  const notify = useNotify();
  const p = parseId(id);
  const rules = useAsync(async () => (await listMetricAlerts()).filter((r) => (r.properties.scopes || []).some((s) => same(s, id))), [id]);
  const defs = useAsync(() => listMetricDefinitions(id).catch(() => []), [id]);
  const groups = useAsync(() => listActionGroups().catch(() => []), []);
  const [form, setForm] = useState(null);
  const [evals, setEvals] = useState({});
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const openNew = () => setForm({ name: "", metric: defs.data?.[0]?.name.value || "ActivityOperations", agg: "Total", op: "GreaterThan", threshold: "0", severity: "2", freq: "PT5M", win: "PT15M", group: "" });
  const save = async () => {
    try {
      await putMetricAlert(p.resourceGroup, form.name, { location: "global", properties: {
        description: `Alert rule on ${name}`, severity: Number(form.severity), enabled: true, scopes: [id], evaluationFrequency: form.freq, windowSize: form.win,
        criteria: { "odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", allOf: [{ criterionType: "StaticThresholdCriterion", name: "Metric1", metricName: form.metric, timeAggregation: form.agg, operator: form.op, threshold: Number(form.threshold) }] },
        actions: form.group ? [{ actionGroupId: form.group }] : [] } });
      notify.success(`Alert rule '${form.name}' created.`, "Create succeeded"); setForm(null); rules.reload();
    } catch (e) { notify.error(e, "Failed to create the alert rule"); }
  };
  const evaluate = async (r) => {
    try { const r2 = await evaluateRule(id, r); setEvals((m) => ({ ...m, [r.name]: r2 })); }
    catch (e) { notify.error(e, "Failed to evaluate the rule"); }
  };
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Alerts`}</div>
      <CapabilityContainer id={CAP} title="Alert rules">
        {!form ? (
          <BrowseGrid
            resourceName="alert rule" rowKey={(r) => r.name} items={rules.data || []} loading={rules.loading} error={rules.error} onRefresh={rules.reload} onCreate={openNew}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteMetricAlert(r.resourceGroup, r.name))); rules.reload(); }} csvName="alert-rules.csv"
            columns={[
              { key: "name", label: "Name", value: (r) => r.name },
              { key: "cond", label: "Condition", value: (r) => conditionSummary(r) },
              { key: "sev", label: "Severity", value: (r) => SEVERITY_LABEL[r.properties.severity] },
              { key: "win", label: "Window / frequency", value: (r) => `${r.properties.windowSize} / ${r.properties.evaluationFrequency}` },
              { key: "ag", label: "Actions", value: (r) => (r.properties.actions || []).map((a) => a.actionGroupId.split("/").pop()).join(", ") || "--" },
              { key: "ev", label: "Evaluate now", render: (r) => (
                <>
                  <Button size="small" onClick={() => evaluate(r)} aria-label={`Evaluate ${r.name}`}>Evaluate</Button>{" "}
                  {evals[r.name] && <span data-testid={`eval-${r.name}`}>{evals[r.name].fires ? "Would fire" : "Healthy"} (value {Math.round(evals[r.name].value * 100) / 100} over {evals[r.name].window})</span>}
                </>), value: () => "" },
            ]}
          />
        ) : (
          <section className="vy-form-section" aria-label="Alert rule">
            <h3>Create an alert rule</h3>
            <Field label="Alert rule name"><Input value={form.name} onChange={(_, d) => set({ name: d.value })} aria-label="Alert rule name" /></Field>
            <Row label="Scope"><span>{name}</span></Row>
            <Row label="Signal"><Select value={form.metric} onChange={(_, d) => set({ metric: d.value })} aria-label="Signal">{(defs.data || []).map((m) => <option key={m.name.value} value={m.name.value}>{m.name.localizedValue}</option>)}</Select></Row>
            <Row label="Aggregation type"><Select value={form.agg} onChange={(_, d) => set({ agg: d.value })} aria-label="Aggregation type">{["Total", "Average", "Minimum", "Maximum", "Count"].map((a) => <option key={a}>{a}</option>)}</Select></Row>
            <Row label="Operator"><Select value={form.op} onChange={(_, d) => set({ op: d.value })} aria-label="Operator">{Object.entries(OPS).map(([k, v]) => <option key={k} value={k}>{v} ({k})</option>)}</Select></Row>
            <Row label="Threshold value"><Input type="number" value={form.threshold} onChange={(_, d) => set({ threshold: d.value })} aria-label="Threshold value" /></Row>
            <Row label="Severity"><Select value={form.severity} onChange={(_, d) => set({ severity: d.value })} aria-label="Severity">{Object.entries(SEVERITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Row>
            <Row label="Check every"><Select value={form.freq} onChange={(_, d) => set({ freq: d.value })} aria-label="Check every">{["PT1M", "PT5M", "PT15M", "PT30M", "PT1H"].map((a) => <option key={a}>{a}</option>)}</Select></Row>
            <Row label="Lookback period"><Select value={form.win} onChange={(_, d) => set({ win: d.value })} aria-label="Lookback period">{Object.keys(WIN_MIN).map((a) => <option key={a}>{a}</option>)}</Select></Row>
            <Row label="Action group"><Select value={form.group} onChange={(_, d) => set({ group: d.value })} aria-label="Action group"><option value="">None</option>{(groups.data || []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></Row>
            <div className="vy-cmdbar"><Button appearance="primary" disabled={!form.name} onClick={save}>Create alert rule</Button> <Button onClick={() => setForm(null)}>Cancel</Button></div>
          </section>
        )}
        <InfoBar>Rules are stored and validated like Azure's, and "Evaluate" computes a rule against this resource's real metric on demand. Vyomi does not evaluate rules on a schedule or fire action groups, and there is no CPU or latency signal.</InfoBar>
      </CapabilityContainer>
    </>
  );
}

/** Logs: KQL over the one table with data (AzureActivity), pre-filtered to this resource. */
export function ResourceLogs({ id, name, title }) {
  const ws = useAsync(() => listWorkspaces().catch(() => []), []);
  const [workspace, setWorkspace] = useState("");
  const [query, setQuery] = useState(`AzureActivity\n| where ResourceId == '${id}'\n| take 50`);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (ws.data?.length && !workspace) setWorkspace(ws.data[0].id); }, [ws.data]);
  const run = async () => {
    const w = ws.data.find((x) => x.id === workspace); if (!w) return;
    setBusy(true); setError(null);
    try { setResult(await runLogQuery(w.resourceGroup, w.name, query)); } catch (e) { setError(e); setResult(null); } finally { setBusy(false); }
  };
  const table = result?.tables?.[0];
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Logs`}</div>
      <CapabilityContainer id={CAP} title="Logs">
        {ws.loading ? <Loading /> : !ws.data?.length ? <p>No Log Analytics workspace yet. <a href="#/monitor/createloganalyticsworkspace">Create one</a> to query logs.</p> : (
          <>
            <Row label="Workspace"><Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">{ws.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></Row>
            <Textarea value={query} onChange={(_, d) => setQuery(d.value)} rows={4} resize="vertical" style={{ width: "100%", fontFamily: "monospace" }} aria-label="KQL query" />
            <div className="vy-cmdbar"><Button appearance="primary" disabled={busy} onClick={run}>Run</Button></div>
            <ErrorBar error={error} title="Query failed" />
            {table && (table.rows.length ? (
              <table aria-label="Query results" className="vy-grid"><thead><tr>{table.columns.map((c) => <th key={c.name}>{c.name}</th>)}</tr></thead>
                <tbody>{table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c == null ? "" : String(c)}</td>)}</tr>)}</tbody></table>
            ) : <p>No results found.</p>)}
          </>
        )}
        <InfoBar>Only the AzureActivity table has data (this resource's real Activity log). Resource-specific log tables stay empty: Vyomi has no log-delivery pipeline.</InfoBar>
      </CapabilityContainer>
    </>
  );
}

/** Workbooks whose sourceId is this resource: list, create, delete. */
export function ResourceWorkbooks({ id, name, title }) {
  const notify = useNotify();
  const p = parseId(id);
  const wbs = useAsync(async () => (await listWorkbooks()).filter((w) => same(w.properties.sourceId, id)), [id]);
  const create = async () => {
    const n = `wb-${Date.now().toString(36)}`;
    try {
      await putWorkbook(p.resourceGroup, n, { location: "eastus", kind: "shared", properties: { displayName: `${name} overview`, category: "workbook", sourceId: id,
        serializedData: JSON.stringify({ version: "Notebook/1.0", items: [{ type: 1, content: { json: `# ${name}` } }] }) } });
      notify.success("Workbook created.", "Create succeeded"); wbs.reload();
    } catch (e) { notify.error(e, "Failed to create the workbook"); }
  };
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Workbooks`}</div>
      <CapabilityContainer id={CAP} title="Workbooks">
        <BrowseGrid resourceName="workbook" rowKey={(w) => w.name} items={wbs.data || []} loading={wbs.loading} error={wbs.error} onRefresh={wbs.reload} onCreate={create}
          onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteWorkbook(r.resourceGroup, r.name))); wbs.reload(); }} csvName="workbooks.csv"
          columns={[{ key: "n", label: "Title", value: (w) => w.properties.displayName }, { key: "c", label: "Category", value: (w) => w.properties.category }, { key: "rg", label: "Resource group", value: (w) => w.resourceGroup }]} />
        <InfoBar>Workbooks are real Microsoft.Insights/workbooks resources linked to this resource. Visual rendering of workbook items is limited to the stored definition.</InfoBar>
      </CapabilityContainer>
    </>
  );
}

/** Insights: metric chart + alert rules + diagnostic settings + recent operations in one page. */
export function ResourceInsightsPanel({ id, name, title }) {
  const series = useAsync(() => getMetrics(id, { metricnames: "ActivityOperations", aggregation: "Total", interval: "PT1H" }).catch(() => null), [id]);
  const rules = useAsync(async () => (await listMetricAlerts()).filter((r) => (r.properties.scopes || []).some((s) => same(s, id))), [id]);
  const diag = useAsync(() => listDiagnosticSettings(id).catch(() => []), [id]);
  const acts = useAsync(() => listActivityLog(id).catch(() => []), [id]);
  const points = pointsOf(series.data, "Total");
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Insights`}</div>
      <CapabilityContainer id={CAP} title="Insights">
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 12 }} data-testid="insights-tiles">
          <div><b>{acts.data?.length ?? "-"}</b><div style={{ fontSize: 12 }}>Operations recorded</div></div>
          <div><b>{rules.data?.length ?? "-"}</b><div style={{ fontSize: 12 }}>Alert rules</div></div>
          <div><b>{diag.data?.length ?? "-"}</b><div style={{ fontSize: 12 }}>Diagnostic settings</div></div>
        </div>
        <h4>Operations over the last 24 hours</h4>
        {series.loading ? <Loading /> : <LineChart points={points} label="Operations over the last 24 hours" />}
        <h4>Recent operations</h4>
        <ul style={{ margin: 0, paddingLeft: 18 }}>{(acts.data || []).slice(0, 5).map((a, i) => <li key={i}>{a.operationName?.localizedValue || a.operationName?.value} - {a.status?.value} ({fmtDate(a.eventTimestamp)})</li>)}
          {acts.data && !acts.data.length && <li>No operations recorded yet.</li>}</ul>
        <p style={{ fontSize: 12 }}><a href={`${location.hash.split("/").slice(0, 4).join("/")}/alerts`}>Alert rules</a> | <a href={`${location.hash.split("/").slice(0, 4).join("/")}/metrics`}>Metrics</a> | <a href={`${location.hash.split("/").slice(0, 4).join("/")}/diagnosticsettings`}>Diagnostic settings</a></p>
        <InfoBar>Built only from this resource's real Activity log, alert rules and diagnostic settings. Request, latency and health rollups need a telemetry pipeline Vyomi does not have.</InfoBar>
      </CapabilityContainer>
    </>
  );
}

export default { ResourceMetrics, ResourceAlerts, ResourceLogs, ResourceWorkbooks, ResourceInsightsPanel };

/** Notifications: the resource's most recent Activity-log events (what the portal's bell/notifications list surfaces). */
export function ResourceNotifications({ id, name, title }) {
  const acts = useAsync(() => listActivityLog(id), [id]);
  return (
    <>
      {title !== null && <div className="vy-panel-title">{title || `${name} | Notifications`}</div>}
      <CapabilityContainer id={CAP} title="Notifications">
        <ErrorBar error={acts.error} title="Failed to load notifications" />
        {acts.loading ? <Loading /> : (
          <ul style={{ margin: 0, paddingLeft: 18 }} data-testid="notifications">
            {(acts.data || []).slice(0, 20).map((a, i) => <li key={i}>{a.operationName?.localizedValue || a.operationName?.value} - {a.status?.value} ({fmtDate(a.eventTimestamp)})</li>)}
            {!acts.data?.length && <li>No notifications.</li>}
          </ul>
        )}
        <InfoBar>Shows this resource's real recent Activity-log events. Service-health and fired-alert notifications do not exist because Vyomi has no monitoring pipeline that raises them.</InfoBar>
      </CapabilityContainer>
    </>
  );
}
