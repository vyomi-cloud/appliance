import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { AlarmStateBadge, LineChart, toSeries } from "./common.jsx";
import * as api from "./api.js";

function GraphTab({ rec }) {
  const now = Math.floor(Date.now() / 1000);
  const period = rec.Period || 300;
  const t = useAsync(() => {
    if (rec.AlarmRule) return Promise.resolve([]);
    const query = rec.Metrics?.length ? rec.Metrics : [{ Id: "m1", MetricStat: { Metric: { Namespace: rec.Namespace, MetricName: rec.MetricName, Dimensions: rec.Dimensions || [] }, Period: period, Stat: rec.Statistic || rec.ExtendedStatistic }, ReturnData: true }];
    return api.getMetricData(query, now - period * 60, now);
  }, [rec.AlarmName]);
  if (rec.AlarmRule) return <Box color="text-body-secondary" padding="l">Composite alarms don't graph a single metric.</Box>;
  if (t.loading) return <Box textAlign="center" padding="l"><Spinner /></Box>;
  return <LineChart series={toSeries((t.data || [])[0])} />;
}

function DetailsTab({ rec, kind, tags }) {
  const isMetric = kind === "MetricAlarm";
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2">Graph</Header>}><GraphTab rec={rec} /></Container>
      <KeyValue title="Details" columns={3} items={[
        ["Name", rec.AlarmName], ["Type", isMetric ? "Metric alarm" : "Composite alarm"], ["Description", rec.AlarmDescription || "-"],
        ["State", <AlarmStateBadge key="s" state={rec.StateValue} />], ["Threshold", isMetric ? (rec.Threshold ?? "-") : "-"], ["Last state update", fmtDate(rec.StateUpdatedTimestamp)],
        ...(isMetric ? [
          ["Metric name", rec.MetricName || "-"], ["Namespace", rec.Namespace || "-"], ["Statistic", rec.Statistic || rec.ExtendedStatistic || "-"],
          ["Period", rec.Period ? `${rec.Period} seconds` : "-"], ["Datapoints to alarm", rec.DatapointsToAlarm != null ? `${rec.DatapointsToAlarm} out of ${rec.EvaluationPeriods}` : "-"],
          ["Missing data treatment", rec.TreatMissingData || "-"],
        ] : [["Alarm rule", rec.AlarmRule]]),
        ["ARN", rec.AlarmArn], ["Actions", rec.ActionsEnabled ? "Enabled" : "Disabled"],
      ]} />
      {!!Object.keys(tags || {}).length && (
        <Table variant="container" items={Object.entries(tags).map(([Key, Value]) => ({ Key, Value }))}
          header={<Header variant="h2" counter={`(${Object.keys(tags).length})`}>Tags</Header>}
          columnDefinitions={[{ id: "k", header: "Key", cell: (r) => r.Key }, { id: "v", header: "Value", cell: (r) => r.Value }]} />
      )}
    </SpaceBetween>
  );
}

function ActionsTab({ rec }) {
  const rows = [];
  for (const [label, key] of [["In alarm", "AlarmActions"], ["OK", "OKActions"], ["Insufficient data", "InsufficientDataActions"]]) {
    for (const arn of rec[key] || []) rows.push({ state: label, arn });
  }
  return (
    <CapabilityContainer id="aws.cloudwatch.alarms.metric" title="Notifications and actions">
      <Table
        variant="embedded"
        items={rows}
        columnDefinitions={[
          { id: "state", header: "Alarm state trigger", cell: (r) => r.state },
          { id: "action", header: "Action", cell: (r) => r.arn },
        ]}
        empty={<Box textAlign="center" color="inherit">No actions configured.</Box>}
      />
    </CapabilityContainer>
  );
}

function HistoryTab({ name }) {
  const t = useAsync(() => api.describeAlarmHistory({ AlarmName: name, MaxRecords: 100 }), [name]);
  return (
    <Table
      variant="embedded"
      loading={t.loading}
      items={t.data || []}
      columnDefinitions={[
        { id: "ts", header: "Time stamp", cell: (h) => fmtDate(h.Timestamp) },
        { id: "type", header: "Type", cell: (h) => h.HistoryItemType },
        { id: "summary", header: "Summary", cell: (h) => h.HistorySummary },
      ]}
      empty={<Box textAlign="center" color="inherit">No history yet.</Box>}
    />
  );
}

function ParentAlarmsTab({ name }) {
  const t = useAsync(() => api.describeAlarms({ ParentsOfAlarmName: name }), [name]);
  const rows = [...(t.data?.CompositeAlarms || [])];
  return (
    <Table
      variant="embedded"
      loading={t.loading}
      items={rows}
      columnDefinitions={[
        { id: "name", header: "Name", cell: (a) => a.AlarmName },
        { id: "state", header: "State", cell: (a) => <AlarmStateBadge state={a.StateValue} /> },
      ]}
      empty={<Box textAlign="center" color="inherit">This alarm isn't referenced by any composite alarm.</Box>}
    />
  );
}

export default function AlarmDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [deleting, setDeleting] = useState(false);
  const t = useAsync(async () => {
    const res = await api.describeAlarms({ AlarmNames: [name] });
    const kind = res.MetricAlarms?.length ? "MetricAlarm" : "CompositeAlarm";
    const rec = (res.MetricAlarms || res.CompositeAlarms || [])[0];
    if (!rec) throw new Error(`Alarm ${name} not found`);
    const tags = Object.fromEntries((await api.listTagsForResource(rec.AlarmArn)).map((x) => [x.Key, x.Value]));
    return { rec, kind, tags };
  }, [name]);

  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const { rec, kind, tags } = t.data;

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <ButtonDropdown
            items={[{ id: "delete", text: "Delete" }, { id: "enable", text: "Enable actions" }, { id: "disable", text: "Disable actions" }]}
            onItemClick={async ({ detail }) => {
              if (detail.id === "delete") setDeleting(true);
              if (detail.id === "enable") { await api.enableAlarmActions([name]); notify.success("Actions enabled."); t.reload(); }
              if (detail.id === "disable") { await api.disableAlarmActions([name]); notify.success("Actions disabled."); t.reload(); }
            }}
          >
            Actions
          </ButtonDropdown>
          <Button onClick={() => { location.hash = `#/cloudwatch/alarms/create?edit=${encodeURIComponent(name)}`; }}>Edit</Button>
        </SpaceBetween>
      }>{name}</Header>
    }>
      <Tabs tabs={[
        { id: "details", label: "Details", content: <DetailsTab rec={rec} kind={kind} tags={tags} /> },
        { id: "actions", label: "Actions", content: <ActionsTab rec={rec} /> },
        { id: "history", label: "History", content: <HistoryTab name={name} /> },
        { id: "parents", label: "Parent alarms", content: <ParentAlarmsTab name={name} /> },
      ]} />
      <DeleteModal
        visible={deleting}
        onDismiss={() => setDeleting(false)}
        resourceType="alarm"
        names={[name]}
        onConfirm={async () => { await api.deleteAlarms([name]); notify.success(`Alarm ${name} deleted.`); navigate("cloudwatch", "alarms"); }}
      />
    </ContentLayout>
  );
}
