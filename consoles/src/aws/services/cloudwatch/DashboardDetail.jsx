/* Dashboard detail: widgets live in DashboardBody JSON exactly like the real console
 * (PutDashboard/GetDashboard). Line, Number, Text and Alarm status widgets are real —
 * backed by GetMetricData / DescribeAlarms. Gauge, Stacked area, Bar, Pie, Logs table and
 * Explorer are declared gaps (Vyomi only has one line-chart primitive; see common.jsx). */
import { useMemo, useRef, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { AlarmStateBadge, LineChart, PERIOD_OPTIONS, toSeries } from "./common.jsx";
import * as api from "./api.js";

const WIDGET_TYPES = ["Line", "Number", "Gauge", "Stacked area", "Bar", "Pie", "Text", "Alarm status", "Logs table", "Explorer"];
const SUPPORTED = new Set(["Line", "Number", "Text", "Alarm status"]);
const TIME_RANGES = [{ label: "1h", value: "3600" }, { label: "3h", value: "10800" }, { label: "12h", value: "43200" }, { label: "1d", value: "86400" }, { label: "3d", value: "259200" }, { label: "1w", value: "604800" }];

function parseBody(body) {
  try { const p = JSON.parse(body || "{}"); return Array.isArray(p.widgets) ? p.widgets : []; } catch { return []; }
}

function MetricWidget({ w, rangeSeconds, refreshKey }) {
  const now = Math.floor(Date.now() / 1000);
  const t = useAsync(() => api.getMetricData(
    [{ Id: "m1", MetricStat: { Metric: { Namespace: w.namespace, MetricName: w.metricName, Dimensions: w.dimensions || [] }, Period: w.period || 300, Stat: w.stat || "Average" }, ReturnData: true }],
    now - rangeSeconds, now,
  ), [w.namespace, w.metricName, w.stat, w.period, rangeSeconds, refreshKey]);
  const series = toSeries((t.data || [])[0]);
  if (t.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  if (w.type === "Number") {
    const last = series.length ? series[series.length - 1].v : null;
    return <Box fontSize="display-l" fontWeight="bold" textAlign="center" padding="l">{last === null ? "-" : last.toFixed(2)}</Box>;
  }
  return <LineChart series={series} />;
}

function Widget({ w, rangeSeconds, refreshKey, onRemove }) {
  return (
    <Container header={<Header variant="h3" actions={<Button variant="icon" iconName="remove" ariaLabel={`Remove widget ${w.title}`} onClick={onRemove} />}>{w.title}</Header>}>
      {(w.type === "Line" || w.type === "Number") && <MetricWidget w={w} rangeSeconds={rangeSeconds} refreshKey={refreshKey} />}
      {w.type === "Text" && <Box variant="p">{w.content}</Box>}
      {w.type === "Alarm status" && (
        <SpaceBetween size="xs">
          {(w.alarms || []).map((a) => <Box key={a}>{a}: <AlarmStateBadgeAsync name={a} refreshKey={refreshKey} /></Box>)}
        </SpaceBetween>
      )}
    </Container>
  );
}

function AlarmStateBadgeAsync({ name, refreshKey }) {
  const t = useAsync(() => api.describeAlarms({ AlarmNames: [name] }), [name, refreshKey]);
  const rec = (t.data?.MetricAlarms || t.data?.CompositeAlarms || [])[0];
  return rec ? <AlarmStateBadge state={rec.StateValue} /> : <Spinner size="normal" />;
}

function AddWidgetForm({ onAdd }) {
  const [type, setType] = useState("Line");
  const metrics = useAsync(() => api.listMetrics({}), []);
  const namespaces = useMemo(() => [...new Set((metrics.data || []).map((m) => m.Namespace))].sort(), [metrics.data]);
  const [namespace, setNamespace] = useState(null);
  const metricNames = useMemo(() => [...new Set((metrics.data || []).filter((m) => m.Namespace === namespace).map((m) => m.MetricName))].sort(), [metrics.data, namespace]);
  const [metricName, setMetricName] = useState(null);
  const [stat, setStat] = useState("Average");
  const [period, setPeriod] = useState("300");
  const [text, setText] = useState("");
  const [alarmNames, setAlarmNames] = useState([]);
  const alarmsList = useAsync(() => api.describeAlarms({}), []);

  const dims = (metrics.data || []).find((m) => m.Namespace === namespace && m.MetricName === metricName)?.Dimensions || [];

  const add = () => {
    if (type === "Line" || type === "Number") {
      if (!namespace || !metricName) return;
      onAdd({ type, title: `${namespace} ${metricName}`, namespace, metricName, dimensions: dims, stat, period: Number(period) });
    } else if (type === "Text") {
      if (!text.trim()) return;
      onAdd({ type, title: "Text", content: text });
      setText("");
    } else if (type === "Alarm status") {
      if (!alarmNames.length) return;
      onAdd({ type, title: "Alarm status", alarms: alarmNames });
      setAlarmNames([]);
    }
  };

  return (
    <SpaceBetween size="l">
      <RadioGroup
        value={type}
        onChange={({ detail }) => setType(detail.value)}
        items={WIDGET_TYPES.map((label) => ({ value: label, label }))}
        ariaLabel="Widget type"
      />
      {!SUPPORTED.has(type) && <Alert type="info" header="Not simulated in Vyomi">This widget type isn't backed by a Vyomi backend yet; Line, Number, Text and Alarm status widgets are.</Alert>}
      {(type === "Line" || type === "Number") && (
        <ColumnFields>
          <Select placeholder="Namespace" selectedOption={namespace ? { label: namespace, value: namespace } : null} onChange={({ detail }) => { setNamespace(detail.selectedOption.value); setMetricName(null); }} options={namespaces.map((n) => ({ label: n, value: n }))} ariaLabel="Namespace" />
          <Select placeholder="Metric name" disabled={!namespace} selectedOption={metricName ? { label: metricName, value: metricName } : null} onChange={({ detail }) => setMetricName(detail.selectedOption.value)} options={metricNames.map((n) => ({ label: n, value: n }))} ariaLabel="Metric name" />
          <Select selectedOption={{ label: stat, value: stat }} onChange={({ detail }) => setStat(detail.selectedOption.value)} options={["Average", "Sum", "Minimum", "Maximum", "SampleCount"].map((s) => ({ label: s, value: s }))} ariaLabel="Statistic" />
          <Select selectedOption={PERIOD_OPTIONS.find((p) => p.value === period)} onChange={({ detail }) => setPeriod(detail.selectedOption.value)} options={PERIOD_OPTIONS} ariaLabel="Period" />
        </ColumnFields>
      )}
      {type === "Text" && <Textarea value={text} onChange={({ detail }) => setText(detail.value)} ariaLabel="Widget text" placeholder="Markdown text for this widget" />}
      {type === "Alarm status" && (
        <Select
          selectedOption={null}
          placeholder="Choose an alarm"
          onChange={({ detail }) => setAlarmNames([...new Set([...alarmNames, detail.selectedOption.value])])}
          options={[...(alarmsList.data?.MetricAlarms || []), ...(alarmsList.data?.CompositeAlarms || [])].map((a) => ({ label: a.AlarmName, value: a.AlarmName }))}
          ariaLabel="Select alarms"
        />
      )}
      <Button onClick={add} disabled={!SUPPORTED.has(type)}>Add to dashboard</Button>
    </SpaceBetween>
  );
}

function ColumnFields({ children }) {
  return <SpaceBetween direction="horizontal" size="s">{children}</SpaceBetween>;
}

export default function DashboardDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const addRef = useRef(null);
  const t = useAsync(() => api.getDashboard(name), [name]);
  const [widgets, setWidgets] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [range, setRange] = useState("3600");
  const [refreshKey, setRefreshKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const current = widgets ?? (t.data ? parseBody(t.data.DashboardBody) : []);

  const addWidget = (w) => { setWidgets([...current, { ...w, id: `w${current.length}-${Date.now() % 100000}` }]); setDirty(true); };
  const removeWidget = (id) => { setWidgets(current.filter((w) => w.id !== id)); setDirty(true); };

  const save = async () => {
    setBusy(true);
    try { await api.putDashboard(name, { widgets: current }); setDirty(false); notify.success(`Dashboard ${name} saved.`); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={() => setRefreshKey((k) => k + 1)} />
          <Select selectedOption={TIME_RANGES.find((r) => r.value === range)} onChange={({ detail }) => setRange(detail.selectedOption.value)} options={TIME_RANGES} ariaLabel="Time range" />
          <ButtonDropdown items={[{ id: "delete", text: "Delete dashboard" }]} onItemClick={({ detail }) => detail.id === "delete" && setDeleting(true)}>Actions</ButtonDropdown>
          <Button onClick={save} loading={busy} disabled={!dirty}>Save</Button>
          <Button variant="primary" onClick={() => addRef.current?.scrollIntoView({ behavior: "smooth" })}>Add widget</Button>
        </SpaceBetween>
      }>{name}</Header>
    }>
      <SpaceBetween size="l">
        {current.length > 0 && (
          <SpaceBetween size="l">
            {current.map((w) => <Widget key={w.id} w={w} rangeSeconds={Number(range)} refreshKey={refreshKey} onRemove={() => removeWidget(w.id)} />)}
          </SpaceBetween>
        )}
        <div ref={addRef}>
          <Container header={<Header variant="h2">Add widget</Header>}>
            <AddWidgetForm onAdd={addWidget} />
          </Container>
        </div>
      </SpaceBetween>
      <DeleteModal
        visible={deleting}
        onDismiss={() => setDeleting(false)}
        resourceType="dashboard"
        names={[name]}
        onConfirm={async () => { await api.deleteDashboards([name]); notify.success(`Dashboard ${name} deleted.`); navigate("cloudwatch", "dashboards"); }}
      />
    </ContentLayout>
  );
}
