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
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { LineChart, toSeries } from "./common.jsx";
import * as api from "./api.js";

const TIME_RANGES = [{ label: "1h", value: "3600" }, { label: "3h", value: "10800" }, { label: "12h", value: "43200" }, { label: "1d", value: "86400" }, { label: "3d", value: "259200" }, { label: "1w", value: "604800" }];
const metricKey = (m) => `${m.Namespace}${m.MetricName}${JSON.stringify(m.Dimensions || [])}`;

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

function MetricGraph({ m, rangeSeconds, refreshKey }) {
  const now = Math.floor(Date.now() / 1000);
  const t = useAsync(() => api.getMetricData(
    [{ Id: "m1", MetricStat: { Metric: { Namespace: m.Namespace, MetricName: m.MetricName, Dimensions: m.Dimensions || [] }, Period: 300, Stat: "Average" }, ReturnData: true }],
    now - rangeSeconds, now,
  ), [m.key, rangeSeconds, refreshKey]);
  if (t.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  return (
    <Box padding={{ bottom: "l" }}>
      <Header variant="h3">{m.Namespace} / {m.MetricName}</Header>
      <LineChart series={toSeries((t.data || [])[0])} />
    </Box>
  );
}

export default function AllMetrics() {
  const notify = useNotify();
  const [graphed, setGraphed] = useState([]);
  const [range, setRange] = useState("3600");
  const [refreshKey, setRefreshKey] = useState(0);
  const [dashName, setDashName] = useState("");

  const addToGraph = (rows) => setGraphed((prev) => {
    const existing = new Set(prev.map((m) => m.key));
    return [...prev, ...rows.filter((m) => !existing.has(m.key))];
  });

  const addToDashboard = async () => {
    if (!dashName || !graphed.length) return;
    try {
      let body = { widgets: [] };
      try { body = JSON.parse((await api.getDashboard(dashName)).DashboardBody); } catch { /* new dashboard */ }
      const widgets = [...(body.widgets || []), ...graphed.map((m) => ({ id: `w${Date.now()}-${m.MetricName}`, type: "Line", title: `${m.Namespace} ${m.MetricName}`, namespace: m.Namespace, metricName: m.MetricName, dimensions: m.Dimensions || [], stat: "Average", period: 300 }))];
      await api.putDashboard(dashName, { widgets });
      notify.success(`Added ${graphed.length} metric(s) to dashboard ${dashName}.`);
    } catch (e) { notify.error(e); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Metrics</Header>}>
      <SpaceBetween size="l">
        <Tabs tabs={[
          { id: "browse", label: "Browse", content: <BrowseTab onGraph={addToGraph} /> },
          { id: "multi", label: "Multi source query", content: <CapabilityContainer id="aws.cloudwatch.metrics.multi-source-query" title="Multi source query" /> },
          { id: "graphed", label: "Graphed metrics", content: <GraphedTab graphed={graphed} onRemove={(key) => setGraphed((g) => g.filter((m) => m.key !== key))} /> },
          { id: "options", label: "Options", content: <CapabilityContainer id="aws.cloudwatch.metrics.multi-source-query" title="Options" /> },
          { id: "source", label: "Source", content: <CapabilityContainer id="aws.cloudwatch.metrics.multi-source-query" title="Source" /> },
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
            {graphed.length ? graphed.map((m) => <MetricGraph key={m.key} m={m} rangeSeconds={Number(range)} refreshKey={refreshKey} />) : <Box color="text-body-secondary">No metrics selected. Choose metrics in Browse and select Graph metrics.</Box>}
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
