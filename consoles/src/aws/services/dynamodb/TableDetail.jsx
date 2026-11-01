import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import Toggle from "@cloudscape-design/components/toggle";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, fmtBytes, fmtDate, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { attrType, capacity, keyOf, statusOf, tableClass } from "./Tables.jsx";
import { getLayoutSettings, TABLE_TAB_ID } from "./prefs.js";
import * as api from "./api.js";

export default function TableDetail({ params, query }) {
  const name = params.name;
  const [tab, setTab] = useState(query.tab || TABLE_TAB_ID[getLayoutSettings().defaultTableTab] || "overview");
  const t = useAsync(() => api.describeTable(name), [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={t.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button variant="primary" href={href("dynamodb", "tables", name, "items")} onFollow={follow}>Explore table items</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "overview", label: "Overview", content: <Overview d={d} reload={t.reload} /> },
        { id: "indexes", label: "Indexes", content: <SpaceBetween size="l">
            <Indexes d={d} />
            <LocalIndexes d={d} />
          </SpaceBetween> },
        { id: "monitor", label: "Monitor", content: <MonitorTab d={d} /> },
        { id: "global-tables", label: "Global tables", content: <GlobalTablesTab d={d} reload={t.reload} /> },
        { id: "backups", label: "Backups", content: <Backups name={name} /> },
        { id: "exports", label: "Exports and streams", content: <ExportsAndStreamsTab d={d} reload={t.reload} /> },
        { id: "permissions", label: "Permissions", content: <PermissionsTab d={d} /> },
        { id: "settings", label: "Additional settings", content: <Settings d={d} reload={t.reload} /> },
      ]} />
    </ContentLayout>
  );
}

function CapacityModal({ d, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [mode, setMode] = useState(capacity(d) === "On-demand" ? "PAY_PER_REQUEST" : "PROVISIONED");
  const [rcu, setRcu] = useState(String(d.ProvisionedThroughput?.ReadCapacityUnits || 5));
  const [wcu, setWcu] = useState(String(d.ProvisionedThroughput?.WriteCapacityUnits || 5));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.updateTable({ TableName: d.TableName, BillingMode: mode, ...(mode === "PROVISIONED" ? { ProvisionedThroughput: { ReadCapacityUnits: Number(rcu), WriteCapacityUnits: Number(wcu) } } : {}) });
      notify.success("Capacity settings updated."); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit read/write capacity"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Capacity mode">
          <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)}
            items={[{ value: "PAY_PER_REQUEST", label: "On-demand" }, { value: "PROVISIONED", label: "Provisioned" }]} />
        </FormField>
        {mode === "PROVISIONED" && (
          <SpaceBetween direction="horizontal" size="l">
            <FormField label="Read capacity units"><Input type="number" value={rcu} onChange={({ detail }) => setRcu(detail.value)} ariaLabel="Read capacity units" /></FormField>
            <FormField label="Write capacity units"><Input type="number" value={wcu} onChange={({ detail }) => setWcu(detail.value)} ariaLabel="Write capacity units" /></FormField>
          </SpaceBetween>
        )}
      </SpaceBetween>
    </Modal>
  );
}

function Overview({ d, reload }) {
  const notify = useNotify();
  const pitr = useAsync(() => api.describeBackups(d.TableName), [d.TableName]);
  const [capModal, setCapModal] = useState(false);
  const [protBusy, setProtBusy] = useState(false);
  const pk = keyOf(d, "HASH"), sk = keyOf(d, "RANGE");
  const pitrOn = pitr.data?.PointInTimeRecoveryDescription?.PointInTimeRecoveryStatus === "ENABLED";
  const toggleProtection = async () => {
    setProtBusy(true);
    try {
      await api.updateTable({ TableName: d.TableName, DeletionProtectionEnabled: !d.DeletionProtectionEnabled });
      notify.success(`Deletion protection turned ${d.DeletionProtectionEnabled ? "off" : "on"}.`);
      reload();
    } catch (e) { notify.error(e); } finally { setProtBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <KeyValue title="General information" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => setCapModal(true)}>Edit capacity</Button>
          <Button loading={protBusy} onClick={toggleProtection}>{d.DeletionProtectionEnabled ? "Turn off deletion protection" : "Turn on deletion protection"}</Button>
        </SpaceBetween>
      } columns={4} items={[
        ["Partition key", pk && `${pk} (${attrType(d, pk)})`], ["Sort key", sk ? `${sk} (${attrType(d, sk)})` : "-"],
        ["Capacity mode", capacity(d)], ["Table status", statusOf(d.TableStatus)],
        ["Alarms", "No active alarms"], ["Point-in-time recovery (PITR)", pitr.data === null ? "-" : (pitrOn ? "On" : "Off")],
        ["Item count", d.ItemCount ?? 0], ["Table size", `${d.TableSizeBytes ?? 0} bytes`],
        ["Amazon Resource Name (ARN)", d.TableArn], ["Creation date", fmtDate(d.CreationDateTime)], ["Deletion protection", d.DeletionProtectionEnabled ? "On" : "Off"],
        ["Table class", tableClass(d)],
      ]} />
      <CapacityModal d={d} visible={capModal} onDismiss={() => setCapModal(false)} onDone={reload} />
    </SpaceBetween>
  );
}

function Indexes({ d }) {
  const rows = d.GlobalSecondaryIndexes || [];
  return (
    <Table variant="container" header={<Header variant="h2" counter={`(${rows.length})`}>Global secondary indexes</Header>} items={rows}
      columnDefinitions={[
        { id: "n", header: "Name", cell: (i) => i.IndexName },
        { id: "s", header: "Status", cell: (i) => statusOf(i.IndexStatus || "ACTIVE") },
        { id: "pk", header: "Partition key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "HASH")?.AttributeName },
        { id: "sk", header: "Sort key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "RANGE")?.AttributeName || "-" },
        { id: "p", header: "Projected attributes", cell: (i) => i.Projection?.ProjectionType || "-" },
        { id: "sz", header: "Size", cell: () => `${d.TableSizeBytes ?? 0} bytes` },
        { id: "ic", header: "Item count", cell: (i) => i.ItemCount ?? 0 },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No global secondary indexes</b><Box variant="p" color="inherit">You have not created any global secondary indexes for this table.</Box></Box>} />
  );
}

function LocalIndexes({ d }) {
  const rows = d.LocalSecondaryIndexes || [];
  return (
    <Table variant="container" header={<Header variant="h2" counter={`(${rows.length})`}>Local secondary indexes</Header>} items={rows}
      columnDefinitions={[
        { id: "n", header: "Name", cell: (i) => i.IndexName },
        { id: "s", header: "Status", cell: () => statusOf(d.TableStatus) },
        { id: "pk", header: "Partition key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "HASH")?.AttributeName },
        { id: "sk", header: "Sort key", cell: (i) => i.KeySchema?.find((k) => k.KeyType === "RANGE")?.AttributeName || "-" },
        { id: "p", header: "Projected attributes", cell: (i) => i.Projection?.ProjectionType || "-" },
        { id: "sz", header: "Size", cell: () => `${d.TableSizeBytes ?? 0} bytes` },
        { id: "ic", header: "Item count", cell: (i) => i.ItemCount ?? 0 },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No local secondary indexes</b><Box variant="p" color="inherit">Local secondary indexes must be created when the table is created.</Box></Box>} />
  );
}

const MONITOR_METRICS = [
  { metric: "ConsumedReadCapacityUnits", label: "Consumed read capacity units", statistic: "Sum" },
  { metric: "ConsumedWriteCapacityUnits", label: "Consumed write capacity units", statistic: "Sum" },
];

function MetricTable({ name, metric, label, statistic }) {
  const m = useAsync(() => api.getTableMetric(name, metric, { statistic }), [name, metric]);
  const points = m.data || [];
  return (
    <Table variant="embedded" items={[...points].reverse().slice(0, 10)}
      header={<Header variant="h3" counter={`(${points.length})`}>{label}</Header>}
      columnDefinitions={[
        { id: "t", header: "Timestamp", cell: (p) => new Date(p.Timestamp * 1000).toLocaleString() },
        { id: "v", header: statistic, cell: (p) => p[statistic] },
      ]}
      empty={<Box textAlign="center" color="inherit">No datapoints yet — read/write this table to generate real activity.</Box>} />
  );
}

function CreateAlarmModal({ name, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [metricName, setMetricName] = useState(MONITOR_METRICS[0].metric);
  const [threshold, setThreshold] = useState("100");
  const [evaluationPeriods, setEvaluationPeriods] = useState("3");
  const [snsArn, setSnsArn] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      const alarmName = `${name}-${metricName}`;
      await api.putTableAlarm(name, {
        alarmName, metricName, statistic: "Sum", comparison: "GreaterThanOrEqualToThreshold",
        threshold: Number(threshold), evaluationPeriods: Math.max(1, Number(evaluationPeriods) || 1), snsArn,
      });
      notify.success(`Alarm ${alarmName} was created.`);
      onDone(); onDismiss();
    } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create alarm"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={create}>Create alarm</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        <FormField label="Metric">
          <Select selectedOption={{ label: MONITOR_METRICS.find((m) => m.metric === metricName)?.label, value: metricName }} ariaLabel="Metric"
            onChange={({ detail }) => setMetricName(detail.selectedOption.value)}
            options={MONITOR_METRICS.map((m) => ({ label: m.label, value: m.metric }))} />
        </FormField>
        <FormField label="Threshold" description="Alarm when the metric's sum is >= this value for the evaluation periods below.">
          <Input type="number" value={threshold} onChange={({ detail }) => setThreshold(detail.value)} ariaLabel="Threshold" />
        </FormField>
        <FormField label="Evaluation periods (1 minute each)">
          <Input type="number" value={evaluationPeriods} onChange={({ detail }) => setEvaluationPeriods(detail.value)} ariaLabel="Evaluation periods" />
        </FormField>
        <FormField label="SNS topic ARN - optional" description="Vyomi really publishes to this topic when the alarm transitions, through the same SNS engine the console's SNS pages use.">
          <Input value={snsArn} onChange={({ detail }) => setSnsArn(detail.value)} placeholder="arn:aws:sns:us-east-1:123456789012:my-topic" ariaLabel="SNS topic ARN" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function MonitorTab({ d }) {
  const name = d.TableName;
  const alarms = useAsync(() => api.describeTableAlarms(name, MONITOR_METRICS.map((m) => m.metric)), [name]);
  const [open, setOpen] = useState(false);
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="dynamodb.monitor" title="CloudWatch alarms" actions={<Button onClick={() => setOpen(true)}>Create alarm</Button>}>
        <Table variant="embedded" items={alarms.data || []}
          columnDefinitions={[
            { id: "name", header: "Name", cell: (a) => a.AlarmName },
            { id: "state", header: "State", cell: (a) => a.StateValue },
            { id: "cond", header: "Conditions", cell: (a) => `${a.MetricName} >= ${a.Threshold}` },
          ]}
          empty={<Box textAlign="center" color="inherit">No alarms configured for this table's metrics.</Box>} />
      </CapabilityContainer>
      <CapabilityContainer id="dynamodb.monitor" title="CloudWatch metrics">
        <SpaceBetween size="l">
          {MONITOR_METRICS.map((m) => <MetricTable key={m.metric} name={name} metric={m.metric} label={m.label} statistic={m.statistic} />)}
        </SpaceBetween>
      </CapabilityContainer>
      <CreateAlarmModal name={name} visible={open} onDismiss={() => setOpen(false)} onDone={alarms.reload} />
    </SpaceBetween>
  );
}

function CreateReplicaModal({ name, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [region, setRegion] = useState("eu-west-1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createReplica(name, region); notify.success(`Creating replica in ${region}.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create replica"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Create replica</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Region" description="Vyomi really backfills and then keeps mirroring this table's writes into the replica (it has no regional endpoint of its own to query — see the Monitor tab's capability note).">
          <Input value={region} onChange={({ detail }) => setRegion(detail.value)} ariaLabel="Region" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function GlobalTablesTab({ d, reload }) {
  const notify = useNotify();
  const name = d.TableName;
  const rows = d.Replicas || [];
  const [sel, setSel] = useState([]);
  const [createModal, setCreateModal] = useState(false);
  const capacityMode = (r) => (r.ReplicaProvisionedReadCapacityAutoScalingSettings ? "On-demand" : "Provisioned");
  return (
    <CapabilityContainer id="dynamodb.global-tables" title="Replicas" counter={`(${rows.length})`} actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button disabled={!sel.length} onClick={async () => {
          for (const r of sel) await api.deleteReplica(name, r.RegionName);
          notify.success(`${sel.length} replica(s) deleted.`); setSel([]); reload();
        }}>Delete replica</Button>
        <Button variant="primary" onClick={() => setCreateModal(true)}>Create replica</Button>
      </SpaceBetween>
    }>
      <Table variant="embedded" items={rows} trackBy="RegionName" selectionType="single" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        columnDefinitions={[
          { id: "region", header: "Region", cell: (r) => r.RegionName },
          { id: "status", header: "Status", cell: (r) => r.ReplicaStatus },
          { id: "rcap", header: "Read capacity mode", cell: capacityMode },
          { id: "wcap", header: "Write capacity mode", cell: capacityMode },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No replicas</b><Box variant="p" color="inherit">This table is not replicated to other Regions.</Box></Box>} />
      <CreateReplicaModal name={name} visible={createModal} onDismiss={() => setCreateModal(false)} onDone={reload} />
    </CapabilityContainer>
  );
}

function StreamModal({ name, enabled, viewType, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [on, setOn] = useState(enabled);
  const [vt, setVt] = useState(viewType || "NEW_AND_OLD_IMAGES");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.updateTable({ TableName: name, StreamSpecification: on ? { StreamEnabled: true, StreamViewType: vt } : { StreamEnabled: false } });
      notify.success(`DynamoDB stream turned ${on ? "on" : "off"}.`); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Manage stream"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Toggle checked={on} onChange={({ detail }) => setOn(detail.checked)}>Turn on DynamoDB stream</Toggle>
        <FormField label="View type">
          <Select disabled={!on} selectedOption={{ label: vt, value: vt }} ariaLabel="View type"
            onChange={({ detail }) => setVt(detail.selectedOption.value)}
            options={["KEYS_ONLY", "NEW_IMAGE", "OLD_IMAGE", "NEW_AND_OLD_IMAGES"].map((v) => ({ label: v, value: v }))} />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function KinesisModal({ name, dest, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [streamArn, setStreamArn] = useState(dest?.StreamArn || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (dest) await api.disableKinesisStreamingDestination(name, dest.StreamArn);
      else await api.enableKinesisStreamingDestination(name, streamArn);
      notify.success(dest ? "Kinesis streaming turned off." : "Kinesis streaming turned on."); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={dest ? "Turn off Kinesis streaming" : "Turn on Kinesis streaming"}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>{dest ? "Turn off" : "Turn on"}</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        {dest ? <Box variant="p">Stop publishing this table's changes to <code>{dest.StreamArn}</code>?</Box> : (
          <FormField label="Kinesis data stream ARN" description="Must name a real stream in the Kinesis console — Vyomi checks it exists.">
            <Input value={streamArn} onChange={({ detail }) => setStreamArn(detail.value)} ariaLabel="Kinesis data stream ARN"
              placeholder="arn:aws:kinesis:us-east-1:123456789012:stream/my-stream" />
          </FormField>
        )}
      </SpaceBetween>
    </Modal>
  );
}

function ExportsAndStreamsTab({ d, reload }) {
  const name = d.TableName;
  const kd = useAsync(() => api.describeKinesisStreamingDestination(name), [name]);
  const [kinesisModal, setKinesisModal] = useState(false);
  const [streamModal, setStreamModal] = useState(false);
  const dest = (kd.data || [])[0];
  const stream = d.StreamSpecification;
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="dynamodb.kinesis" title="Amazon Kinesis data stream details"
        actions={<Button onClick={() => setKinesisModal(true)}>{dest ? "Turn off" : "Turn on"}</Button>}>
        {dest ? <KeyValue columns={2} items={[["Destination status", dest.DestinationStatus], ["Stream ARN", dest.StreamArn]]} />
          : <Box textAlign="center" color="inherit">Kinesis data streaming is turned off for this table.</Box>}
      </CapabilityContainer>
      <CapabilityContainer id="dynamodb.streams" title="DynamoDB stream details"
        actions={<Button onClick={() => setStreamModal(true)}>{stream?.StreamEnabled ? "Turn off" : "Turn on"}</Button>}>
        <KeyValue columns={2} items={[["Stream status", stream?.StreamEnabled ? "On" : "Off"], ["View type", stream?.StreamViewType || "-"],
          ["Latest stream ARN", d.LatestStreamArn || "-"]]} />
      </CapabilityContainer>
      <NotSimulatedContainer title="Trigger" feature="DynamoDB stream triggers (Lambda)" />
      <KinesisModal name={name} dest={dest} visible={kinesisModal} onDismiss={() => setKinesisModal(false)} onDone={() => { reload(); kd.reload(); }} />
      <StreamModal name={name} enabled={!!stream?.StreamEnabled} viewType={stream?.StreamViewType} visible={streamModal} onDismiss={() => setStreamModal(false)} onDone={reload} />
    </SpaceBetween>
  );
}

function PolicyModal({ arn, policy, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [text, setText] = useState(policy?.Policy || JSON.stringify({ Version: "2012-10-17", Statement: [] }, null, 2));
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.putResourcePolicy(arn, text, policy?.RevisionId, confirm);
      notify.success("Resource-based policy saved."); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit resource-based policy" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save policy</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Policy document">
          <Textarea value={text} onChange={({ detail }) => setText(detail.value)} rows={12} ariaLabel="Policy document" />
        </FormField>
        <Toggle checked={confirm} onChange={({ detail }) => setConfirm(detail.checked)}>Confirm this policy even if it grants public access (ConfirmRemoveSelfResourceAccess)</Toggle>
      </SpaceBetween>
    </Modal>
  );
}

function PermissionsTab({ d }) {
  const notify = useNotify();
  const arn = d.TableArn;
  const policy = useAsync(() => api.getResourcePolicy(arn), [arn]);
  const [editModal, setEditModal] = useState(false);
  return (
    <CapabilityContainer id="dynamodb.resource-policy" title="Resource-based policy for table" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => setEditModal(true)}>{policy.data ? "Edit" : "Create table policy"}</Button>
        {policy.data && <Button onClick={async () => { await api.deleteResourcePolicy(arn, policy.data.RevisionId); notify.success("Policy deleted."); policy.reload(); }}>Delete</Button>}
      </SpaceBetween>
    }>
      {policy.loading ? <Spinner /> : policy.data
        ? <FormField label="Policy" stretch><Textarea value={JSON.stringify(JSON.parse(policy.data.Policy), null, 2)} readOnly rows={10} ariaLabel="Policy" /></FormField>
        : <Box textAlign="center" color="inherit">This table does not have a resource-based policy.</Box>}
      <PolicyModal arn={arn} policy={policy.data} visible={editModal} onDismiss={() => setEditModal(false)} onDone={policy.reload} />
    </CapabilityContainer>
  );
}

function PitrModal({ name, enabled, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [on, setOn] = useState(enabled);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.updateContinuousBackups(name, on); notify.success(`Point-in-time recovery turned ${on ? "on" : "off"}.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit point-in-time recovery (PITR)"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      {error && <ErrorAlert error={error} />}
      <Toggle checked={on} onChange={({ detail }) => setOn(detail.checked)}>Turn on point-in-time recovery</Toggle>
    </Modal>
  );
}

function CreateBackupModal({ name, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [backupName, setBackupName] = useState(`${name}-backup`);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createBackup(name, backupName); notify.success(`Creating backup "${backupName}".`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create backup"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Create backup</Button></SpaceBetween></Box>}>
      {error && <ErrorAlert error={error} />}
      <FormField label="Backup name"><Input value={backupName} onChange={({ detail }) => setBackupName(detail.value)} ariaLabel="Backup name" /></FormField>
    </Modal>
  );
}

function Backups({ name }) {
  const notify = useNotify();
  const b = useAsync(() => api.describeBackups(name), [name]);
  const rows = useAsync(() => api.listBackups(name), [name]);
  const [sel, setSel] = useState([]);
  const [pitrModal, setPitrModal] = useState(false);
  const [createModal, setCreateModal] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState("");
  const [restoring, setRestoring] = useState(null);
  const [del, setDel] = useState(false);
  if (b.loading) return <Spinner />;
  if (b.data === null) return <NotSimulatedContainer title="Point-in-time recovery (PITR)" />;
  const pitrOn = b.data?.PointInTimeRecoveryDescription?.PointInTimeRecoveryStatus === "ENABLED";
  return (
    <SpaceBetween size="l">
      <KeyValue title="Point-in-time recovery (PITR)" actions={<Button onClick={() => setPitrModal(true)}>Edit</Button>}
        columns={2} items={[["Status", pitrOn ? "On" : "Off"], ["Earliest restore date", fmtDate(b.data?.PointInTimeRecoveryDescription?.EarliestRestorableDateTime)]]} />
      <Table
        variant="container"
        items={rows.data || []}
        loading={rows.loading}
        trackBy="BackupArn"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${(rows.data || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => { setRestoreTarget(`${name}-restored`); setRestoring(sel[0]); }}>Restore</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button variant="primary" onClick={() => setCreateModal(true)}>Create backup</Button>
          </SpaceBetween>
        }>Backups</Header>}
        columnDefinitions={[
          { id: "name", header: "Name", cell: (x) => x.BackupName },
          { id: "status", header: "Status", cell: (x) => <StatusIndicator type={x.BackupStatus === "AVAILABLE" ? "success" : "in-progress"}>{x.BackupStatus}</StatusIndicator> },
          { id: "created", header: "Creation time", cell: (x) => fmtDate(x.BackupCreationDateTime) },
          { id: "size", header: "Size", cell: (x) => fmtBytes(x.BackupSizeBytes) },
          { id: "type", header: "Type", cell: (x) => x.BackupType },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No backups</b></Box>} />

      <PitrModal name={name} enabled={pitrOn} visible={pitrModal} onDismiss={() => setPitrModal(false)} onDone={b.reload} />
      <CreateBackupModal name={name} visible={createModal} onDismiss={() => setCreateModal(false)} onDone={rows.reload} />
      <Modal visible={!!restoring} onDismiss={() => setRestoring(null)} header="Restore backup"
        footer={<Box float="right"><Button variant="primary" disabled={!restoreTarget} onClick={async () => {
          try { await api.restoreTableFromBackup(restoring.BackupArn, restoreTarget); notify.success(`Restoring "${restoreTarget}" from backup "${restoring.BackupName}".`); setRestoring(null); }
          catch (e) { notify.error(e); }
        }}>Restore backup</Button></Box>}>
        <FormField label="New table name"><Input value={restoreTarget} onChange={({ detail }) => setRestoreTarget(detail.value)} ariaLabel="New table name" /></FormField>
      </Modal>
      <DeleteModal visible={del} resourceType="backup" names={sel.map((x) => x.BackupName)} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const x of sel) await api.deleteBackup(x.BackupArn); notify.success(`${sel.length} backup(s) deleted.`); setSel([]); rows.reload(); }} />
    </SpaceBetween>
  );
}

function TtlModal({ name, ttl, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [enabled, setEnabled] = useState(ttl?.TimeToLiveStatus === "ENABLED");
  const [attr, setAttr] = useState(ttl?.AttributeName || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.updateTtl(name, { AttributeName: attr, Enabled: enabled }); notify.success(`TTL turned ${enabled ? "on" : "off"}.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit Time to Live (TTL)"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Save changes</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Turn on TTL</Toggle>
        <FormField label="TTL attribute" description="A number attribute (epoch seconds) that marks when an item should expire.">
          <Input value={attr} onChange={({ detail }) => setAttr(detail.value)} disabled={!enabled} ariaLabel="TTL attribute" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function Settings({ d, reload }) {
  const ttl = useAsync(() => api.describeTtl(d.TableName), [d.TableName]);
  const tags = useAsync(() => api.tags(d.TableArn), [d.TableArn]);
  const [ttlModal, setTtlModal] = useState(false);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Read/write capacity" columns={2} items={[["Capacity mode", capacity(d)], ["Read capacity", d.ProvisionedThroughput?.ReadCapacityUnits || "On-demand"], ["Write capacity", d.ProvisionedThroughput?.WriteCapacityUnits || "On-demand"]]} />
      {ttl.data === null ? <NotSimulatedContainer title="Time to Live (TTL)" /> : (
        <KeyValue title="Time to Live (TTL)" actions={<Button onClick={() => setTtlModal(true)}>{ttl.data?.TimeToLiveStatus === "ENABLED" ? "Turn off" : "Turn on"}</Button>}
          columns={2} items={[["TTL status", ttl.data?.TimeToLiveStatus === "ENABLED" ? "On" : "Off"], ["TTL attribute", ttl.data?.AttributeName]]} />
      )}
      <KeyValue title="Encryption" columns={2} items={[["Key management", d.SSEDescription?.SSEType === "KMS" ? "AWS managed key" : "Owned by Amazon DynamoDB"]]} />
      {tags.data === null ? <NotSimulatedContainer title="Tags" /> : (
        <Table variant="container" header={<Header variant="h2" counter={`(${tags.data?.length || 0})`}>Tags</Header>} items={tags.data || []} loading={tags.loading}
          columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
          empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      )}
      {ttl.data !== null && <TtlModal name={d.TableName} ttl={ttl.data} visible={ttlModal} onDismiss={() => setTtlModal(false)} onDone={ttl.reload} />}
    </SpaceBetween>
  );
}
