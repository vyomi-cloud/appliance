/* Data stream detail — Configuration (stream details, shards, encryption, resource policy,
 * tags), Data viewer (PutRecord/GetRecords round trip), Monitoring (enhanced shard-level
 * metrics flag is real; the CloudWatch graph dashboard is the one declared gap —
 * core/capabilities/aws/kinesis.json: kinesis.stream.monitoring-metrics) and Enhanced fan-out
 * (register/deregister consumers), all wired to real Kinesis_20131202 calls. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const statusType = (s) => (s === "ACTIVE" ? "success" : s === "DELETING" ? "error" : "in-progress");

function EditStreamModal({ summary, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [mode, setMode] = useState(api.capacityLabel(summary.StreamModeDetails));
  const [shards, setShards] = useState("");
  const [retention, setRetention] = useState(String(summary.RetentionPeriodHours));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const wantMode = mode === "On-demand" ? "ON_DEMAND" : "PROVISIONED";
      if (wantMode !== summary.StreamModeDetails.StreamMode) await api.updateStreamMode(summary.StreamARN, wantMode);
      if (wantMode === "PROVISIONED" && shards) await api.updateShardCount(summary.StreamName, Number(shards));
      await api.setRetention(summary.StreamName, summary.RetentionPeriodHours, Number(retention));
      notify.success("Stream details updated.");
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit stream details"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Save changes</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Capacity mode">
          <RadioGroup value={mode} onChange={({ detail }) => setMode(detail.value)}
            items={[{ value: "On-demand", label: "On-demand" }, { value: "Provisioned", label: "Provisioned" }]} />
        </FormField>
        {mode === "Provisioned" && (
          <FormField label="Target shard count" constraintText="Can scale to between half and double the current open shard count.">
            <Input type="number" value={shards} onChange={({ detail }) => setShards(detail.value)} ariaLabel="Target shard count" />
          </FormField>
        )}
        <FormField label="Retention period (hours)" constraintText="24 to 8760 hours.">
          <Input type="number" value={retention} onChange={({ detail }) => setRetention(detail.value)} ariaLabel="Retention period (hours)" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function EncryptionModal({ summary, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [enabled, setEnabled] = useState(summary.EncryptionType === "KMS");
  const [keyId, setKeyId] = useState(summary.KeyId || "alias/aws/kinesis");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (enabled) await api.startEncryption(summary.StreamName, keyId);
      else await api.stopEncryption(summary.StreamName);
      notify.success(`Server-side encryption ${enabled ? "enabled" : "disabled"}.`);
      onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Edit server-side encryption"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} onClick={submit}>Save changes</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <Checkbox checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Enable server-side encryption</Checkbox>
        {enabled && <FormField label="KMS key ID or alias"><Input value={keyId} onChange={({ detail }) => setKeyId(detail.value)} ariaLabel="KMS key ID or alias" /></FormField>}
      </SpaceBetween>
    </Modal>
  );
}

function ResourcePolicySection({ streamArn }) {
  const p = useAsync(() => api.getResourcePolicy(streamArn), [streamArn]);
  const notify = useNotify();
  const [edit, setEdit] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <Container header={<Header variant="h2" actions={<Button onClick={() => { setErr(null); setEdit(p.data || "{}"); }}>Edit</Button>}>Resource policy</Header>}>
      {p.loading ? <Spinner /> : <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{p.data}</pre></Box>}
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit resource policy"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            try { JSON.parse(edit); } catch (e) { setErr(`Policy is not valid JSON: ${e.message}`); return; }
            setBusy(true);
            try { await api.putResourcePolicy(streamArn, edit); notify.success(`Resource policy updated.${saveNotice("kinesis.stream.resource-policy")}`); setEdit(null); p.reload(); }
            catch (e) { setErr(e.message); } finally { setBusy(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Policy" errorText={err} stretch><Textarea rows={14} value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} spellcheck={false} /></FormField>
      </Modal>
    </Container>
  );
}

function TagsSection({ name }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTagsForStream(name), [name]);
  const [edit, setEdit] = useState(null);
  return (
    <Container header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={() => setEdit((t.data || []).map((x) => ({ key: x.Key, value: x.Value })))}>Manage tags</Button>}>Tags</Header>}>
      <Table variant="embedded" items={t.data || []} loading={t.loading}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Manage tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              const current = new Set((t.data || []).map((x) => x.Key));
              const next = new Set(edit.filter((x) => !x.markedForRemoval && x.key).map((x) => x.key));
              const toRemove = [...current].filter((k) => !next.has(k));
              if (toRemove.length) await api.removeTagsFromStream(name, toRemove);
              const toAdd = Object.fromEntries(edit.filter((x) => !x.markedForRemoval && x.key).map((x) => [x.key, x.value || ""]));
              if (Object.keys(toAdd).length) await api.addTagsToStream(name, toAdd);
              notify.success("Tags updated."); setEdit(null); t.reload();
            } catch (e) { notify.error(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </Container>
  );
}

function ConfigurationTab({ summary, reload }) {
  const [editOpen, setEditOpen] = useState(false);
  const [encOpen, setEncOpen] = useState(false);
  const shards = useAsync(() => api.listShards(summary.StreamName), [summary.StreamName]);
  return (
    <SpaceBetween size="l">
      <KeyValue title="Stream details" actions={<Button onClick={() => setEditOpen(true)}>Edit</Button>} columns={3} items={[
        ["Stream name", summary.StreamName], ["Stream ARN", summary.StreamARN],
        ["Status", <StatusIndicator key="s" type={statusType(summary.StreamStatus)}>{summary.StreamStatus}</StatusIndicator>],
        ["Creation time", fmtDate(summary.StreamCreationTimestamp)], ["Capacity mode", api.capacityLabel(summary.StreamModeDetails)],
        ["Retention period", `${summary.RetentionPeriodHours} hours`],
      ]} />
      <Table variant="container" header={<Header variant="h2" counter={`(${(shards.data || []).length})`}>Shards</Header>}
        items={shards.data || []} loading={shards.loading} trackBy="ShardId"
        columnDefinitions={[
          { id: "id", header: "Shard ID", cell: (s) => s.ShardId },
          { id: "status", header: "Status", cell: (s) => (s.SequenceNumberRange.EndingSequenceNumber ? "Closed" : "Open") },
          { id: "start", header: "Starting hash key", cell: (s) => s.HashKeyRange.StartingHashKey },
          { id: "end", header: "Ending hash key", cell: (s) => s.HashKeyRange.EndingHashKey },
          { id: "seq", header: "Starting sequence number", cell: (s) => s.SequenceNumberRange.StartingSequenceNumber },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No shards</b></Box>} />
      <Container header={<Header variant="h2" actions={<Button onClick={() => setEncOpen(true)}>Edit</Button>}>Server-side encryption</Header>}>
        <KeyValue columns={2} items={[["Encryption type", summary.EncryptionType === "KMS" ? "KMS" : "Disabled"], ["KMS key ARN", summary.KeyId || "-"]]} />
      </Container>
      <ResourcePolicySection streamArn={summary.StreamARN} />
      <TagsSection name={summary.StreamName} />
      <EditStreamModal key={`${summary.StreamModeDetails.StreamMode}-${summary.RetentionPeriodHours}`} summary={summary} visible={editOpen} onDismiss={() => setEditOpen(false)} onDone={reload} />
      <EncryptionModal key={`${summary.EncryptionType}-${summary.KeyId}`} summary={summary} visible={encOpen} onDismiss={() => setEncOpen(false)} onDone={reload} />
    </SpaceBetween>
  );
}

function DataViewerTab({ name }) {
  const shards = useAsync(() => api.listShards(name), [name]);
  const [shardId, setShardId] = useState(null);
  const [position, setPosition] = useState({ value: "TRIM_HORIZON", label: "Trim horizon" });
  const [timestamp, setTimestamp] = useState("");
  const [seq, setSeq] = useState("");
  const [records, setRecords] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const options = (shards.data || []).map((s) => ({ value: s.ShardId, label: s.ShardId }));
  const getRecords = async () => {
    const sid = shardId?.value || options[0]?.value;
    if (!sid) return;
    setBusy(true); setError(null);
    try {
      const extra = position.value === "AT_TIMESTAMP" ? { Timestamp: Number(timestamp) }
        : position.value === "AT_SEQUENCE_NUMBER" ? { StartingSequenceNumber: seq } : {};
      const it = await api.getShardIterator(name, sid, position.value, extra);
      const r = await api.getRecords(it, 25);
      setRecords(r.Records || []);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2">Data viewer</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Shard ID"><Select selectedOption={shardId || options[0] || null} onChange={({ detail }) => setShardId(detail.selectedOption)} options={options} placeholder="Choose a shard" /></FormField>
        <FormField label="Starting position">
          <Select selectedOption={position} onChange={({ detail }) => setPosition(detail.selectedOption)} options={[
            { value: "TRIM_HORIZON", label: "Trim horizon" }, { value: "LATEST", label: "Latest" },
            { value: "AT_TIMESTAMP", label: "At timestamp" }, { value: "AT_SEQUENCE_NUMBER", label: "At sequence number" },
          ]} />
        </FormField>
        {position.value === "AT_TIMESTAMP" && <FormField label="Timestamp"><Input value={timestamp} onChange={({ detail }) => setTimestamp(detail.value)} placeholder="Unix epoch seconds" ariaLabel="Timestamp" /></FormField>}
        {position.value === "AT_SEQUENCE_NUMBER" && <FormField label="Sequence number"><Input value={seq} onChange={({ detail }) => setSeq(detail.value)} ariaLabel="Sequence number" /></FormField>}
        <Button loading={busy} onClick={getRecords}>Get records</Button>
        <Table variant="embedded" items={records || []} loading={busy}
          columnDefinitions={[
            { id: "pk", header: "Partition key", cell: (r) => r.PartitionKey },
            { id: "seq", header: "Sequence number", cell: (r) => r.SequenceNumber },
            { id: "size", header: "Size", cell: (r) => `${atob(r.Data || "").length} bytes` },
            { id: "ts", header: "Timestamp", cell: (r) => fmtDate(r.ApproximateArrivalTimestamp) },
            { id: "data", header: "Data", cell: (r) => { try { return api.unb64(r.Data); } catch { return r.Data; } } },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No records retrieved yet</b></Box>} />
      </SpaceBetween>
    </Container>
  );
}

function MonitoringTab({ summary, reload }) {
  const notify = useNotify();
  const [editOpen, setEditOpen] = useState(false);
  const [checked, setChecked] = useState(summary.EnhancedMonitoring?.[0]?.ShardLevelMetrics || []);
  const current = summary.EnhancedMonitoring?.[0]?.ShardLevelMetrics || [];
  const submit = async () => {
    const add = checked.filter((m) => !current.includes(m));
    const remove = current.filter((m) => !checked.includes(m));
    try {
      if (add.length) await api.enableMonitoring(summary.StreamName, add);
      if (remove.length) await api.disableMonitoring(summary.StreamName, remove);
      notify.success("Enhanced (shard-level) metrics updated.");
      setEditOpen(false); reload();
    } catch (e) { notify.error(e); }
  };
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="kinesis.stream.monitoring-metrics" title="CloudWatch metrics" />
      <Container header={<Header variant="h2" actions={<Button onClick={() => { setChecked(current); setEditOpen(true); }}>Edit</Button>}>Enhanced (shard-level) metrics</Header>}>
        <KeyValue columns={1} items={[["Shard-level metrics", current.length ? current.join(", ") : "Basic (stream-level) metrics only"]]} />
      </Container>
      <Modal visible={editOpen} onDismiss={() => setEditOpen(false)} header="Edit enhanced (shard-level) metrics"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={submit}>Save changes</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="xs">
          {api.ALL_METRICS.map((m) => (
            <Checkbox key={m} checked={checked.includes(m)} onChange={({ detail }) => setChecked((c) => (detail.checked ? [...c, m] : c.filter((x) => x !== m)))}>{m}</Checkbox>
          ))}
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
}

function EnhancedFanOutTab({ summary }) {
  const notify = useNotify();
  const c = useAsync(() => api.listConsumers(summary.StreamARN), [summary.StreamARN]);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  return (
    <Container>
      <Table variant="embedded" items={c.data || []} loading={c.loading} trackBy="ConsumerARN"
        selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${(c.data || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={async () => { for (const x of sel) await api.deregisterConsumer(summary.StreamARN, x.ConsumerName); notify.success("Consumer(s) deregistered."); setSel([]); c.reload(); }}>Deregister</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Register consumer</Button>
          </SpaceBetween>
        }>Registered consumers</Header>}
        columnDefinitions={[
          { id: "n", header: "Consumer name", cell: (x) => x.ConsumerName },
          { id: "a", header: "Consumer ARN", cell: (x) => x.ConsumerARN },
          { id: "s", header: "Status", cell: (x) => <StatusIndicator type={x.ConsumerStatus === "ACTIVE" ? "success" : "in-progress"}>{x.ConsumerStatus}</StatusIndicator> },
          { id: "c", header: "Consumer creation time", cell: (x) => fmtDate(x.ConsumerCreationTimestamp) },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No registered consumers</b></Box>} />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Register consumer"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" disabled={!name} onClick={async () => { await api.registerConsumer(summary.StreamARN, name); notify.success(`Registered consumer "${name}".`); setCreate(false); setName(""); c.reload(); }}>Register consumer</Button>
        </SpaceBetween></Box>}>
        <FormField label="Consumer name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Consumer name" /></FormField>
      </Modal>
    </Container>
  );
}

export default function StreamDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const d = useAsync(() => api.describeStreamSummary(name), [name]);
  const [deleteOpen, setDeleteOpen] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const summary = d.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "delete", text: "Delete" }]}
        onItemClick={({ detail }) => { if (detail.id === "delete") setDeleteOpen(true); }}>Actions</ButtonDropdown>
    }>{summary.StreamName}</Header>}>
      <Tabs tabs={[
        { id: "configuration", label: "Configuration", content: <ConfigurationTab summary={summary} reload={d.reload} /> },
        { id: "viewer", label: "Data viewer", content: <DataViewerTab name={name} /> },
        { id: "monitoring", label: "Monitoring", content: <MonitoringTab summary={summary} reload={d.reload} /> },
        { id: "fanout", label: "Enhanced fan-out", content: <EnhancedFanOutTab summary={summary} /> },
      ]} />
      <DeleteModal
        visible={deleteOpen}
        onDismiss={() => setDeleteOpen(false)}
        resourceType="data stream"
        names={[name]}
        onConfirm={async () => { await api.deleteStream(name, true); notify.success(`Deleting data stream "${name}".`); navigate("kinesis", "streams"); }}
      />
    </ContentLayout>
  );
}
